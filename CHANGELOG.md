# Changelog

All notable changes to PrintGuard are documented in this file, by hand, in the pull
request that ships them. Each version's section is published verbatim as its GitHub
release notes.

The format is [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[2.0.1]: https://github.com/oliverbravery/PrintGuard/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/oliverbravery/PrintGuard/compare/v1.0.0b3...v2.0.0
