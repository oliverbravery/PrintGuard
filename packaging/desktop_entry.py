"""PyInstaller entry point that runs the desktop app as a package import."""

from __future__ import annotations

import multiprocessing

from printguard.server.desktop import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
