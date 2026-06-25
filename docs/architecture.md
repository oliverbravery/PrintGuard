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
        registry["camera + printer registries"]
        monitors["monitors (camera + printer)"]
        scheduler["fair scheduler"]
        watchdog["watchdog (defect response)"]
        vision["vision (preprocess / classify)"]
        integrations["integration adapters"]
        notifiers["notifier adapters"]
    end

    engine -- "Platform protocol" --> platform

    subgraph platform["one Platform per runtime"]
        server["server/platform.py<br/>CPython · LiteRT · PyAV · httpx"]
        browser["browser/platform.py<br/>Pyodide · LiteRT.js · getUserMedia · fetch"]
    end

    server --- mediamtx["MediaMTX<br/>RTSP / RTMP / HLS"]
    integrations --- printersvc["OctoPrint / Moonraker / Bambu Lab"]
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
`printer.add/update/remove`, `printer.action`, `printer.test`, `printer.cameras.refresh`,
`monitor.add/update/remove`, `notify.test`, `settings.update`, `update.check`. Every command
may carry a `req_id`, echoed on the responding event so the UI can resolve pending requests.

A **camera** is a video source and a **printer** is a control-service connection
(OctoPrint/Klipper/Bambu); both are registered resources, created and deleted only in
their registry. A **monitor** binds one of each (the printer is optional) and carries the
inference thresholds and defect-response policy.

A printer integration that exposes a webcam registers it automatically as a camera owned
by that printer (`Camera.printer_id`): the OctoPrint and Moonraker stream URLs, and the
Bambu chamber camera (RTSP for X1/H2, the proprietary port-6000 protocol for A1/P1). The
adapter's optional `cameras()` declares them and the engine reconciles them on printer
add/update, and on demand via `printer.cameras.refresh` (the camera registry's Printer
cameras tab) to pick up a camera attached later. Such cameras can't be removed on their
own and are dropped with their printer.

Events (engine → UI): a full `state` snapshot (on connect, after every command, and on a
1 s ticker; it carries the running version and any available update), plus incremental
`result`, `alert`, `warning`, `device`, `discovered`, `printer_test`, `notify_test` and
`error` events.

## The programmatic surface (hub only)

The MCP server, REST API and Home Assistant MQTT bridge are thin transports over the same
commands the UI sends — they add no logic of their own, so they cannot drift from the
dashboard. All are hub only (they need a server runtime, like `server/publish.py`); local
mode never mounts them.

- [`engine.request()`](../printguard/engine/engine.py) turns the broadcast protocol into
  request/response by correlating a `req_id`; `engine.snapshot()` encodes a camera's
  freshest frame as JPEG. Both are mode-agnostic engine methods.
- [`server/api.py`](../printguard/server/api.py) is a FastAPI sub-app at `/api/v1`; each
  route delegates to those methods and is tagged with the scope it requires.
- [`server/mcp.py`](../printguard/server/mcp.py) derives its tools from that app with
  `FastMCP.from_fastapi`, adds a camera-frame tool that returns native image content, and
  enforces the route scope tags so a caller only sees the tools its token may use.
- [`server/mqtt.py`](../printguard/server/mqtt.py) bridges the engine to Home Assistant: it
  subscribes to engine events as a transport sink and reconciles one MQTT device per monitor
  through Home Assistant discovery, and routes inbound commands (the Enabled switch, the
  printer buttons) back through `engine.request()`. The discovery payloads, state blob and
  command routing are pure functions; an `aiomqtt` session that reconnects on failure and on
  a settings change wraps them. Control is gated by broker access, not by a token.

The REST and MCP surfaces are gated by cumulative scopes (`read` ⊂ `control` ⊂ `manage`);
see [docs/api.md](api.md).

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
    participant W as Watchdog
    participant I as Integration adapter
    participant N as Notifier adapters

    S->>P: grab freshest frame, infer()
    P-->>S: classification result
    S->>W: on_score(monitor, frame, score)
    alt score ≥ threshold for N consecutive frames
        W->>I: pause / cancel the linked printer (retried on failure)
        I-->>W: ok, or "failed" after retries
        W-->>W: emit alert event (action included)
        W->>N: snapshot + outcome to every enabled channel
    else score below threshold
        W-->>W: streak and alert reset
    end
```

A failed printer action is retried, then reported in the alert, the UI error feed and the push notification.

## Failing safely

A monitor's **watching** state gates inference
([`monitors.monitor_watching`](../printguard/engine/monitors.py)):

| Linked printer reports | Watched? | Why |
|---|---|---|
| no printer linked | yes | nothing to gate on |
| `printing` | yes | the job needs eyes |
| no state yet / `unknown` | yes | can't tell → watch |
| `offline` (unreachable) | yes | losing the signal must not stop monitoring |
| `idle` / `paused` / `error` | no (standby) | positively not printing |

Only a *positive* "not printing" stands inference down. The watchdog loop then
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
    registry.py      camera + printer registries (registered resources)
    monitors.py      monitor config: a camera + printer pairing and its thresholds
    printers.py      registered-printer (integration connection) validation
    watchdog.py      defect response: streaks, printer actions, notifications, health
    integrations/    printer service adapters (OctoPrint, Klipper, Bambu Lab, …)
    notifiers/       alert channel adapters (ntfy, Telegram, Discord, …)
    adapters.py      shared adapter contract (id, label, docs_url, JSON-schema config)
  server/            hub platform: FastAPI, MediaMTX, LiteRT, PyAV
    api.py           REST API (/api/v1) over the engine protocol, scoped by token
    mcp.py           MCP server for agents, derived from the REST API
    mqtt.py          Home Assistant MQTT bridge (device discovery + two-way control)
    bambu_camera.py  Bambu A1/P1 chamber-camera reader (proprietary port-6000 protocol)
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
