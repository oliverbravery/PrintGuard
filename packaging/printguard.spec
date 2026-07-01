# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the PrintGuard desktop app.

Set ``MEDIAMTX_BUNDLE`` to the path of a MediaMTX binary to ship video streaming,
and ``PRINTGUARD_ICON`` to a platform icon (.icns / .ico). The web UI must be built
into ``web/dist`` and the model present in ``models`` before building.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent
ICON = os.environ.get("PRINTGUARD_ICON") or None
MEDIAMTX = os.environ.get("MEDIAMTX_BUNDLE")

staging = Path(tempfile.mkdtemp(prefix="printguard-build-"))
icon_png = staging / "icon.png"
shutil.copyfile(ROOT / "web" / "public" / "apple-touch-icon.png", icon_png)

binaries = collect_dynamic_libs("av") + collect_dynamic_libs("ai_edge_litert")
if MEDIAMTX:
    binaries.append((MEDIAMTX, "."))

datas = [
    (str(ROOT / "models"), "models"),
    (str(ROOT / "mediamtx.yml"), "."),
    (str(ROOT / "web" / "dist"), "static"),
    (str(icon_png), "."),
    (str(ROOT / "printguard" / "__init__.py"), "printguard"),
    (str(ROOT / "printguard" / "engine"), "printguard/engine"),
    (str(ROOT / "printguard" / "browser"), "printguard/browser"),
]
datas += copy_metadata("printguard") + copy_metadata("fastmcp", recursive=True)

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("av")
    + collect_submodules("fastmcp.server")
    + collect_submodules("mcp.server")
    + ["ai_edge_litert.interpreter"]
)

if sys.platform == "win32":
    clr_datas, clr_binaries, clr_hidden = collect_all("clr_loader")
    datas += clr_datas + copy_metadata("pythonnet")
    binaries += clr_binaries
    hiddenimports += clr_hidden + ["clr"]

a = Analysis(
    [str(Path(SPECPATH) / "desktop_entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, exclude_binaries=True, name="PrintGuard", console=False, icon=ICON)
coll = COLLECT(exe, a.binaries, a.datas, name="PrintGuard")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="PrintGuard.app",
        icon=ICON,
        bundle_identifier="io.printguard.desktop",
        info_plist={
            "CFBundleName": "PrintGuard",
            "NSHighResolutionCapable": True,
            "LSUIElement": True,
            "NSCameraUsageDescription": "PrintGuard watches this device's camera for print defects.",
        },
    )
