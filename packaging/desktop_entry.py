"""PyInstaller entry point that runs the desktop app as a package import.

Velopack's install, update and uninstall hooks run and exit before the app
opens, after ``freeze_support`` so a spawned window process never reaches them.
It never installs a downloaded release at launch by itself, since the engine
decides when that is, and a skipped release must stay uninstalled.
"""

from __future__ import annotations

import multiprocessing

import velopack

from printguard.server.desktop import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    velopack.App().set_auto_apply_on_startup(False).run()
    main()
