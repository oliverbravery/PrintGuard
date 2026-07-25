<div align="center">

# Troubleshooting

[Docs](README.md) · [Architecture](architecture.md) · [Printers & cameras](printers.md) · [Hardware](hardware.md) · [Deployment](deployment.md) · [API & MCP](api.md) · **Troubleshooting**

</div>

Find the symptom, apply the fix. Every row links to the page that explains the reasoning.

- [Starting up](#starting-up)
- [Cameras and video](#cameras-and-video)
- [Printers](#printers)
- [Detection and alerts](#detection-and-alerts)
- [Acceleration](#acceleration)
- [Getting logs and diagnostics](#getting-logs-and-diagnostics)

## Starting up

| Symptom | Cause | Fix |
|---|---|---|
| `bind: address already in use` for `8000` or `8554` | Another PrintGuard already holds the port, often a desktop app or a container you forgot | Find the holder with `lsof -nP -iTCP:8554 -sTCP:LISTEN` on macOS or Linux, or `netstat -ano \| findstr 8554` on Windows, then stop it. Versions before 2.3.8 could leave the streaming server behind after a crash |
| Dashboard loads but the header shows "Reconnecting" | The engine WebSocket cannot connect, usually a proxy that does not forward WebSockets, or a rewritten `Origin` | Check the proxy forwards upgrade headers, then see [origin checking](deployment.md#origin-checking) |
| First launch of the desktop app is blocked | The builds are unsigned | macOS: **System Settings → Privacy & Security → Open Anyway**. Windows: **More info → Run anyway** |
| Container restarts repeatedly | Usually an unwritable `/data` volume | Check the volume mount and its permissions, then read `docker logs printguard` |

## Cameras and video

| Symptom | Cause | Fix |
|---|---|---|
| Tile reads **no signal** | The source is unreachable from the hub, or it stopped producing frames | Open the stream URL from the machine running the hub, not from your laptop. In Docker, remember `localhost` means the container: see [networking caveats](printers.md#networking-caveats) |
| Camera is **offline** in the registry but the feed works elsewhere | Wrong scheme or path, or a source that needs credentials in the URL | Re-test the URL. RTSP sources are pulled by MediaMTX, so it must reach them too |
| **This device** camera will not start | Browsers only allow camera access on secure pages | Serve the hub over HTTPS or open it on `localhost`. [Deployment](deployment.md) covers both |
| Feed plays but the risk score never moves | The monitor is in standby because its printer positively reports "not printing" | This is by design. See [failing safely](architecture.md#failing-safely) |
| Video is smooth for one camera and choppy for several | The host's sustainable capacity is shared across cameras | Check the **capacity** and **latency** readouts, then [Hardware](hardware.md#how-much-hardware-you-need) |

## Printers

| Symptom | Cause | Fix |
|---|---|---|
| Test fails with *all connection attempts failed* | The hub is in a container, so `localhost` is the container | Use `http://host.docker.internal:5000`, and make the service listen on `0.0.0.0` on Linux hosts. [Details](printers.md#networking-caveats) |
| Test fails with *access control checks* | Local mode only: the print service sends no CORS headers | Enable CORS in OctoPrint or add `cors_domains` to `moonraker.conf`, or use hub mode |
| Test fails with *not allowed to request resource* over HTTPS | The browser blocks an `http://` printer from an HTTPS page as mixed content | Use hub mode, where the server makes the request, or serve the printer over HTTPS |
| Bambu, Elegoo or Prusa is missing from the list | Those services need a raw socket, an access code exchange or HTTP Digest, none of which a browser can do | Use hub mode. [Supported print services](printers.md#supported-print-services) |
| Printer shows `offline` but is printing | The hub cannot reach the service | Monitoring keeps running by design. Fix reachability, then the state clears itself |
| Pause or cancel did nothing | The service rejected the action | The failure is in the alert, the dashboard error feed and the notification. Check the service's own logs |

## Detection and alerts

| Symptom | Cause | Fix |
|---|---|---|
| Too many false alerts | Sensitivity or threshold too aggressive for your camera and lighting | Raise the threshold or lower sensitivity on that monitor, and raise the consecutive-frame count so brief blips are ridden out |
| Failures caught too late | The opposite | Lower the threshold or the frame count. Watch the risk history on the monitor's detail page to pick a value |
| No notifications arrive | The channel is off for that monitor, or the channel itself is failing | Send a test alert from **Settings**. Delivery failures raise an `error` event rather than passing silently |
| Telegram is not offered | Telegram's API sends no CORS headers | Hub mode only. [Notifications](printers.md#notifications) |
| Home Assistant shows nothing | The broker settings are wrong, or discovery is disabled in Home Assistant | Check **Settings → Home Assistant** and the broker's own log |

## Acceleration

| Symptom | Cause | Fix |
|---|---|---|
| An Intel GPU is not used | The standard image leaves the Intel GPU runtime out | Use the `latest-intel` tag *and* pass `--device /dev/dri`. [Intel GPU](hardware.md#intel-gpu) |
| An NVIDIA GPU is not used | Missing Container Toolkit, missing `--gpus all`, or the wrong tag | [NVIDIA GPU](hardware.md#nvidia-gpu) |
| **compute** reads `cpu` on a machine with an accelerator | No compatible provider was usable, so ONNX Runtime fell back | [Execution providers by platform](hardware.md#execution-providers-by-platform) |
| Throughput differs from what you expected | Automatic mode picks whichever runtime benchmarks faster on the host | The choice is logged at start. Pin one in **Settings → Advanced** |

## Getting logs and diagnostics

| Where | How |
|---|---|
| Container | `docker logs printguard`, or `docker compose logs -f` |
| Desktop app | A rotating log file in the app's data directory, path set by `LOG_FILE` |
| More detail | Set `LOG_LEVEL=DEBUG` for command traces and exception tracebacks |
| Everything at once | The bug icon in the header, then **Download logs**: a zip with the sanitised diagnostics bundle and both log tails, credentials stripped |

The same bug dialog sends a report straight to the developer, anonymously, with the same
scrubbed contents and an optional email for follow-up. Nothing leaves the machine unless you
submit it or download it yourself.

If you are stuck, open an [issue](https://github.com/oliverbravery/PrintGuard/issues) and
attach that zip.
