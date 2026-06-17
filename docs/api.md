# API & MCP

A PrintGuard **hub** exposes its engine to agents and developers through two transports
over one protocol — the same commands the dashboard sends, so nothing here can drift from
the UI:

- a **Model Context Protocol** server at `/mcp` (Streamable HTTP) for agents, and
- a versioned **REST API** at `/api/v1` for any HTTP client.

Both are hub-only. Local (in-browser) mode has no server to host them.

## Authentication & scopes

PrintGuard ships no identity layer of its own — put a proxy in front of the hub
([docs/deployment.md](deployment.md)). On top of that, the API and MCP surface is gated by
**capability scopes** so you can decide exactly what an agent may do.

Scopes are cumulative:

| Scope | Grants |
|---|---|
| `read` | status of printers and cameras, the current camera frame, recent events |
| `control` | everything in `read`, plus pause / resume / cancel a print |
| `manage` | everything in `control`, plus add/remove/edit printers and cameras, change settings, test integrations and notifiers, discover cameras |

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
| `GET` | `/state` | read | Full snapshot: cameras, printers, settings, stats |
| `GET` | `/printers` | read | List printers with status, progress and job |
| `GET` | `/printers/{id}` | read | One printer |
| `GET` | `/cameras` | read | List cameras with rate, health and latest score |
| `GET` | `/cameras/{id}` | read | One camera |
| `GET` | `/cameras/{id}/frame` | read | Freshest frame as `image/jpeg` |
| `GET` | `/events` | read | Recent alerts, warnings, device changes and errors |
| `POST` | `/printers/{id}/action` | control | `{"action": "pause" \| "resume" \| "cancel"}` |
| `POST` | `/printers` | manage | Add a printer |
| `PATCH` | `/printers/{id}` | manage | Update a printer |
| `DELETE` | `/printers/{id}` | manage | Remove a printer |
| `POST` | `/cameras` | manage | Add a camera |
| `PATCH` | `/cameras/{id}` | manage | Update a camera |
| `DELETE` | `/cameras/{id}` | manage | Remove a camera |
| `POST` | `/cameras/discover` | manage | List attachable, unregistered sources |
| `PATCH` | `/settings` | manage | Update settings (e.g. notifiers) |
| `POST` | `/integrations/test` | manage | `{"provider", "config"}` — reachability |
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

Endpoint `https://<host>/mcp`, transport **Streamable HTTP**, authenticated with the same
bearer token. Tools mirror the REST operations one-to-one (by `operation_id`); the tool
list a client sees is filtered to the scopes its token holds.

| Tool | Scope | |
|---|---|---|
| `get_state`, `list_printers`, `get_printer`, `list_cameras`, `get_camera`, `recent_events` | read | status |
| `get_camera_frame` | read | returns the frame as **image content** an agent can look at |
| `control_printer` | control | pause / resume / cancel |
| `add_printer`, `update_printer`, `remove_printer`, `add_camera`, `update_camera`, `remove_camera`, `discover_cameras`, `update_settings`, `test_integration`, `test_notifier` | manage | configuration |

Point a client at the endpoint with the token as a bearer header:

```json
{
  "mcpServers": {
    "printguard": {
      "url": "https://host/mcp",
      "headers": { "Authorization": "Bearer YOUR_TOKEN" }
    }
  }
}
```

Or explore it with the [MCP Inspector](https://github.com/modelcontextprotocol/inspector):

```bash
npx @modelcontextprotocol/inspector
# Transport: Streamable HTTP · URL: https://host/mcp
# Header: Authorization: Bearer YOUR_TOKEN
```

## The printer model

Every integration (OctoPrint, Klipper/Moonraker, …) is normalised to one shape, so a
printer reads and controls the same way regardless of its service.

- **Status** — one of `printing`, `paused`, `idle`, `error`, `offline`, `unknown`.
- **State** — `{ "status", "progress" (0–100), "job" }`, reported on printer objects as
  `device_state`.
- **Actions** — `pause`, `resume`, `cancel`.
