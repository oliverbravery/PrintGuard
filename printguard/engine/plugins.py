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

from . import urls
from .adapters import HttpFn

MANIFEST_FILE = "plugin.json"
SOURCE_FILES = ("plugin.js", "worker.js")
MAX_ASSET_BYTES = 256 * 1024
MAX_ASSETS_BYTES = 1024 * 1024
SURFACES = ("panel", "monitor", "settings")
MAX_SOURCE_BYTES = 64 * 1024
MAX_CONFIG_BYTES = 16 * 1024
MIN_TICK_S = 5.0
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
        for one no plugin may hook. A state event comes back as the projection
        the grants allow, so a plugin watching it reads what it gets on
        ``ctx.state`` rather than the whole snapshot.
    """
    name = str(event.get("event", ""))
    fields = EVENTS.get(name)
    if fields is None:
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
        if starts and not data.startswith(starts):
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
    events = sorted({str(e).strip() for e in raw.get("events", [])} & set(EVENTS))
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
        "events": events,
        "tick_s": min(tick_s, 86400.0) if tick_s >= MIN_TICK_S else 0.0,
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
    """
    fields = request if isinstance(request, dict) else {}
    return {
        "cmd": "plugin.http",
        "method": str(fields.get("method", "GET")),
        "url": str(fields.get("url", "")),
        "headers": fields.get("headers"),
        "json": fields.get("json"),
        "tag": str(fields.get("tag", "")),
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
