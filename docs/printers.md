<div align="center">

# Printers, cameras and notifications

[Docs](README.md) · [Architecture](architecture.md) · **Printers & cameras** · [Hardware](hardware.md) · [Deployment](deployment.md) · [API & MCP](api.md) · [Plugins](plugins.md) · [Troubleshooting](troubleshooting.md)

</div>

Connecting print services and cameras, what PrintGuard does with a printer's webcam, and
how alerts are wired up.

- [How the pieces fit](#how-the-pieces-fit)
- [Register a printer](#register-a-printer)
- [Supported print services](#supported-print-services)
- [Printer cameras](#printer-cameras)
- [Adding cameras yourself](#adding-cameras-yourself)
- [Notifications](#notifications)
- [Networking caveats](#networking-caveats)

## How the pieces fit

A camera and a printer are registered once each, then bound together by a monitor. One
printer connection can back several monitors, and a monitor without a printer still watches
and alerts.

```mermaid
flowchart LR
    cam["Camera<br/>a video source"] --> mon
    prn["Printer<br/>a print service connection"] -.-> mon
    mon["Monitor<br/>thresholds + defect response"] --> act["Alert · Pause · Cancel"]
    prn -. "job state gates inference" .-> mon
```

The dotted lines are the optional parts. Bind no printer and PrintGuard still alerts you, it
just cannot stop the print.

## Register a printer

Open the printer registry, choose the service, fill in the form and **Test** it before
saving. Then bind it to a monitor and choose whether a sustained defect alerts you, pauses the
print or cancels it.

Linked printers report job name, progress and state on every monitor that uses them, and they
gate inference. A printer that positively reports "not printing" stands its monitors down, so
an idle printer costs nothing. Losing contact with a printer never stands monitoring down, and
neither does a state the adapter cannot read, so a monitor left watching an apparently idle
printer warns and says which state it is getting. See
[failing safely](architecture.md#failing-safely).

## Supported print services

| Service | Modes | Authentication | Exposes a camera |
|---|---|---|---|
| [OctoPrint](https://octoprint.org) | Hub and local | API key | Yes, its webcam stream |
| [Klipper via Moonraker](https://moonraker.readthedocs.io) | Hub and local | Optional API key | Yes, its configured webcams |
| [Elegoo](https://github.com/ELEGOO-3D/elegoo-link) | Hub only | Access code, or Moonraker API key | Centauri chamber camera |
| [Prusa via PrusaLink](https://help.prusa3d.com/guide/wi-fi-and-prusa-connect-link-setup-core-one-mk4-s-mk3-9-mk3-5-xl-mini_413293) | Hub only | HTTP Digest, user `maker` | No local stream |
| [Bambu Lab](https://github.com/Doridian/OpenBambuAPI) | Hub only | Access code and serial | Chamber camera |

"Hub only" means a browser cannot make the connection at all, so the integration is offered
only when PrintGuard runs as a server. The reasons are per service and listed below.

<details>
<summary><b>Bambu Lab</b>: LAN Only Mode, Developer Mode, and why hub only</summary>

Bambu printers speak MQTT over TLS rather than HTTP, and a browser cannot open a raw
socket, so control is hub only.

1. On the printer, enable **LAN Only Mode**, then **Developer Mode** under
   Network in Settings. This opens the MQTT channel.
2. Note the **access code** shown there, and the **serial number** under Device in Settings.
3. Register the printer with its IP address, serial number and access code.

The chamber camera is registered automatically: RTSP on the X1 and H2 series, or the
proprietary port 6000 protocol on the A1 and P1 series. The form links Bambu's
[Enable LAN Mode](https://wiki.bambulab.com/en/knowledge-sharing/enable-lan-mode) guide.

</details>

<details>
<summary><b>Elegoo</b>: two families, Centauri and Neptune/OrangeStorm</summary>

Elegoo control is hub only. Choose the family that matches your printer:

**Centauri** covers the Centauri Carbon and Centauri Carbon 2. PrintGuard detects which
local protocol the printer speaks and registers its chamber camera automatically.

- Carbon 2: enable **LAN Only Mode** in its network settings and use the access code shown
  there.
- Original Carbon: the IP address is enough.

**Neptune/OrangeStorm** covers the Neptune 4 Pro, Plus and Max, the OrangeStorm Giga, and
any other Elegoo printer running Moonraker. PrintGuard uses the stock Moonraker service on
port `7125` and accepts an API key if you set one.

All state, camera and control traffic stays between PrintGuard and the printer on your LAN.
Elegoo's cloud is never involved.

</details>

<details>
<summary><b>Prusa</b>: PrusaLink, not PrusaConnect</summary>

Prusa printers connect over **PrusaLink**, the API that runs on the printer itself on the
MK4, MK4S, MK3.9, MK3.5, MINI, XL and CORE One, or on a Raspberry Pi attached to an MK3 or
MK2.5. It authenticates with HTTP Digest, which a browser cannot perform, so Prusa is hub
only.

1. Enable **PrusaLink** on the printer under Settings, Network, then PrusaLink.
2. Register it with its URL and the password shown there. The username is always `maker`.

PrusaConnect is not used, so no frames or job data leave hardware you own. PrusaLink's
webcam feature pushes snapshots to PrusaConnect rather than serving a local video stream, so
if the printer has a camera, add it separately as a **Stream URL**.

</details>

## Printer cameras

If a registered printer exposes a webcam, PrintGuard registers it as a camera for you, with
no stream URL to copy. The camera registry's **Printer cameras** tab lists them and a
**Refresh** button picks up a camera attached after the printer was registered.

These cameras belong to their printer, so they cannot be removed on their own and they are
dropped when the printer is.

## Adding cameras yourself

Beyond printer webcams, a hub takes cameras three ways:

| Source | What it accepts | Notes |
|---|---|---|
| **Stream URL** | RTSP, RTMP, HTTP/MJPEG or WHEP | PrintGuard creates a MediaMTX pull path for it |
| **This device** | The browser's own camera | Publishes to the hub over a WebSocket and reconnects after a hub restart |
| **Discovered** | Anything already pushed to MediaMTX | For example `rtsp://host:8554/mycam` from a Raspberry Pi |

> [!IMPORTANT]
> Browsers only grant camera access on secure pages. **This device** publishing and local
> mode both need the hub served over HTTPS or opened on `localhost`.
> [Deployment](deployment.md) covers HTTPS with Tailscale or a tunnel.

## Notifications

Alert channels live in **Settings**. Enable a channel, fill in the form and send a test
alert. Every enabled channel receives defect snapshots and watchdog warnings for monitors
that have notifications switched on.

A monitor's **cooldown** is the quiet window after a defect alert. Watchdog warnings are
separate, so a camera or printer that keeps dropping out warns once for the whole unstable
episode, and the recovery is only announced once it has stayed healthy, so reconnections
cannot turn into a stream of notifications.

| Channel | Modes | Notes |
|---|---|---|
| [ntfy](https://ntfy.sh) | Hub and local | Self-hostable, no account needed |
| [Pushover](https://pushover.net) | Hub and local | One-off app purchase, needs an application token you create |
| [Discord](https://discord.com) | Hub and local | Webhook URL |
| [Telegram](https://telegram.org) | Hub only | Telegram's API sends no CORS headers |
| Desktop notification | Desktop app only | Native OS notification on the computer running the app |

## Networking caveats

Most connection problems come down to who makes the request. In hub mode the server does,
from inside the container. In local mode the browser does, under browser security rules.

```mermaid
flowchart LR
    subgraph hub["Hub mode"]
        server["PrintGuard server"] -->|"server-side HTTP, no browser rules"| svc1["Print service"]
    end
    subgraph local["Local mode"]
        browser["Browser tab"] -->|"CORS and mixed content apply"| svc2["Print service"]
    end
```

### Running in Docker

The hub reaches printer services from inside the container, so
`localhost` means the container, not your host, and a URL like `http://localhost:5000`
fails with *all connection attempts failed*. Use `http://host.docker.internal:5000`. The
shipped [`docker-compose.yaml`](../docker-compose.yaml) maps that name for you. On a Linux
host the print service must also listen on `0.0.0.0` rather than loopback only.

### Local mode URLs

Give the browser a URL it can reach itself: `http://localhost:5000`
when the service runs on the same machine, otherwise the host's LAN IP. Never
`host.docker.internal`, which only resolves inside a container.

### CORS in local mode

The browser enforces CORS, so enable it in OctoPrint under
Settings, API, or add `cors_domains` to `moonraker.conf`. Without it the connection test
fails with *access control checks*.

### Mixed content

If PrintGuard itself is served over HTTPS, for example through a
Cloudflare Tunnel, the browser blocks calls to an `http://` printer. Safari reports *not
allowed to request resource* even for `http://localhost`. To control an HTTP printer from
an HTTPS deployment, use hub mode, where the server makes the request, or serve the printer
over HTTPS.

[Troubleshooting](troubleshooting.md) has more symptoms and fixes.
