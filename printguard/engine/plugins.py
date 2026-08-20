"""Plugin sourcing, verification and the permission table.

A plugin is plain JavaScript: ``plugin.js`` draws a panel in the UI and
``worker.js`` runs in the background. Neither ever runs here - this module only
fetches the source, validates the manifest, hashes what it got and checks that
hash against the catalogue of reviewed plugins. Execution happens in a sandbox
on each side: an opaque-origin iframe in the browser, QuickJS compiled to
WebAssembly on the hub.

Permissions live here as data. The UI and the hub runtime both enforce them at
their own sandbox edge, because by the time a command reaches the engine it is
indistinguishable from one the dashboard sent.
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
SECRET_REFERENCE = re.compile(r"\{\{\s*secret\.([a-z0-9_-]{1,40})\s*\}\}")
"""How a plugin names a secret it may use but never read.

The value is substituted as the request leaves PrintGuard, so the reference is
all the plugin ever holds and all that is ever stored in anything it can read.
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

PERMISSIONS: dict[str, dict[str, Any]] = {
    "state:read": {
        "label": "Read the dashboard",
        "description": "Monitor names, scores and alerts, camera and printer names and status. Never credentials or tokens.",
        "fields": {
            "monitors": ["id", "name", "camera_id", "printer_id", "enabled", "watching", "threshold", "result", "alert"],
            "cameras": ["id", "name", "online", "standby", "in_use", "max_fps", "achieved_fps"],
            "printers": ["id", "name", "provider", "online", "device_state"],
        },
    },
    "camera:view": {
        "label": "Show live camera feeds",
        "description": "Place a camera feed in its own panel. The plugin never receives the video itself.",
    },
    "monitor:control": {
        "label": "Change monitors",
        "description": "Enable, disable and retune any monitor, including its defect threshold.",
        "commands": ["monitor.update"],
        "risky": True,
    },
    "monitor:manage": {
        "label": "Add and remove monitors",
        "description": "Set up new monitors and delete existing ones, losing their history with them.",
        "commands": ["monitor.add", "monitor.remove"],
        "risky": True,
    },
    "camera:control": {
        "label": "Retune cameras",
        "description": "Change any camera's brightness, contrast, sharpness, crop, rotation and frame rate.",
        "commands": ["camera.update"],
    },
    "camera:manage": {
        "label": "Add and remove cameras",
        "description": "Register new cameras and delete existing ones.",
        "commands": ["camera.add", "camera.remove", "discover"],
        "risky": True,
    },
    "camera:frames": {
        "label": "Read your camera images",
        "description": "Take a still from any camera and hand it to the plugin. This is the picture itself, so a plugin holding this and a way out can send your images anywhere.",
        "commands": ["camera.snapshot"],
        "risky": True,
    },
    "history:read": {
        "label": "Read risk history",
        "description": "How each monitor's defect score has moved over time, and when it alerted.",
        "commands": ["history.get"],
    },
    "printer:manage": {
        "label": "Add and remove printers",
        "description": "Connect new printers and delete existing ones. It supplies the credentials and can never read back one already stored.",
        "commands": ["printer.add", "printer.update", "printer.remove", "printer.test", "printer.cameras.refresh"],
        "fields": {"integrations": ["id", "label", "schema", "docs_url", "setup_url", "setup_hint", "experimental"]},
        "risky": True,
    },
    "settings": {
        "label": "Change your settings",
        "description": "Alert channels, theme, Home Assistant and the rest of Settings. It can never read back a credential already stored.",
        "commands": ["settings.update", "notify.test"],
        "fields": {"notifiers": ["id", "label", "schema", "docs_url", "setup_url", "setup_hint", "browser_ok"]},
        "risky": True,
    },
    "tokens": {
        "label": "Manage API tokens",
        "description": "Mint and revoke tokens for the API. It never sees the secret of one it minted, nor of any that already exists.",
        "commands": ["token.create", "token.remove"],
        "risky": True,
    },
    "printer:control": {
        "label": "Control printers",
        "description": "Pause, resume and cancel prints on any connected printer.",
        "commands": ["printer.action"],
        "risky": True,
    },
    "notify": {
        "label": "Show notifications",
        "description": "Raise a message in this dashboard. Does not use your alert channels.",
    },
    "sound": {
        "label": "Play a sound",
        "description": "Sound a short alert through this device's speakers, once you have pressed something.",
    },
    "alert:send": {
        "label": "Use your alert channels",
        "description": "Send a message through the same ntfy, Telegram or Discord your defect alerts use, so it reaches your phone.",
        "commands": ["notify.send"],
        "risky": True,
    },
    "net": {
        "label": "Reach the internet",
        "description": "Send requests to the addresses the plugin lists, and nowhere else.",
        "urls": True,
    },
    "net:local": {
        "label": "Reach your own network",
        "description": "Send requests to addresses on this machine and the network around it, such as a printer or a hub of your own.",
        "urls": True,
        "risky": True,
    },
    "oauth": {
        "label": "Connect an account",
        "description": "Sign you in to the service it names and hold the result. PrintGuard keeps the tokens; the plugin only ever gets to use them.",
        "risky": True,
    },
    "background": {
        "label": "Paint the dashboard's background",
        "description": "Put a picture behind the dashboard and make the panels see-through over it. It changes how PrintGuard looks and nothing else.",
    },
    "link:provide": {
        "label": "Answer other plugins",
        "description": "Offer the channels it lists to other plugins you have installed, so they can ask it for something or hear what it publishes.",
    },
    "link:consume": {
        "label": "Talk to other plugins",
        "description": "Ask the plugins and channels it names for something, and hear what they publish. It reaches nothing they do not offer.",
        "channels": True,
    },
    "routes": {
        "label": "Serve its own pages",
        "description": "Answer requests under /plugins/<id>/ on the hub, reading the headers each one carries, including your session cookie.",
        "hub_only": True,
    },
    "gate": {
        "label": "Authorise every request",
        "description": "See and approve or refuse every request to the hub, including the dashboard and the API. A plugin holding this can lock you out.",
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
"""What a plugin may ship beside its code, and the type each is handed over as.

An allowlist rather than a blocklist, since the dangerous formats are the ones
nobody thinks of. SVG is not here because it is markup wearing an image's
extension, and the type is the one this table gives, never the one the file
claims.
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

An id extends the one before its hyphen, so a plugin naming ``docker`` runs on
every image and one naming ``docker-nvidia`` runs only on that one. A plugin
naming none of them runs everywhere.
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

Engine events carry far more than a plugin's grants allow, a printer's
credentials in a state snapshot or a new API token's secret, so a plugin is
handed these fields and nothing else, and an event missing from here never
reaches one at all.
"""

EVENT_PERMISSIONS: dict[str, str] = {
    "state": "state:read",
    "frame": "camera:frames",
    "history": "history:read",
    "call": "link:provide",
    "answer": "link:consume",
    "message": "link:consume",
}
"""Events carrying something a permission covers, and which one that is.

An event is broadcast to every plugin that named it, so one carrying a camera
still or a monitor's history has to be held to the same grant the command that
asked for it needed. Without this a plugin could name the event, wait for
somebody else to ask, and read the answer.
"""


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

    Everything is dropped unless a permission names it, so a field added to
    the snapshot later is invisible to plugins until it is listed here. The UI
    applies the same table, which it reads from ``permissions_meta()``.
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
        The event carrying only the fields ``EVENTS`` lists for it, or None
        for one no plugin may hook and for one this plugin has not been granted.
        A state event comes back as the projection the grants allow, so a plugin
        watching it reads what it gets on ``ctx.state`` rather than the whole
        snapshot.
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

    The platform's HTTP function returns parsed JSON in both modes and never
    the bytes it came from, so a manifest is pinned by the hash of its
    canonical form rather than of the file as written.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digests(manifest: dict[str, Any], sources: dict[str, str], assets: dict[str, str]) -> dict[str, str]:
    """Hashes a bundle, the canonical manifest and every file that came with it."""
    hashed = {MANIFEST_FILE: hashlib.sha256(canonical(manifest)).hexdigest()}
    hashed.update({name: hashlib.sha256(code.encode()).hexdigest() for name, code in sources.items()})
    hashed.update({name: hashlib.sha256(base64.b64decode(data)).hexdigest() for name, data in assets.items()})
    return hashed


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
    declared = raw.get("secrets") if isinstance(raw.get("secrets"), dict) else {}
    secrets = {str(name).strip().lower(): str(why).strip()[:200] for name, why in list(declared.items())[:MAX_SECRETS]}
    if any(not SECRET_REFERENCE.match("{{secret.%s}}" % name) or not why for name, why in secrets.items()):
        raise ValueError("each secret needs a short name and a line saying what it is")
    offered = raw.get("provides") if isinstance(raw.get("provides"), dict) else {}
    provides = {str(name).strip().lower(): str(why).strip()[:200] for name, why in list(offered.items())[:MAX_CHANNELS]}
    if any(not CHANNEL_PATTERN.match(name) or not why for name, why in provides.items()):
        raise ValueError("each channel in provides needs a short name and a line saying what it answers")
    consumes = sorted({str(link).strip().lower() for link in raw.get("consumes", []) if str(link).strip()})[:MAX_CONSUMES]
    if any(not LINK_PATTERN.match(link) for link in consumes):
        raise ValueError("each entry in consumes names a plugin and a channel, as plugin-id:channel")
    if provides and "link:provide" not in permissions:
        raise ValueError("provides needs the link:provide permission")
    if consumes and "link:consume" not in permissions:
        raise ValueError("consumes needs the link:consume permission")
    sign_in = sanitise_oauth(raw.get("oauth"))
    if sign_in and "oauth" not in permissions:
        raise ValueError("oauth needs the oauth permission")
    if sign_in:
        secrets[oauth.CLIENT_ID] = f"The client id of the {sign_in['label']} app you registered"
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
        "homepage": str(raw.get("homepage", "")).strip()[:200],
        "permissions": permissions,
        "reasons": reasons,
        "surfaces": surfaces,
        "platforms": platforms,
        "assets": assets,
        "urls": patterns,
        "secrets": secrets,
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

    The plugin's id is set last, as it is for a request, so a sandbox cannot
    spread over the command and speak as somebody else.
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


def sanitise_oauth(raw: Any) -> dict[str, Any]:
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
        "register_url": str(raw.get("register_url", "")).strip()[:200],
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

    Only these fields are carried over, and the plugin's id is set last: the
    request comes from inside a sandbox, so left to spread over the command it
    could name a *different* installed plugin and borrow its network grant.
    ``binary`` asks for the answer base64 encoded, which is how a picture gets
    back to a plugin that has no way of its own to fetch one.
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


def unpack(data: bytes) -> tuple[dict[str, Any], dict[str, str], dict[str, bytes]]:
    """Reads a manifest, sources and declared assets out of a zipped bundle.

    Files may sit at the root or under a single directory, which is what a
    repository archive downloaded from GitHub looks like.

    Args:
        data: The zip as uploaded.

    Returns:
        The parsed manifest, the source files as text, and every asset the
        manifest declared as bytes.

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

    def read(name: str, cap: int) -> bytes:
        entry = entries[name]
        if archive.getinfo(entry).file_size > cap:
            raise ValueError(f"{name} is larger than {cap // 1024} KB")
        return archive.read(entry)

    manifest = json.loads(read(MANIFEST_FILE, MAX_SOURCE_BYTES))
    sources = {name: read(name, MAX_SOURCE_BYTES).decode("utf-8", "replace") for name in SOURCE_FILES if name in entries}
    declared = {str(name).strip().lower() for name in manifest.get("assets", []) if isinstance(manifest, dict)}
    assets = {name: read(name, MAX_ASSET_BYTES) for name in sorted(declared) if name in entries}
    return manifest, sources, assets


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
