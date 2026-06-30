# Contributing

Read [docs/architecture.md](docs/architecture.md) first

PrintGuard runs in two modes: local (in-browser) and hub (server). The engine is shared code running on CPython and Pyodide, all mode differences live behind the `Platform` contract.

## Development setup

```bash
uv sync                              # Python engine + hub server
uv run printguard                    # hub on :8000 (MediaMTX is bundled into the image; for video in dev, brew install mediamtx and set MEDIAMTX_BINARY=$(which mediamtx))
cd web && npm install && npm run dev # UI with hot reload on :5173, proxied to :8000
```

To work on the desktop app, run the tray build in dev or produce a local installer:

```bash
uv run --extra desktop printguard-desktop   # tray app: the hub in the background
bash packaging/build.sh                      # build a .dmg / .zip / .AppImage into dist/
```

Run the tests before and after your change:

```bash
uv run pytest                        # engine simulation + adapter contract tests
cd web && npm run typecheck          # strict TypeScript over the UI
```

`tests/test_engine.py` simulates cameras and printers against a fake platform (fairness,
gating, watchdog, alerts, protocol); `tests/test_adapters.py` pins the exact request
shapes of every integration and notifier. If you touch the scheduler, monitor or printer
state handling extend the former; a new adapter gets its payloads tested in the latter.

## Regenerating the docs screenshots

The images in `docs/assets/` are rendered from fake data (no backend, broker or video feed)
by a Playwright script — regenerate them whenever the UI changes:

```bash
cd web
npx playwright install chromium      # one-time: fetch the browser binary
npm run screenshots                  # renders docs/assets/*.png from web/screenshots/
```

Each image is one entry in `SCENES` in `web/screenshots/capture.spec.ts`; add a scene there
to capture a new screen.

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

Merging to `main` starts the release process, so every PR carries its own release
metadata: a version bump and a changelog entry.

```bash
uv version --bump patch   # or minor / major (also updates uv.lock)
```

Then add a matching section at the top of [CHANGELOG.md](CHANGELOG.md) in
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) form:

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added | Changed | Fixed | Removed

- What changed, written for someone deciding whether to pull the new image.
```

The section is published verbatim as the GitHub release notes, so describe the
user-visible effect, not the implementation.

A PR can only merge once three required checks pass —

- **tests** — the engine simulation suite;
- **image** — the production Docker image must build, so a change that breaks the image
  can never reach `main`;
- **version** — the version must be bumped past the last release and have a matching
  `CHANGELOG.md` section, so every merge ships as a unique, documented, immutable
  version (re-publishing an existing tag is refused).

On merge, the [release workflow](.github/workflows/release.yml):

1. builds and pushes the multi-arch image to `ghcr.io/oliverbravery/printguard`,
   tagged `X.Y.Z`, `X.Y` and `latest`;
2. only after the image is published, tags the merge commit `vX.Y.Z` and creates the
   GitHub release with the changelog section as its notes — a failed build never
   becomes a release;
3. deploys the in-browser demo to GitHub Pages;
4. builds the macOS, Windows and Linux desktop apps and attaches them to the release.

Docker (servers and NAS boxes) and the desktop app (personal computers) are the supported
distributions.
