# Architecture

PrintGuard is a monolith where the engine is shared code and runs unchanged on
CPython (hub mode) and on Pyodide in the browser (local mode). Everything
mode-specific is confined to one `Platform` implementation per runtime. The two modes
cannot drift apart because there is nothing to drift — they execute the same files.

```mermaid
flowchart LR
    subgraph UI["React UI (presentation only)"]
        store["zustand store"]
    end

    store <-- "JSON commands / events" --> engine

    subgraph engine["printguard/engine (shared Python)"]
        registry["camera registry"]
        scheduler["fair scheduler"]
        monitor["monitor + watchdog"]
        vision["vision (preprocess / classify)"]
        integrations["integration adapters"]
        notifiers["notifier adapters"]
    end

    engine -- "Platform protocol" --> platform

    subgraph platform["one Platform per runtime"]
        server["server/platform.py<br/>CPython · LiteRT · PyAV · httpx"]
        browser["browser/platform.py<br/>Pyodide · LiteRT.js · getUserMedia · fetch"]
    end

    server --- mediamtx["MediaMTX<br/>RTSP / RTMP / LL-HLS"]
    integrations --- printersvc["OctoPrint / Moonraker"]
    notifiers --- push["ntfy / Telegram / Discord"]
```

## The platform contract

[`engine/platform.py`](../printguard/engine/platform.py) defines everything the engine
needs but cannot implement portably. Identical signatures, different runtimes:

| Method | Hub (CPython) | Local (browser) |
|---|---|---|
| `infer(rgb)` | ai-edge-litert on CPU threads | LiteRT.js in WASM via a JS bridge |
| `discover_cameras()` | MediaMTX path list | `enumerateDevices()` |
| `open_camera(id, source)` | PyAV reader thread per RTSP stream | `getUserMedia` + canvas grabs |
| `http(...)` | httpx | `fetch` (CORS applies) |
| `encode_jpeg(rgb)` | PyAV mjpeg | canvas `toBlob` |
| `load_state` / `save_state` | `data/state.json` | `localStorage` |

The UI is presentation-only and speaks one JSON command/event protocol — over a WebSocket
in hub mode, over an in-page Pyodide bridge in local mode. The engine cannot tell which
transport it is on. **Never add mode-specific logic anywhere else**; if a feature needs a
runtime service, extend the Platform contract on both sides.

## The protocol

Commands (UI → engine): `discover`, `camera.add/update/remove`,
`printer.add/update/remove`, `printer.action`, `device.test`, `notify.test`,
`settings.update`. Every command may carry a `req_id`, echoed on the responding event so
the UI can resolve pending requests.

Events (engine → UI): a full `state` snapshot (on connect, after every command, and on a
1 s ticker), plus incremental `result`, `alert`, `warning`, `device`, `discovered`,
`device_test`, `notify_test` and `error` events.

## Scheduling inference

When a camera is registered its native frame rate is measured once. From then on
allocation is fully dynamic:

1. A smoothed estimate of observed inference latency continuously yields the sustainable
   total rate (`workers / latency`).
2. That capacity is water-filled across in-use cameras (max-min fairness): no camera is
   allocated beyond its native fps, and surplus flows to cameras that can use it.
3. A free worker takes the most overdue camera and grabs its **freshest** frame at
   dispatch time. Frames carry a sequence identity, so the same frame is never inferred
   twice and results always describe the present, not a backlog.

MediaMTX bursts the buffered GOP on RTSP connect, so stream fps istrusted from the SDP `average_rate`, else measured only after a warm-up.

## The defect pipeline

```mermaid
sequenceDiagram
    participant S as Scheduler
    participant P as Platform
    participant M as Monitor
    participant I as Integration adapter
    participant N as Notifier adapters

    S->>P: grab freshest frame, infer()
    P-->>S: classification result
    S->>M: on_score(printer, frame, score)
    alt score ≥ threshold for N consecutive frames
        M->>I: pause / cancel (retried on failure)
        I-->>M: ok, or "failed" after retries
        M-->>M: emit alert event (action included)
        M->>N: snapshot + outcome to every enabled channel
    else score below threshold
        M-->>M: streak and alert reset
    end
```

A failed device action is retried, then reported in the alert, the UI error feed and the push notification.

## Failing safely

A printer's **watching** state gates inference
([`printers.printer_watching`](../printguard/engine/printers.py)):

| Linked service reports | Watched? | Why |
|---|---|---|
| no service linked | yes | nothing to gate on |
| `printing` | yes | the job needs eyes |
| no state yet / `unknown` | yes | can't tell → watch |
| `offline` (unreachable) | yes | losing the signal must not stop monitoring |
| `idle` / `paused` / `error` | no (standby) | positively not printing |

Only a *positive* "not printing" stands inference down. The monitor's watchdog loop then
keeps the whole pipeline honest — each sustained condition warns exactly once (after a
grace period, so reconnecting sources don't flap) and announces recovery:

- a watched camera goes **offline**,
- a watched camera stays online but stops producing fresh frames (**stalled** — a frozen
  RTSP feed must not pass for monitoring),
- a linked printer service becomes **unreachable** (defects could no longer pause it).

Warnings surface as dashboard toasts and go out through the notification channels.
Notifier delivery failures and inference crashes emit `error` events — there is no
silent `except: pass` anywhere in the alert path.

## Repository layout

```
printguard/
  engine/            shared engine — runs on CPython and Pyodide
    integrations/    printer service adapters (OctoPrint, Klipper, …)
    notifiers/       alert channel adapters (ntfy, Telegram, Discord, …)
    adapters.py      shared adapter contract (id, label, docs_url, JSON-schema config)
  server/            hub platform: FastAPI, MediaMTX, LiteRT, PyAV
  browser/           local platform: Pyodide bridge to LiteRT.js and getUserMedia
  pysrc.py           builds the engine source archive Pyodide unpacks
web/                 React + Tailwind UI (presentation only)
models/              TFLite encoder, normalisation metadata, class prototypes
tests/               engine simulation + adapter contract tests (pytest)
```

## The static demo

Local mode needs no backend at all, so the same `web/dist` build deploys to GitHub Pages:
the release workflow zips the engine source (`printguard/pysrc.py`), copies `models/`
into the bundle, and every asset is fetched base-relative. The mode picker probes
`api/health` — when no hub answers, the hub card becomes a Docker self-host link.
