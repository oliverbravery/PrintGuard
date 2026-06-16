# Changelog

All notable changes to PrintGuard are documented in this file, by hand, in the pull
request that ships them. Each version's section is published verbatim as its GitHub
release notes.

The format is [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.2.0] - 2026-06-16

### Added

- **API & MCP tokens managed from the UI** — issue, name, scope and revoke the bearer
  tokens that gate the hub's REST API and MCP server directly from **Settings → API & MCP
  access**, with no restart and nothing to edit in the environment. Generating a token
  reveals its secret once (a `pg_…` string) and stores only a SHA-256 hash, so it can never
  be retrieved later — revoke and reissue if one is lost; revoking takes effect
  immediately. Tokens persist with the rest of the engine state and are managed only over
  the UI's protocol (behind your auth proxy), never over the API itself, so an agent
  holding a `manage` token can drive printers and cameras but cannot mint or escalate
  tokens.

### Removed

- **`PRINTGUARD_API_TOKENS`** — API and MCP tokens are now issued from the dashboard rather
  than a comma-separated environment variable, which is no longer read. Recreate any tokens
  you had set in **Settings → API & MCP access**.

## [2.1.0] - 2026-06-16

### Added

- **Bambu Lab printers** — link a printer over its local MQTT API alongside the existing
  OctoPrint and Klipper services, with the same pause/cancel-on-defect response, job and
  progress reporting, and inference gating. Enable **LAN Only Mode** and **Developer Mode**
  on the printer, then link it with its IP, serial number and access code — the form links
  Bambu's official setup guide. The protocol is MQTT over TLS, which needs a raw socket the
  browser sandbox forbids, so Bambu Lab is offered in **hub mode only** — the same
  constraint that already makes some notifiers hub-only.
- **Setup guides in config forms** — each printer service and notification channel now
  shows a one-line setup hint and a link to its official setup docs, so steps taken
  outside PrintGuard (API keys, CORS, bot tokens, webhooks, LAN mode) are spelled out
  where you configure them.
- **Experimental tag** — a reusable badge that flags new, not-yet-battle-tested features
  and links to the issue tracker for reports. Bambu Lab carries it.
- **MCP server and REST API for hub mode** — agents and developers can now drive the
  same engine protocol the dashboard speaks. The Model Context Protocol server
  (Streamable HTTP, at `/mcp`) lets an agent read printer and camera status, fetch the
  current camera frame as an image, and pause, resume or cancel a print; the versioned
  REST API at `/api/v1` exposes the same operations to any HTTP client, with the frame
  served as `image/jpeg`. Both are thin transports over the existing engine commands, so
  they never drift from the UI. See
  [docs/api.md](https://github.com/oliverbravery/PrintGuard/blob/main/docs/api.md).
- **Scoped access tokens** — capability is configurable per token through cumulative
  `read` ⊂ `control` ⊂ `manage` scopes set in `PRINTGUARD_API_TOKENS`. With no token
  configured the surface is read-only behind your existing auth proxy; issuing scoped
  tokens unlocks control and management, and MCP hides any tool a token cannot use.

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
