"""Desktop app: runs hub mode behind a tray icon on macOS and Windows.

Packaged with PyInstaller, this is the install-free, no-terminal way to run a hub
on a personal computer. The hub server and a system-tray icon live in this
process; the window runs in a child process, so closing the window ends only that
process while the tray and the engine keep running and the printer stays watched.
Quit from the tray. Linux is served by the container image. The hub's FastAPI
application is reused unchanged; only resource discovery and the window/process
lifecycle differ from the container entry point in :mod:`printguard.server.app`.
"""

from __future__ import annotations

import io
import multiprocessing
import os
import sys
import threading
import time
from pathlib import Path

import platformdirs
import pystray
import uvicorn
import webview
from PIL import Image

APP_NAME = "PrintGuard"
BUNDLE_ID = "io.printguard.desktop"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
READY_TIMEOUT_S = 30.0
STOP_TIMEOUT_S = 10.0
WIN_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

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
    running from source. ``setdefault`` leaves any explicit override in place.
    """
    data_dir = Path(platformdirs.user_data_dir(APP_NAME, APP_NAME))
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DATA_DIR", str(data_dir))
    if not getattr(sys, "frozen", False):
        return
    bundle = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    os.environ.setdefault("MODEL_DIR", str(bundle / "models"))
    os.environ.setdefault("STATIC_DIR", str(bundle / "static"))
    os.environ.setdefault("MEDIAMTX_CONFIG", str(bundle / "mediamtx.yml"))
    os.environ.setdefault("MEDIAMTX_BINARY", str(bundle / ("mediamtx.exe" if os.name == "nt" else "mediamtx")))


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


def _run_webview(url: str) -> None:
    """Child-process entry point: shows the hub in a native window.

    The window owns its process's main thread, so it never contends with the
    tray's, and closing it ends only this process.
    """
    if sys.platform == "darwin":
        _enable_wkwebview_camera()
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.create_window(APP_NAME, url, width=1280, height=820)
    webview.start()


class _Window:
    """Shows the hub window in a child process spawned from the tray."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._context = multiprocessing.get_context("spawn")
        self._process: multiprocessing.process.BaseProcess | None = None

    def open(self) -> None:
        """Opens the window, reusing the existing one if it is still up."""
        if self._process is None or not self._process.is_alive():
            self._process = self._context.Process(target=_run_webview, args=(self._url,), daemon=True)
            self._process.start()

    def close(self) -> None:
        """Closes the window if it is open."""
        if self._process is not None and self._process.is_alive():
            self._process.terminate()


class _Server:
    """Runs the hub's uvicorn server on a background daemon thread."""

    def __init__(self, port: int) -> None:
        from .app import create_app

        config = uvicorn.Config(create_app(), host="0.0.0.0", port=port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._server.install_signal_handlers = lambda: None
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> None:
        """Starts serving and blocks until startup (engine and streamer) completes."""
        self._thread.start()
        deadline = time.monotonic() + READY_TIMEOUT_S
        while time.monotonic() < deadline and not self._server.started:
            time.sleep(0.1)

    def stop(self) -> None:
        """Asks the server to exit and waits for the thread to finish."""
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
    """Console entry point: serves the hub behind a tray icon on the main thread.

    The window runs in a child process; closing it leaves the tray and the hub
    server running so the printer stays watched, and the tray's Quit exits.
    """
    _configure_environment()
    port = int(os.environ.get("PORT", "8000"))
    server = _Server(port)
    server.start()
    window = _Window(f"http://localhost:{port}")
    window.open()

    def open_window(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        window.open()

    def toggle_autostart(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        _set_autostart(not _autostart_enabled())

    def quit_app(icon: pystray.Icon, item: pystray.MenuItem) -> None:
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
