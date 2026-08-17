"""Desktop app that runs hub mode behind a tray icon on macOS and Windows.

Packaged with PyInstaller, this is the install-free, no-terminal way to run a hub
on a personal computer. The hub server and a system-tray icon live in this
process; the window runs in a child process, so closing the window ends only that
process while the tray and the engine keep running and the printer stays watched.
Quit from the tray. Linux is served by the container image. The hub's FastAPI
application is reused unchanged; only resource discovery and the window/process
lifecycle differ from the container entry point in :mod:`printguard.server.app`.
"""

from __future__ import annotations

import html
import io
import logging
import multiprocessing
import os
import signal
import socket
import sys
import threading
import time
from importlib import metadata
from pathlib import Path
from string import Template
from typing import Any

import platformdirs
import pystray
import uvicorn
import webview
from PIL import Image

from ..engine import logs

logger = logging.getLogger(__name__)

APP_NAME = "PrintGuard"
BUNDLE_ID = "io.printguard.desktop"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
READY_TIMEOUT_S = 30.0
STOP_TIMEOUT_S = 10.0
FAILURE_LOG_LINES = 30
WIN_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

FAILURE_PAGE = Template("""<!doctype html>
<meta charset="utf-8">
<title>PrintGuard</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 14px/1.6 -apple-system, "Segoe UI", system-ui, sans-serif; margin: 0; padding: 40px 44px; }
  h1 { font-size: 19px; margin: 0 0 14px; }
  p { margin: 0 0 14px; max-width: 62ch; }
  code { font-size: 13px; }
  pre { background: rgba(127, 127, 127, 0.14); border-radius: 10px; font-size: 12px; overflow: auto; padding: 16px; }
</style>
<h1>PrintGuard could not start</h1>
<p>Its server stopped while starting up, so there is nothing to show here and no printer is
being watched. The reason is at the end of the log below, kept in full at
<code>$log</code>.</p>
<p>Quit PrintGuard from its menu bar or system tray icon and open it again once the cause is
dealt with. If the log does not explain it, report it with the log attached at
<a href="https://github.com/oliverbravery/PrintGuard/issues">github.com/oliverbravery/PrintGuard/issues</a>.</p>
<pre>$log_tail</pre>
""")

PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
\t<key>Label</key><string>{label}</string>
\t<key>ProgramArguments</key><array>{args}</array>
\t<key>RunAtLoad</key><true/>
</dict>
</plist>
"""


def _configure_environment() -> None:
    """Points the hub at a per-user data directory and bundled read-only assets.

    The data directory is always a writable per-user location; the model, UI and
    MediaMTX assets come from the bundle when frozen and from the repository when
    running from source. The update asset names this platform's installer on each
    release, so the update dialog can offer it for download. ``setdefault`` leaves
    any explicit override in place.
    """
    data_dir = Path(platformdirs.user_data_dir(APP_NAME, APP_NAME))
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DATA_DIR", str(data_dir))
    os.environ.setdefault("LOG_FILE", str(data_dir / "printguard.log"))
    os.environ.setdefault(
        "UPDATE_ASSET", "PrintGuard-macos-arm64.dmg" if sys.platform == "darwin" else "PrintGuard-windows-x64.zip"
    )
    if not getattr(sys, "frozen", False):
        return
    bundle = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    os.environ.setdefault("MODEL_DIR", str(bundle / "models"))
    os.environ.setdefault("STATIC_DIR", str(bundle / "static"))
    os.environ.setdefault("MEDIAMTX_CONFIG", str(bundle / "mediamtx.yml"))
    os.environ.setdefault("MEDIAMTX_BINARY", str(bundle / ("mediamtx.exe" if os.name == "nt" else "mediamtx")))
    if sys.platform == "win32":
        os.environ.setdefault("APP_ICON", str(bundle / "icon.png"))


def _set_windows_app_id() -> None:
    """Ties this process to a stable AppUserModelID so Windows attributes its toasts.

    Windows groups a program's taskbar entry and its toast notifications by AppUserModelID;
    a frozen Python process has none of its own, so the desktop notifier's toasts would appear
    under a generic identity. Pinning it to the app name - the same id desktop-notifier registers
    the app icon against - gives those toasts PrintGuard's name and icon.
    """
    if sys.platform != "win32":
        return
    import ctypes

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(APP_NAME))


def _enable_wkwebview_camera() -> None:
    """Lets the macOS WKWebView use this device's camera for the "this device" source.

    WKWebView ships with the media-stream feature disabled, so ``navigator.mediaDevices``
    is undefined even on a secure localhost page and the UI reports the camera as blocked.
    Turn the WebKit media preferences on and auto-grant the capture permission that
    pywebview otherwise leaves unhandled (WebKit then defaults to deny); the bundle's
    ``NSCameraUsageDescription`` covers the macOS device-access prompt.
    """
    import objc
    from webview.platforms import cocoa

    media_preferences = ("mediaDevicesEnabled", "mediaStreamEnabled", "peerConnectionEnabled")
    host_class = cocoa.BrowserView.WebKitHost

    class WebKitHost(objc.Category(host_class)):
        def initWithFrame_configuration_(self, frame, configuration):
            preferences = configuration.preferences()
            for key in media_preferences:
                preferences.setValue_forKey_(True, key)
            return objc.super(host_class, self).initWithFrame_configuration_(frame, configuration)

    class BrowserDelegate(objc.Category(cocoa.BrowserView.BrowserDelegate)):
        def webView_requestMediaCapturePermissionForOrigin_initiatedByFrame_type_decisionHandler_(
            self, web_view, origin, frame, capture_type, decision_handler
        ):
            decision_handler(1)


def _run_webview(**contents: Any) -> None:
    """Child-process entry point that shows the hub, or why it is not there, in a native window.

    The window owns its process's main thread, so it never contends with the
    tray's, and closing it ends only this process. The webview must keep its
    website data between windows - pywebview's default private mode erases
    localStorage on every launch (on macOS it wipes the whole store), which
    would lose the page's record of which "this device" cameras it publishes,
    so a reopened window would never resume them.
    """
    if sys.platform == "darwin":
        _enable_wkwebview_camera()
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.create_window(APP_NAME, width=1280, height=820, **contents)
    webview.start(private_mode=False, storage_path=os.path.join(os.environ["DATA_DIR"], "webview"))


def _webview_url(port: int) -> str:
    return f"http://localhost:{port}/?v={metadata.version('printguard')}"


def _failure_page() -> str:
    """The page shown in place of the hub when its server never came up."""
    return FAILURE_PAGE.substitute(
        log=html.escape(os.environ["LOG_FILE"]), log_tail=html.escape("\n".join(logs.recent()[-FAILURE_LOG_LINES:]))
    )


class _Window:
    """Shows the hub window in a child process spawned from the tray."""

    def __init__(self, **contents: Any) -> None:
        self._contents = contents
        self._context = multiprocessing.get_context("spawn")
        self._process: multiprocessing.process.BaseProcess | None = None

    def open(self) -> None:
        """Opens the window, reusing the existing one if it is still up."""
        if self._process is None or not self._process.is_alive():
            self._process = self._context.Process(target=_run_webview, kwargs=self._contents, daemon=True)
            self._process.start()

    def close(self) -> None:
        """Closes the window if it is open."""
        if self._process is not None and self._process.is_alive():
            self._process.terminate()


class _Server:
    """Runs the hub's uvicorn server on a background daemon thread."""

    def __init__(self, port: int) -> None:
        from .app import create_app

        self._port = port
        config = uvicorn.Config(create_app(), host="0.0.0.0", port=port, log_config=None, access_log=False)
        self._server = uvicorn.Server(config)
        self._server.install_signal_handlers = lambda: None
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> bool:
        """Starts serving, blocks until startup completes, and reports whether it did.

        A startup that fails ends the serving thread, so the wait stops there
        instead of running the timeout out: what the window shows next depends on
        the answer, and the user should not sit in front of a blank one until then.
        """
        self._thread.start()
        deadline = time.monotonic() + READY_TIMEOUT_S
        while time.monotonic() < deadline and self._thread.is_alive() and not self._server.started:
            time.sleep(0.1)
        logger.info("hub server %s on :%d", "listening" if self._server.started else "did not start", self._port)
        return self._server.started

    def stop(self) -> None:
        """Asks the server to exit and waits for the thread to finish."""
        logger.info("hub server stopping")
        self._server.should_exit = True
        self._thread.join(timeout=STOP_TIMEOUT_S)


def _autostart_args() -> list[str]:
    """Command that relaunches this app, used by the platform's login service."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "printguard.server.desktop"]


def _macos_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{BUNDLE_ID}.plist"


def _autostart_enabled() -> bool:
    """Whether the app is registered to launch at login on this platform."""
    if sys.platform == "darwin":
        return _macos_plist().exists()
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WIN_RUN_KEY) as key:
                winreg.QueryValueEx(key, APP_NAME)
            return True
        except FileNotFoundError:
            return False
    return False


def _set_autostart(enabled: bool) -> None:
    """Registers or removes the login-launch entry for this platform."""
    if sys.platform == "darwin":
        path = _macos_plist()
        if enabled:
            args = "".join(f"<string>{arg}</string>" for arg in _autostart_args())
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(PLIST_TEMPLATE.format(label=BUNDLE_ID, args=args))
        else:
            path.unlink(missing_ok=True)
    elif sys.platform == "win32":
        import winreg

        command = " ".join(f'"{arg}"' if " " in arg else arg for arg in _autostart_args())
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WIN_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass


def _watch_termination(window: _Window, server: _Server) -> None:
    """Turns SIGTERM and Ctrl-C into the same clean shutdown as the tray's Quit.

    Without this, a kill or logout ends the process without stopping the window
    process or the MediaMTX child, leaving the streaming ports held by an orphan
    that makes the next launch crash-loop. Python-level signal handlers cannot do
    it: they only run when the main thread executes bytecode, and the Cocoa run
    loop owns the main thread. The C-level handler however always writes the
    signal number to the wakeup fd no matter which thread received the signal,
    so a reader thread performs the shutdown.
    """
    received, notify = socket.socketpair()
    notify.setblocking(False)
    signal.set_wakeup_fd(notify.fileno())
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: None)

    def wait() -> None:
        watched = {int(signal.SIGTERM), int(signal.SIGINT)}
        while received.recv(1)[0] not in watched:
            pass
        logger.info("termination signal received, shutting down")
        notify.close()
        window.close()
        server.stop()
        os._exit(0)

    threading.Thread(target=wait, daemon=True).start()


def _load_icon() -> Image.Image:
    """Loads the tray icon, reduced to a macOS menu-bar template silhouette.

    macOS status-bar icons are template images that the system tints for the light or dark
    menu bar, so the colour app icon is flattened to its opaque shape there to sit among the
    other status items; every other platform keeps the full-colour icon.
    """
    bundle = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else None  # type: ignore[attr-defined]
    path = (bundle / "icon.png") if bundle else (REPO_ROOT / "web" / "public" / "apple-touch-icon.png")
    icon = Image.open(path)
    if sys.platform != "darwin":
        return icon
    silhouette = icon.convert("L").point(lambda level: max(0, min(255, (level - 16) * 12)))
    template = Image.new("RGBA", icon.size, (0, 0, 0, 0))
    template.putalpha(silhouette)
    return template


def _show_tray(icon: pystray.Icon) -> None:
    """Reveals the tray icon, rebuilding it as a crisp macOS menu-bar template.

    pystray sizes the status-bar NSImage to the menu-bar thickness in pixels, so on Retina it
    is upscaled and blurry and it carries no template flag. Rebuild it from the full-resolution
    silhouette, cap its point size to the menu-bar thickness so macOS keeps the surplus pixels
    for high-DPI, and tag it as a template so it adapts to the light or dark menu bar. A
    ``setup`` callback owns making the icon visible.
    """
    icon.visible = True
    if sys.platform != "darwin":
        return
    import AppKit
    import Foundation

    buffer = io.BytesIO()
    icon._icon.save(buffer, "png")
    image = AppKit.NSImage.alloc().initWithData_(Foundation.NSData(buffer.getvalue()))
    thickness = icon._status_bar.thickness()
    image.setSize_(AppKit.NSMakeSize(thickness, thickness))
    image.setTemplate_(True)
    icon._status_item.button().setImage_(image)


def main() -> None:
    """Console entry point that serves the hub behind a tray icon on the main thread.

    The window runs in a child process; closing it leaves the tray and the hub
    server running so the printer stays watched, and the tray's Quit exits.
    """
    _configure_environment()
    _set_windows_app_id()
    logs.setup_from_env()
    logger.info("desktop app starting (frozen=%s, data=%s)", getattr(sys, "frozen", False), os.environ["DATA_DIR"])
    port = int(os.environ.get("PORT", "8000"))
    server = _Server(port)
    window = _Window(url=_webview_url(port)) if server.start() else _Window(html=_failure_page())
    window.open()
    if sys.platform == "darwin":
        _watch_termination(window, server)

    def open_window(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        window.open()

    def toggle_autostart(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        _set_autostart(not _autostart_enabled())

    def quit_app(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        logger.info("quit from tray")
        window.close()
        server.stop()
        icon.stop()

    icon = pystray.Icon(
        APP_NAME,
        _load_icon(),
        APP_NAME,
        menu=pystray.Menu(
            pystray.MenuItem("Open PrintGuard", open_window, default=True),
            pystray.MenuItem("Start at login", toggle_autostart, checked=lambda item: _autostart_enabled()),
            pystray.MenuItem("Quit", quit_app),
        ),
    )
    icon.run(setup=_show_tray)


if __name__ == "__main__":
    main()
