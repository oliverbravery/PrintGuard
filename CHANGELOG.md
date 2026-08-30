# Changelog

All notable changes to PrintGuard are documented in this file, by hand, in the pull
request that ships them. Each version's section is published verbatim as its GitHub
release notes.

The format is [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.5.0] - 2026-08-30

### Added

- **Pushover as an alert channel**, alongside ntfy, Telegram and Discord. Create an application
  at [pushover.net/apps/build](https://pushover.net/apps/build), then paste its API token and your
  user key into the Alerts tab in Settings. Defect snapshots arrive as an attachment. Priority is
  yours to pick and defaults to High, which cuts through the quiet hours set on the device; it
  applies to every notice the channel carries, warnings and recoveries included. It works in both
  hub and local mode.

## [2.4.0] - 2026-08-24

### Added

- A plugin store, in the Plugins tab in Settings. Plugins are written in JavaScript and run in
  a sandbox, drawing a panel on your dashboard or running a job on the hub. Install verified
  ones from the catalogue, or from a GitHub repo or a zip.
  [docs/plugins.md](docs/plugins.md) has the API, and [CONTRIBUTING.md](CONTRIBUTING.md) covers
  getting one listed.
- Each catalogue plugin has a page: an icon, screenshots or GIFs and its README, rendered the
  way GitHub renders it, with the permissions it will ask for and the author's reason for each.
  Everything is read from the plugin's repository at the pinned commit, so nothing new is
  installed or executed by looking. Installed plugins sit in the same list behind an
  Installed filter, a search box covers it all, every plugin's page opens from its card,
  and a plugin installed from a zip carries its page inside the zip.
- Four come as standard. Picture in picture floats a camera above your other windows, alert
  sounds plays a horn when a defect is caught, progress reports sends a tally of a print through
  your alert channels, and Spotify puts the current cover behind the dashboard.
- A five-page walkthrough on first load, covering what PrintGuard does, cameras and printers,
  monitors, and when inference runs and when it stands down. Each page carries a shot of the part
  of the dashboard it describes, as does the guide behind the ? in the header. It opens once in
  every browser that has not seen it.
- A Glass theme, alongside System, Light and Dark. The panels frost over whatever is behind
  them, which is what the Spotify plugin's cover shows through. It opens dark and as clear as
  the text can carry, and two sliders adjust how solid the panels are and how light or dark,
  with text taking whichever colour holds 4.5:1 over what the glass lets through.

- Plugins install switched off. Enable lists every permission with the author's reason for it,
  and it is all or nothing. An update that asks for more waits until you accept it.
- What you gave a plugin carries across updates from the repository it came from. A bundle that
  shares only its id starts with nothing.
- Enabling one shows what its code does against what it asks for. The catalogue is held to the
  same check, so a listed plugin is one whose code and claims agree.
- Plugins can reach the network on match patterns like `https://*.example.com/*`, hold a
  WebSocket open, and read what they fetch. Reaching your own network is a separate permission.
- Plugins can add printers, cameras and monitors, change settings and mint API tokens, each
  behind its own permission.
- Plugins can hold credentials they can never read back, and PrintGuard runs OAuth sign-ins on
  their behalf.
- Plugins can take camera stills and read risk history, each behind its own permission.
- A plugin can ship a `panel.html` and draw its own panel, with video and larger images. Panels
  drag, pin and hide with your monitors.
- Plugins can call each other on channels both sides declared.
- `PRINTGUARD_PLUGINS=off` starts the hub with every plugin switched off.

### Fixed

- The walkthrough and guide screenshots show whole panels, where several stopped mid-slider or
  mid-list. Dialogs and the walkthrough pages also move with a softer ease.
- `state.json` is written readable only by the account running the hub. It holds printer
  passwords, notifier keys and API token hashes, and was taking the system default.
- A plugin's credentials are scrubbed from bug reports.
- A plugin's own pages can no longer pull a live camera stream.
- A camera that keeps dropping out no longer alerts on every reconnect. A recovery is announced
  once the feed has held for a minute, and each one doubles what the next has to hold for, up to
  fifteen minutes. Outages are never delayed. Worth pulling if you run a camera on marginal
  wifi. Thanks to @subpanel0576 for the report.
- The `latest-intel` image now carries Intel's current GPU runtime, covering Arc, Battlemage
  and every iGPU from Tiger Lake on. Debian's driver predates Meteor Lake, so OpenVINO was
  handed no GPU and inference quietly stayed on the CPU. Gen8 to Gen11 iGPUs stay on the CPU
  path, since Intel publishes no current driver for them.
- The compute readout names the hardware, so `intel openvino` now reads `intel gpu` or
  `intel cpu`, and the log lists what the providers offered at start.
- The Getting Started progress bar is visible in dark and Glass, where its track was taking a
  colour that all but vanished into the panel behind it.
- A monitor whose printer reports a state PrintGuard cannot read now warns and says so on its
  panel. It keeps watching, which is the safe direction, but only an unreachable printer warned
  before, so a printer stuck in something like OctoPrint's "Connecting" ran inference at the
  camera's full frame rate with nothing explaining why. A printer that starts reporting again
  is announced as recovered even if it comes back idle.

## [2.3.12] - 2026-08-12

### Fixed

- The `latest-nvidia` image never carried the CUDA 12 runtime the TensorRT RTX provider
  links against, so since 2.3.7 it exited at startup with `libcudart.so.12: cannot open
  shared object file`. It carries it now. Thanks to @ForceConstant for the report.

## [2.3.11] - 2026-08-04

### Security

- **Picked up the `cryptography` 50.0.0 security fix** ([CVE-2026-69247](https://github.com/advisories/GHSA-g6cj-pr64-35w5),
  high). The flaw is in that library's PKCS#7 `EnvelopedData` decryption, which PrintGuard
  never calls: the package is here only as a dependency of the JWT and token libraries
  behind sign-in and push notifications, so no PrintGuard install was exposed. Nothing else
  changed in this release. Pull the new image if you want a clean dependency scan.

## [2.3.10] - 2026-08-04

### Added

- **You can now sponsor PrintGuard.** Apple charges $99 a year for the Developer Program, and
  without it the macOS desktop app cannot be signed or notarised, which is why macOS calls it
  an unidentified developer the first time you open it. Sponsorship goes towards that licence
  first, and nothing in PrintGuard is locked behind it. Nothing else changed in this release,
  so there is nothing to gain by updating from 2.3.9.

## [2.3.9] - 2026-08-03

### Fixed

- **The macOS desktop app no longer opens to a blank white window.** On 2.3.7 and 2.3.8 the
  app started, showed an empty window and never loaded, while the menu bar icon stayed
  alive: Core ML could not load the model from the app's own data folder, because the
  runtime's cache lookup rejects any path containing a space and macOS puts that folder in
  `~/Library/Application Support`. Nothing was watched for as long as the window sat there.
  Core ML now compiles the model each time the app starts, which adds about a fifth of a
  second to startup and no longer depends on where your data lives. Update and open the
  app; you can delete the leftover `model-cache` folder in the data directory.

- **When the server does fail to start, the window says so.** Instead of a blank page, it
  now shows what went wrong, the end of the log and where the full log is kept, so a broken
  start can be reported or fixed rather than guessed at. A failed start also no longer
  leaves the bundled streaming server running behind it, holding port 8554 against the next
  hub you start.

## [2.3.8] - 2026-07-24

### Added

- **Keep a copy of your diagnostics, or send them wherever you like.** The bug report
  dialog now has a **Download logs** button that saves exactly what a report would carry,
  the diagnostics bundle plus PrintGuard's own and the dashboard's recent logs, with every
  credential stripped and no camera frames, as a single zip. Read it before anything
  leaves your machine, attach it to a GitHub issue, or hand it to whoever is helping you.
  Nothing is sent when you download.

- **Read the changelog for any version, not just the pending ones.** The version chip in
  the header now opens a picker covering every published release, with the one you are
  running and the newest one both marked, so you can see what a version changed before you
  take it, or catch up on what you already have.

- **The live demo says what it cannot do.** Local mode now opens with a short notice
  covering the four things that need an installed hub: watching after the tab closes,
  network and printer cameras, Bambu Lab, Prusa and Elegoo printers, and GPU or NPU
  inference across several cameras. It appears once per browser, and the **local** chip in
  the header reopens it.

### Changed

- **The Docker image is a third smaller.** The amd64 image drops from 1.1 GB to 720 MB on
  disk, a 377 MB download becomes 263 MB, and arm64 from 623 MB to 566 MB. Compiled
  dependencies now ship without their debug symbols, and the 290 MB Intel GPU compute
  runtime moved into its own image. Pulls and updates are quicker, and nothing about how
  PrintGuard runs changes.
- **Intel GPU inference now uses the `-intel` image.** Pair `--device /dev/dri` with
  `ghcr.io/oliverbravery/printguard:latest-intel`, which carries the Intel GPU compute
  runtime; if you pass `/dev/dri` to the standard image today, switch tags to keep GPU
  inference. Intel **CPU** acceleration through OpenVINO is unchanged on the standard
  image, and NVIDIA hosts keep using `latest-nvidia`.
- **The report button in the header is now a bug icon** rather than a flag, so it is clear
  at a glance what it opens.
- **Elegoo and Prusa printers, and desktop notifications, are no longer marked
  experimental.** They have held up in use, so the warning is gone from their setup forms;
  nothing about how they are configured changes.

### Fixed

- **CPU inference is fast again after 2.3.7 cut it to a quarter of its throughput.** 2.3.7
  ran at most two frames at once on hosts that could sustain many more, so capacity fell
  from roughly 2,000 fps to under 500 on the same machine, and both LiteRT and ONNX Runtime
  were affected. PrintGuard now measures how far the runtime on your host actually scales
  instead of guessing from the core count, and runs that many frames at once. Expect the
  **capacity** readout to return to what 2.3.6 showed or better, on Intel CPUs through
  OpenVINO especially. Nothing to change: the measurement runs at startup and its result is
  in the log as `inference ready:`. Thanks to @hedger for the report.
- **A hub that is force quit or crashes no longer blocks the next one from starting.** The
  bundled streaming server was left running when PrintGuard did not exit cleanly, and it
  kept port 8554, so the next start, whether the desktop app, a container or another hub
  on that machine, failed with "address already in use" from an app that was no longer
  running. The streaming server now always stops with the hub, however the hub ends.

## [2.3.7] - 2026-07-22

### Added

- **Health checks can now read the running PrintGuard version.** The unauthenticated
  `/api/health` endpoint reports readiness and the installed version for uptime and update
  monitors without exposing printer, camera or configuration data.
- **Hub and desktop model inference now selects the fastest runtime on each machine.**
  Automatic mode benchmarks LiteRT and ONNX Runtime locally, with ONNX able to use Apple
  Core ML, Windows ML, Intel OpenVINO or NVIDIA TensorRT RTX. The new **Advanced** settings
  tab can pin either model runtime, and the dashboard's compute readout opens it directly.
  Docker and Unraid users can expose `/dev/dri` for Intel hardware, while NVIDIA hosts can
  use the `-nvidia` image with GPU passthrough.

### Fixed

- **Dashboard feeds no longer stick on "no signal" while the camera is live.** Opening a
  monitor's details or a dialog left a second player running for the same camera behind it,
  and once the platform paused that hidden one it never resumed — the tile stayed frozen
  under a "no signal" overlay although the camera was streaming and monitoring never
  stopped. A tile now hands its stream to whatever opens on top and takes it back on close,
  any feed that is paused resumes itself at the live edge, and the overlay only reads "no
  signal" when the camera really has none.
- **Webcams no longer drop out at random during long runs.** Every captured frame started a
  fresh pool of operating-system threads to convert it, faster than they could be reclaimed,
  so after a few minutes the feed froze and monitoring stopped until the camera restarted
  itself, while memory climbed by hundreds of megabytes. Capture now holds a flat thread
  count and steady memory over hours. This affected the desktop app's own webcams most, and
  MJPEG and Bambu cameras on any hub; a snapshot taken during inference could also read a
  half-converted frame.
- **Live risk no longer appears stuck at zero while inference is running.** PrintGuard now
  keeps the latest score in authoritative state, bounds and conflates live telemetry
  without dropping ordered events, and uses the engine clock for detailed history.

## [2.3.6] - 2026-07-19

### Fixed

- **Idle cameras no longer keep decoding and converting every frame.** When a printer is
  positively idle and nobody is viewing its feed, PrintGuard puts the camera in standby and
  resumes it automatically when printing or viewing starts. RTSP, RTMP and WHEP feeds are pulled
  on demand, while MJPEG, Bambu and device cameras keep their existing browser-compatible H.264
  bridge without running it unnecessarily. Unknown or unreachable printers remain monitored.
- **Desktop webcams now preview immediately after registration.** The camera stays live while its
  preview connects, then still enters standby after viewing or monitoring stops. Slow desktop
  camera startup no longer leaves orphaned captures running after the window closes.
- **Camera and monitor status lights no longer flicker between healthy colours.** Camera indicators
  now show stable availability, while monitor indicators stay green when watching and switch red
  only for a genuine defect alert.
- **RTSP cameras recover after a damaged stream.** If packet loss or decoder errors leave a camera
  offline, PrintGuard now replaces the failed reader and its MediaMTX pull automatically instead
  of retrying the same broken session until the camera is toggled manually.
- **Alert-only notifications now state that no printer action is configured.** This makes clear that
  detection and push alerts are still active when a printer is powered off or unreachable.
- **Printer actions and notifications no longer pause camera inference.** Slow or unreachable
  services are handled independently while monitoring continues, and genuinely stalled camera
  sources are replaced automatically after a fresh-frame timeout.

## [2.3.5] - 2026-07-15

### Fixed

- **Centauri Carbon printer status now stays connected instead of flickering offline.**
  PrintGuard keeps one local connection open for status checks, camera discovery and printer
  controls, then reconnects only if that session is lost. Connection tests are reliable, and
  original Centauri Carbon printers can still be reached while paused or in an error state.

## [2.3.4] - 2026-07-14

### Added

- **Elegoo printers can now be monitored and controlled directly on the local network.**
  Register a Centauri Carbon or Centauri Carbon 2 to read its job, progress and state,
  automatically add its chamber camera, and let PrintGuard pause or cancel a failed print.
  The same Elegoo option covers Neptune 4 Pro/Plus/Max and OrangeStorm Giga printers through
  their stock Moonraker service. Centauri Carbon 2 owners need to enable **LAN Only Mode** and
  enter the access code shown in the printer's network settings. Elegoo control is available in
  hub and desktop mode, keeps all traffic on your LAN, and never uses Elegoo's cloud.

### Fixed

- **Mobile pages no longer widen around connection errors or install controls.** Long printer
  test errors wrap inside their dialog, while the landing page keeps desktop download buttons
  and Docker commands within the viewport.

## [2.3.3] - 2026-07-13

### Added

- **WebRTC cameras with a WHEP endpoint can now be watched directly.** Paste a `whep://`
  or `wheps://` URL into **Cameras → Stream URL** and PrintGuard pulls the original feed
  through its bundled MediaMTX server, without converting it to MJPEG or adding another
  service. This also gives go2rtc users a lower-overhead bridge for printer cameras: use
  `whep://<go2rtc-host>:1984/api/webrtc?src=<stream>` instead of its MJPEG output. Cameras
  with proprietary WebRTC signalling, including camera-streamer and Creality feeds, still
  need their MJPEG endpoint or a bridge such as go2rtc.

### Fixed

- **Updates now load the matching dashboard instead of a cached older one.** The HTML shell
  is revalidated while Vite's content-hashed assets remain safely cached, so Docker browsers
  pick up the new interface on reload. Desktop builds also open a versioned local URL, which
  bypasses HTML cached by an earlier app version without erasing saved settings or camera state.

## [2.3.2] - 2026-07-10

### Fixed

- **Landing-page macOS install steps match current macOS.** The desktop-app panel on the
  [project site](https://oliverbravery.github.io/PrintGuard/) now shows the macOS Sequoia unlock
  path — **System Settings → Privacy & Security → Open Anyway** — in place of the old
  right-click → **Open** that newer macOS no longer offers. Website copy only; the app and Docker
  image are unchanged.

## [2.3.1] - 2026-07-10

### Changed

- **The macOS app installs like a normal Mac app.** The download now presents PrintGuard beside
  your Applications folder to drag it into, instead of a lone app icon. The builds are still
  unsigned for now, so the first launch needs one manual approval — and on macOS Sequoia that moved
  from the old right-click → **Open** to **System Settings → Privacy & Security → Open Anyway**
  (double-click the app once, then approve it there).

### Security

- **API token secrets stay out of the hub's logs.** Generating a token under **Settings → API &
  MCP access** now hands its one-time secret to the dashboard without that secret ever passing
  through the server's log writer, resolving a code-scanning finding about clear-text logging of
  sensitive data. The token is still shown once and only its hash is stored — nothing about your
  existing tokens changes.

## [2.3.0] - 2026-07-03

### Added

- **A desktop app for macOS and Windows — run a hub as an application.** PrintGuard now ships as a
  native app that runs the full hub from your menu bar / system tray. Close the window and the hub
  keeps watching, so it covers the multi-hour prints that matter; quit from the tray. The computer's
  own webcams register straight on the hub — the app's window offers them under **Cameras →
  This device**, and macOS asks for camera access the first time you register one — so they
  keep watching with every window closed (Linux Docker hubs can still attach mapped
  `/dev/video*` devices through the API). Reach it from your phone on the same network at `http://<computer>:8000`. Detection still runs entirely on
  your own machine; no frame leaves your hardware. Turn on **Start at login** and forget about it.
  Download it from the landing page or the
  [Releases page](https://github.com/oliverbravery/PrintGuard/releases) — the builds are unsigned for
  now, so the first launch needs a right-click → **Open** on macOS, or **More info → Run anyway** on
  Windows. On Linux, run the Docker hub as before. When a newer version ships, the update dialog
  offers the right download for your computer; the Docker hub keeps its pull instructions.

- **Native notifications on the desktop app.** The macOS and Windows desktop app can now post
  defect alerts to the operating system's own notification centre — with the snapshot attached —
  so a native banner reaches you even with the window closed and no phone app set up. Turn on
  **Desktop notification** under **Settings → Alerts** (it is offered only inside the desktop app,
  next to ntfy, Telegram and Discord); on macOS, allow notifications for PrintGuard the first time
  it asks. The Docker hub, which has no desktop of its own, keeps using the push channels.

- **Prusa printers now connect over PrusaLink.** Register a Prusa printer — MK4, MK4S, MK3.9,
  MK3.5, MINI, XL, CORE One, or an MK3/MK2.5 running PrusaLink on a Raspberry Pi — alongside
  OctoPrint, Klipper and Bambu. PrintGuard reads its job, progress and state, gates inference
  while it is idle, and can **pause or cancel** the print when a defect holds. Enable PrusaLink
  on the printer, then link it with its URL and the password shown under Settings → Network →
  PrusaLink (the username is `maker`). Everything stays on your network: PrintGuard talks to the
  printer directly and never to Prusa's cloud, so **PrusaConnect is not involved**. Like Bambu,
  Prusa is offered in **hub mode only**.

- **Report a bug straight from the dashboard.** Hit the ⚑ chip in the header, describe what
  happened, attach screenshots and optionally leave an email for follow-up — anonymously, no
  account needed. Each report carries a diagnostics bundle (version, platform, configuration,
  recent errors and warnings) with **every credential stripped**, and no camera frames unless
  you attach them yourself. Nothing is ever sent unless you submit a report.

- **Everything leaves a trace.** The hub now logs its whole lifecycle — boot, camera
  attach/drop, printer actions, alerts, rejected API and socket attempts — to `docker logs`,
  and the desktop app writes a self-rotating `printguard.log` beside its data, so problems on
  a computer with no terminal can still be diagnosed. Bug reports automatically attach the
  recent engine and interface logs, scrubbed of every credential, so a report carries the
  story leading up to the bug. Set `LOG_LEVEL=DEBUG` for deeper traces when asked during
  support.

- **A detection history for every monitor.** Open a monitor's detail page to see its defect risk
  charted over selectable periods, alongside a snapshot of every alert it fired — what the camera
  saw at the moment PrintGuard acted.

- **Monitor settings now explain themselves.** The alert threshold, sensitivity and
  consecutive-detections sliders carry inline hints on what each one does and which way to move
  it.

- **The `/api/v1` read surface now describes its response bodies.** PrintGuard's API reference
  (`docs/api.md`) documents the camera and monitor object shapes — including where a camera's
  failure signal lives (`last_result.prediction`), since the smoothed 0–1 defect score is a
  per-monitor quantity, not a field on the camera. The camera and monitor routes now carry
  response schemas too, so the interactive `/api/v1/docs` shows the shapes instead of empty bodies.

- **`POST /api/v1/classify` — score a single supplied frame.** Hand the model a frame directly
  (POST the bytes as `image/jpeg`, `read` scope, optional `?sensitivity=`) and get back
  `{prediction, distances, margin, defect_score}` — the same per-frame verdict the scheduler
  produces for a registered camera, without registering one. Useful for an external orchestrator
  that can reach a camera PrintGuard can't (e.g. a cloud tool tunnelling to a LAN printer), or an
  agent wanting a one-off check. Exposed both over REST and as a `classify_frame` MCP tool, so an
  agent can hand PrintGuard an image from the conversation and get a verdict back. Reuses the
  engine's own inference; hub only.

### Fixed

- Registering a camera could report "no frames" even though the stream was healthy — the hub
  gave a source eight seconds to produce a frame, which a freshly published "this device"
  camera or a slow-starting stream often exceeds. Registration now waits out a cold start
  before giving up.

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
