<div align="center">

# Plugins

[Docs](README.md) · [Architecture](architecture.md) · [Printers & cameras](printers.md) · [Hardware](hardware.md) · [Deployment](deployment.md) · [API & MCP](api.md) · **Plugins** · [Troubleshooting](troubleshooting.md)

</div>

Plugins are written in JavaScript and run in a sandbox. One can draw a panel on your
dashboard, run a job on the hub, or do both. They can be granted fine-grained permissions to
reach an internal API, so developers can safely add features to PrintGuard without waiting on
a release. A plugin never reaches your credentials, your cameras or your tokens.

- [Installing a plugin](#installing-a-plugin)
- [What a plugin can and cannot do](#what-a-plugin-can-and-cannot-do)
- [Permissions](#permissions)
- [Writing a plugin](#writing-a-plugin)
- [The panel half](#the-panel-half)
- [The worker half](#the-worker-half)
- [Publishing](#publishing)

## Installing a plugin

![The Plugins tab in Settings, with an installed plugin, the catalogue, and installing from a repository or a file](assets/plugins.png)

The Plugins tab in Settings lists what you have installed and what the catalogue offers. You
can install one three ways.

| From | How |
|---|---|
| The catalogue | Pick one and confirm what it asks for. These are the ones I have reviewed |
| A GitHub repository | Paste `owner/repo`, or `owner/repo/path@branch` for one inside a larger repo |
| A file | Import a `.zip` of the plugin's folder |

A plugin shows as verified when the manifest and every source file hash to exactly what the
catalogue pins at a specific commit. Anything else shows as third party, which means nobody
has reviewed it, so read it first. Both run under the same restrictions either way.

A repository install pins the commit it resolved to, so a plugin never changes underneath
you. **Update** re-resolves the branch and re-checks the hashes.

Permissions are granted at install and can be changed or revoked per plugin at any time,
which takes effect immediately.

## What a plugin can and cannot do

PrintGuard hands a plugin the state its permissions allow, and gets back what to draw and a
list of things to do. PrintGuard is what does them, and it checks each one against your
permissions first.

| Half | Runs in | On a hub | In local mode |
|---|---|---|---|
| `plugin.js` | An iframe with an opaque origin and `default-src 'none'` | ✅ | ✅ |
| `worker.js` | [QuickJS](https://github.com/quickjs-ng/quickjs) compiled to WebAssembly, under wasmtime | ✅ | The browser sandbox, headless |

Only the hub can serve a plugin's own routes or let one gate requests, since local mode has no
server for either to mean anything.

| Attack | What stops it |
|---|---|
| Take your credentials somewhere | Neither sandbox has sockets. The browser half's policy is `connect-src 'none'`; the hub half has no WASI network and no filesystem. The only way out is a request through PrintGuard, to hosts the plugin declared |
| Read your credentials at all | State is cut down to the fields a permission names. Printer configuration, notifier settings, MQTT credentials and API tokens are in no permission |
| Read your camera frames | A `camera` node is a placeholder PrintGuard fills with its own player. The video never enters the sandbox, and a cross-origin frame cannot read it |
| Hang or exhaust the hub | The worker runs against a memory cap and a CPU budget, and traps in milliseconds. A plugin that fails is disabled and reported |
| Do something it was not granted | Every command maps to a permission, checked at the sandbox edge before it goes anywhere |
| Pretend to be PrintGuard | Plugins have no styling and no markup of their own, and PrintGuard draws every node itself. A plugin's own pages are served into a sandboxed origin that is not the dashboard's |
| Change after review | The manifest and every source file are pinned by SHA-256 at a commit |

A plugin that holds **Authorise every request** can lock you out of your own hub. To start the
hub with every plugin switched off, add `PRINTGUARD_PLUGINS=off` to its environment, then
remove the plugin.

## Permissions

| Permission | Lets the plugin | Hub only |
|---|---|---|
| `state:read` | Read monitor names, scores and alerts, and camera and printer names and status | |
| `camera:view` | Put a live feed in its own panel | |
| `monitor:control` | Enable, disable and retune any monitor | |
| `printer:control` | Pause, resume and cancel prints | |
| `notify` | Raise a message in the dashboard | |
| `net` | Reach the hosts its manifest lists, and nowhere else | |
| `routes` | Answer requests under `/plugins/<id>/`, reading each request's headers | ✅ |
| `gate` | See and refuse every other request to the hub | ✅ |

Storing its own data needs no permission. The store is the plugin's own, capped at 16 KB, and
saved as part of your PrintGuard state.

## Writing a plugin

A plugin is a folder with a manifest and one or two JavaScript files. There's no build step
and nothing to minify, so what you publish is what people read before they install it.

```
my-plugin/
  plugin.json     the manifest
  plugin.js       draws a panel                (optional)
  worker.js       runs in the background       (optional)
```

```json
{
  "id": "bed-clearance",
  "name": "Bed clearance",
  "version": "1.0.0",
  "description": "One line about what it does.",
  "author": "you",
  "homepage": "https://github.com/you/bed-clearance",
  "permissions": ["state:read", "notify"],
  "surfaces": ["panel", "float"],
  "hosts": ["api.example.com"],
  "events": ["alert"],
  "tick_s": 300
}
```

`surfaces` says where the panel appears, `panel` on the dashboard and `float` to offer a
pop-out window. `hosts` lists the only hosts `ctx.http` may reach. `events` and `tick_s` are
the worker's, naming which engine events wake it and how often to run it anyway.

Both files get `plugin` to register with, and every handler gets a `ctx`:

| On `ctx` | |
|---|---|
| `ctx.state` | The state your permissions allow, refreshed each call |
| `ctx.store` | Your own data. Assign to it and PrintGuard saves it |
| `ctx.command(cmd)` | Ask PrintGuard to run an engine command |
| `ctx.http(request)` | Ask PrintGuard to make a request, to a host you declared |
| `ctx.notify(text)` | Raise a message in the dashboard |
| `ctx.log(text)` | Write a line to PrintGuard's log |

Each file runs inside a function with nothing else in scope, so there's no `import`, no
`fetch`, no DOM and no storage. Everything you need arrives on `ctx`.

Install it with **Import a .zip** while you work on it, or point PrintGuard at your repo
and press **Update** as you push.

## The panel half

`plugin.js` returns a tree of nodes. PrintGuard draws them with its own components, so a
plugin looks like the rest of the dashboard and inherits the user's theme.

| Node | Fields |
|---|---|
| `row`, `col` | `children` |
| `text` | `value`, `muted` |
| `chip` | `value`, `tone`: `ok`, `warn`, `bad`, `accent` |
| `camera` | `camera_id` |
| `button` | `label`, `action`, `arg` |
| `select` | `value`, `options`, `action`, `label` |

`render` is called whenever state changes, and again after every action, so keep it a plain
function of `ctx`. Pressing a `button` or changing a `select` calls `action` with the node's
`action` name and `arg`.

```js
plugin.action((name, arg, ctx) => {
  if (name === "watch") ctx.command({ cmd: "monitor.update", id: arg, patch: { enabled: true } });
});

plugin.render((ctx) => ({
  type: "col",
  children: (ctx.state.monitors || []).map((monitor) => ({
    type: "row",
    children: [
      { type: "text", value: monitor.name },
      { type: "chip", value: monitor.enabled ? "watching" : "idle", tone: monitor.enabled ? "ok" : undefined },
      { type: "button", label: "Watch", action: "watch", arg: monitor.id },
    ],
  })),
}));
```

[`plugins/picture-in-picture`](../plugins/picture-in-picture) is a whole plugin, in about 25
lines.

## The worker half

`worker.js` runs without a UI. It wakes on the engine events its manifest lists, on its own
timer, and for requests to its routes. It gets a fresh VM each time, so anything it needs to
remember goes in `ctx.store`.

These are the events a worker can name in `events`:

| Event | Fires | Carries |
|---|---|---|
| `result` | Every inference on a watched monitor, capped at 5 per second per monitor | `monitor_id`, `camera_id`, `score`, `prediction`, `margin`, `ms`, `ts` |
| `alert` | A defect held long enough to act on | `monitor_id`, `score`, `action`, `ts` |
| `warning` | A watchdog condition, and its recovery | `monitor_id`, `message`, `recovered` |
| `device` | A printer's status changed | `printer_id`, `status`, `progress`, `job` |
| `error` | Anything that failed | `message` |
| `state` | The full snapshot, once a second | Everything your permissions allow |

`result` is the one to use for "do something whenever the risk goes over x". It fires per
inference, with the raw score, before any threshold or streak logic the monitor applies. A
worker still busy with the previous event is skipped rather than queued behind it, so a slow
plugin drops events instead of falling further behind.

```js
plugin.on("result", (event, ctx) => {
  if (event.score < (ctx.store.limit || 0.8)) return;
  ctx.command({ cmd: "printer.action", id: ctx.store.printer, action: "pause" });
  ctx.notify(`${event.monitor_id} hit ${event.score}`);
});
```

That needs `printer:control` and `notify`, and it fires on a single frame. A monitor's own
defect response waits for a streak, so a plugin acting on one frame will be twitchier than
PrintGuard is by default. Count consecutive hits in `ctx.store` if you want the same
steadiness.

```js
plugin.on("alert", (event, ctx) => {
  ctx.store.alerts = (ctx.store.alerts || 0) + 1;
  ctx.http({ method: "POST", url: "https://api.example.com/hook", json: { score: event.score } });
});

plugin.on("tick", (event, ctx) => ctx.log(`${ctx.store.alerts || 0} alerts so far`));

plugin.route((request, ctx) => ({
  status: 200,
  type: "text/html",
  body: `<h1>${ctx.store.alerts || 0} alerts</h1>`,
}));

plugin.gate((request, ctx) => request.path.startsWith("/api/") || Boolean(ctx.store.session));
```

`route` answers everything under `/plugins/<id>/`, and may return `headers` with
`Set-Cookie`, `Location` or `Cache-Control`. Its pages are served into a sandboxed origin,
so they can render and script themselves but can never act as the dashboard.

`gate` is consulted for every other request when the plugin holds that permission, apart from
`/api/health`, which stays open so uptime checks keep working, and its own pages, which stay
open so it can serve a sign-in page it would otherwise refuse. Answers are cached briefly per
session and path. Anything but `true` refuses, and a gate that cannot answer refuses too, so a
broken plugin cannot open the hub up.

## Publishing

Push the folder to a public repository and people can install it by name. To have it
reviewed and listed in the catalogue, open a pull request adding it under `plugins/` in
[PrintGuard](https://github.com/oliverbravery/PrintGuard), then:

```bash
uv run python plugins/pin.py
```

That rewrites `plugins/catalogue.json` with the commit the plugin last changed in and the
hash of every file. Commit the plugin first, since a pin has to describe bytes already in
history. Run it again after every change, or the plugin stops verifying.

You can run your own catalogue by pointing `catalogue_url` in settings at a JSON file of the
same shape.
