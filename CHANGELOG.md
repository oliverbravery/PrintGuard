# Changelog

All notable changes to PrintGuard are documented in this file, by hand, in the pull
request that ships them. Each version's section is published verbatim as its GitHub
release notes.

The format is [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.3.0] - 2026-06-30

### Added

- **A desktop app for macOS and Windows — run a hub as an application.** PrintGuard now ships as a
  native app that runs the full hub from your menu bar / system tray. Close the window and the hub
  keeps watching, so it covers the multi-hour prints that matter; quit from the tray. Reach it from
  your phone on the same network at `http://<computer>:8000`. Detection still runs entirely on
  your own machine; no frame leaves your hardware. Turn on **Start at login** and forget about it.
  Download it from the landing page or the
  [Releases page](https://github.com/oliverbravery/PrintGuard/releases) — the builds are unsigned for
  now, so the first launch needs a right-click → **Open** on macOS, or **More info → Run anyway** on
  Windows. On Linux, run the Docker hub as before.

## [2.2.2] - 2026-06-26

### Fixed

- **Bambu A1, A1 mini, P1P and P1S chamber cameras now show up on the dashboard.** Adding one of
  these printers registered the printer but not its chamber camera — PrintGuard kept probing the
  live camera stream instead of opening it, so no camera and no video appeared. The stream now
  opens on its first frame and the camera registers like any other. (X1- and H2-series cameras use
  RTSP and were never affected.)

## [2.2.1] - 2026-06-25

### Changed

- **One container, no second image, no terminal needed.** PrintGuard now ships as a **single
  image** with the streaming server built in — there is no separate MediaMTX container to install
  and no specific version of it to track down (the sticking point on Unraid and similar). Install
  it with a single `docker run`, the now one-service `docker-compose.yaml`, or **one click from
  Unraid Community Applications**. The hub still serves everything — dashboard, live video and all
  — on `:8000`; the camera-publish ports `8554`/`1935` are optional and only matter if a camera
  pushes a stream into PrintGuard. To put it on your network your own way — private over Tailscale,
  public behind Cloudflare Access or an auth proxy — see the deployment guide.

  *Upgrading from the two-container setup?* Pull the new image and remove the `mediamtx` service
  (and its `mediamtx.yml` mount) from your compose file — the built-in server replaces it. Your
  `/data` volume and settings carry over untouched.

- **Settings now save themselves.** Camera image adjustments (brightness, contrast, sharpness,
  rotation, crop) and monitor settings (thresholds, sensitivity, defect response, notifications)
  now apply **live everywhere the moment you change them** — the camera preview, dashboard tiles
  and risk gauges update as you drag, with no **Save** button to remember. A small **saved ✓**
  indicator confirms each change is stored, and anything still in flight is saved automatically
  when you close the panel. Notification channels, printers and Home Assistant (MQTT) keep an
  explicit **Save**, since they hold credentials or open a live connection and shouldn't act on
  half-typed input.

## [2.2.0] - 2026-06-25

### Added

- **Built-in guide and a setup checklist** — a new **?** in the header opens a Guide that explains
  every part of PrintGuard — cameras, printers, monitors, how detection and alerts work, and what
  you can automate — each with a shortcut that jumps straight to the right place. Until your first
  monitor is watching, the dashboard shows a **Getting started** checklist that tracks your progress
  from camera to printer to alerts to monitor, so you always know what to do next. Works the same in
  local (in-browser) mode.
- **Light, dark and custom themes** — pick **System** (follows your device), **Light** or
  **Dark** from the new header toggle or **Settings → Appearance**, or design your own. The
  theme editor lets you set every colour — surfaces, text, lines and the accent/ok/warn/bad
  status colours — with a live preview as you go, and your themes are saved and synced to every
  browser that opens the hub. The selection defaults to System, so each device follows its own
  light/dark preference until you choose one, and the correct theme paints on load with no
  flash. Works the same in local (in-browser) mode.
- **Customisable dashboard layout** — tap **Customise** (the ▦ in the header) to arrange the
  dashboard around your workflow: drag monitors into any order, **pin** the ones that matter
  to the front, and **hide** the ones you don't, with a tray to bring hidden ones back. The
  camera registry can be reordered and hidden the same way. Dragging works with mouse, touch
  and keyboard, your layout is saved and synced to every browser that opens the hub, and it
  works the same in local (in-browser) mode.
- **Home Assistant integration over MQTT** — point the hub at your MQTT broker (**Settings →
  Home Assistant (MQTT)**) and every monitor appears in Home Assistant automatically through
  MQTT discovery, each as its own device: a **Defect** problem sensor, defect-score and state
  sensors, the latest failure **snapshot**, an **Enabled** switch, and — when the monitor is
  linked to a printer — live status and progress with **Pause / Resume / Cancel** buttons.
  Control is two-way, so Home Assistant dashboards and automations can arm a monitor or stop
  a print, and the hub publishes an availability signal so entities show as unavailable if it
  goes offline. Monitor state is published on change rather than on every inference frame — a
  defect or printer-status transition appears at once while the live score updates in steps —
  so monitors never flood Home Assistant's history. The broker is yours and the bridge runs on
  the hub, so no frames leave your hardware. Optional TLS, username/password and custom topic
  prefixes are supported. Anyone
  with access to the broker can control PrintGuard, so treat broker access as you would the
  dashboard.
- **Accessibility pass** — the dashboard is now fully keyboard-operable and screen-reader
  friendly. Every control, camera and monitor tile is reachable by Tab with a clear focus
  outline; dialogs and the monitor panel trap focus while open, close on **Esc** or a click
  outside, lock the page behind them and return focus to wherever you left off; the
  **Settings** tabs follow the standard arrow-key pattern. Switches, tabs and icon buttons
  carry proper labels, defect alerts are announced aloud, and a "skip to monitors" link
  starts the page. Text, status colours and the light theme were tuned to meet **WCAG 2.2 AA**
  contrast, and all motion respects your system's reduced-motion setting.

## [2.1.2] - 2026-06-20

### Fixed

- **WebRTC camera feeds no longer fail silently.** PrintGuard reads cameras with FFmpeg,
  which cannot ingest WebRTC (WHEP/WHIP) streams. A camera that only offered WebRTC — most
  often a Klipper/Crowsnest setup on **camera-streamer**, the Crowsnest V5 default — was
  registered but produced no frames, with nothing to say why. Such streams are now detected
  up front: adding one by hand is rejected with a clear message pointing at the MJPEG
  (`…?action=stream`) or RTSP URL to use instead, and a printer that exposes only a WebRTC
  webcam raises a visible warning rather than quietly skipping it.
- **Klipper webcams on camera-streamer fix.** When Moonraker advertises a webcam as
  WebRTC, PrintGuard automatically attaches to the same feed's MJPEG endpoint (derived from
  the webcam's snapshot URL) instead of the unreadable WebRTC one, so no manual reconfiguration
  is needed. Webcams already served as MJPEG/HLS are unaffected.
- **Klipper webcam URLs resolve to the right port.** A webcam advertised by a relative path
  (e.g. `/webcam/?action=stream`) is now fetched from the printer's web port, where the stream
  is actually served, rather than Moonraker's API port (7125) — which carries no webcam routes
  and silently produced no frames when the printer was added with its `…:7125` base URL.

## [2.1.1] - 2026-06-19

### Added

- **Camera rotation** — every camera now has a rotation control (0°, 90°, 180°, 270°) in the
  camera registry. The rotation is applied to **both** the live view and the frames the
  on-device model runs on, so a camera mounted sideways or upside down can be set upright
  once and everything follows: monitoring, the crop region, REST/MCP snapshots and the
  images attached to defect alerts. Crops are defined on the rotated image, so what you see
  is what the model sees.

### Fixed

- Camera snapshots returned over the REST API and MCP now apply the same image pipeline as
  the live view and alert images (rotation, crop, brightness/contrast/sharpness) instead of
  returning the raw frame.

## [2.1.0] - 2026-06-16

### Added

- **Camera, printer and monitor registries** — printers (OctoPrint, Klipper, Bambu Lab) are
  now registered once in their own registry, exactly like cameras, then picked from a list;
  the registry is the only place to create or delete one. A **monitor** binds a registered
  camera and an optional registered printer and carries the inference thresholds and
  defect-response policy, so one printer connection can back several monitors and its
  connection details are entered once instead of re-typed per printer.
- **Bambu Lab printers** — link a printer over its local MQTT API alongside the existing
  OctoPrint and Klipper services, with the same pause/cancel-on-defect response, job and
  progress reporting, and inference gating. Enable **LAN Only Mode** and **Developer Mode**
  on the printer, then link it with its IP, serial number and access code — the form links
  Bambu's official setup guide. The protocol is MQTT over TLS, which needs a raw socket the
  browser sandbox forbids, so Bambu Lab is offered in **hub mode only** — the same
  constraint that already makes some notifiers hub-only.
- **Printer-exposed cameras** — when a registered printer's service exposes a webcam,
  PrintGuard registers it as a camera automatically (no stream URL to copy). A camera
  attached to the printer later is picked up from the camera registry's new **Printer
  cameras** tab with a **Refresh** button. Covers OctoPrint and Klipper (Moonraker) webcam
  streams and the Bambu Lab chamber camera — RTSP on the X1/H2 series and the proprietary
  port-6000 JPEG protocol on the A1/P1 series (hub mode). These cameras are managed by their
  printer: they cannot be removed on their own and are dropped with it, and the REST and MCP
  read surface strips the access codes their sources carry.
- **Setup guides in config forms** — each printer service and notification channel now
  shows a one-line setup hint and a link to its official setup docs, so steps taken
  outside PrintGuard (API keys, CORS, bot tokens, webhooks, LAN mode) are spelled out
  where you configure them.
- **Experimental tag** — a reusable badge that flags new, not-yet-battle-tested features
  and links to the issue tracker for reports. Bambu Lab carries it.
- **MCP server and REST API for hub mode** — agents and developers can now drive the
  same engine protocol the dashboard speaks. The Model Context Protocol server
  (Streamable HTTP, at `/mcp/`) lets an agent read monitor, printer and camera status, fetch
  the current camera frame as an image, and pause, resume or cancel a print; the versioned
  REST API at `/api/v1` exposes the same operations to any HTTP client, with the frame
  served as `image/jpeg`. Both are thin transports over the existing engine commands, so
  they never drift from the UI. See
  [docs/api.md](https://github.com/oliverbravery/PrintGuard/blob/main/docs/api.md).
- **Scoped access tokens, managed from the UI** — capability is configurable per token
  through cumulative `read` ⊂ `control` ⊂ `manage` scopes. Issue, name and revoke tokens
  from the dashboard (**Settings → API & MCP access**); each secret (a `pg_…` string) is
  shown once and stored only as a SHA-256 hash, and tokens are managed over the dashboard's
  own protocol, never over the API itself. With no token issued the surface is read-only
  behind your existing auth proxy; issuing scoped tokens unlocks control and management, and
  MCP hides any tool a token cannot use.
- **Update notifications** — the hub checks the public GitHub releases once a day for a newer
  version and flags it in the header. A dialog shows the changelog for every version above
  the one you run and the `docker compose pull && docker compose up -d` command to upgrade.
  The check runs server-side with no telemetry and can be switched off in **Settings →
  Software updates**; local mode, which is always the latest deployed build, never calls out.

### Changed

- **The dashboard entity is now a "monitor".** What 2.0 called a printer — a camera bound
  to a service with thresholds — is a monitor; the printer is the registered service
  connection it points at. Upgrading from 2.0 preserves registered cameras, but printers
  must be re-registered and their monitors re-created.

### Fixed

- Klipper's API-reference link pointed at Moonraker's old `/web_api/` page, which now
  404s; repointed to the current reference.

## [2.0.1] - 2026-06-15

### Added

- `LICENSE.md` with the full GNU General Public License v2 text, matching the
  `GPL-2.0-only` declaration in `pyproject.toml`.

## [2.0.0] - 2026-06-12

A ground-up rewrite. One Python engine now runs everywhere — in your browser on Pyodide
or on a server on CPython — with every runtime difference behind a single `Platform`
contract. Nothing from 1.x is migrated: a 2.0 hub starts from a fresh configuration.

### Added

- **Local mode** — the full engine runs in the browser (Pyodide, with
  [LiteRT.js](https://developers.google.com/edge/litert) WASM inference). Nothing is
  installed and no frame leaves the device; a
  [live demo](https://oliverbravery.github.io/PrintGuard/) deploys to GitHub Pages on
  every release.
- **Klipper (Moonraker) integration** alongside OctoPrint: read printer state, pause or
  cancel jobs, with per-printer thresholds, consecutive-detection counts and cooldowns.
- **ntfy, Telegram and Discord notifications**, each carrying a snapshot of the defect.
- **Live video via MediaMTX** — pull any RTSP/RTMP/HTTP source, publish this device's
  camera over a WebSocket, auto-discover streams already pushed to the server. Playback
  is HLS served through the hub's own port, so a single HTTPS port — and the auth proxy
  in front of it — covers the dashboard, control and video.
- **Print-aware gating** — printers linked to a service are only watched while they
  actually print; inference stands by when they sit idle.
- **Fail-safe watchdog** — warnings on the dashboard and through notification channels
  when a camera drops, a feed freezes or a printer service stops answering; a failed
  pause is announced, never swallowed.
- **Fair multi-camera scheduling** — inference capacity is shared evenly across as many
  cameras as the hardware sustains.

### Changed

- The UI is rewritten in React + TypeScript; one dashboard serves both modes.
- Inference moved from PyTorch/ONNX Runtime to LiteRT (TFLite): a ≈5 MB ShuffleNetV2
  encoder classified by nearest prototype, with per-printer sensitivity and threshold
  sliders mapped to prototype distances.
- Cameras are network streams through MediaMTX instead of host devices, so the container
  no longer needs `--privileged`.
- Securing a hub is delegated to an identity layer in front — Tailscale, Cloudflare
  Access or oauth2-proxy, documented step by step in
  [docs/deployment.md](https://github.com/oliverbravery/PrintGuard/blob/main/docs/deployment.md)
  — instead of in-app SSL certificates and tunnel management.
- Docker is the only supported distribution: multi-arch (`amd64`, `arm64`) images on
  [`ghcr.io/oliverbravery/printguard`](https://github.com/oliverbravery/PrintGuard/pkgs/container/printguard),
  with a compose file that includes MediaMTX.

### Removed

- The PyPI package — use the Docker image, or local mode for an install-free run.
- Web push notifications and VAPID key setup — replaced by ntfy, Telegram and Discord.
- The setup page's SSL certificate generation and built-in Cloudflare/ngrok tunnelling —
  replaced by
  [docs/deployment.md](https://github.com/oliverbravery/PrintGuard/blob/main/docs/deployment.md).
- 32-bit ARM (`arm/v7`) images — `arm64` (Raspberry Pi 4/5) remains supported.

[2.1.0]: https://github.com/oliverbravery/PrintGuard/compare/v2.0.1...v2.1.0
[2.0.1]: https://github.com/oliverbravery/PrintGuard/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/oliverbravery/PrintGuard/compare/v1.0.0b3...v2.0.0
