"""Builds the Python source archive that local mode unpacks in Pyodide.

The hub serves it from memory at /pysrc.zip; static deployments (GitHub
Pages) generate the same archive at build time:

    python printguard/pysrc.py web/public/pysrc.zip
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parent


def build_pysrc() -> bytes:
    """Zips the shared engine and browser platform source for Pyodide.

    A frozen desktop build ships compiled modules so the
    source is read from the PyInstaller extraction directory where the spec
    bundles it rather than from this module's location.
    """
    root = Path(sys._MEIPASS) / "printguard" if getattr(sys, "frozen", False) else PACKAGE_ROOT  # type: ignore[attr-defined]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(root / "__init__.py", "printguard/__init__.py")
        for module_dir in ("engine", "browser"):
            for path in sorted((root / module_dir).rglob("*.py")):
                archive.write(path, f"printguard/{path.relative_to(root)}")
    return buffer.getvalue()


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(build_pysrc())
    print(f"wrote {out} ({out.stat().st_size} bytes)")
