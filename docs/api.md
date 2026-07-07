# API & MCP

A PrintGuard **hub** exposes its engine to agents and developers through two transports
over one protocol — the same commands the dashboard sends, so nothing here can drift from
the UI:

- a **Model Context Protocol** server at `/mcp/` (Streamable HTTP) for agents, and
- a versioned **REST API** at `/api/v1` for any HTTP client.

Both are hub-only. Local (in-browser) mode has no server to host them.

## Authentication & scopes

PrintGuard ships no identity layer of its own — put a proxy in front of the hub
([docs/deployment.md](deployment.md)). On top of that, the API and MCP surface is gated by
**capability scopes** so you can decide exactly what an agent may do.

Scopes are cumulative:

| Scope | Grants |
|---|---|
| `read` | status of monitors, printers and cameras, the current camera frame, recent events |
| `control` | everything in `read`, plus pause / resume / cancel a print |
| `manage` | everything in `control`, plus add/remove/edit cameras, printers and monitors, change settings, test printer services and notifiers, discover cameras |

Issue scoped **bearer tokens** from the dashboard — **Settings → API & MCP access**. Name a
token, choose its scope and **Generate**; the full secret (a `pg_…` string) is shown
**once**, so copy it then. Only a hash is stored, so a token can never be retrieved later —
if one is lost, revoke it and issue another. Revoking takes effect immediately.

```http
Authorization: Bearer pg_Zr8...agent
```

- **No tokens issued (default):** the surface is **read-only** and trusts whatever
  fronts it — control and management stay closed until you issue a token.
- **Any token issued:** a valid bearer is required for every request; its scope
  decides what it can reach. MCP additionally **hides** tools a token cannot use.

Tokens are stored hashed and are managed only from the UI (behind your proxy), never over
the API itself — an agent holding a `manage` token can drive printers and cameras but
cannot mint or escalate tokens. Serve the hub over HTTPS so tokens are never sent in clear.

## REST API

Base path `/api/v1`. Requests and responses are JSON, except the camera frame, which is
`image/jpeg`. Mutating endpoints return the affected collection.

| Method | Path | Scope | Description |
|---|---|---|---|
| `GET` | `/state` | read | Full snapshot: cameras, printers, monitors, settings, stats |
| `GET` | `/monitors` | read | List monitors with camera, linked printer and latest alert |
| `GET` | `/monitors/{id}` | read | One monitor |
| `GET` | `/printers` | read | List registered printers with status, progress and job |
| `GET` | `/printers/{id}` | read | One printer |
| `GET` | `/cameras` | read | List cameras with rate, health and latest score |
| `GET` | `/cameras/{id}` | read | One camera |
| `GET` | `/cameras/{id}/frame` | read | Freshest frame as `image/jpeg` |
| `GET` | `/events` | read | Recent alerts, warnings, device changes and errors |
| `POST` | `/printers/{id}/action` | control | `{"action": "pause" \| "resume" \| "cancel"}` |
| `POST` | `/monitors` | manage | Add a monitor (binds a camera + optional printer) |
| `PATCH` | `/monitors/{id}` | manage | Update a monitor |
| `DELETE` | `/monitors/{id}` | manage | Remove a monitor |
| `POST` | `/printers` | manage | Register a printer |
| `PATCH` | `/printers/{id}` | manage | Update a printer |
| `DELETE` | `/printers/{id}` | manage | Remove a printer |
| `POST` | `/printers/test` | manage | `{"provider", "config"}` — reachability |
| `POST` | `/cameras` | manage | Add a camera |
| `PATCH` | `/cameras/{id}` | manage | Update a camera |
| `DELETE` | `/cameras/{id}` | manage | Remove a camera |
| `POST` | `/cameras/discover` | manage | List attachable, unregistered sources |
| `POST` | `/cameras/refresh-printers` | manage | Register cameras newly exposed by registered printers |
| `PATCH` | `/settings` | manage | Update settings (e.g. notifiers) |
| `POST` | `/notifiers/test` | manage | `{"provider", "config"}` — send a test |

Interactive schema (OpenAPI) is served at `/api/v1/docs`.

```bash
# Status of every printer
curl -H "Authorization: Bearer $TOKEN" https://host/api/v1/printers

# Save the current frame of a camera
curl -H "Authorization: Bearer $TOKEN" https://host/api/v1/cameras/$CAM/frame -o frame.jpg

# Pause a print
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"action":"pause"}' https://host/api/v1/printers/$PRINTER/action
```

## MCP server

Endpoint `https://<host>/mcp/`, transport **Streamable HTTP**, authenticated with the same
bearer token. Tools mirror the REST operations one-to-one (by `operation_id`); the tool
list a client sees is filtered to the scopes its token holds.

| Tool | Scope | |
|---|---|---|
| `get_state`, `list_monitors`, `get_monitor`, `list_printers`, `get_printer`, `list_cameras`, `get_camera`, `recent_events` | read | status |
| `get_camera_frame` | read | returns the frame as **image content** an agent can look at |
| `control_printer` | control | pause / resume / cancel |
| `add_monitor`, `update_monitor`, `remove_monitor`, `add_printer`, `update_printer`, `remove_printer`, `test_printer`, `add_camera`, `update_camera`, `remove_camera`, `discover_cameras`, `refresh_printer_cameras`, `update_settings`, `test_notifier` | manage | configuration |

Point a client at the endpoint with the token as a bearer header:

```json
{
  "mcpServers": {
    "printguard": {
      "url": "https://host/mcp/",
      "headers": { "Authorization": "Bearer YOUR_TOKEN" }
    }
  }
}
```

Or explore it with the [MCP Inspector](https://github.com/modelcontextprotocol/inspector):

```bash
npx @modelcontextprotocol/inspector
# Transport: Streamable HTTP · URL: https://host/mcp/
# Header: Authorization: Bearer YOUR_TOKEN
```

## The resource model

Cameras and printers are **registered resources** — each is created and deleted only
through its own collection (`/cameras`, `/printers`). A **monitor** binds one camera and,
optionally, one printer (by `camera_id` / `printer_id`) and carries the inference
thresholds and defect-response policy; removing a resource clears it from any monitor that
referenced it.

Credentials are redacted from this read surface: any printer or notifier config field its
adapter marks secret (API keys, access codes, bot tokens) is stripped from every REST and
MCP response; only the dashboard's own WebSocket, behind your proxy, receives them.

Every printer integration (OctoPrint, Klipper/Moonraker, Bambu Lab, …) is normalised to one
shape, so a printer reads and controls the same way regardless of its service.

- **Status** — one of `printing`, `paused`, `idle`, `error`, `offline`, `unknown`.
- **State** — `{ "status", "progress" (0–100), "job" }`, reported on printer objects as
  `device_state`.
- **Actions** — `pause`, `resume`, `cancel`.

## Reading detection state

The response bodies below are what an integrator polls to answer "is this print failing?".
Two facts matter and are easy to miss: the **camera** carries a per-frame *classification*,
while the smoothed **0–1 defect score** is a per-**monitor** quantity — the camera object has
no numeric score field.

**Camera object** (`GET /cameras`, `GET /cameras/{id}`):

```jsonc
{
  "id": "cam_1a2b",
  "name": "Left printer",
  "source": { /* redacted of any access_code / credentials */ },
  "printer_id": "prn_…" | null,
  "max_fps": 5.0, "target_fps": 2.0, "achieved_fps": 1.9,   // rate
  "inferring": true, "in_use": true, "online": true,        // health
  "last_result": {                                          // latest score (per FRAME)
    "prediction": "success",                                //   "success" | "failure" | "unknown"
    "distances": { "success": 0.48, "failure": 1.64 },      //   distance to each class prototype
    "margin": 1.16                                          //   runner-up minus best (confidence)
  },
  "brightness": 1.0, "contrast": 1.0, "sharpness": 0.0, "crop": null, "rotation": 0
}
```

`last_result` is the newest raw classification, or `null` before the camera has been
inferred. `prediction` is simply the **nearest class prototype** for that frame (no
threshold applied) — the quickest per-camera "failing?" read. It is `"unknown"` when the
frame can't be classified (e.g. the embedding isn't finite).

**Monitor object** (`GET /monitors`, `GET /monitors/{id}`): binds a camera (+ optional
printer) and holds the detection policy and the latest alert:

```jsonc
{
  "id": "mon_…",
  "camera_id": "cam_1a2b",
  "printer_id": "prn_…" | "",
  "sensitivity": 1.0,          // scales how far the distance margin moves the score off 0.5
  "threshold": 0.6,            // defect score at/above which a frame counts as a failure
  "watching": true,            // whether it is actively inferring right now
  "alert": {                   // null until a sustained defect trips the watchdog
    "score": 0.82, "action": "pause", "ts": 1720000000.0
  }
}
```

**Prediction vs defect score.** The **0–1 defect score** (`0.5` = decision boundary, higher
= more defective) applies a monitor's `sensitivity` to the frame's distance margin, so it is
**per-monitor, not on the camera**. It appears in:

- the `result` events on the WebSocket and `GET /events`:
  `{ "event": "result", "monitor_id", "camera_id", "score" (0–1), "prediction" (this
  monitor's `threshold` applied), "margin", "ms", "ts" }`,
- a monitor's `alert.score` once it trips, and
- the MQTT *Defect score* sensor, published as `0–100` (the `0–1` score ×100).

So: to poll one camera's current verdict, read `GET /cameras/{id}` → `last_result.prediction`;
for the smoothed `0–1` score or a monitor's threshold-applied verdict, read the monitor or the
`result` events.
