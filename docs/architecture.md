<div align="center">

# Architecture

[Docs](README.md) · [Printers](printers.md) · [Cameras](cameras.md) · [Monitoring](monitoring.md) · [Notifications](notifications.md) · [Training frames](feedback.md) · [Hardware](hardware.md) · [Deployment](deployment.md) · [API & MCP](api.md) · [Plugins](plugins.md) · [Writing plugins](plugin-development.md) · **Architecture** · [Troubleshooting](troubleshooting.md)

</div>

PrintGuard is a monolith. One Python engine owns every decision, a hub server runs it, and
the React dashboard, the REST API, the MCP server and the MQTT bridge are transports that only
send it commands. The engine's own logic reaches hardware, the network and disk through one
`Platform` protocol, so the tests run it against an in-memory fake. Adapters built on a
vendor's client library are the exception, covered under
[the platform contract](#the-platform-contract).

- [The shape of it](#the-shape-of-it)
- [The platform contract](#the-platform-contract)
- [The protocol](#the-protocol)
- [Resources and monitors](#resources-and-monitors)
- [Scheduling inference](#scheduling-inference)
- [The defect pipeline](#the-defect-pipeline)
- [Failing safely](#failing-safely)
- [The programmatic surface](#the-programmatic-surface)
- [Plugins](#plugins)
- [Updates and bug reports](#updates-and-bug-reports)
- [Logging](#logging)
- [Configuration](#configuration)
- [Repository layout](#repository-layout)
- [The website](#the-website)

## The shape of it

```mermaid
flowchart LR
    subgraph transports["Transports (no logic of their own)"]
        ui["React UI<br/>WebSocket"]
        surface["REST API · MCP · MQTT bridge"]
    end

    transports <-- "JSON commands / events" --> engine

    subgraph engine["printguard/engine"]
        registry["registries<br/>cameras · printers · prints · tokens · plugins"]
        monitors["monitors (camera + printer)"]
        scheduler["fair scheduler"]
        vision["vision (transform / preprocess / classify)"]
        history["risk history"]
        watchdog["watchdog (defect response)"]
        integrations["integration adapters"]
        notifiers["notifier adapters"]
        plugins["plugins (sourcing + permissions)"]
    end

    engine -- "Platform protocol" --> server["server/platform.py<br/>LiteRT / ONNX Runtime · PyAV · httpx · QuickJS"]

    server --- mediamtx["MediaMTX<br/>RTSP / RTMP / WHEP / HLS"]
    integrations --- printersvc["OctoPrint / Moonraker / Elegoo / PrusaLink / Bambu Lab"]
    notifiers --- push["ntfy / Pushover / Telegram / Discord / native"]
```

### What the hub serves

[`server/app.py`](../printguard/server/app.py) builds one FastAPI app on one port.

| Route | Serves |
|---|---|
| `/api/ws` | The engine socket the dashboard speaks the protocol over |
| `/api/publish/{path}` | A second WebSocket taking a browser's camera recording, which [`server/publish.py`](../printguard/server/publish.py) remuxes into MediaMTX over RTSP |
| `/hls/{path}` | A proxy to MediaMTX's HLS, served as fMP4 segments (`hlsVariant: fmp4`, not the low-latency variant), which also wakes a sleeping camera source for the viewer. A request from another origin is refused and MediaMTX's CORS headers are dropped, so neither a page on another site nor a plugin page can pull a feed |
| `/api/health` | `{ok, version}`, used by the image's health check |
| `/api/prints`, `/api/prints/inspect`, `/api/prints/{id}/gcode`, `/api/prints/{id}/thumbnail` | The dashboard's print library upload, pre-upload inspection, gcode viewer and previews |
| `/plugins/{id}/{path}` | A plugin's own routes, answered from its sandbox |
| `/oauth/callback` | Where a provider sends the user back after a plugin's sign-in |
| `/api/v1`, `/mcp` | The REST API and the MCP server |
| `/` | The built dashboard from `STATIC_DIR` |

Every request is refused unless its host is an address, a local name or one listed in
`PRINTGUARD_ORIGINS`. Both WebSockets and the two print `POST` routes also check the request's
`Origin` against that host. See
[host and origin checking](deployment.md#host-and-origin-checking).

## The platform contract

[`engine/platform.py`](../printguard/engine/platform.py) defines everything the engine needs
but does not do itself. [`server/platform.py`](../printguard/server/platform.py) implements it
for the hub:

| Member | On the hub |
|---|---|
| `host` | Which deployment this is: `macos`, `windows`, or `docker` plus the image variant |
| `workers` | How many inferences run at once, measured when the runtime loads |
| `inference_device` | The name of the device the selected runtime runs on, shown in the dashboard |
| `version` | The installed package version |
| `update_repo`, `update_asset` | The GitHub repository whose releases are checked, and the installer the desktop app updates with |
| `plugin_runtime` | A `PluginRuntime`, or `None` with `PRINTGUARD_PLUGINS=off` |
| `files` | A `FileStore` |
| `configure(settings)` | Selects LiteRT, ONNX Runtime or the faster local benchmark, and measures its worker count |
| `take_notices()` | What the hub has worked around since the last call, as `Notice` records: an accelerator passed over for the CPU, and a camera whose live view cannot publish or has come back. The hub meets these on its own threads, so the engine collects them on its ticker and raises each as a `warning` |
| `infer(rgb)` | `vision.preprocess`, the selected LiteRT or ONNX Runtime model, then `vision.classify` |
| `discover_cameras()` | V4L2, AVFoundation or DirectShow capture devices, plus the MediaMTX path list |
| `open_camera(id, source)` | A `FrameSource`. MediaMTX pulls every URL that is not plain HTTP, so RTSP, RTMP and WHEP, and PyAV reads HTTP MJPEG and capture devices directly. A `path` source reads a stream already on MediaMTX, and a `bambu` source the A1 and P1 chamber camera |
| `release_camera(id, source)` | Closes the source and removes its MediaMTX pull path. A reader that is stuck inside a device read cannot be stopped, so `open_camera` refuses to start another for that camera while it lasts |
| `http(...)` | httpx. A redirect that would replay the request under another method, such as a POST answered with 301 or 302, raises. So does a body over `max_bytes`, which a plugin's request, a plugin install, the catalogue and the update check pass, counted as it is decompressed, and an answer to one of those in any encoding but gzip |
| `open_socket(url, arrived)` | A `websockets` client connection held for a plugin, which refuses a redirect |
| `encode_jpeg(rgb)` / `decode_jpeg(data)` | PyAV |
| `load_state()` / `save_state(state)` | `data/state.json`, written atomically and readable only by its owner |

Three smaller protocols hang off it:

| Protocol | Members | On the hub |
|---|---|---|
| `FrameSource` | `fps`, `online`, `standby`, `grab()`, `set_monitoring(active)`, `close()` | A PyAV reader thread per camera |
| `FileStore` | `store(key, chunks)`, `read(key)`, `remove(key)` | Print files, their previews and the frames kept from each print, on disk under `data/prints/` |
| `PluginRuntime` | `attach()`, `on_event()`, `reload()`, `serve()`, `authorise()`, `gate_paths()`, `close()` | QuickJS in WebAssembly, under wasmtime |

A `Frame` is the RGB array, a `seq` that identifies it and its capture time.

[`tests/fakes.py`](../tests/fakes.py) implements the same protocols in memory, with synthetic
cameras, a canned model and recorded HTTP. That is how the engine tests drive alerts, outages
and printer actions in milliseconds with no camera, model or network.

> [!IMPORTANT]
> The engine never imports from `server/`, and its own logic does no I/O outside `Platform`.
> If a feature needs a runtime service, add it to the `Platform` protocol and implement it in
> `server/platform.py` and in the test fake.

HTTP adapters go through `platform.http`, so the tests pin every request they make. Adapters
built on a vendor's client library open their own connections:

| Module | Reaches outside `Platform` through |
|---|---|
| [`integrations/bambu.py`](../printguard/engine/integrations/bambu.py) | paho MQTT on one connection held per printer, `ftplib` over TLS and raw sockets |
| [`integrations/elegoo.py`](../printguard/engine/integrations/elegoo.py) | pycentauri, which holds its own connection, a DNS lookup and a temporary file for an upload |
| [`integrations/prusa.py`](../printguard/engine/integrations/prusa.py) | pyprusalink with its own httpx client |
| [`notifiers/native.py`](../printguard/engine/notifiers/native.py) | desktop-notifier and a temporary snapshot file |
| [`urls.py`](../printguard/engine/urls.py) | A DNS lookup, to tell whether a plugin's URL lands on a private address |
| [`logs.py`](../printguard/engine/logs.py) | The rotating log file |

The tests cover those adapters by monkeypatching their private seams, such as Bambu's
`_pull_report` and `_publish`. See [`tests/test_adapters.py`](../tests/test_adapters.py).

## The protocol

Commands, UI to engine. The table is the engine's `_handlers` map:

| Group | Commands |
|---|---|
| Cameras | `discover`, `camera.add`, `camera.update`, `camera.remove`, `camera.snapshot` |
| Printers | `printer.add`, `printer.update`, `printer.remove`, `printer.action`, `printer.heat`, `printer.test`, `printer.cameras.refresh` |
| Prints | `print.add`, `print.update`, `print.remove`, `print.start` |
| Monitors | `monitor.add`, `monitor.update`, `monitor.remove` |
| History | `history.get`, `snapshot.get`, `review.get`, `review.send`, `review.retry`, `review.dismiss` |
| Plugins | `plugin.install`, `plugin.remove`, `plugin.update`, `plugin.code`, `plugin.catalogue`, `plugin.page`, `plugin.http`, `plugin.socket`, `plugin.call`, `plugin.answer`, `plugin.publish`, `plugin.secrets`, `plugin.oauth`, `plugin.effect` |
| System | `settings.update`, `notify.test`, `notify.send`, `token.create`, `token.remove`, `update.check`, `update.releases`, `report.send`, `report.bundle` |

Every command may carry a `req_id`, echoed on the responding event so the UI can resolve
pending requests. A command that succeeds ends with a `state` event carrying that `req_id`,
or with its own event for the four that only read, and one that fails ends with an `error`,
an unknown command included. An error that carries no text of its own, as a timeout does, is
reported by its type.

Events, engine to UI:

| Event | Carries |
|---|---|
| `state` | Full snapshot, on connect, after every command that can change it and on a 1 s ticker. `history.get`, `snapshot.get`, `review.get` and `camera.snapshot` only read, so they save nothing and answer with their own event alone. The commands in `UNSAVED_COMMANDS`, such as `discover`, `printer.test`, `notify.test`, `update.check`, `report.bundle` and a plugin's requests, change nothing that is stored, so they save nothing either and their closing `state` goes only to the transport that sent them. The fields are listed below |
| `result` | One monitor's score, sampled at up to 5 Hz per monitor |
| `alert` | A sustained defect, with the action taken |
| `warning` | Watchdog conditions and their recovery, an MQTT broker the bridge cannot reach, once when the outage starts and once when it ends, and what the platform reports through `take_notices()` |
| `device` | A printer's status, progress, job, time left and heaters |
| `print_started` | A file from the library has been sent to a printer and started |
| `discovered`, `printer_test`, `notify_test` | Command responses |
| `history`, `snapshot`, `review` | Risk history buckets, a kept frame's JPEG, and the frames kept from one print, each delivered only to the transport that asked |
| `review_sent` | How far a reviewed print's upload got, with the refusal code and retry time when it is queued |
| `frame` | A camera's current picture as a JPEG, the answer to `camera.snapshot`. A camera on standby or offline has none, and the command fails |
| `releases` | The changelog history the update dialog browses |
| `token_created` | A new API token's secret, delivered only to the transport that asked, never to the others and never written to the log |
| `report_sent`, `report_bundle` | Bug report outcome, and the downloadable diagnostics zip |
| `plugin_code`, `plugin_page`, `catalogue`, `plugin_effect` | A plugin's source for its sandbox, the page files a zip install carries, the reviewed-plugin catalogue, and an effect a dashboard performs for a plugin that has no screen of its own |
| `plugin_oauth` | The provider URL the dashboard opens to start a plugin's sign-in |
| `http`, `socket` | An answer to a plugin's own request, and a frame on a socket it is holding, both addressed to the plugin that asked |
| `call`, `answer`, `message` | One plugin's question to another, the reply, and a message published on a channel other plugins listen to |
| `error` | Anything that failed, including failed printer actions and a Home Assistant command the bridge could not run |

`state_event()` in [`engine/engine.py`](../printguard/engine/engine.py) returns these fields:

| Field | Holds |
|---|---|
| `host`, `version`, `update` | The deployment, the running version and the release status |
| `cameras`, `printers`, `prints`, `tokens`, `plugins` | The public record of everything in each registry |
| `monitors` | Each monitor with `watching` and its latest `result` |
| `reviews`, `feedback_hub` | A count of the frames kept from each print with its review status, and the public half of the hub's training inbox token |
| `settings` | Notifier configs, MQTT, theme, custom themes, glass, layout, inference runtime, catalogue URL, grace period, preheat presets, and whether to check for updates and ask for print reviews |
| `stats` | `inference_device`, `infer_ms` and `capacity_fps` from the scheduler |
| `integrations`, `notifiers` | Adapter metadata the config forms are drawn from |
| `plugin_permissions`, `plugin_events`, `plugin_event_permissions`, `plugin_oauth_callback`, `plugin_platforms`, `plugin_assets` | The plugin policy both sandboxes apply |

Each socket gets its own queue in [`server/events.py`](../printguard/server/events.py). Ordered
events and command responses leave first and are never dropped. A slow transport keeps only
the newest ticker `state` and the newest `result` per monitor.

The engine socket runs each command a tab sends as its own task, so a slow one such as
registering a stream does not hold a pause behind it. A command that waits on nothing finishes
before the next one starts, which covers every auto-saved update. A tab with 16 commands
running is not read from until one finishes. A frame that is not a JSON
object is answered with an `error` event. Both sockets refuse a handshake that names no
`Origin`, and the publish socket closes on a text frame.

The message of every `warning` and `error` loses each stored credential in `emit()`, before it
is logged or broadcast, because it often quotes an exception a library raised. A value shorter
than 8 characters is only removed where it stands alone, so a short login does not break up
ordinary words.

## Resources and monitors

A camera is a video source and a printer is a control-service connection. Both are
registered resources, created and deleted only in their own registry. A monitor binds one of
each, the printer optionally, and carries the inference thresholds and the
defect-response policy.

| Monitor field | Default | Clamped to |
|---|---|---|
| `threshold` | 0.75 | 0.05 to 0.95 |
| `consecutive` | 3 | 1 to 30 |
| `cooldown_s` | 60 | 0 to 600 |
| `on_defect` | `none` | `none`, `pause` or `cancel` |
| `notify` | off | |

A camera's `detect_fps` caps its inference rate. It defaults to 60 and is clamped to between
0.1 and 60. [Monitoring](monitoring.md) covers how to choose these.

A printer integration that exposes a webcam registers it automatically as a camera owned by
that printer through `Camera.printer_id`, covering the OctoPrint and Moonraker stream URLs, the
Elegoo Centauri chamber camera, and the Bambu chamber camera, over RTSP on the X1 and H2
series or the proprietary port 6000 protocol on the A1 and P1. The adapter's optional
`cameras()` declares them, and the engine reconciles them on printer add and update, and on
demand through `printer.cameras.refresh` to pick up a camera attached later. One printer is
reconciled by one caller at a time, and a camera whose source changed with the printer's
connection details is attached again at the new address with its name and tuning kept. A
printer whose connection details change also loses the status last read through the old ones,
so its monitors watch until the new address answers. Such
cameras cannot be removed on their own and are dropped with their printer. See
[printers](printers.md) and [cameras](cameras.md).

A print file is the third registered resource. The bytes are far
too large for the protocol, so the hub's own upload route streams them into the platform's
`files` store under an id it mints and `print.add` then registers the record, reading the
slicer's estimates, temperatures and preview out of the file through
[`engine/gcode.py`](../printguard/engine/gcode.py). A `nozzle` or `bed` target on `print.add`
rewrites the stored file first. Before uploading, the dashboard sends the same head and tail
of the file that module reads to `/api/prints/inspect`, so its upload panel shows what the slicer
wrote while the file is still on the user's device. Where the slicer wrote no preview the
dashboard draws one from the toolpath and adds it to the gcode as a standard thumbnail block,
so the record arrives with a picture like any other.
A file carries the printers it is tagged for, checked against the adapter's `formats` when the
tag is set, and `print.start` re-polls the printer and refuses unless it answers idle before
the adapter's `print_file()` uploads and starts it. A second `print.start` for a printer still
being sent a file is refused.

API tokens and installed plugins are held in the same registry module and saved with the rest
of the state.

A deployment can declare video devices the same way. The Docker image sets
`PRINTGUARD_CAMERAS=auto`, so every capture device passed into the container comes back from
`discover_cameras()` marked `declared`, and the engine reconciles those into the registry at
boot under a deterministic id through `Camera.declared`. A declared camera keeps the name and
tuning it was given across restarts and cannot be removed on its own.

| Device at boot | Its camera |
|---|---|
| Listed and declared | Registered, or marked `declared` again if it was already there |
| Listed, no longer declared | Dropped |
| Not listed | Kept, offline and no longer `declared`, so `camera.remove` works on it |

A monitor keeps its `camera_id` when a declared or printer-owned camera is dropped, so it
watches again when the camera returns under the same id. Only `camera.remove` and
`printer.remove` clear the binding.

## Scheduling inference

A camera registers with a 15 fps placeholder. Its native frame rate is read from the source
when it attaches, and read again on every 1 s tick and every re-attach. Allocation is fully
dynamic:

1. A smoothed estimate of observed inference latency, a camera's own image adjustments
   included, continuously yields the sustainable total rate, `workers / latency`. `workers` is measured once when the runtime loads, by
   adding concurrency until throughput stops growing, so the division holds rather than
   extrapolating past a ceiling the host cannot reach. See
   [model runtimes](hardware.md#model-runtimes).
2. That capacity is water-filled across in-use cameras with max-min fairness, so no camera is
   allocated beyond its native fps, or beyond the detection rate its user capped it at, and
   surplus flows to cameras that can use it.
3. A free worker takes the most overdue camera and grabs its freshest frame at dispatch
   time. Frames carry a sequence identity, so the same frame is never inferred twice and
   results always describe the present, not a backlog. With nothing due, the dispatcher
   sleeps until the earliest idle camera's interval is up or any inference comes back, so a
   camera capped to a low rate never sets the pace for a faster one beside it.

Changing `settings.inference_runtime` waits for the inferences in flight before the new runtime
loads. One that has not come back after 10 s is given up on and the command fails with the
runtime unchanged.

```mermaid
flowchart LR
    lat["observed latency<br/>smoothed"] --> cap["sustainable total fps<br/>workers / latency"]
    cap --> fill["water-fill across cameras<br/>max-min fairness"]
    native["each camera's native fps<br/>held to its detection rate cap"] --> fill
    fill --> target["per-camera target fps"]
    target --> pick["free worker takes the<br/>most overdue camera"]
    pick --> fresh["grab its freshest frame<br/>never the same frame twice"]
```

MediaMTX bursts the buffered GOP on RTSP connect, so stream fps is trusted from the SDP
`average_rate`, and otherwise measured only after a warm-up. A Bambu A1 or P1 camera is always
measured, since the raw MJPEG demuxer it is read through declares 25 for every stream.

Hub camera capture is demand-driven. A source stays active while an enabled monitor is
watching or while an HLS viewer is requesting it. MediaMTX pulls RTSP, RTMP and WHEP sources
on demand, and PrintGuard wakes its own MJPEG, Bambu and device-camera publisher for
viewers. A positively idle printer lets the source sleep, while an unknown or unreachable
printer keeps it active.

A pull path is added through MediaMTX's API and lives in its memory. When the supervisor
restarts a MediaMTX that exited, the hub adds every path again once the new one answers, so a
sleeping camera's live view is there for the next viewer.

## The defect pipeline

```mermaid
sequenceDiagram
    participant S as Scheduler
    participant V as Vision
    participant P as Platform
    participant E as Engine
    participant W as Watchdog
    participant I as Integration adapter
    participant N as Notifier adapters

    S->>P: grab the camera's freshest frame
    S->>V: transform (rotate, crop, adjust)
    S->>P: infer()
    P-->>S: classification result
    S->>E: _on_result(camera, frame, result)
    E-->>E: defect_score, record in history, emit result (up to 5 Hz)
    E->>W: on_score(monitor, frame, score)
    alt score ≥ threshold for N consecutive frames, outside the cooldown
        W-->>W: start the cooldown
        W->>I: pause / cancel the linked printer (retried on failure)
        I-->>W: ok, or "failed" after retries
        W-->>W: emit alert event (action included)
        W->>N: snapshot + outcome to every configured channel, if notify is on
        W->>I: re-read the printer, so a paused print stands the monitor down
        W->>E: note_alert (snapshot into history)
    else score below threshold
        W-->>W: streak and alert reset
    end
    E-->>E: consider the frame for the print's review
```

[`engine/vision.py`](../printguard/engine/vision.py) holds every image step. `transform`
applies the camera's settings in a fixed order, so rotation, then the crop in the rotated
frame's coordinates, then brightness, contrast and sharpness. `preprocess` resizes the
shortest edge to 256 with Pillow's bilinear filter, converts to luminance, centre-crops to 224
and normalises. `classify` picks the nearest class prototype by Euclidean distance.

`defect_score` maps the two distances to `0.5 * (1 + tanh((success² - failure²) / 2))`, the
softmax over negative squared distances the model was trained with. 0.5 is the decision
boundary, and a frame that could not be classified scores 0.5.

The engine runs `_on_result` for every monitor on that camera that is watching. Each score
goes into [`engine/history.py`](../printguard/engine/history.py), which is held in memory and
lost on restart. The frame that fired each alert is kept on disk by [print reviews](#print-reviews):

| Series | Size |
|---|---|
| Rollup buckets | 60 s each, the newest 1440, so 24 hours of watching |
| Alert log | The newest 50 |

An alert starts the monitor's `cooldown_s`, and no second response fires inside it or while
the first is still in flight. The cooldown ends once the printer reports the print over, so it
never carries into the next one, and a pause keeps it. Push notifications have their own 30 s
floor per monitor and outcome. A printer action is tried 3 times, 1 s apart, then reported as
failed in the alert, the UI error feed and the push notification, and tried again after
`ACT_FAILED_COOLDOWN_S` at the latest. A streak is dropped when its monitor stands down or is
bound to another camera. The notification channels are sent to together with `NOTIFY_TIMEOUT_S`
each, 30 s, so one that never answers cannot hold the response open.

Everything that writes to disk comes after the part that protects the print. A frame is
scored and passed to the watchdog before it is considered for the review, and an alert is
pushed before its frame is stored, so a full data volume raises an `error` event and costs
only the kept frames.

### Print reviews

[`engine/reviews.py`](../printguard/engine/reviews.py) keeps a few frames from every print a
monitor watches, scaled to 512px and stored in the `files` store, with their records in the
persisted state so they survive a restart. With `settings.feedback` set to `off` it keeps only
the alert frames, and switching it off dismisses every `ready` and `queued` print and deletes
the other frames already held. A print runs from a monitor's first frame until its printer
positively reports idle or error, or the monitor is disabled or removed, so a pause stays
inside it. A print whose monitor has a defect response in flight stays open until that
response has kept its alert frame, so a cancelled printer read idle while the notifiers are
still answering can't close the print without it. A monitor with no printer closes its print
after a day.

| Kind | Kept | Chosen by |
|---|---|---|
| `alert` | The last 40 | The frame that fired each alert, which is what the risk history gallery shows |
| `near` | The top 5 | The highest scores under the threshold, at least a minute apart |
| `spaced` | Up to 19 | One per interval, and every other one is dropped and the interval doubled at 20, so a long print keeps no more than a short one |

The hub holds the last 20 prints or 200 MB and drops the oldest finished print first, so
prints still running never push out every finished one. A print that ends with no frames kept
is `dismissed`, since there is nothing to review. The
`state` snapshot carries only a count per print, and `review.get` returns one print's frames.

A finished print can be [sent as training data](feedback.md). `review.send` records which
frames show a failure and which were left out, and
[`engine/feedback.py`](../printguard/engine/feedback.py) uploads the rest through
`platform.http` to the Worker in [`feedback-worker/`](../feedback-worker), one frame per
request. The upload runs as a background task and its progress rides in the `state` snapshot.
It is deliberately absent from the REST API, the MCP server and the plugin permission table,
so frames only leave the hub when a person presses Send in the dashboard.

| `status` | Meaning |
|---|---|
| `running` | The print is still being watched |
| `ready` | It has ended and waits to be reviewed |
| `dismissed` | Nobody wants to review it, or `settings.feedback` is `off` |
| `queued` | It was reviewed and frames are uploading, or wait on a refusal's `retry_at` |
| `sent` | Every chosen frame is in the inbox |

The Worker is the only writer to a private R2 bucket and holds every limit in one Durable
Object, so the hub only reports what it was told. A refused print keeps its frames and the
engine's ticker sends the rest once `retry_at` passes, six hours on where the refusal named no
time or one already past on the hub's clock. A send cut short by a restart has no `retry_at` and is picked up on the next tick. A print dismissed while it uploads stops after the frame in flight. A frame over 150 KB is re-encoded once at 384px and skipped if it is still too big, as is one whose file is missing or that the Worker rejects as `details`, `not_jpeg`, `too_large` or `length`, since it could never be sent. A skipped frame leaves the submission, so `chosen` and `sent` count only what the inbox took. The Worker counts a network under an HMAC of its address, never the address, and counts a frame it already holds as no new upload. The hub's token is issued by the Worker
and persisted, and the `state` snapshot carries only its public half as `feedback_hub`.

## Failing safely

A monitor's watching state gates inference
([`monitors.monitor_watching`](../printguard/engine/monitors.py)):

| Linked printer reports | Watched? | Why |
|---|---|---|
| No printer linked | Yes | Nothing to gate on |
| No state yet | Yes | Cannot tell, so watch |
| `printing` | Yes | The job needs eyes |
| `idle`, `paused`, `error` | No, standby | Positively not printing |
| `offline`, `unknown`, unreachable | Whatever it last reported | Contact lost mid-print keeps watching, and a printer switched off after a print stays in standby |

Only a positive "not printing" stands inference down, and only a positive "printing" wakes
it again ([`Printer.observe`](../printguard/engine/registry.py) keeps the last status the
service could report, and it is saved with the printer so a restart keeps it too). A command sent from PrintGuard, such as a pause or starting a print
from the library, re-reads the printer and re-gates straight away. The watchdog loop then keeps the
pipeline honest. A condition has to hold for the grace period before it is announced, apart from the
coverage warning below, so a brief outage passes unremarked, and it is then repeated every thirty minutes for as long as
it lasts. Recovery is announced once health has held.

```mermaid
stateDiagram-v2
    direction LR
    [*] --> Watching
    Standby --> Watching: positively printing
    Watching --> Standby: positively not printing
    Watching --> Faulting: fault
    Faulting --> Watching: recovered inside the grace period
    Faulting --> Warned: held for the grace period
    Warned --> Watching: healthy for the recovery hold
    note right of Warned
        Still watching. A warning
        never stands inference down.
        Faulting again while warned
        stays one warning.
    end note
```

The four watchdog conditions are a watched camera going offline or not being registered at
all, a watched camera staying
online but producing no fresh frames, since a frozen RTSP feed must not pass for monitoring,
a watched camera that delivered frames for under 90% of the last ten minutes, and a linked
printer whose state cannot be read, whether it is unreachable or reporting something the
adapter does not recognise. The last one only counts while the monitor is watching, where it
means a defect could not pause the print. A printer switched off after a print leaves its
monitor in standby and warns about nothing. A monitor with no registered camera reads as not
`watching` in the state, and a monitor that stands down forgets its camera faults, so the
next print starts with a full grace period.

The grace period is `settings.fault_grace_s`, two minutes by default, and it is clamped to
between thirty seconds and fifteen minutes so it can be lengthened for a camera that drops
out and comes straight back but never turned into an off switch. A camera that keeps
dropping, or freezing and giving a frame each time it is re-attached, clears the grace period
every time yet is only watching part of the print, which is what the coverage condition is
for: the share of the recent window it delivered frames for is one warning about an
unreliable feed rather than one per drop.

Warnings surface as dashboard toasts, and go out through the notification channels when the
monitor has `notify` on, so the watchdog suppresses flapping rather than repeating itself. A
source that reconnects and drops
again is still the same warning, and each announced recovery doubles how long the
next one must hold before it is announced, up to fifteen minutes. Only the notification
waits on the grace period. The dashboard shows a fault as it happens, and re-attaching a
failed camera runs on its own timer, so a longer grace period never delays recovery. A stall
starts once an online camera has gone `STALL_GRACE_S` without a completed inference and ends
only when one completes again, so re-attaching the camera neither restarts its grace period
nor counts as recovery, and the warning follows the last result by `STALL_GRACE_S` plus the
grace period. A stall is not announced while its camera is offline, and an announced outage
takes over from it, so a feed that froze and then dropped is one fault.
Notifier delivery failures and inference crashes emit `error` events. There is no silent
`except: pass` anywhere in the alert path.

The scheduler, the printer poll, the health check and the state ticker each run one pass at a
time under `Engine._repeat`. A pass that raises emits an `error` event and the loop carries
on a second later, and a defect response that raises is reported the same way. A fault that
repeats is reported once every 30 s.

The timings are constants at the top of [`engine/watchdog.py`](../printguard/engine/watchdog.py):

| Constant | Value | Governs |
|---|---|---|
| `DEVICE_POLL_S` | 5 s | The gap between reads of every printer's state, which are made together |
| `WATCH_TICK_S` | 2 s | How often the health conditions are checked |
| `GRACE_DEFAULT_S`, `GRACE_MIN_S`, `GRACE_MAX_S` | 120 s, 30 s, 900 s | The grace period and its clamp |
| `REPEAT_EVERY_S` | 1800 s | How often a standing warning is repeated |
| `RECOVER_HOLD_S`, `FLAP_HOLD_MAX_S` | 60 s, 900 s | The first recovery hold, and the ceiling it doubles towards |
| `STALL_GRACE_S` | 30 s | How long an online camera may go without a completed inference before it counts as stalled |
| `COVERAGE_WINDOW_S`, `COVERAGE_MIN` | 600 s, 0.9 | The window and share behind the coverage condition |
| `RESTART_AFTER_S`, `RESTART_COOLDOWN_S` | 15 s, 60 s | How long a camera faults before it is re-attached, and the gap between attempts |
| `ACT_ATTEMPTS`, `ACT_RETRY_S` | 3, 1 s | Printer action attempts and their spacing |
| `ACT_FAILED_COOLDOWN_S` | 30 s | The longest a failed printer action waits before the next defect frame tries it again |
| `NOTIFY_COOLDOWN_S` | 30 s | The floor between defect notifications with the same outcome for one monitor |

A camera with no source at all is retried by the engine's ticker every 10 s.

## The programmatic surface

The MCP server, REST API and Home Assistant MQTT bridge are thin transports over the same
engine the UI talks to, so they add no logic of their own and cannot drift from the dashboard.

- [`engine.request()`](../printguard/engine/engine.py) turns the broadcast protocol into
  request and response by correlating a `req_id`, and `engine.snapshot()` encodes a camera's
  freshest frame as JPEG.
- [`server/api.py`](../printguard/server/api.py) is a FastAPI sub-app at `/api/v1`, each
  route tagged with the scope it requires. Every write goes through `engine.request()`. The history route does too. Other reads
  call the engine directly: the state, list and get routes use `state_event()` with printer,
  notifier, MQTT and camera-source credentials stripped and each plugin's store left out, and the alert snapshot, camera frame,
  classify and events routes use `monitor_snapshot()`, `snapshot()`, `classify()` and
  `recent_events()`. `recent_events()` is the newest 100 alert, warning, device and error
  events.
- [`server/mcp.py`](../printguard/server/mcp.py) derives its tools from that app with
  `FastMCP.from_fastapi`, leaving out the camera frame, the alert snapshot,
  classify, and the print file download and upload, which carry a binary body. It adds three tools of its own,
  `get_camera_frame` and `get_monitor_snapshot` returning native image content and `classify_frame` taking a base64
  image, and enforces the route scope tags so a caller only sees the tools its token may use.
- [`server/mqtt.py`](../printguard/server/mqtt.py) bridges the engine to Home Assistant. It
  subscribes to engine events as a transport sink, reconciles one MQTT device per monitor
  through Home Assistant discovery, and routes inbound commands, the Enabled switch and the
  printer buttons, back through `engine.request()`. The discovery payloads, state blob and
  command routing are pure functions, wrapped in an `aiomqtt` session that reconnects on
  failure and on a settings change. Control is gated by broker access, not by a token.

REST and MCP are gated by cumulative scopes, where `control` includes `read` and `manage`
includes both. See
[API & MCP](api.md).

## Plugins

Plugins are third-party code, and the engine runs none of it.
[`engine/plugins.py`](../printguard/engine/plugins.py) only sources it: a fetch from GitHub at
a resolved commit or a zip, manifest validation, a hash of every file, and a comparison against
the catalogue. The registry holds the result beside the cameras, printers and tokens.

Execution is a sandbox on each side. `PERMISSIONS` is the one policy both enforce, and it
reaches the UI in the state snapshot as `plugin_permissions`, the way `integrations_meta()`
already drives the config forms.

```mermaid
flowchart LR
    engine["engine (state, commands)"] -- "permitted state" --> panel & page & worker
    panel["plugin.js<br/>plugin-sandbox.html<br/>opaque-origin iframe"] -- "node tree + effects" --> ui["UI draws it"]
    page["panel.html<br/>plugin-panel.html<br/>opaque-origin iframe"] -- "its own markup + effects" --> ui
    worker["worker.js<br/>QuickJS in wasm<br/>no fs, no sockets, fuel-capped"] -- "effects" --> engine
    ui -- "checked effects" --> engine
```

Both frames set `default-src 'none'`. A plugin ships either `plugin.js`, which
returns a node tree the dashboard draws, or `panel.html`, which draws itself inside its frame.

Four things keep a frame from sending out what it is handed, and
[`sandboxFrame`](../web/src/plugins.ts) is the one place both hosts get them from.

| Measure | Closes |
|---|---|
| `frame-src 'self'` on the dashboard, in `web/index.html` | A frame navigating itself to another host, or to a `data:` or `blob:` page |
| The dashboard removes a frame on its second `load` | A frame that navigated within the hub staying alive |
| State travels over a `MessagePort` transferred once at boot | A page that replaced the sandbox document hearing anything |
| The bootstrap script is allowed by hash, with no `'unsafe-inline'` | A nested frame running its own script to get back the WebRTC constructors the bootstrap deleted. No engine has a policy directive for WebRTC |

The hash covers the inline script in each of `web/public/plugin-sandbox.html` and
`plugin-panel.html`, so an edit to either script needs the new hash in that file's policy. The
browser console prints it.

A sandbox asks for effects and PrintGuard carries them out, checking each against the grants
first. That check belongs at the sandbox edge: by the time a command reaches the engine it is
indistinguishable from one the dashboard sent.

A plugin's source never rides in the state snapshot, which broadcasts every second. It travels
on request through `plugin.code`. That response reaches
every connected client, so a tab ignores one whose `req_id` is not its own, or a second tab
starts a duplicate sandbox.

The hub mounts `/plugins/<id>/` onto a plugin's route handler. A plugin holding the `gate`
permission is asked about every other HTTP request except `/api/health` and its own routes,
and about both WebSocket handshakes. An allowed HTTP answer is cached for 10 s per credential,
method and path. A refusal is never cached.

`PRINTGUARD_PLUGINS=off` starts with every plugin off, and the state snapshot reports each as
disabled so the dashboard stops its half too. [Plugins](plugins.md) covers installing
them and [what each permission grants](plugins.md#permissions), and
[writing plugins](plugin-development.md) covers the API.

## Updates and bug reports

`update.check` refreshes the release status against GitHub
([`engine/updates.py`](../printguard/engine/updates.py)) and `update.releases` serves the
changelog history the update dialog browses, each release with the `files_url` its notes'
relative links resolve against. The engine also checks at boot and every 24
hours after it while `settings.update_check` is on, and 15 minutes after a check that failed. With it off, `update.releases` serves an
empty history until `update.check` is sent. The `state` snapshot carries only the status,
meaning version, latest and whether an update is available, because every release's notes
together dwarf the rest of the snapshot and the history is wanted only while that dialog is
open.

`report.send` is the anonymous bug report
([`engine/reports.py`](../printguard/engine/reports.py)). It is one user-initiated POST of a
Sentry feedback envelope carrying the description, an optional contact email, user-attached files,
the address the dashboard is open at, its user agent and window size,
a diagnostics bundle and the engine and UI log tails, with every credential redacted, sent
through `platform.http`. There is no SDK and no
automatic telemetry, and nothing is sent unless the user submits a report. `report.bundle` packs
those same scrubbed files into a zip the UI downloads instead, for a user who would rather
read the diagnostics or take them somewhere else.

## Logging

One setup ([`engine/logs.py`](../printguard/engine/logs.py)) serves the container and the
desktop app. Entry points call it once and records flow to stdout for `docker logs`, to a rotating file where
no console exists, since the desktop app sets `LOG_FILE` in its data directory, and into a
bounded in-memory tail of 400 lines. The desktop app's window is a separate process, and its
records come back over a queue to be written by the same handlers. The formatter on all three
runs every line, traceback included, through the scrubber events use, so a stored credential
an exception quotes is redacted whichever module logged it.

Alert, warning and error events are logged as they broadcast, so the tail
carries the same timeline the UI shows plus the lifecycle around it, so boot, camera attach
and drop, resource registration, printer actions, and API and socket denials. Device events
log at DEBUG, so they are absent at the default `INFO`. Uvicorn runs without
its own log config so its records land in the same handlers. The UI keeps its own ring
([`web/src/log.ts`](../web/src/log.ts)) of boot milestones, socket drops, toasts, console
warnings and errors, and uncaught exceptions.

Bug reports attach both tails, scrubbed of every configured credential value, and the same
pair can be downloaded as a zip from the report dialog. `LOG_LEVEL=DEBUG` adds command
traces, device events and exception tracebacks.

## Configuration

Everything a user changes is a setting in the dashboard, saved in `state.json`. The variables a
deployment sets are in [deployment](deployment.md#environment-variables). These are the rest,
for development and packaging.

| Variable | Does | Default |
|---|---|---|
| `MODEL_DIR` | The model, its metadata and prototypes | `models/` |
| `STATIC_DIR` | The built dashboard the hub serves | `web/dist` |
| `LOG_FILE` | A rotating log file, 2 MB with two backups | None, and `printguard.log` in the desktop app's data directory |
| `MEDIAMTX_BINARY` | The MediaMTX binary the hub supervises, 1.15.4 or newer. The hub starts it with a random login for its control API, which `mediamtx.yml` grants to nobody. Unset, the hub expects one already running | Unset |
| `MEDIAMTX_CONFIG` | The config that binary starts with. The hub adds its API login as the second entry of `authInternalUsers`, so a config of your own has to declare exactly one user there, as `mediamtx.yml` does. A second one would be overwritten | `mediamtx.yml` |
| `MEDIAMTX_API`, `MEDIAMTX_RTSP`, `MEDIAMTX_HLS` | Where MediaMTX's control API, RTSP and HLS listeners are. If a MediaMTX you run yourself wants a login for its API, put it in the URL as `http://user:pass@host:9997` | `http://localhost:9997`, `rtsp://localhost:8554`, `http://localhost:8888` |
| `UPDATE_ASSET` | The release asset this deployment updates with. Setting it marks the hub as the desktop app | Unset, and the platform's installer in the desktop app |
| `PRINTGUARD_VARIANT` | The image variant suffix reported in `host`, set from the image build arg | Empty |
| `APP_ICON` | The icon on native notifications, set by the Windows desktop app | Unset |
| `PRINTGUARD_DEBUG_PORT` | Opens the Windows desktop window to the DevTools protocol, which is how CI drives it | Unset |
| `MEDIAMTX_BUNDLE`, `PRINTGUARD_ICON` | The binary and icon `printguard.spec` bundles, exported by `build.sh` | Set by the build |
| `APPLE_SIGNING_IDENTITY`, `APPLE_API_KEY`, `APPLE_API_KEY_ID`, `APPLE_API_ISSUER` | Sign and notarise the macOS build | Unset, giving an unsigned build |
| `PRINTGUARD_URL` | The running hub the launch tests drive. Unset, Playwright starts the Vite dev server | Unset |
| `PRINTGUARD_CAMERA_HOST` | The host the hub under test reaches the launch tests' fake camera on | `127.0.0.1` |
| `PRINTGUARD_CDP`, `PRINTGUARD_LOG` | The desktop window's DevTools endpoint and the app's log file, for the launch tests | Unset |

## Repository layout

```
printguard/
  engine/            the engine - every decision, with its own logic doing no I/O outside Platform
    engine.py        the command handlers, events, state snapshot and background loops
    platform.py      the Platform, FrameSource, FileStore and PluginRuntime protocols
    registry.py      registered resources: cameras, printers, prints, tokens and plugins
    bounds.py        the one clamp every sanitiser uses, refusing NaN and Infinity
    appearance.py    the shape of the theme, custom themes, glass and layout the dashboard saves
    cameras.py       camera settings: defaults, clamps and WebRTC URL detection
    monitors.py      monitor config: a camera + printer pairing and its thresholds
    printers.py      registered-printer (integration connection) validation
    prints.py        print library records: formats, names and which printers a file may go to
    gcode.py         what a sliced file says about itself: estimates, printer model, preview
    scheduler.py     fair allocation of inference across cameras
    vision.py        image transform, preprocessing, prototype classification and the defect score
    history.py       per-monitor risk buckets and the alert log, in memory
    reviews.py       the frames kept from each watched print, and which ones are worth keeping
    feedback.py      uploads a reviewed print's frames to the training inbox
    watchdog.py      defect response: streaks, printer actions, notifications, health
    tokens.py        scoped API tokens
    updates.py       GitHub release check and changelog history
    reports.py       anonymous bug report and downloadable diagnostics bundle
    logs.py          the one logging setup and the in-memory tail
    plugins.py       plugin sourcing, hash pinning and the permission table (never executes)
    oauth.py         a plugin's sign-in to a service, by authorisation code with PKCE
    sockets.py       WebSockets held open for plugins
    urls.py          URL match patterns, the scope of a plugin's network grant
    integrations/    printer service adapters (OctoPrint, Klipper, Elegoo, PrusaLink, Bambu Lab)
    notifiers/       alert channel adapters (ntfy, Pushover, Telegram, Discord, native desktop)
    adapters.py      shared adapter contract (id, label, docs_url, JSON-schema config)
  server/            hub platform: FastAPI, bundled MediaMTX (child process), LiteRT / ONNX Runtime, PyAV
    app.py           the FastAPI app: engine socket, publish socket, HLS proxy, plugin routes and gate
    platform.py      the hub's Platform: capture, MediaMTX, httpx, the state file and the file store
    inference.py     LiteRT and ONNX Runtime selection and the worker benchmark
    events.py        the per-socket queue that conflates state and result events
    publish.py       pushes browser recordings and MJPEG sources into MediaMTX over RTSP
    api.py           REST API (/api/v1) over the engine protocol, scoped by token
    mcp.py           MCP server for agents, derived from the REST API
    prints.py        print library uploads and downloads, shared by the dashboard and the REST API
    mqtt.py          Home Assistant MQTT bridge (device discovery + two-way control)
    plugins.py       plugin worker sandbox: QuickJS in WebAssembly, under wasmtime
    runtime/         the vendored quickjs-ng WASI build the sandbox runs
    mediamtx.py      MediaMTX control client and supervisor for the bundled binary
    bambu_camera.py  Bambu A1/P1 chamber-camera reader (proprietary port-6000 protocol)
    desktop.py       macOS and Windows tray app around the hub
web/                 React + Tailwind UI (presentation only)
  src/               the dashboard: the store, the engine socket and the components
  public/            plugin-sandbox.html and plugin-panel.html, the opaque-origin frames a plugin runs in
  site/              the landing page published to GitHub Pages
  launch/            Playwright run from camera to alert against a running build
  tests/             Playwright tests of the browser plugin sandbox, the dashboard and README rendering
  screenshots/       renders docs/assets from fake data
  scripts/           the plugin linter
feedback-worker/     the Cloudflare Worker and R2 inbox that take training frames, and the script that empties it
plugins/             first-party plugins and the hash-pinned catalogue they are verified by
models/              TFLite and ONNX encoders, normalisation metadata, class prototypes
tests/               engine simulation, adapter contracts, the hub and the plugin sandbox (pytest)
packaging/           the desktop app build: PyInstaller spec and its entry script, build script, macOS entitlements and the Windows app config
templates/           the Unraid container template
docs/                these pages and their screenshots
Dockerfile           the image, with MediaMTX and the built dashboard inside
mediamtx.yml         the config the bundled MediaMTX starts with
```

## The website

[oliverbravery.github.io/PrintGuard](https://oliverbravery.github.io/PrintGuard/) is the landing
page in [`web/site`](../web/site), a second Vite root that shares the dashboard's stylesheet
and takes its screenshots from `docs/assets`. The release workflow builds it with
`npm run site:build` and publishes `web/dist-site` to GitHub Pages. The hub never serves it.
