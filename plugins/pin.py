"""Rewrites the plugin catalogue from what is committed in this repository.

Each entry pins the commit that last touched the plugin plus the SHA-256 of its
manifest and every source file, which is what makes a plugin show as verified.
Commit the plugin first: a pin has to describe bytes that are already in
history.

Every plugin is read against its own manifest before it is pinned, so a listed
plugin is one whose code and its claims agree. Anything the check cannot decide
from the code is reported rather than pinned over.

    uv run python plugins/pin.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from printguard.engine import plugins  # noqa: E402

HERE = Path(__file__).parent
WEB = HERE.parent / "web"
REPO = "oliverbravery/PrintGuard"
CATALOGUE = HERE / "catalogue.json"


def last_commit(path: Path) -> str:
    """The commit that last changed a plugin directory."""
    sha = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", str(path)], capture_output=True, text=True, check=True
    ).stdout.strip()
    if not sha:
        raise SystemExit(f"{path} is not committed yet")
    return sha


def findings(manifest: dict, sources: dict[str, str]) -> list[dict]:
    """Reads a plugin's code and reports where it disagrees with its manifest.

    Args:
        manifest: The validated manifest.
        sources: The plugin's source files as text.

    Returns:
        One entry per finding, each naming what it is and what it is about.

    Raises:
        SystemExit: If the checker could not run at all, since pinning a plugin
            nobody has read is the thing this exists to stop.
    """
    bundle = json.dumps({
        "manifest": manifest,
        "sources": sources,
        "permissions": plugins.permissions_meta(),
        "event_permissions": plugins.EVENT_PERMISSIONS,
    })
    result = subprocess.run(
        ["npm", "run", "--silent", "lint:plugin", "--", "/dev/stdin"], input=bundle, cwd=WEB, capture_output=True, text=True
    )
    if result.returncode:
        raise SystemExit(f"could not check {manifest['id']}, run npm install in web/ first\n{result.stderr.strip()}")
    return json.loads(result.stdout)


def entry(directory: Path) -> dict:
    """Builds one catalogue entry for a plugin directory."""
    manifest = plugins.sanitise_manifest(json.loads((directory / plugins.MANIFEST_FILE).read_text()))
    sources = {
        name: (directory / name).read_text() for name in plugins.SOURCE_FILES if (directory / name).exists()
    }
    assets = plugins.sanitise_assets({name: (directory / name).read_bytes() for name in manifest["assets"]})
    found = findings(manifest, sources)
    disagreements = [f for f in found if f["kind"] != "dynamic"]
    if disagreements:
        raise SystemExit(
            f"{manifest['id']} does not do what it says:\n"
            + "\n".join(f"  {f['kind']}: {f['what']}" for f in disagreements)
        )
    for unknowable in [f for f in found if f["kind"] == "dynamic"]:
        print(f"{manifest['id']}: {unknowable['what']}")
    return {
        "id": manifest["id"],
        "name": manifest["name"],
        "description": manifest["description"],
        "author": manifest["author"],
        "version": manifest["version"],
        "icon": manifest["icon"],
        "media": manifest["media"],
        "permissions": manifest["permissions"],
        "surfaces": manifest["surfaces"],
        "platforms": manifest["platforms"],
        "repo": REPO,
        "path": f"plugins/{directory.name}",
        "ref": last_commit(directory),
        "digests": plugins.digests(manifest, plugins.sanitise_sources(sources), assets),
    }


def main() -> None:
    entries = [entry(d) for d in sorted(HERE.iterdir()) if (d / plugins.MANIFEST_FILE).exists()]
    CATALOGUE.write_text(json.dumps({"version": 1, "plugins": entries}, indent=2) + "\n")
    print(f"pinned {len(entries)} plugin(s) into {CATALOGUE}")


if __name__ == "__main__":
    main()
