"""Plugin sourcing, verification and the permission table.

Nothing runs here. This module fetches a plugin's source, validates the
manifest, hashes what it got and checks that hash against the catalogue.
Execution is a sandbox on each side, an opaque-origin iframe in the browser and
QuickJS in WebAssembly on the hub.

Permissions are data. Both sandboxes enforce them at their own edge, since by
the time a command reaches the engine it looks like one the dashboard sent.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import zipfile
from typing import Any
from urllib.parse import urlsplit

from . import oauth, urls
from .adapters import HttpFn

MANIFEST_FILE = "plugin.json"
SOURCE_FILES = ("plugin.js", "worker.js", "panel.html")
MAX_ASSET_BYTES = 4 * 1024 * 1024
MAX_ASSETS_BYTES = 12 * 1024 * 1024
SURFACES = ("panel", "monitor", "settings")
MAX_SOURCE_BYTES = 256 * 1024
MAX_CONFIG_BYTES = 16 * 1024
MIN_TICK_S = 5.0
MAX_SECRETS = 8
MAX_CHANNELS = 8
MAX_CONSUMES = 16
CHANNEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]$")
LINK_PATTERN = re.compile(r"^([a-z0-9][a-z0-9-]{1,38}[a-z0-9]):([a-z0-9][a-z0-9-]{0,38}[a-z0-9])$")
MAX_SECRET_BYTES = 4096
SECRET_NAME = re.compile(r"^[a-z0-9_-]{1,40}$")
SECRET_REFERENCE = re.compile(r"\{\{\s*secret\.([a-z0-9_-]{1,40})\s*\}\}")
"""How a plugin names a secret it may use but never read.

The value is substituted as the request leaves, so the reference is all a
plugin ever holds.
"""
CATALOGUE_URL = "https://raw.githubusercontent.com/oliverbravery/PrintGuard/main/plugins/catalogue.json"
GITHUB_COMMIT_URL = "https://api.github.com/repos/{repo}/commits/{ref}"
GITHUB_RAW_URL = "https://raw.githubusercontent.com/{repo}/{sha}/{path}"
GITHUB_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
TIMEOUT_S = 20.0

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")
_REPO_PATTERN = re.compile(r"^[\w.-]+/[\w.-]+$")
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_PATH_PATTERN = re.compile(r"^[\w./-]*$")
_ASSET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")
VERSION_PATTERN = re.compile(r"^[\w.+-]{1,32}$")
MEDIA_PATTERN = re.compile(r"^[a-z0-9][\w-]*(?:/[\w-]+)*\.(?:png|jpe?g|webp|gif|svg)$")
MAX_MEDIA = 8
README_FILE = "README.md"
MAX_README_BYTES = 64 * 1024

PERMISSIONS: dict[str, dict[str, Any]] = {
    "state:read": {
        "label": "Read the dashboard",
        "description": "Monitor names, scores and alerts, camera and printer status.",
        "fields": {
            "monitors": ["id", "name", "camera_id", "printer_id", "enabled", "watching", "threshold", "result", "alert"],
            "cameras": ["id", "name", "online", "standby", "in_use", "max_fps", "achieved_fps"],
            "printers": ["id", "name", "provider", "online", "device_state"],
        },
    },
    "camera:view": {
        "label": "Show live camera feeds",
        "description": "Show a live feed in its panel.",
    },
    "monitor:control": {
        "label": "Change monitors",
        "description": "Enable, disable and retune any monitor.",
        "commands": ["monitor.update"],
        "risky": True,
    },
    "monitor:manage": {
        "label": "Add and remove monitors",
        "description": "Add monitors, and delete them with their history.",
        "commands": ["monitor.add", "monitor.remove"],
        "risky": True,
    },
    "camera:control": {
        "label": "Retune cameras",
        "description": "Change any camera's picture and frame rate.",
        "commands": ["camera.update"],
    },
    "camera:manage": {
        "label": "Add and remove cameras",
        "description": "Add and delete cameras.",
        "commands": ["camera.add", "camera.remove", "discover"],
        "risky": True,
    },
    "camera:frames": {
        "label": "Read your camera images",
        "description": "Take a still from any camera. With net, it can send your pictures anywhere.",
        "commands": ["camera.snapshot"],
        "risky": True,
    },
    "history:read": {
        "label": "Read risk history",
        "description": "Every monitor's score history and past alerts.",
        "commands": ["history.get"],
    },
    "printer:manage": {
        "label": "Add and remove printers",
        "description": "Add and delete printers. It can set credentials, not read them.",
        "commands": ["printer.add", "printer.update", "printer.remove", "printer.test", "printer.cameras.refresh"],
        "fields": {"integrations": ["id", "label", "schema", "docs_url", "setup_url", "setup_hint", "experimental"]},
        "risky": True,
    },
    "settings": {
        "label": "Change your settings",
        "description": "Change anything in Settings. It can set credentials, not read them.",
        "commands": ["settings.update", "notify.test"],
        "fields": {"notifiers": ["id", "label", "schema", "docs_url", "setup_url", "setup_hint", "browser_ok"]},
        "risky": True,
    },
    "tokens": {
        "label": "Manage API tokens",
        "description": "Mint and revoke API tokens. It never sees the secret.",
        "commands": ["token.create", "token.remove"],
        "risky": True,
    },
    "printer:control": {
        "label": "Control printers",
        "description": "Pause, resume and cancel any print.",
        "commands": ["printer.action"],
        "risky": True,
    },
    "notify": {
        "label": "Show notifications",
        "description": "Show a message in the dashboard.",
    },
    "sound": {
        "label": "Play a sound",
        "description": "Play a sound on this device.",
    },
    "alert:send": {
        "label": "Use your alert channels",
        "description": "Send through your ntfy, Pushover, Telegram or Discord.",
        "commands": ["notify.send"],
        "risky": True,
    },
    "net": {
        "label": "Reach the internet",
        "description": "Reach the addresses it lists.",
        "urls": True,
    },
    "net:local": {
        "label": "Reach your own network",
        "description": "Reach this machine and the network around it.",
        "urls": True,
        "risky": True,
    },
    "oauth": {
        "label": "Connect an account",
        "description": "Sign you in to a service. PrintGuard holds the tokens.",
        "risky": True,
    },
    "background": {
        "label": "Paint the dashboard's background",
        "description": "Put a picture behind the dashboard.",
    },
    "link:provide": {
        "label": "Answer other plugins",
        "description": "Answer other plugins on the channels it lists.",
    },
    "link:consume": {
        "label": "Talk to other plugins",
        "description": "Call the plugins and channels it names.",
        "channels": True,
    },
    "routes": {
        "label": "Serve its own pages",
        "description": "Serve pages under /plugins/<id>/, reading your session cookie.",
        "hub_only": True,
    },
    "gate": {
        "label": "Authorise every request",
        "description": "Approve or refuse every request to the hub. It can lock you out.",
        "hub_only": True,
        "risky": True,
    },
}

PERMISSION_COMMANDS = {
    command: name for name, spec in PERMISSIONS.items() for command in spec.get("commands", [])
}

ASSET_TYPES: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "wav": "audio/wav",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "json": "application/json",
    "csv": "text/csv",
    "txt": "text/plain",
}
"""What a plugin may ship beside its code, and the type each is served as.

An allowlist, since the dangerous formats are the ones nobody thinks of. SVG is
markup wearing an image's extension, so it is not here. The type comes from this
table, never from the file.
"""

ASSET_MAGIC: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/webp": (b"RIFF",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "audio/mpeg": (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
    "audio/ogg": (b"OggS",),
    "audio/wav": (b"RIFF",),
    "video/mp4": (b"ftyp",),
    "video/webm": (b"\x1a\x45\xdf\xa3",),
}
"""How each binary type starts, so a file has to be what its name says it is."""

PLATFORMS: dict[str, str] = {
    "docker": "Docker",
    "docker-nvidia": "NVIDIA image",
    "docker-intel": "Intel image",
    "macos": "macOS",
    "windows": "Windows",
    "browser": "Browser",
}
"""Where PrintGuard runs, as a plugin declares it and a deployment reports it.

An id extends the one before its hyphen, so ``docker`` covers every image and
``docker-nvidia`` covers that one. Naming none of them runs everywhere.
"""

EVENTS: dict[str, list[str]] = {
    "http": ["tag", "status", "body"],
    "frame": ["camera_id", "jpeg"],
    "call": ["from", "channel", "body", "call_id"],
    "answer": ["tag", "from", "channel", "body"],
    "message": ["from", "channel", "body"],
    "history": ["monitor_id", "now", "buckets", "alerts", "stats"],
    "socket": ["tag", "state", "text"],
    "result": ["monitor_id", "camera_id", "score", "prediction", "margin", "ms", "ts"],
    "alert": ["monitor_id", "score", "action", "ts"],
    "warning": ["monitor_id", "message", "recovered"],
    "device": ["printer_id", "status", "progress", "job"],
    "error": ["message"],
    "state": [],
}
"""The events a plugin may hook, and the fields each one hands it.

Engine events carry more than a plugin's grants allow, such as a printer's
credentials or a new token's secret, so a plugin gets these fields only. An
event missing from here never reaches one.
"""

EVENT_PERMISSIONS: dict[str, str] = {
    "state": "state:read",
    "frame": "camera:frames",
    "history": "history:read",
    "call": "link:provide",
    "answer": "link:consume",
    "message": "link:consume",
}
"""Events carrying something a permission covers, and which one.

Events broadcast to every plugin that named them, so one carrying a camera still
or a monitor's history needs the grant its command needed. Without this a plugin
could name the event, wait for somebody else to ask, and read the answer.
"""


UI_EFFECTS: dict[str, str] = {"notify": "notify", "sound": "sound", "background": "background"}
"""Effects a dashboard carries out for a plugin, and the permission each needs.

A worker on the hub has no speakers and no screen, so it asks and every open
dashboard performs it, the way an extension's service worker reaches a document.
The grant is checked at the engine as well as at the sandbox edge.
"""

MAX_EFFECT_BYTES = 3 * 1024 * 1024
"""How large one may be, which a background picture is the reason for."""


def sanitise_secrets(raw: Any, names: list[str]) -> dict[str, str]:
    """Keeps the secrets a manifest declared, refusing anything oversized.

    Args:
        raw: Values as the user typed them into PrintGuard's own form.
        names: What the manifest declared, which is all that may be stored.

    Returns:
        The named secrets, dropping any the manifest does not declare and any
        left blank.

    Raises:
        ValueError: If a value is larger than a credential has any business being.
    """
    kept = {name: str(raw.get(name, "")) for name in names if str(raw.get(name, ""))}
    if any(len(value.encode()) > MAX_SECRET_BYTES for value in kept.values()):
        raise ValueError(f"a secret is {MAX_SECRET_BYTES // 1024} KB at most")
    return kept


def missing_secrets(value: Any, secrets: dict[str, str]) -> set[str]:
    """Names the secrets a request refers to that the plugin has nothing for.

    Args:
        value: The request, walked the same way ``fill_secrets`` walks it.
        secrets: What the plugin holds.

    Returns:
        Every name referenced that is unset, empty when the request is ready to go.
    """
    if isinstance(value, str):
        return {name for name in SECRET_REFERENCE.findall(value) if not secrets.get(name)}
    if isinstance(value, dict):
        return set().union(*(missing_secrets(item, secrets) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(missing_secrets(item, secrets) for item in value)) if value else set()
    return set()


def fill_secrets(value: Any, secrets: dict[str, str]) -> Any:
    """Replaces every secret reference in a request with the value it names.

    Walks the whole structure, so a reference works in the URL, a header or
    anywhere in a JSON body. A reference to something unset resolves to nothing
    rather than travelling as the reference itself.
    """
    if isinstance(value, str):
        return SECRET_REFERENCE.sub(lambda found: secrets.get(found.group(1), ""), value)
    if isinstance(value, dict):
        return {key: fill_secrets(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [fill_secrets(item, secrets) for item in value]
    return value


def consented(manifest: dict[str, Any], granted: list[str]) -> bool:
    """Whether every permission a manifest asks for has been accepted.

    Args:
        manifest: The validated manifest.
        granted: What the user accepted, which an update can leave short.

    Returns:
        True when nothing the plugin asks for is still unaccepted.
    """
    return set(manifest["permissions"]) <= set(granted)


def same_source(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    """Whether a bundle comes from the place the installed one came from.

    A repository is the nearest thing a plugin has to a signing key. A zip has
    no identity, so it is never the same place twice.

    Args:
        previous: The source recorded against the installed plugin.
        current: Where the bundle being installed came from.

    Returns:
        True when both name the same repository and path.
    """
    if previous.get("kind") != "github" or current.get("kind") != "github":
        return False
    return (previous["repo"], previous.get("path", "")) == (current["repo"], current.get("path", ""))


def widens(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    """Whether an update reaches further than the manifest that was accepted.

    Permissions, addresses and the plugins it calls are what the user agreed to,
    so a change to any of them is a fresh question. Anything not written exactly
    as before counts as wider, since a narrower-looking pattern can cover more.

    Args:
        previous: The manifest the grants were given against.
        current: The manifest being installed over it.

    Returns:
        True when the new manifest asks for anything the old one did not.
    """
    return any(not set(current[field]) <= set(previous[field]) for field in ("permissions", "urls", "consumes"))


def runs_here(platforms: list[str], host: str) -> bool:
    """Whether a plugin's declared platforms cover the deployment running it.

    Args:
        platforms: What the manifest declared, empty for everywhere.
        host: The deployment's own id, the most specific one it has.

    Returns:
        True when the plugin declared nothing, the host itself, or a platform
        the host extends.
    """
    return not platforms or any(host == name or host.startswith(f"{name}-") for name in platforms)


def permissions_meta() -> list[dict[str, Any]]:
    """Serialises the permission table for the state snapshot."""
    return [{"id": name, **spec} for name, spec in PERMISSIONS.items()]


def project_state(state: dict[str, Any], granted: list[str]) -> dict[str, Any]:
    """Cuts a state snapshot down to the fields a plugin's grants allow.

    Everything is dropped unless a permission names it, so a field added to the
    snapshot later is invisible until it is listed. The UI applies the same
    table, read from ``permissions_meta()``.
    """
    view: dict[str, Any] = {"mode": state.get("mode"), "version": state.get("version")}
    for name in granted:
        for collection, fields in PERMISSIONS.get(name, {}).get("fields", {}).items():
            view[collection] = [{k: item[k] for k in fields if k in item} for item in state.get(collection, [])]
    return view


def project_event(event: dict[str, Any], granted: list[str]) -> dict[str, Any] | None:
    """Cuts an engine event down to what a plugin may see.

    Args:
        event: The event as the engine broadcast it.
        granted: Permissions the user gave the plugin.

    Returns:
        The event carrying only the fields ``EVENTS`` lists for it, or None if
        no plugin may hook it or this one lacks the grant. A state event comes
        back as the projection the grants allow.
    """
    name = str(event.get("event", ""))
    fields = EVENTS.get(name)
    needed = EVENT_PERMISSIONS.get(name)
    if fields is None or (needed is not None and needed not in granted):
        return None
    if name == "state":
        return {"event": name, **project_state(event, granted)}
    return {"event": name, **{field: event[field] for field in fields if field in event}}


def asset_type(name: str) -> str | None:
    """The media type an asset is handed over as, or None if it may not ship."""
    extension = name.rsplit(".", 1)[-1] if "." in name else ""
    return ASSET_TYPES.get(extension) if _ASSET_PATTERN.match(name) else None


def sanitise_assets(raw: dict[str, bytes]) -> dict[str, str]:
    """Checks a plugin's shipped files and encodes them for the record.

    Args:
        raw: File contents keyed by the name the manifest declared.

    Returns:
        Each file base64 encoded, ready to travel as JSON.

    Raises:
        ValueError: If a name, type, size or content fails the checks.
    """
    assets: dict[str, str] = {}
    total = 0
    for name, data in raw.items():
        media = asset_type(name)
        if media is None:
            raise ValueError(f"{name} is not a kind of file a plugin may ship")
        total += len(data)
        if len(data) > MAX_ASSET_BYTES or total > MAX_ASSETS_BYTES:
            raise ValueError(f"{name} takes the plugin past {MAX_ASSETS_BYTES // 1024} KB of files")
        starts = ASSET_MAGIC.get(media)
        if starts and not (data.startswith(starts) or (media == "video/mp4" and data[4:8] == b"ftyp")):
            raise ValueError(f"{name} is not really {media}")
        if not starts:
            try:
                data.decode()
            except UnicodeDecodeError as exc:
                raise ValueError(f"{name} is not text") from exc
        assets[name] = base64.b64encode(data).decode()
    return assets


def text_assets(assets: dict[str, str]) -> dict[str, str]:
    """Decodes the assets a plugin can read itself, leaving audio and images out."""
    return {
        name: base64.b64decode(data).decode()
        for name, data in assets.items()
        if not ASSET_MAGIC.get(asset_type(name) or "")
    }


def canonical(value: Any) -> bytes:
    """Encodes a manifest the one way both ends agree to hash it.

    The platform's HTTP function returns parsed JSON in both modes, never the
    bytes it came from, so a manifest is pinned by the hash of this form.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digests(manifest: dict[str, Any], sources: dict[str, str], assets: dict[str, str]) -> dict[str, str]:
    """Hashes a bundle, the canonical manifest and every file that came with it."""
    hashed = {MANIFEST_FILE: hashlib.sha256(canonical(manifest)).hexdigest()}
    hashed.update({name: hashlib.sha256(code.encode()).hexdigest() for name, code in sources.items()})
    hashed.update({name: hashlib.sha256(base64.b64decode(data)).hexdigest() for name, data in assets.items()})
    return hashed


def described(raw: Any, field: str, pattern: re.Pattern[str], cap: int, complaint: str) -> dict[str, str]:
    """Reads one of the manifest's maps of a name against the line describing it.

    Args:
        raw: The parsed ``plugin.json``.
        field: Which map to read.
        pattern: What every name in the map has to match.
        cap: How many entries are kept.
        complaint: What to raise when an entry is unusable.

    Returns:
        Every name in the map against its description.

    Raises:
        ValueError: If a name or its description is unusable.
    """
    given = raw.get(field) if isinstance(raw.get(field), dict) else {}
    lines = {str(name).strip().lower(): str(why).strip()[:200] for name, why in list(given.items())[:cap]}
    if any(not pattern.match(name) or not why for name, why in lines.items()):
        raise ValueError(complaint)
    return lines


def sanitise_manifest(raw: Any) -> dict[str, Any]:
    """Validates a plugin manifest, dropping anything unrecognised.

    Args:
        raw: The parsed ``plugin.json``.

    Returns:
        A complete manifest record.

    Raises:
        ValueError: If the manifest is unusable.
    """
    if not isinstance(raw, dict):
        raise ValueError("plugin.json is not an object")
    plugin_id = str(raw.get("id", "")).strip().lower()
    if not ID_PATTERN.match(plugin_id):
        raise ValueError("plugin id must be 3-40 lowercase letters, digits or hyphens")
    version = str(raw.get("version", "")).strip()
    if not VERSION_PATTERN.match(version):
        raise ValueError("plugin version is missing or unusable")
    permissions = [p for p in PERMISSIONS if p in raw.get("permissions", [])]
    given = raw.get("reasons") if isinstance(raw.get("reasons"), dict) else {}
    reasons = {p: str(given.get(p, "")).strip()[:200] for p in permissions}
    unexplained = [p for p, why in reasons.items() if not why]
    if unexplained:
        raise ValueError(f"reasons must say why the plugin wants {', '.join(unexplained)}")
    wanted = described(raw, "secrets", SECRET_NAME, MAX_SECRETS, "each secret needs a short name and a line saying what it is")
    provides = described(raw, "provides", CHANNEL_PATTERN, MAX_CHANNELS, "each channel in provides needs a short name and a line saying what it answers")
    consumes = sorted({str(link).strip().lower() for link in raw.get("consumes", []) if str(link).strip()})[:MAX_CONSUMES]
    if any(not LINK_PATTERN.match(link) for link in consumes):
        raise ValueError("each entry in consumes names a plugin and a channel, as plugin-id:channel")
    if provides and "link:provide" not in permissions:
        raise ValueError("provides needs the link:provide permission")
    if consumes and "link:consume" not in permissions:
        raise ValueError("consumes needs the link:consume permission")
    sign_in = sanitise_sign_in(raw.get("oauth"))
    if sign_in and "oauth" not in permissions:
        raise ValueError("oauth needs the oauth permission")
    if sign_in:
        wanted[oauth.CLIENT_ID] = f"The client id of the {sign_in['label']} app you registered"
    icon = str(raw.get("icon", "")).strip().lower()
    if icon and not MEDIA_PATTERN.match(icon):
        raise ValueError("icon names an image file inside the plugin's folder")
    media = [str(shot).strip().lower() for shot in raw.get("media", []) if str(shot).strip()][:MAX_MEDIA]
    if any(not MEDIA_PATTERN.match(shot) for shot in media):
        raise ValueError("each media entry names an image file inside the plugin's folder")
    surfaces = [s for s in raw.get("surfaces", []) if s in SURFACES] or ["panel"]
    platforms = sorted({str(p).strip() for p in raw.get("platforms", [])} & set(PLATFORMS))
    assets = sorted({str(a).strip().lower() for a in raw.get("assets", [])} - {MANIFEST_FILE, *SOURCE_FILES})
    if any(asset_type(name) is None for name in assets):
        raise ValueError(f"a plugin may only ship {', '.join(sorted(set(ASSET_TYPES)))}")
    patterns = urls.sanitise(raw.get("urls"))
    local = [pattern for pattern in patterns if urls.reaches_local(pattern)]
    if patterns and "net" not in permissions:
        raise ValueError("urls needs the net permission")
    if local and "net:local" not in permissions:
        raise ValueError(f"reaching {', '.join(local)} needs the net:local permission")
    events = sorted(({str(e).strip() for e in raw.get("events", [])} & set(EVENTS)) | linked_events(raw))
    try:
        tick_s = max(0.0, float(raw.get("tick_s", 0)))
    except (TypeError, ValueError):
        tick_s = 0.0
    return {
        "id": plugin_id,
        "name": str(raw.get("name", "")).strip() or plugin_id,
        "version": version,
        "description": str(raw.get("description", "")).strip()[:400],
        "author": str(raw.get("author", "")).strip()[:80],
        "homepage": urls.link(raw.get("homepage")),
        "icon": icon,
        "media": media,
        "permissions": permissions,
        "reasons": reasons,
        "surfaces": surfaces,
        "platforms": platforms,
        "assets": assets,
        "urls": patterns,
        "secrets": wanted,
        "provides": provides,
        "consumes": consumes,
        "oauth": sign_in,
        "events": events,
        "tick_s": min(tick_s, 86400.0) if tick_s >= MIN_TICK_S else 0.0,
    }


def linked_events(raw: Any) -> set[str]:
    """The events a plugin gets for talking to other plugins.

    Declaring a channel is the whole declaration, so the events that carry the
    traffic are added rather than asked for a second time in ``events``.
    """
    offered = bool(raw.get("provides")) if isinstance(raw, dict) else False
    wanted = bool(raw.get("consumes")) if isinstance(raw, dict) else False
    return ({"call"} if offered else set()) | ({"answer", "message"} if wanted else set())


def outbound_link(plugin_id: str, kind: str, request: Any) -> dict[str, Any]:
    """Builds a plugin.call, plugin.publish or plugin.answer out of what a plugin asked for.

    The id is set last, so a sandbox cannot spread over the command and speak as
    somebody else.
    """
    fields = request if isinstance(request, dict) else {}
    return {
        "cmd": f"plugin.{kind}",
        "to": str(fields.get("to", "")),
        "channel": str(fields.get("channel", "")),
        "tag": str(fields.get("tag", "")),
        "call_id": str(fields.get("call_id", "")),
        "body": fields.get("body"),
        "id": plugin_id,
    }


def sanitise_sign_in(raw: Any) -> dict[str, Any]:
    """Validates the sign-in a manifest declares, if it declares one.

    Args:
        raw: The manifest's ``oauth`` block.

    Returns:
        The provider's endpoints, public client id and scopes, or an empty dict
        when the plugin signs in to nothing.

    Raises:
        ValueError: If the block is there but unusable. Neither a client id nor a
            client secret is accepted: a plugin is a public client, PKCE stands
            in for the secret, and the id belongs to the app whoever installs it
            registered rather than to the plugin.
    """
    if not isinstance(raw, dict) or not raw:
        return {}
    endpoints = {key: str(raw.get(key, "")).strip() for key in ("authorize_url", "token_url")}
    if any(not urls.parse(f"{value}{'' if '/' in value.split('://')[-1] else '/'}") for value in endpoints.values()):
        raise ValueError("oauth needs an https authorize_url and token_url")
    return {
        **endpoints,
        "register_url": urls.link(raw.get("register_url")),
        "scopes": [str(scope).strip() for scope in raw.get("scopes", []) if str(scope).strip()][:20],
        "label": str(raw.get("label", "")).strip()[:80] or urlsplit(endpoints["authorize_url"]).hostname or "",
    }


def sanitise_sources(files: dict[str, str]) -> dict[str, str]:
    """Keeps the recognised source files, refusing oversized ones."""
    sources = {name: files[name] for name in SOURCE_FILES if files.get(name)}
    if not sources:
        raise ValueError(f"bundle has no {' or '.join(SOURCE_FILES)}")
    for name, code in sources.items():
        if len(code.encode()) > MAX_SOURCE_BYTES:
            raise ValueError(f"{name} is larger than {MAX_SOURCE_BYTES // 1024} KB")
    return sources


def sanitise_config(raw: Any) -> dict[str, Any]:
    """Accepts a plugin's own stored data, refusing oversized objects."""
    if not isinstance(raw, dict):
        return {}
    if len(canonical(raw)) > MAX_CONFIG_BYTES:
        raise ValueError(f"plugin data is larger than {MAX_CONFIG_BYTES // 1024} KB")
    return raw


def outbound_request(plugin_id: str, request: Any) -> dict[str, Any]:
    """Builds a plugin.http command out of what a plugin asked for.

    Only these fields carry over, and the id is set last. The request comes from
    a sandbox, so spreading it over the command could name another installed
    plugin and borrow its network grant. ``binary`` asks for a base64 answer,
    which is how a picture reaches a plugin.
    """
    fields = request if isinstance(request, dict) else {}
    return {
        "cmd": "plugin.http",
        "method": str(fields.get("method", "GET")),
        "url": str(fields.get("url", "")),
        "headers": fields.get("headers"),
        "json": fields.get("json"),
        "tag": str(fields.get("tag", "")),
        "binary": fields.get("binary") is True,
        "id": plugin_id,
    }


def outbound_socket(plugin_id: str, action: str, request: Any) -> dict[str, Any]:
    """Builds a plugin.socket command out of what a plugin asked for.

    Carries the same risk as an outbound request and is pinned the same way.
    """
    fields = request if isinstance(request, dict) else {}
    return {
        "cmd": "plugin.socket",
        "action": action,
        "url": str(fields.get("url", "")),
        "text": str(fields.get("text", "")),
        "tag": str(fields.get("tag", "")),
        "id": plugin_id,
    }


def unpack(data: bytes) -> tuple[dict[str, Any], dict[str, str], dict[str, bytes], dict[str, bytes]]:
    """Reads a manifest, sources, declared assets and page files out of a zipped bundle.

    Files may sit at the root or under a single directory, the shape a GitHub
    archive comes in. Page files are the icon, the media the manifest lists and
    a README beside the manifest: a zip is the only copy of its plugin, so what
    presents it travels with it.

    Args:
        data: The zip as uploaded.

    Returns:
        The parsed manifest, the source files as text, every asset the
        manifest declared as bytes, and the page files as bytes keyed by the
        path the manifest uses.

    Raises:
        ValueError: If the zip is unreadable or carries no manifest.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("not a zip archive") from exc
    entries: dict[str, str] = {}
    for entry in archive.namelist():
        entries.setdefault(entry.rsplit("/", 1)[-1], entry)
    if MANIFEST_FILE not in entries:
        raise ValueError(f"bundle has no {MANIFEST_FILE}")
    prefix = entries[MANIFEST_FILE][: -len(MANIFEST_FILE)]

    def read(name: str, cap: int) -> bytes:
        entry = entries[name]
        if archive.getinfo(entry).file_size > cap:
            raise ValueError(f"{name} is larger than {cap // 1024} KB")
        return archive.read(entry)

    manifest = json.loads(read(MANIFEST_FILE, MAX_SOURCE_BYTES))
    sources = {name: read(name, MAX_SOURCE_BYTES).decode("utf-8", "replace") for name in SOURCE_FILES if name in entries}
    declared = {str(name).strip().lower() for name in manifest.get("assets", []) if isinstance(manifest, dict)}
    assets = {name: read(name, MAX_ASSET_BYTES) for name in sorted(declared) if name in entries}
    listed = [str(manifest.get("icon", "")).strip().lower(), README_FILE]
    listed += [str(shot).strip().lower() for shot in manifest.get("media", []) if isinstance(manifest, dict)]
    named = set(archive.namelist())
    page: dict[str, bytes] = {}
    for path in listed:
        entry = f"{prefix}{path}"
        if path and entry in named:
            cap = MAX_README_BYTES if path == README_FILE else MAX_ASSET_BYTES
            if archive.getinfo(entry).file_size <= cap:
                page[path] = archive.read(entry)
    return manifest, sources, assets, page


def sanitise_page(raw: dict[str, bytes]) -> dict[str, str]:
    """Checks a bundle's page files and encodes them for the record.

    Args:
        raw: Icon, media and README bytes keyed by manifest path.

    Returns:
        Each file base64 encoded, dropped rather than refused when it fails a
        check, since the page only presents the plugin.
    """
    page: dict[str, str] = {}
    total = 0
    for path, data in raw.items():
        if path != README_FILE and not MEDIA_PATTERN.match(path):
            continue
        total += len(data)
        if total > MAX_ASSETS_BYTES:
            break
        page[path] = base64.b64encode(data).decode()
    return page


async def fetch_github(http: HttpFn, repo: str, path: str, ref: str) -> tuple[dict[str, Any], dict[str, str], dict[str, bytes], str]:
    """Downloads a plugin from a GitHub repository at an immutable commit.

    A branch or tag is resolved to its commit SHA first, so what gets hashed
    is a specific revision rather than whatever the branch points at later.

    Args:
        http: Platform HTTP function.
        repo: GitHub ``owner/name``.
        path: Directory inside the repository holding the plugin, or "".
        ref: Branch, tag or commit SHA.

    Returns:
        The parsed manifest, the source files, the assets it declared, and the
        resolved commit SHA.

    Raises:
        ValueError: If the reference is unusable or the plugin is not there.
    """
    if not _REPO_PATTERN.match(repo):
        raise ValueError(f"{repo!r} is not an owner/name repository")
    path = path.strip("/")
    if not _PATH_PATTERN.match(path):
        raise ValueError(f"{path!r} is not a usable path")
    sha = ref if _SHA_PATTERN.match(ref) else await _resolve_commit(http, repo, ref)
    prefix = f"{path}/" if path else ""
    status, manifest = await http("GET", GITHUB_RAW_URL.format(repo=repo, sha=sha, path=f"{prefix}{MANIFEST_FILE}"), timeout=TIMEOUT_S)
    if status != 200 or not isinstance(manifest, dict):
        raise ValueError(f"no {MANIFEST_FILE} at {repo}/{prefix} ({status})")
    sources: dict[str, str] = {}
    for name in SOURCE_FILES:
        status, body = await http("GET", GITHUB_RAW_URL.format(repo=repo, sha=sha, path=f"{prefix}{name}"), timeout=TIMEOUT_S)
        if status == 200 and isinstance(body, str):
            sources[name] = body
    assets: dict[str, bytes] = {}
    for name in sorted({str(a).strip().lower() for a in manifest.get("assets", [])}):
        if asset_type(name) is None:
            raise ValueError(f"{name} is not a kind of file a plugin may ship")
        status, body = await http(
            "GET", GITHUB_RAW_URL.format(repo=repo, sha=sha, path=f"{prefix}{name}"), binary=True, timeout=TIMEOUT_S
        )
        if status != 200 or not isinstance(body, str):
            raise ValueError(f"no {name} at {repo}/{prefix} ({status})")
        assets[name] = base64.b64decode(body)
    return manifest, sources, assets, sha


async def _resolve_commit(http: HttpFn, repo: str, ref: str) -> str:
    status, body = await http("GET", GITHUB_COMMIT_URL.format(repo=repo, ref=ref), headers=GITHUB_HEADERS, timeout=TIMEOUT_S)
    if status != 200 or not isinstance(body, dict) or not _SHA_PATTERN.match(str(body.get("sha", ""))):
        raise ValueError(f"GitHub could not resolve {repo}@{ref} ({status})")
    return str(body["sha"])


async def fetch_catalogue(http: HttpFn, url: str) -> list[dict[str, Any]]:
    """Reads the catalogue of reviewed plugins.

    Raises:
        RuntimeError: If the catalogue cannot be read.
    """
    status, body = await http("GET", url, timeout=TIMEOUT_S)
    if status != 200:
        raise RuntimeError(f"catalogue at {url} returned {status}")
    if not isinstance(body, dict) or not isinstance(body.get("plugins"), list):
        raise RuntimeError(f"catalogue at {url} is not a plugin catalogue")
    return [entry for entry in body["plugins"] if isinstance(entry, dict) and ID_PATTERN.match(str(entry.get("id", "")))]


def verified_by(catalogue: list[dict[str, Any]], plugin_id: str, hashed: dict[str, str]) -> dict[str, Any] | None:
    """Returns the catalogue entry vouching for these exact bytes, or None."""
    for entry in catalogue:
        if entry.get("id") == plugin_id and entry.get("digests") == hashed:
            return entry
    return None
