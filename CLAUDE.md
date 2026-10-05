# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

PrintGuard watches 3D-printer cameras with an on-device vision model, pauses the printer
on a sustained defect, and pushes a snapshot alert. It runs as a self-hosted **hub**, either
the Docker image or the macOS and Windows desktop app, and that is the only way to run it.
Frames leave hardware the user owns only when they review a print and send its frames for
training.

## Commands

```bash
uv sync                                   # Python engine + hub server (use uv, never pip)
uv run printguard                         # hub on :8000 (MediaMTX is bundled into the image; for video in dev: brew install mediamtx && MEDIAMTX_BINARY=$(which mediamtx) uv run printguard)
cd web && npm install && npm run dev      # UI hot-reload on :5173, proxied to :8000

uv run pytest                             # engine simulation + adapter contract tests
uv run pytest tests/test_engine.py::test_fair_allocation_and_dedup   # a single test (asyncio_mode=auto)
cd web && npm run typecheck               # strict TypeScript over the UI
cd web && npm run test:sandbox            # the browser plugin sandbox in Playwright, chromium and webkit
cd web && npm run build                   # production UI build
cd web && npm run site                    # the GitHub Pages landing page (web/site), hot-reload
cd feedback-worker && npm ci && npm test  # the training inbox Worker
```

There is no Python lint step. The **tests** check in CI runs `uv run pytest`, `npm run typecheck`
and `npm run test:sandbox` in `web/`, and the feedback Worker's `typecheck` and tests.

## Architecture

Read [docs/architecture.md](docs/architecture.md) for the full picture and diagrams; the
essentials a change must respect:

- **The engine decides, the platform does.** The engine's own logic in `printguard/engine/` does
  no I/O. Inference, capture, HTTP, sockets, JPEG coding and storage live
  behind the `Platform` protocol in [`engine/platform.py`](printguard/engine/platform.py),
  implemented for the hub in `server/platform.py` and in memory by `tests/fakes.py`. **The
  engine never imports from `server/`.** When engine code needs a runtime service, add it to
  the `Platform` protocol and implement it on the hub and in the fake. There is no local or
  browser mode any more (removed in 2.5.0), so never add a mode, a `browser_ok`-style flag or
  an optional capability for a runtime that does not exist.

- **The engine owns one JSON command/event protocol.**
  [`engine/engine.py`](printguard/engine/engine.py) dispatches commands through its
  `_handlers` map and broadcasts events to subscribed transport "sinks". `state_event()`
  is the full snapshot the UI renders; any new engine-owned data the UI needs is added
  there. The UI is **presentation-only** - it never holds logic the engine should own, and
  it reaches the engine over one WebSocket (`/api/ws`).

- **Resources vs monitors.** A **camera** (video source) and a **printer** (control-service
  connection) are registered resources, created/deleted only in their registry. A
  **monitor** binds one of each (printer optional) and carries the thresholds and
  defect-response policy. A printer integration that exposes a webcam auto-registers it as a
  camera owned by that printer.

- **Adapters are the extension points.** Printer integrations
  ([`engine/integrations/`](printguard/engine/integrations/)) and alert notifiers
  ([`engine/notifiers/`](printguard/engine/notifiers/)) subclass `IntegrationAdapter` and
  `NotifierAdapter` in their package's `base.py`, which share
  [`engine/adapters.py`](printguard/engine/adapters.py). They reach HTTP services through
  `platform.http` so the tests can pin every request, and are registered in their package
  `__init__.py`. An adapter built on a vendor's client library (Bambu, Elegoo Centauri, PrusaLink,
  the native notifier) opens its own connections, the main place engine code does its own I/O
  ([docs/architecture.md](docs/architecture.md#the-platform-contract) lists them all), and its tests monkeypatch the adapter's private connection functions.
  Adding one needs no other code change - the config form, connection test, polling and
  actions all follow from the adapter. CONTRIBUTING.md has the step-by-step.

- **Plugins are third-party code, and none of it runs in the engine.**
  [`engine/plugins.py`](printguard/engine/plugins.py) only sources and hash-pins it; execution
  is a sandbox on each side (an opaque-origin iframe in the dashboard for `plugin.js` and
  `panel.html`, QuickJS in WebAssembly on the hub for `worker.js`, via
  `platform.plugin_runtime`). A plugin returns a view and a list of effects and
  performs nothing itself, and each side checks every effect against the granted permissions
  before acting: the engine cannot tell a plugin's command from the dashboard's. `PERMISSIONS`
  in that module is the single policy both sides apply.

- **The programmatic surface adds no logic.** The REST API (`server/api.py`, `/api/v1`) and MCP
  server (`server/mcp.py`, `/mcp`) are thin transports over `engine.request()`, scoped by
  cumulative `read ⊂ control ⊂ manage` tokens. The Home Assistant MQTT bridge
  (`server/mqtt.py`) is a third such transport: it consumes engine events via `add_sink` and
  routes inbound commands through `engine.request()`, publishing one Home Assistant device
  per monitor via MQTT discovery (config in `settings.mqtt`, gated by broker access). None
  add logic, so they cannot drift from the dashboard.

- **Fail safe, fail loud.** A monitor's `watching` state gates inference; only a *positive*
  "not printing" stands it down (losing the signal keeps watching). Nothing on the alert
  path swallows errors - failed printer actions, notifier failures and dropped feeds emit
  `error`/`warning` events. See `engine/watchdog.py`.

- **State** persists through `platform.load_state()`/`save_state()`, a JSON file in the
  hub's data directory.

- **The website is not the dashboard.** `web/site/` is the GitHub Pages landing page, a second
  Vite root sharing `web/src/styles.css`. The hub never serves it and it never imports the
  store, which opens the engine socket on import.

## Conventions

- **No comments; let names document intent.** The TypeScript/React UI carries **no** comments
  or JSDoc - never narrate what the code does. Everything under [`plugins/`](plugins) is the
  exception, since it is what a plugin author reads to learn the API:
  [`plugin.d.ts`](plugins/plugin.d.ts) carries TSDoc on every member for the hover, and the
  shipped plugins are commented throughout to work as examples. In the Python engine/server,
  every module, class and public method gets a docstring, but still no inline comments unless
  the *why* is genuinely non-obvious.
- **Docstrings are Google style.** A summary line, then `Args:`, `Returns:` and `Raises:`
  whenever the function takes arguments, gives something back or fails. Never repeat a type
  there: the signature is annotated, so say what a value means, not what it is.
- **Minimal and consolidated.** No fallbacks, defensive guards or speculative abstractions
  unless asked. Prefer extending/refactoring existing code over adding parallel variants;
  delete code a change makes dead.
- `from __future__ import annotations` heads every Python module; type everything.
- **The version lives only in `pyproject.toml`.** Read it at runtime via
  `importlib.metadata.version("printguard")`; bump it with `uv version --bump {patch,minor,major}`.
- **Tests.** `tests/test_engine.py` simulates the engine against `tests/fakes.py`
  (`FakePlatform`); `tests/test_adapters.py` pins each adapter's exact request shapes;
  `tests/test_plugin_runtime.py` runs real JavaScript in the shipped QuickJS build to hold the
  hub's plugin sandbox to what it promises, and `web/tests/sandbox.spec.ts` does the same for
  the browser sandbox through Playwright (`npm run test:sandbox`, chromium and webkit).
  `web/launch/launch.spec.ts` drives a running build from camera to alert, and CI runs it on
  the container and both desktop apps before a release merges. New
  scheduler/monitor/watchdog/protocol behaviour extends the former; a new adapter is tested
  in the latter. Tests reach the engine through `engine.handle()`/`engine.request()`, not by
  poking internals.
- **Prose: English, no em dashes.** Never use `—` in docs, changelog entries, commit
  messages, PR descriptions or UI copy; use a comma, colon, brackets or a spaced hyphen.
  Concise and factual, no filler or salesmanship.
- **Anything published is written in the first person, as the maintainer.** PR titles and
  descriptions, issue and PR comments, commit messages and release notes all go out under the
  maintainer's account, so never write in the third person, never mention having been asked,
  and never sign off as an assistant. Say what changed and what the reader needs to do, then
  stop.

## Documentation is part of every change

**Docs are not optional follow-up work: a change is unfinished while a page still describes
the old behaviour.** Before finishing any change, check the table below and update every page
it touches in the same change - add what is new, correct what moved, and delete what the
change made wrong or redundant. Never leave a doc describing something that no longer exists.

| Changed | Update |
|---|---|
| Install steps, ports, image tags, headline features | `README.md`, and the landing page in `web/site/Home.tsx` |
| A supported printer service, camera source or alert channel | The lists in `README.md`, `web/site/Home.tsx` and `web/src/guide.tsx` |
| Engine protocol, events, `Platform` contract, scheduler, logging, repo layout | `docs/architecture.md` |
| A printer integration or its setup, the print library, temperatures | `docs/printers.md` |
| A camera source | `docs/cameras.md` |
| A monitor or camera setting, risk history | `docs/monitoring.md` |
| The frames kept from a print, what's sent for training, the Worker's limits | `docs/feedback.md` |
| A notifier, or when a notice is sent | `docs/notifications.md` |
| Model runtimes, execution providers, image variants, GPU setup | `docs/hardware.md` |
| Exposure, proxies, origin checks, ports, hardening, an environment variable, the data directory | `docs/deployment.md` |
| A REST endpoint, MCP tool, scope, response shape or Home Assistant entity | `docs/api.md` |
| Installing plugins, a permission, what a plugin can reach | `docs/plugins.md` |
| The plugin API, a manifest field, a limit, either sandbox, the catalogue | `docs/plugin-development.md` |
| A failure mode users will hit, or its fix | `docs/troubleshooting.md` |
| Anything user-visible | `CHANGELOG.md` (see Release) |
| The UI's appearance | `docs/assets/` screenshots: `cd web && npm run screenshots` |
| Dev setup, tests, adapter how-tos, release process | `CONTRIBUTING.md` |

Docs favour tables and Mermaid diagrams over long prose, keep the centred nav line at the top
of each page, and link rather than restate: duplicated documentation rots. `docs/README.md`
indexes the set, so a new page goes in that table, in the README's Documentation table and in
the nav line of every page.

## Release

Merging to `main` publishes a release, so work collects on a `release/vX.Y.Z` branch first.
Check `gh pr list` for an open one before branching. A fix or feature branches off `main` and
PRs into the release branch with **no version bump**, adding its line under the release's
heading in [CHANGELOG.md](CHANGELOG.md). The release branch owns the bump and that heading
([Keep a Changelog](https://keepachangelog.com) form), and its PR into `main` is the release.
The changelog section is published **verbatim** as the GitHub release notes - write it for
someone deciding whether to pull the new image, not about the implementation.

Five checks are required: **tests** (`uv run pytest`, the UI's `typecheck` and `test:sandbox`,
and the feedback Worker's `typecheck` and tests), **audit** (`uv audit` and `npm audit`
over the lockfiles), the production **image** build (which
also builds the UI), **version** (not yet tagged, with a matching
changelog section) and, on pull requests into `main` only, **launch** (the container and both
desktop apps start and catch a failing print) plus the changelog date, which must be the day it
merges into `main` in London time. PrintGuard is distributed as the Docker image and the macOS
and Windows desktop app.

The closing keyword (`Fixes #123`) goes on the release PR into `main`, and a PR into a release
branch says `Reported in #123` instead. The issue lifecycle hangs off that link: the merge
reopens the issue rather than closing it, marks it `status: completed`, and the published
release asks the reporter to verify. See
[CONTRIBUTING.md](CONTRIBUTING.md#what-a-merge-does-to-the-issues-it-fixes).
