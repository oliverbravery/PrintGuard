"""Rewrites the plugin catalogue from what is committed in this repository.

Each entry pins the commit that last touched the plugin plus the SHA-256 of its
manifest and every source file, which is what makes a plugin show as verified.
Commit the plugin first: a pin has to describe bytes that are already in
history.

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


def entry(directory: Path) -> dict:
    """Builds one catalogue entry for a plugin directory."""
    manifest = plugins.sanitise_manifest(json.loads((directory / plugins.MANIFEST_FILE).read_text()))
    sources = {
        name: (directory / name).read_text() for name in plugins.SOURCE_FILES if (directory / name).exists()
    }
    return {
        "id": manifest["id"],
        "name": manifest["name"],
        "description": manifest["description"],
        "author": manifest["author"],
        "version": manifest["version"],
        "permissions": manifest["permissions"],
        "surfaces": manifest["surfaces"],
        "platforms": manifest["platforms"],
        "repo": REPO,
        "path": f"plugins/{directory.name}",
        "ref": last_commit(directory),
        "digests": plugins.digests(manifest, plugins.sanitise_sources(sources)),
    }


def main() -> None:
    entries = [entry(d) for d in sorted(HERE.iterdir()) if (d / plugins.MANIFEST_FILE).exists()]
    CATALOGUE.write_text(json.dumps({"version": 1, "plugins": entries}, indent=2) + "\n")
    print(f"pinned {len(entries)} plugin(s) into {CATALOGUE}")


if __name__ == "__main__":
    main()
