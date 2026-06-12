# PrintGuard

![GitHub stars](https://img.shields.io/github/stars/oliverbravery/PrintGuard?style=flat&color=ff4d00)
![Licence](https://img.shields.io/badge/licence-GPL--2.0-2ea44f)
[![Container](https://img.shields.io/badge/ghcr.io-oliverbravery%2Fprintguard-2496ed?logo=docker&logoColor=white)](https://github.com/oliverbravery/PrintGuard/pkgs/container/printguard)
[![Live demo](https://img.shields.io/badge/demo-try_it_in_your_browser-ff4d00)](https://oliverbravery.github.io/PrintGuard/)

**PrintGuard watches your 3D printer cameras with an on-device vision model, pauses the
printer when a failure takes hold, and pushes a snapshot alert to your phone.** No cloud,
no subscription — your frames never leave hardware you own.

![PrintGuard dashboard: one healthy print, one detected defect that has been auto-paused](docs/assets/dashboard.png)

## Try it now

**[oliverbravery.github.io/PrintGuard](https://oliverbravery.github.io/PrintGuard/)** runs
the full engine in your browser — point your webcam at a print and watch it score frames.
Nothing is installed and no frame leaves your device.

## What it does

- **Detects** — a compact vision encoder ([≈5 MB](#the-model)) scores every frame for
  print failure, shared fairly across as many cameras as your hardware can sustain.
- **Acts** — a sustained defect pauses or cancels the print through
  [OctoPrint](https://octoprint.org) or [Klipper (Moonraker)](https://moonraker.readthedocs.io),
  with per-printer thresholds, consecutive-detection counts and cooldowns.
- **Alerts** — the moment a defect holds, a snapshot lands on your phone over
  [ntfy](https://ntfy.sh), [Telegram](https://telegram.org) or [Discord](https://discord.com).
- **Rests** — printers linked to a service are only watched while they actually print;
  inference stands by when they sit idle and resumes the moment a job starts.
- **Fails safe** — a watchdog warns you (on the dashboard *and* through your notification
  channels) when a camera drops, a feed freezes, or a printer service stops answering.
  If PrintGuard cannot tell whether a printer is printing, it keeps watching — losing the
  signal never silently stops monitoring, and a failed pause is announced, never swallowed.

## Quick start

You can deploy PrintGuard using Docker Compose:

```bash
curl -fsSLO https://raw.githubusercontent.com/oliverbravery/PrintGuard/main/docker-compose.yaml
curl -fsSLO https://raw.githubusercontent.com/oliverbravery/PrintGuard/main/mediamtx.yml
docker compose up -d
```

Open `http://<host>:8000`, pick a mode, register a camera, add a printer. Images for
`amd64` and `arm64` (Raspberry Pi 4/5) are published to
[`ghcr.io/oliverbravery/printguard`](https://github.com/oliverbravery/PrintGuard/pkgs/container/printguard)
on every release.

## Two modes, one engine

| | Local mode | Hub mode |
|---|---|---|
| Engine runs | in your browser (Pyodide) | on the server (CPython) |
| Model runs | [LiteRT.js (WASM)](https://developers.google.com/edge/litert) | [ai-edge-litert](https://pypi.org/project/ai-edge-litert/) |
| Frames leave the device | never | only to your own server |
| Survives closing the tab | no | yes |

### Hub mode cameras

- **Stream URL** — any RTSP/RTMP/HTTP source; PrintGuard creates a MediaMTX pull path.
- **This device** — publishes a browser camera to the hub over WebRTC (WHIP). Publishing
  stops when the tab closes. Browsers only allow camera access on secure pages, so this
  (and local mode) needs the hub served over HTTPS or opened on `localhost`.
- **Discovered** — anything already pushed to MediaMTX (e.g. `rtsp://host:8554/mycam`
  from a Raspberry Pi) appears automatically.

Live playback uses WebRTC (WHEP) directly from MediaMTX on port `8889`.

## Printers and notifications

Link a printer to OctoPrint or Klipper from its detail panel, choose what a sustained
defect should do (alert only, pause, cancel), and test the connection in place. Linked
printers report job, progress and state on their tiles — and gate inference, so an idle
printer costs you nothing.

Notification channels live in Settings: enable ntfy, Telegram or Discord, fill in the
form, and send a test alert. Every enabled channel receives defect snapshots and watchdog
warnings for printers with notifications switched on.

![Printer detail panel with live risk score and printer controls](docs/assets/printer-detail.png)

In local mode the browser calls the services directly — enable CORS in OctoPrint
(Settings → API) or add `cors_domains` to `moonraker.conf`. Telegram's API sends no CORS
headers, so that channel is hub-only.

## The model

The detector is a ShuffleNetV2 encoder classified by nearest prototype, trained for
few-shot FDM fault detection in
[Edge-FDM-Fault-Detection](https://github.com/oliverbravery/Edge-FDM-Fault-Detection)
(with an accompanying technical paper). `models/` holds the TFLite export, normalisation
metadata and class prototypes. Sensitivity and threshold sliders per printer map straight
onto the prototype distances, so you can tune for your camera and lighting without
retraining.

## For developers

- [docs/architecture.md](docs/architecture.md) — how one engine runs on CPython and in
  the browser, the platform contract, the scheduler and the fail-safe design, with
  diagrams.
- [CONTRIBUTING.md](CONTRIBUTING.md) — dev setup, tests, and step-by-step guides for
  adding printer integrations and notification providers (the two easiest ways to
  contribute).
