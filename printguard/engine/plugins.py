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

import hashlib
import io
import json
import re
import zipfile
from typing import Any
from urllib.parse import urlsplit

from .adapters import HttpFn

MANIFEST_FILE = "plugin.json"
SOURCE_FILES = ("plugin.js", "worker.js")
SURFACES = ("panel", "float")
MAX_SOURCE_BYTES = 64 * 1024
MAX_CONFIG_BYTES = 16 * 1024
MIN_TICK_S = 5.0
CATALOGUE_URL = "https://raw.githubusercontent.com/oliverbravery/PrintGuard/main/plugins/catalogue.json"
GITHUB_COMMIT_URL = "https://api.github.com/repos/{repo}/commits/{ref}"
GITHUB_RAW_URL = "https://raw.githubusercontent.com/{repo}/{sha}/{path}"
GITHUB_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
TIMEOUT_S = 20.0

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")
_REPO_PATTERN = re.compile(r"^[\w.-]+/[\w.-]+$")
_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_PATH_PATTERN = re.compile(r"^[\w./-]*$")
_VERSION_PATTERN = re.compile(r"^[\w.+-]{1,32}$")

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
    "net": {
        "label": "Reach the internet",
        "description": "Send requests to the hosts the plugin lists, and nowhere else.",
        "hosts": True,
    },
    "routes": {
        "label": "Serve its own pages",
        "description": "Answer requests under /plugins/<id>/ on the hub.",
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


def canonical(value: Any) -> bytes:
    """Encodes a manifest the one way both ends agree to hash it.

    The platform's HTTP function returns parsed JSON in both modes and never
    the bytes it came from, so a manifest is pinned by the hash of its
    canonical form rather than of the file as written.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digests(manifest: dict[str, Any], sources: dict[str, str]) -> dict[str, str]:
    """Hashes a bundle: the canonical manifest and each source file."""
    hashed = {MANIFEST_FILE: hashlib.sha256(canonical(manifest)).hexdigest()}
    hashed.update({name: hashlib.sha256(code.encode()).hexdigest() for name, code in sources.items()})
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
    if not _ID_PATTERN.match(plugin_id):
        raise ValueError("plugin id must be 3-40 lowercase letters, digits or hyphens")
    version = str(raw.get("version", "")).strip()
    if not _VERSION_PATTERN.match(version):
        raise ValueError("plugin version is missing or unusable")
    surfaces = [s for s in raw.get("surfaces", []) if s in SURFACES] or ["panel"]
    hosts = sorted({str(h).strip().lower() for h in raw.get("hosts", []) if str(h).strip()})
    events = sorted({str(e).strip() for e in raw.get("events", []) if str(e).strip()})
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
        "permissions": [p for p in PERMISSIONS if p in raw.get("permissions", [])],
        "surfaces": surfaces,
        "hosts": hosts,
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


def host_allowed(url: str, hosts: list[str]) -> bool:
    """Whether a URL targets one of the hosts a plugin declared."""
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        return False
    return parsed.hostname is not None and parsed.hostname.lower() in hosts


def unpack(data: bytes) -> tuple[dict[str, Any], dict[str, str]]:
    """Reads a manifest and sources out of a zipped plugin bundle.

    Files may sit at the root or under a single directory, which is what a
    repository archive downloaded from GitHub looks like.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("not a zip archive") from exc
    wanted = (MANIFEST_FILE, *SOURCE_FILES)
    found: dict[str, str] = {}
    for entry in archive.namelist():
        name = entry.rsplit("/", 1)[-1]
        if name in wanted and name not in found and archive.getinfo(entry).file_size <= MAX_SOURCE_BYTES:
            found[name] = archive.read(entry).decode("utf-8", "replace")
    if MANIFEST_FILE not in found:
        raise ValueError(f"bundle has no {MANIFEST_FILE}")
    return json.loads(found.pop(MANIFEST_FILE)), found


async def fetch_github(http: HttpFn, repo: str, path: str, ref: str) -> tuple[dict[str, Any], dict[str, str], str]:
    """Downloads a plugin from a GitHub repository at an immutable commit.

    A branch or tag is resolved to its commit SHA first, so what gets hashed
    is a specific revision rather than whatever the branch points at later.

    Args:
        http: Platform HTTP function.
        repo: GitHub ``owner/name``.
        path: Directory inside the repository holding the plugin, or "".
        ref: Branch, tag or commit SHA.

    Returns:
        The parsed manifest, the source files, and the resolved commit SHA.

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
    return manifest, sources, sha


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
    if status != 200 or not isinstance(body, dict) or not isinstance(body.get("plugins"), list):
        raise RuntimeError(f"catalogue at {url} returned {status}")
    return [entry for entry in body["plugins"] if isinstance(entry, dict) and _ID_PATTERN.match(str(entry.get("id", "")))]


def verified_by(catalogue: list[dict[str, Any]], plugin_id: str, hashed: dict[str, str]) -> dict[str, Any] | None:
    """Returns the catalogue entry vouching for these exact bytes, or None."""
    for entry in catalogue:
        if entry.get("id") == plugin_id and entry.get("digests") == hashed:
            return entry
    return None
