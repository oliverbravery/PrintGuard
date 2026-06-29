# Printers, cameras and notifications

How to connect printers, what PrintGuard does with their webcams, how to wire up alerts —
and the networking caveats that trip people up.

## Register a printer

Register a printer — [OctoPrint](https://octoprint.org),
[Klipper (Moonraker)](https://moonraker.readthedocs.io),
[Prusa (PrusaLink)](https://help.prusa3d.com/guide/wi-fi-and-prusa-connect-link-setup-core-one-mk4-s-mk3-9-mk3-5-xl-mini_413293)
or [Bambu Lab](https://github.com/Doridian/OpenBambuAPI) — in the printer registry and test the
connection there, then bind it to a monitor. A monitor's detail panel chooses what a
sustained defect should do: **alert only**, **pause** or **cancel**. Linked printers report
job, progress and state on the monitors that use them — and gate inference, so an idle
printer costs you nothing.

## Printer cameras

If a registered printer exposes a webcam, PrintGuard registers it as a camera automatically
— no stream URL to copy. The camera registry's **Printer cameras** tab lists them, and a
**Refresh** button picks up any camera attached to a printer after it was registered. This
covers OctoPrint and Moonraker webcam streams and the Bambu chamber camera (over RTSP on the
X1/H2 series, or the proprietary port-6000 protocol on the A1/P1 series, hub mode only).
These cameras are managed by their printer and removed with it.

## Hub mode cameras

Beyond printer webcams, a hub takes cameras three ways:

- **Stream URL** — any RTSP/RTMP/HTTP source; PrintGuard creates a MediaMTX pull path.
- **This device** — publishes a browser camera to the hub over a WebSocket. It reconnects if
  the hub restarts and resumes when you reopen the page on that device. Browsers only allow
  camera access on secure pages, so this (and local mode) needs the hub served over HTTPS or
  opened on `localhost`.
- **Discovered** — anything already pushed to MediaMTX (e.g. `rtsp://host:8554/mycam` from a
  Raspberry Pi) appears automatically.

## Bambu Lab

Bambu Lab printers speak MQTT over TLS rather than HTTP, which a browser cannot open, so they
are offered in **hub mode only**. On the printer, enable **LAN Only Mode** then **Developer
Mode** (Settings → Network) to open the MQTT channel, then link it with its IP, serial number
and access code; the form links Bambu's
[Enable LAN Mode](https://wiki.bambulab.com/en/knowledge-sharing/enable-lan-mode) guide.

## Prusa

Prusa printers connect over **PrusaLink**, the API that runs on the printer itself (MK4, MK4S,
MK3.9, MK3.5, MINI, XL, CORE One) or on a Raspberry Pi attached to an MK3/MK2.5. It
authenticates with HTTP Digest, which a browser cannot perform, so Prusa is offered in **hub
mode only**. Enable **PrusaLink** on the printer (Settings → Network → PrusaLink) and link it
with its URL and the password shown there; the username is always `maker`. PrintGuard talks to
PrusaLink on your network and never to Prusa's cloud — **PrusaConnect is not used**, so no
frames or job data leave hardware you own. PrusaLink's webcam pushes snapshots to PrusaConnect
rather than serving a local video stream, so if the printer has a camera, add it as a separate
**Stream URL**.

## Running in Docker

The hub reaches printer services from *inside the container*, so `localhost` points at the
container, not your host — connections to `http://localhost:5000` fail with *all connection
attempts failed*. Use `host.docker.internal` instead (e.g. `http://host.docker.internal:5000`);
the shipped `docker-compose.yaml` maps it for you. On a Linux host the service must also
listen on `0.0.0.0`, not just loopback.

## Local mode printer URLs

In local mode the browser calls the services directly, so give it a URL the *browser* can
reach — `http://localhost:5000` when it runs on the same machine, or the host's LAN IP
otherwise (not `host.docker.internal`, which only resolves inside the container). The browser
also enforces CORS: enable it in OctoPrint (Settings → API) or add `cors_domains` to
`moonraker.conf`, otherwise the request is blocked with *access control checks* and the test
fails. And if PrintGuard itself is served over HTTPS (e.g. a Cloudflare Tunnel), the browser
blocks calls to an `http://` printer as mixed content — Safari reports *not allowed to request
resource* even for `http://localhost`. To control a local HTTP printer from an HTTPS
deployment, use **hub mode** (the server makes the request, with no browser restrictions) or
serve the printer over HTTPS. Telegram's API sends no CORS headers, so that channel is
hub-only.

## Notifications

Notification channels live in Settings: enable [ntfy](https://ntfy.sh),
[Telegram](https://telegram.org) or [Discord](https://discord.com), fill in the form, and
send a test alert. Every enabled channel receives defect snapshots and watchdog warnings for
printers with notifications switched on.
