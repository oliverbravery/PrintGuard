# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

PrintGuard watches 3D-printer cameras with an on-device vision model, pauses the printer
on a sustained defect, and pushes a snapshot alert. It runs as a self-hosted **hub**
(Docker/CPython) and as an install-free **local** mode (the same engine in the browser on
Pyodide). No frames leave hardware the user owns.

## Commands

```bash
uv sync                                   # Python engine + hub server (use uv, never pip)
uv run printguard                         # hub on :8000 (MediaMTX optional: docker compose up mediamtx)
cd web && npm install && npm run dev      # UI hot-reload on :5173, proxied to :8000

uv run pytest                             # engine simulation + adapter contract tests
uv run pytest tests/test_engine.py::test_fair_allocation_and_dedup   # a single test (asyncio_mode=auto)
cd web && npm run typecheck               # strict TypeScript over the UI (no test runner on the web side)
cd web && npm run build                   # production UI build
python printguard/pysrc.py web/public/pysrc.zip   # rebuild the Pyodide source archive for the static demo
```

There is no separate Python lint step in the project's required checks — `uv run pytest`
and `npm run typecheck` are the gates (see CONTRIBUTING.md "Release cycle").

## Architecture

Read [docs/architecture.md](docs/architecture.md) for the full picture and diagrams; the
essentials a change must respect:

- **One engine, two platforms.** Everything in `printguard/engine/` is shared code that
  runs unchanged on CPython (`printguard/server/`) and Pyodide (`printguard/browser/`).
  The *only* things allowed to differ between modes live behind the `Platform` protocol in
  [`engine/platform.py`](printguard/engine/platform.py). **Never branch on `platform.mode`.**
  When shared code needs a runtime-specific service, add it to the `Platform` protocol with
  one implementation per side; when a mode merely *lacks* a capability, express that as
  platform **data** (e.g. `update_repo` is `None` in the browser, notifier `browser_ok`),
  not a mode check.

- **The engine owns one JSON command/event protocol.**
  [`engine/engine.py`](printguard/engine/engine.py) dispatches commands through its
  `_handlers` map and broadcasts events to subscribed transport "sinks". `state_event()`
  is the full snapshot the UI renders; any new engine-owned data the UI needs is added
  there. The UI is **presentation-only** — it never holds logic the engine should own. The
  transport is a WebSocket in hub mode and an in-page Pyodide bridge in local mode, and the
  engine cannot tell which.

- **Resources vs monitors.** A **camera** (video source) and a **printer** (control-service
  connection) are registered resources, created/deleted only in their registry. A
  **monitor** binds one of each (printer optional) and carries the thresholds and
  defect-response policy. A printer integration that exposes a webcam auto-registers it as a
  camera owned by that printer.

- **Adapters are the extension points.** Printer integrations
  ([`engine/integrations/`](printguard/engine/integrations/)) and alert notifiers
  ([`engine/notifiers/`](printguard/engine/notifiers/)) subclass the contracts in
  [`engine/adapters.py`](printguard/engine/adapters.py), talk to the outside world *only*
  through `platform.http`, and are registered in their package `__init__.py`. Adding one
  needs no other change in either mode — the config form, connection test, polling and
  actions all follow from the adapter. CONTRIBUTING.md has the step-by-step.

- **Programmatic surface is hub-only.** The REST API (`server/api.py`, `/api/v1`) and MCP
  server (`server/mcp.py`, `/mcp`) are thin transports over `engine.request()`, scoped by
  cumulative `read ⊂ control ⊂ manage` tokens. They add no logic, so they cannot drift from
  the dashboard. Local mode never mounts them.

- **Fail safe, fail loud.** A monitor's `watching` state gates inference; only a *positive*
  "not printing" stands it down (losing the signal keeps watching). Nothing on the alert
  path swallows errors — failed printer actions, notifier failures and dropped feeds emit
  `error`/`warning` events. See `engine/watchdog.py`.

- **State** persists through `platform.load_state()`/`save_state()` (a JSON file on the
  hub, `localStorage` in the browser).

## Conventions

- **Docstrings, not comments.** Every module, class and public method gets a docstring;
  inline comments only when the *why* is non-obvious — never narrate what the code does. Let
  descriptive names document intent.
- **Minimal and consolidated.** No fallbacks, defensive guards or speculative abstractions
  unless asked. Prefer extending/refactoring existing code over adding parallel variants;
  delete code a change makes dead.
- `from __future__ import annotations` heads every Python module; type everything.
- **The version lives only in `pyproject.toml`.** Read it at runtime via
  `importlib.metadata.version("printguard")`; bump it with `uv version --bump {patch,minor,major}`.
- **Tests.** `tests/test_engine.py` simulates the engine against `tests/fakes.py`
  (`FakePlatform`); `tests/test_adapters.py` pins each adapter's exact request shapes. New
  scheduler/monitor/watchdog/protocol behaviour extends the former; a new adapter is tested
  in the latter. Tests reach the engine through `engine.handle()`/`engine.request()`, not by
  poking internals.

## Release

Merging to `main` ships a release, so every PR carries its own metadata: a version bump and
a matching top section in [CHANGELOG.md](CHANGELOG.md) ([Keep a Changelog](https://keepachangelog.com)
form), which is published **verbatim** as the GitHub release notes — write it for someone
deciding whether to pull the new image, not about the implementation. Three required checks
must pass: **tests**, the production **image** build, and **version** (bumped past the last
release with a matching changelog section). Docker is the only supported distribution.
