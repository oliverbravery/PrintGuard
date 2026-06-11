# PrintGuard

![GitHub stars](https://img.shields.io/github/stars/oliverbravery/PrintGuard?style=flat&color=ff4d00)
![Licence](https://img.shields.io/badge/licence-GPL--2.0-2ea44f)
![Docker](https://img.shields.io/badge/deploy-docker-2496ed)

Real-time FDM 3D print failure detection. One Python engine — the inference loop, camera
registry, fair scheduler, defect monitor and printer integrations — runs unchanged in two
places:

| | Local mode | Hub mode |
|---|---|---|
| Engine runs | in your browser (Pyodide) | on the server (CPython) |
| Model runs | LiteRT.js (WASM) | ai-edge-litert |
| Cameras | this device (`getUserMedia`) | RTSP/RTMP/WebRTC via MediaMTX |
| Frames leave the device | never | only to your own server |
| Survives closing the tab | no | yes |

The only mode-specific code is one `Platform` implementation per side
([engine/platform.py](printguard/engine/platform.py) defines the contract): `infer()`,
`open_camera()`, `http()`, JPEG encoding and persistence — identical signatures, different
runtimes. Everything else is shared by construction, so the two modes cannot drift apart.

## Quick start

```bash
docker compose up -d
```

Open `http://<host>:8000`, pick a mode, register a camera, add a printer. Both modes are
served by the same container; local mode uses it only for static files, so frames never
leave your device.

## How inference is allocated

When a camera is registered its native frame rate is measured once and stored in the
registry. From then on allocation is fully dynamic — there is no benchmarking step:

1. A smoothed estimate of observed inference latency continuously yields the sustainable
   total rate (`workers / latency`).
2. That capacity is water-filled across in-use cameras (max-min fairness): no camera is
   allocated beyond its native fps, and surplus flows to cameras that can use it.
3. A free worker takes the most overdue camera and grabs its **freshest** frame at dispatch
   time. Frames carry a sequence identity, so the same frame is never inferred twice and
   results always describe the present, not a backlog.

Per-camera stats (max fps, allocated fps, achieved fps, inferring, in use) are live in the
dashboard's camera registry rail.

## Printer services

Link a printer to OctoPrint or Klipper (Moonraker) and PrintGuard can pause or cancel the
print when a defect is sustained, with a configurable threshold, consecutive-detection
count and cooldown. Alerts can also push to any [ntfy](https://ntfy.sh) topic with a
snapshot attached.

In local mode the browser calls the printer service directly — enable CORS in OctoPrint
(Settings → API) or add `cors_domains` to `moonraker.conf`. Hub mode needs no CORS.

### Adding a new integration

Integrations are shared code: one adapter runs in both modes because it only talks through
the platform's HTTP function.

1. Create `printguard/engine/integrations/<service>.py` subclassing
   [`IntegrationAdapter`](printguard/engine/integrations/base.py): implement
   `fetch_state()` and `send()`, normalising to the canonical `DeviceStatus` values, and
   describe your config form as a JSON Schema (`secret: true` masks fields). Link the
   official API docs in `docs_url` — it is required for review.
2. Register an instance in
   [`integrations/__init__.py`](printguard/engine/integrations/__init__.py).

The configuration UI, connection test, polling and defect actions all follow from the
adapter — no other changes in either mode.

## Hub mode cameras

- **Stream URL** — any RTSP/RTMP/HTTP source; PrintGuard creates a MediaMTX pull path.
- **This device** — publishes a browser camera to the hub over WebRTC (WHIP). Publishing
  stops when the tab closes.
- **Discovered** — anything already pushed to MediaMTX (e.g.
  `rtsp://host:8554/mycam` from a Pi) appears here.

Live playback in the dashboard uses WebRTC (WHEP) directly from MediaMTX on port `8889`.

## Exposing a hub

PrintGuard ships no auth: keep it on a trusted network, or front it with
[oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/) and/or a Cloudflare Tunnel —
proxy HTTP/WebSocket to `printguard:8000`. WebRTC (UDP `8189`) should stay directly
reachable for playback and publishing.

## Development

```bash
uv sync                              # Python engine + server
uv run printguard                    # serve on :8000
cd web && npm install && npm run dev # UI with hot reload on :5173
uv run python tests/test_engine.py   # engine simulation tests
```

The model is a ShuffleNetV2 encoder ([Edge-FDM-Fault-Detection](https://github.com/oliverbravery/Edge-FDM-Fault-Detection))
classified by nearest prototype; `models/` holds the TFLite file, normalisation metadata
and class prototypes.
