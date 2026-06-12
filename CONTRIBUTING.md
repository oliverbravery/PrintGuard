# Contributing

Read [docs/architecture.md](docs/architecture.md) first

PrintGuard runs in two modes: local (in-browser) and hub (server). The engine is shared code running on CPython and Pyodide, all mode differences live behind the `Platform` contract.

## Development setup

```bash
uv sync                              # Python engine + hub server
uv run printguard                    # hub on :8000 (MediaMTX optional: docker compose up mediamtx)
cd web && npm install && npm run dev # UI with hot reload on :5173, proxied to :8000
```

Run the tests before and after your change:

```bash
uv run python tests/test_engine.py   # engine simulation: fairness, gating, watchdog, alerts
cd web && npm run typecheck          # strict TypeScript over the UI
```

The engine tests simulate cameras and printers against a fake platform — if you touch the
scheduler, monitor or printer state handling, extend them; they are the only gate.

## Adding a printer integration

Integrations talk to print servers (OctoPrint, Moonraker, …) to read state and
pause/cancel jobs. One adapter runs in both modes because it only speaks through the
platform's HTTP function.

1. Create `printguard/engine/integrations/<service>.py` subclassing
   [`IntegrationAdapter`](printguard/engine/integrations/base.py):
   - implement `fetch_state()`, normalising to the canonical `DeviceStatus` values —
     `offline` must mean "unreachable", not "idle", because it keeps inference watching;
   - implement `send()` for pause/resume/cancel, raising `RuntimeError` on rejection;
   - describe the config form as a JSON Schema (`secret: true` masks fields,
     `placeholder` hints at the expected value);
   - set `docs_url` to the official API reference — it is required for review.
2. Register an instance in
   [`integrations/__init__.py`](printguard/engine/integrations/__init__.py).

The configuration form, connection test, device polling, inference gating and defect
actions all follow from the adapter — no other change in either mode.

## Adding a notification provider

Notifiers deliver defect snapshots and watchdog warnings.

1. Create `printguard/engine/notifiers/<service>.py` subclassing
   [`NotifierAdapter`](printguard/engine/notifiers/base.py):
   - implement `send(http, config, title, body, image)`; attach the JPEG `image` when the
     service supports uploads (`multipart_form()` in the same module builds the body),
     and raise `RuntimeError` with the service's error detail on rejection;
   - set `browser_ok = False` if the service sends no CORS headers (it will be offered
     in hub mode only — check from a browser console before assuming);
   - JSON-schema config and `docs_url`, exactly as for integrations.
2. Register an instance in
   [`notifiers/__init__.py`](printguard/engine/notifiers/__init__.py).

The settings form, test button, and delivery of alerts and warnings all follow from the
adapter.

## Ground rules

- **No mode forks.** If shared code needs something runtime-specific, extend the
  `Platform` protocol on both sides with identical signatures — never branch on mode.
- **Fail loudly.** Anything on the alert path that can fail must emit an `error` or
  `warning` event. No bare `except: pass` where a user would want to know.
- **Minimal code.** Prefer consolidating existing code over adding parallel variants;
  no speculative abstractions or defensive defaults.

## Release cycle

Merging to `main` starts the release process. The release's version is derived from the [`pyproject.toml`](pyproject.toml). Bump it as part of every PR:

```bash
uv version --bump patch   # or minor / major (also updates uv.lock)
```

A PR can only merge once three required checks pass —

- **tests** — the engine simulation suite;
- **image** — the production Docker image must build, so a change that breaks the image
  can never reach `main`;
- **version** — the version must be bumped past the last release, so every merge ships
  as a unique, immutable version (re-publishing an existing tag is refused).

On merge, the [release workflow](.github/workflows/release.yml):

1. builds and pushes the multi-arch image to `ghcr.io/oliverbravery/printguard`,
   tagged `X.Y.Z`, `X.Y` and `latest`;
2. only after the image is published, tags the merge commit `vX.Y.Z` and creates the
   GitHub release with generated notes — a failed build never becomes a release;
3. deploys the in-browser demo to GitHub Pages.

Docker is the only supported distribution.
