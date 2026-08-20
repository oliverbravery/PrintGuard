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
| The catalogue | Pick one. These are the ones I have reviewed |
| A GitHub repository | Paste `owner/repo`, or `owner/repo/path@branch` for one inside a larger repo |
| A file | Import a `.zip` of the plugin's folder |

PrintGuard reads a plugin's code before you enable it and says where the code and the manifest
disagree, above the permissions it is asking for. Three things come out of it.

| It says | Meaning |
|---|---|
| Asks for something it never uses | The manifest is wider than the code needs |
| Uses something it never asked for | PrintGuard refuses it at the sandbox edge anyway, so this is early notice |
| Builds a command or an address as it runs | Nobody can tell from the code what it reaches, so it says so |

It reads what is there rather than passing a verdict. A plugin that builds a URL is not a bad
plugin, and the check that actually stops anything is the one at the sandbox edge every time a
plugin asks for something. What it does settle is the catalogue: a listed plugin is one whose
code and manifest agree, because `pin.py` will not pin one that does not.

A plugin shows as verified when the manifest and every source file hash to exactly what the
catalogue pins at a specific commit. Anything else shows as third party, which means nobody
has reviewed it, so read it first. Both run under the same restrictions either way.

A repository install pins the commit it resolved to, so a plugin never changes underneath
you. **Update** re-resolves the branch and re-checks the hashes.

A plugin arrives switched off and holding nothing. Pressing **Enable** shows what it asks
for, what each permission lets it do and the plugin author's own reason for wanting it, and
it starts once you allow the lot. There is no partial yes: a plugin either gets what it asks
for or does not run. Disabling one stops it and keeps what you accepted, so switching it back
on asks nothing again.

An update that asks for more than you accepted stands the plugin down until you accept the
wider list, so nothing new happens behind an **Update** press. More means anything the
consent dialog read out to you: a permission, an address or another plugin it calls.

Your grants, the plugin's own data and the credentials you gave it carry across an update
only when the new bundle comes from the repository the old one came from, which is the
closest thing a plugin has to a signature. A bundle from anywhere else, a zip included, shares
nothing with the plugin it replaces but the id, so it installs holding none of them and asks
you from scratch.

## What a plugin can and cannot do

PrintGuard hands a plugin the state its permissions allow, and gets back what to draw and a
list of things to do. PrintGuard is what does them, and it checks each one against your
permissions first.

| Half | Runs in | On a hub | In local mode |
|---|---|---|---|
| `plugin.js` | An iframe with an opaque origin and `default-src 'none'` | ✅ | ✅ |
| `panel.html` | The same, with your own markup, styles and scripts allowed | ✅ | ✅ |
| `worker.js` | [QuickJS](https://github.com/quickjs-ng/quickjs) compiled to WebAssembly, under wasmtime | ✅ | The browser sandbox, headless |

Only the hub can serve a plugin's own routes or let one gate requests, since local mode has no
server for either to mean anything.

| Attack | What stops it |
|---|---|
| Take your credentials somewhere | Neither sandbox has sockets. The browser half's policy is `connect-src 'none'`; the hub half has no WASI network and no filesystem. The only way out is a request through PrintGuard, to addresses the plugin declared |
| Read your credentials at all | State is cut down to the fields a permission names. Printer configuration, notifier settings, MQTT credentials and API tokens are in no permission |
| Read your camera frames | A `camera` node is a placeholder PrintGuard fills with its own player, and the video never enters the sandbox. Reading the picture itself is `camera:frames`, which is its own thing to agree to, and a plugin's own pages are refused the live stream |
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
| `sound` | Sound a short alert through the speakers | |
| `monitor:control` | Enable, disable and retune any monitor | |
| `printer:control` | Pause, resume and cancel prints | |
| `notify` | Raise a message in the dashboard | |
| `alert:send` | Send through your own ntfy, Telegram or Discord | |
| `net` | Reach the addresses its manifest lists, and nowhere else | |
| `net:local` | Reach addresses on this machine and the network around it | |
| `monitor:manage` | Add monitors and delete them | |
| `camera:control` | Retune any camera's brightness, crop, rotation and frame rate | |
| `camera:manage` | Register cameras and delete them | |
| `camera:frames` | Take a still of any camera and read the picture itself | |
| `history:read` | Read how a monitor's risk has moved and when it alerted | |
| `printer:manage` | Connect printers, supplying the credentials, and delete them | |
| `settings` | Change alert channels, theme and the rest of Settings | |
| `tokens` | Mint and revoke API tokens | |
| `oauth` | Sign you in to a service and use the result | |
| `link:provide` | Answer other plugins on the channels it offers | |
| `link:consume` | Ask the plugins and channels it names, and hear them | |
| `background` | Put a picture behind the dashboard and make the panels see-through | |
| `routes` | Answer requests under `/plugins/<id>/`, reading each request's headers | ✅ |
| `gate` | See and refuse every other request to the hub | ✅ |

Every permission a manifest asks for needs a line in `reasons` saying why, in the plugin
author's own words, and one without a reason will not install. That line sits under
PrintGuard's own description of the permission when you are asked to accept it, so you get
both what it allows and what this plugin claims to want it for.

Storing its own data needs no permission. The store is the plugin's own, capped at 16 KB, and
saved as part of your PrintGuard state.

## Credentials

A plugin can supply a credential and can never read one back, whether it put it there or not.
Printer passwords, notifier keys and API tokens go in and never come out, so nothing a plugin
holds and nothing the dashboard shows it carries a stored value.

Its own credentials work the same way. Declare them in `secrets` and PrintGuard draws the form,
holds the values and fills them in as your requests leave.

```json
"secrets": {
  "api_key": "The key from your account page"
}
```

```js
ctx.http({ url: "https://api.example.com/v1/me", headers: { Authorization: "Bearer {{secret.api_key}}" }, tag: "me" });
```

The reference is all your code ever holds, in the URL, a header or anywhere in a JSON body. A
plugin gets eight secrets at most.

What that does and does not buy you is worth being straight about. The value is never in the
sandbox, never in the plugin's own stored data, never in the state this page reads and never
in a bug report, and it is written to disk in a file only the account running the hub can read.
What it cannot do is stop a plugin you granted the network from sending a secret somewhere it
declared: PrintGuard fills the value in as the request leaves, so a plugin can aim one at a
host of its own as easily as at the real service. The addresses it may reach are in front of
you before you enable it, the code check reads them against what it actually calls, and a
listed plugin has been reviewed. That is the control, not the substitution.

For a service with a sign-in rather than a key, declare `oauth` and PrintGuard runs the flow
itself, with PKCE and no client secret, since a plugin is a public client. The access token
arrives as `{{secret.oauth}}` and is refreshed before it expires, so your code never handles
one.

```json
"permissions": ["net", "oauth"],
"oauth": {
  "label": "Spotify",
  "authorize_url": "https://accounts.spotify.com/authorize",
  "token_url": "https://accounts.spotify.com/api/token",
  "register_url": "https://developer.spotify.com/dashboard",
  "scopes": ["user-read-playback-state"]
}
```

There is no client id in there and one written in is dropped at install. A plugin travels as a
repository, a zip or a listing in the catalogue, so an id you shipped would be one app shared
by everybody who installed it, which is the thing providers hand out quota and terms against.
Whoever installs it registers their own and types it into PrintGuard, which shows them the
exact redirect URI to give the provider and points `register_url` at wherever they create it.

The redirect URI is the hub's own address with `/oauth/callback` on the end, and a loopback
name is written as `127.0.0.1` because providers have stopped accepting the name.

Signing in is hub only, since local mode has no address for a provider to send anyone back to.

## Writing a plugin

A plugin is a folder with a manifest and one or two JavaScript files. There's no build step
and nothing to minify, so what you publish is what people read before they install it. The
three that come as standard live in [`plugins/`](../plugins) and are commented throughout, so
the quickest start is to copy the one closest to what you want.

```
my-plugin/
  plugin.json     the manifest
  plugin.js       draws a panel from nodes     (optional)
  panel.html      draws its own panel instead  (optional)
  worker.js       runs in the background       (optional)
  alarm.mp3       anything it ships            (optional)
```

```json
{
  "$schema": "https://raw.githubusercontent.com/oliverbravery/PrintGuard/main/plugins/plugin.schema.json",
  "id": "bed-clearance",
  "name": "Bed clearance",
  "version": "1.0.0",
  "description": "One line about what it does.",
  "author": "you",
  "homepage": "https://github.com/you/bed-clearance",
  "permissions": ["state:read", "notify"],
  "reasons": {
    "state:read": "To see which monitors are printing.",
    "notify": "To tell you when the bed needs clearing."
  },
  "surfaces": ["panel"],
  "platforms": ["docker", "windows"],
  "assets": ["alarm.mp3"],
  "urls": ["https://api.example.com/v1/*"],
  "secrets": { "api_key": "The key from your account page" },
  "events": ["alert"],
  "tick_s": 300
}
```

`reasons` is one line per permission, required for every one you ask for, shown to whoever is
deciding whether to enable it. Say what your plugin does with it, not what the permission is.

`surfaces` says where the panel appears.

| Surface | Where it puts you |
|---|---|
| `panel` | A panel of its own on the dashboard |
| `monitor` | Drawn on every monitor tile |
| `settings` | Drawn in every monitor's settings, under its own heading |

On `monitor` and `settings`, `render` is called once more per monitor, with `ctx.target` naming
which and `ctx.surface` naming where, so a plugin can put a button on the tile and its own
settings in the panel behind it. Anything that belongs to one monitor rather than all of them
goes in `settings`.

`platforms` says where it runs, and leaving it out means everywhere. The store filters the
catalogue by the one you are on, so anything that would not work is out of the way.

| Platform | |
|---|---|
| `docker` | The self-hosted hub, on any image |
| `docker-nvidia`, `docker-intel` | Only that image, for a plugin that needs the GPU it brings |
| `macos`, `windows` | The desktop app |
| `browser` | Local mode |

Naming `docker` covers the images built from it, so declare a variant only when a plainer
image would not do.

`assets` names the files it ships beside its code, which are hashed and pinned the same way,
so a plugin brings its own sounds and images rather than asking PrintGuard for them.

| Kind | |
|---|---|
| Images | `png`, `jpg`, `webp`, `gif`, drawn by an `image` node |
| Audio | `mp3`, `ogg`, `wav`, played by `ctx.sound("alarm.mp3")` |
| Text | `json`, `csv`, `txt`, read from `ctx.assets` as a string |

| Video | `mp4`, `webm`, played by a `panel.html` |

An asset is 4 MB at most and a plugin ships 12 MB in total. The type comes from the
extension and the file has to start like the format it claims, so a script renamed to `.png`
is refused at install. SVG is not on the list, since an SVG is markup and would run as the
dashboard's own. Images and audio never enter the sandbox: it names one and PrintGuard draws
or plays it.

`urls` lists the only addresses `ctx.http` and `ctx.socket` may reach, each a match pattern of
`scheme://host/path`, the same grammar a browser extension uses.

| Pattern | Reaches |
|---|---|
| `https://api.example.com/v1/*` | Anything under `/v1/` on that one host |
| `https://*.example.com/*` | `example.com` and every subdomain of it |
| `*://example.com/*` | That host over http or https |
| `wss://hub.local:8123/api/*` | That endpoint over a WebSocket, on that port |
| `*://*/*` | Anywhere at all, which is the widest thing you can ask for |

A `*` scheme covers http and https, and `ws`, `wss`, `rtsp` and `rtsps` are named in full. A
missing port means any port.

A pattern landing on the machine PrintGuard runs on or the network around it needs
`net:local` as well as `net`, so reaching a printer of your own is a separate thing to agree
to than reaching the internet. A wildcard host counts, since it covers both. PrintGuard checks
the address a name actually resolves to, not just the name, so a public name pointing at a
private address is caught.

`provides` and `consumes` are how plugins reach each other, covered below. `secrets` and
`oauth` are credentials, covered below. `events` and `tick_s` are the worker's,
naming which engine events wake it and how often to run it anyway.

Both files get `plugin` to register with, and every handler gets a `ctx`:

| On `ctx` | |
|---|---|
| `ctx.state` | The state your permissions allow, refreshed each call |
| `ctx.store` | Your own data. Assign to it and PrintGuard saves it |
| `ctx.command(cmd)` | Ask PrintGuard to run an engine command |
| `ctx.http(request)` | Ask PrintGuard to make a request, to an address you declared. Answers on the `http` event |
| `ctx.socket({ url, tag })` | Ask PrintGuard to hold a WebSocket open for you. Answers on the `socket` event |
| `ctx.socketSend(tag, text)` | Write one frame to a socket you opened |
| `ctx.socketClose(tag)` | Close a socket you opened |
| `ctx.call(request)` | Ask another plugin for something. Answers on the `call` event's reply |
| `ctx.publish(request)` | Publish on one of your own channels |
| `ctx.background(image)` | Put a picture behind the dashboard, or nothing to clear it |
| `ctx.notify(text)` | Raise a message in the dashboard |
| `ctx.sound(tones)` | Sound your own tones through the speakers, `{ hz, ms }` each, or name an audio asset |
| `ctx.assets` | The text files you shipped, keyed by name |
| `ctx.log(text)` | Write a line to PrintGuard's log |

Each file runs inside a function with nothing else in scope, so there's no `import`, no
`fetch`, no DOM and no storage. Everything you need arrives on `ctx`.

### Your editor

The `$schema` key above is what completes and checks the manifest as you type it, in VS Code,
JetBrains, Zed or anything else speaking to a JSON language server. Nothing to install.

For the JavaScript, drop these two next to your plugin and every editor with TypeScript in it
completes `plugin` and `ctx` and marks a typo as you make it. There's still no build step,
since nothing here is compiled.

```bash
curl -O https://raw.githubusercontent.com/oliverbravery/PrintGuard/main/plugins/plugin.d.ts
curl -O https://raw.githubusercontent.com/oliverbravery/PrintGuard/main/plugins/jsconfig.json
```

Without a `jsconfig.json`, a `// @ts-check` line at the top of a file does the same for that
file alone.

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
| `image` | `asset`, `label` |
| `float` | `camera_id`, `label`, `value` |
| `button` | `label`, `action`, `arg` |
| `select` | `value`, `options`, `action`, `label` |
| `input` | `value`, `action`, `label`, `kind`: `text` or `number`, `placeholder`, `secret` |
| `toggle` | `on`, `action`, `label` |

A `float` node is the one thing PrintGuard acts on from the press rather than from what you
return, since a browser only floats a video for something the user did and a trip through the
sandbox loses that. It draws nothing where the browser cannot float one. The floating window
carries the camera as it arrives, without the brightness, crop or rotation the dashboard
draws, because picture-in-picture shows the video itself and nothing drawn over it.

An `input` and a `select` draw their `label` above the field, the way the dashboard's own
settings do, so say what the value is for rather than leaving a bare box.

`render` is called whenever state changes, and again after every action, so keep it a plain
function of `ctx`. Pressing a `button` or changing a `select` calls `action` with the node's
`action` name and `arg`. An `input` commits on blur or Enter rather than on every keystroke,
and a `toggle` hands you `true` or `false`, which is how a plugin asks for a webhook URL or a
key without PrintGuard knowing anything about it.

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

[`plugins/picture-in-picture`](../plugins/picture-in-picture) is a whole plugin, in five lines of code.
It takes the `monitor` surface and returns one `float` node per monitor.
[`plugins/alert-sounds`](../plugins/alert-sounds) is another. It adds a switch and a
sound picker to each monitor's settings, and watches each monitor's `alert` between renders,
sounding the chosen tones the moment one appears. Its main view returns nothing, since a
plugin's `render` runs whether or not it has a panel to draw. The
tones are its own, since `ctx.sound` takes a list of them rather than a name PrintGuard knows:

```js
plugin.render((ctx) => {
  ctx.sound([
    { hz: 880, ms: 1400 },
    { hz: 1320, ms: 1100, together: true },
  ]);
  return null;
});
```

Each tone runs after the one before it unless it says `together`, which starts it alongside
instead, and `shape` picks `sine`, `square`, `sawtooth` or `triangle`. Four seconds is the
most PrintGuard will play in one go.

## Drawing it yourself

A node tree looks like the rest of the dashboard, which is what most plugins want. Ship a
`panel.html` instead and you draw the panel, with your own markup, styles and scripts.

```html
<style>
  .risk { font-family: var(--font-display); color: var(--color-accent); font-size: 32px; }
</style>
<p class="risk" id="worst">0</p>
<video id="loop" autoplay muted loop></video>
<script>
  document.getElementById("loop").src = pg.asset("loop.mp4");
  pg.on("state", (state) => {
    const scores = (state.monitors || []).map((m) => (m.result ? m.result.score : 0));
    document.getElementById("worst").textContent = Math.max(0, ...scores).toFixed(2);
  });
</script>
```

It runs in an opaque origin with `connect-src 'none'`, so `pg` is the only way out and every
call on it is the `ctx` above under another name, checked against the same permissions.
`pg.on("ready")` fires once the panel is drawn, `pg.on("state")` on every change, and any
event your manifest names arrives the same way.

The dashboard's colours and fonts come through as the custom properties it uses itself, so
`var(--color-accent)` is the accent the user picked and `pg.theme` is the lot. The background
is transparent and the panel is as tall as it draws itself, up to 900px.

`pg.asset(name)` gives a URL for a file you shipped, good inside your panel and nowhere else,
which is how a picture or a video gets on screen.

A panel may show pictures but may not fetch one, so a picture from elsewhere comes back
through `pg.http` with `binary: true` and arrives base64 encoded on the `http` event, ready to
be a `data:` URL. `pg.background(image)` puts one behind the whole dashboard and makes the
panels see-through over it, which needs `background` and is cleared by passing nothing.

A panel joins the dashboard's layout, so it drags, pins and hides alongside the monitors.

## Talking to other plugins

Plugins reach each other only where both sides said so and the user agreed. A plugin offering
something declares the channels it answers on, and a plugin wanting them names the exact
plugin and channel it will call. PrintGuard carries the message; neither one sees the other's
code, its store or anything it was not handed.

```json
"permissions": ["link:provide"],
"provides": { "now-playing": "The track playing right now" }
```

```js
plugin.serve((request, ctx) => ({ track: ctx.store.track, artist: ctx.store.artist }));
```

The plugin on the other side names it in full, so `spotify:now-playing` is one channel of one
plugin rather than a door left open.

```json
"permissions": ["link:consume"],
"consumes": ["spotify:now-playing"]
```

```js
plugin.on("tick", (event, ctx) => ctx.call({ to: "spotify", channel: "now-playing", tag: "np" }));

plugin.on("answer", (event, ctx) => { ctx.store.track = event.body.track; });
```

A provider with something to say rather than something to answer publishes instead, and every
plugin that named that channel hears it.

```js
plugin.publish({ channel: "now-playing", body: { track: "Blue" } });
```

Both sides show up when the user is asked, the offer as what it answers and the call as which
plugin and channel it reaches. A plugin that is disabled answers nobody, and a body is 16 KB
at most.

## The worker half

[`plugins/spotify`](../plugins/spotify) is one file. It signs you in, asks Spotify what is
playing, draws the cover, the title and the transport, and puts the cover behind the whole
dashboard. [`plugins/progress-reports`](../plugins/progress-reports) is the one with both halves. Its
panel puts a switch and an interval in each monitor's settings, its worker counts alerts and
flagged frames from the events, and on its own timer it sends the tally through your alert
channels with `notify.send`. Both halves share one store, so either can read what the other
wrote.

`worker.js` runs without a UI. It wakes on the engine events its manifest lists, on its own
timer, and for requests to its routes. It gets a fresh VM each time, so anything it needs to
remember goes in `ctx.store`.

It has no screen and no speakers of its own, so `ctx.notify`, `ctx.sound` and `ctx.background`
are carried out by whichever dashboards are open, and nothing happens while none are.

These are the events a worker can name in `events`:

| Event | Fires | Carries |
|---|---|---|
| `http` | An answer to one of your own `ctx.http` calls | `tag`, `status`, `body` |
| `socket` | A socket you opened coming up, carrying a frame, or ending | `tag`, `state`, `text` |
| `frame` | A still you asked for with `camera.snapshot` | `camera_id`, `jpeg` |
| `call` | Another plugin asking on a channel you offer | `from`, `channel`, `body`, `call_id` |
| `answer` | The answer to one of your own `ctx.call`s | `tag`, `from`, `channel`, `body` |
| `message` | Something a plugin you named published | `from`, `channel`, `body` |
| `history` | A monitor's risk history, answering `history.get` | `monitor_id`, `now`, `buckets`, `alerts`, `stats` |
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

A plugin runs and returns rather than waiting, so `ctx.http` hands nothing back on the spot.
Name the request with a `tag` and read the answer when it arrives.

```js
plugin.on("tick", (event, ctx) => ctx.http({ url: "https://api.example.com/v1/now", tag: "now" }));

plugin.on("http", (event, ctx) => {
  if (event.tag === "now") ctx.store.latest = event.body;
});
```

A socket works the same way. `ctx.socket` opens one under a tag, `socket` events carry every
frame that arrives on it, and PrintGuard drops it when the plugin is disabled or removed. Both
need `http` or `socket` in the manifest's `events`, or the answer never reaches you.

Camera stills and risk history come back the same way, asked for with a command and answered
on an event.

```js
plugin.on("tick", (event, ctx) => {
  for (const monitor of ctx.state.monitors || []) ctx.command({ cmd: "history.get", monitor_id: monitor.id });
  ctx.command({ cmd: "camera.snapshot", camera_id: "cam-1" });
});

plugin.on("history", (event, ctx) => { ctx.store.peak = event.stats.max; });
plugin.on("frame", (event, ctx) => { ctx.store.last = event.jpeg.length; });
```

`history.get` answers with the same rollups the detailed monitor page draws, so a plugin
watching a trend needs no store of its own. `camera.snapshot` hands over a base64 JPEG, which
is the picture rather than a placeholder, so it needs `camera:frames` and says as much.

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

That reads your code against your manifest and refuses to list a plugin where the two
disagree, then rewrites `plugins/catalogue.json` with the commit the plugin last changed in and
the hash of every file. Commit the plugin first, since a pin has to describe bytes already in
history. Run it again after every change, or the plugin stops verifying.

You can run your own catalogue by pointing `catalogue_url` in settings at a JSON file of the
same shape.
