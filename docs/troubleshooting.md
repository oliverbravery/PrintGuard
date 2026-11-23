<div align="center">

# Troubleshooting

[Docs](README.md) · [Printers](printers.md) · [Cameras](cameras.md) · [Monitoring](monitoring.md) · [Notifications](notifications.md) · [Training frames](feedback.md) · [Hardware](hardware.md) · [Deployment](deployment.md) · [API & MCP](api.md) · [Plugins](plugins.md) · [Writing plugins](plugin-development.md) · [Architecture](architecture.md) · **Troubleshooting**

</div>

Look up what you're seeing and jump straight to the fix. Every row links back to the relevant doc if you want the full context.

- [Starting up](#starting-up)
- [Cameras and video](#cameras-and-video)
- [Printers](#printers)
- [Detection and alerts](#detection-and-alerts)
- [Plugins](#plugins)
- [The API](#the-api)
- [Acceleration](#acceleration)
- [Getting logs and diagnostics](#getting-logs-and-diagnostics)

## Starting up

| Symptom | Likely cause | Fix |
|---|---|---|
| Port `8000` or `8554` already in use at startup | Another PrintGuard instance is already running (often a forgotten container or background desktop app) | Check what holds the port with `lsof -nP -iTCP:8554 -sTCP:LISTEN` (macOS/Linux) or `netstat -ano \| findstr 8554` (Windows) and stop it |
| Page shows a single line starting "PrintGuard refused a request for" (`403`) | You opened PrintGuard via a domain it doesn't know (usually behind a reverse proxy or tunnel). Since 2.6.0 it only answers to IPs, local names and explicitly listed origins | Add the `PRINTGUARD_ORIGINS` line shown in the error message to your hub environment and restart. See [Host and origin checking](deployment.md#host-and-origin-checking) |
| Stuck on "Connecting to hub" then "The hub is not answering" | The WebSocket failed to connect, usually because a proxy isn't forwarding WebSocket upgrades or is stripping/rewriting `Origin` (2.6.0+ rejects WebSockets without an `Origin`) | Enable WebSocket forwarding and pass `Origin` through your proxy. See [Host and origin checking](deployment.md#host-and-origin-checking) |
| A hostname in `PRINTGUARD_ORIGINS` still gets `403`, and the log says it `is ignored because it has no scheme` or `is ignored because it is not an address` | Missing `http://`/`https://`, unsupported scheme, non-numeric port or malformed IPv6 bracket | Include the scheme and valid port (e.g. `https://hub.example.com`) and restart. See [Host and origin checking](deployment.md#host-and-origin-checking) |
| Hub boots completely empty and logs `state.json is damaged` | `state.json` was corrupt (often from a full disk or power loss) or had an invalid structure. The hub moved it aside to `state.json.corrupt` in your [data directory](deployment.md#your-data-and-backups) and booted fresh (subsequent corrupt files become `.1`..`.4` without overwriting the first) | Stop the hub and restore a backup as `state.json`, or repair the corrupt file and rename it back. Remember API tokens live in `state.json` too, so reads are open again until restored |
| Hub refuses to start, logging `state.json could not be read`, `could not be moved aside` or `could not be created` | Wrong file permissions/owner on the data directory (often after restoring a backup or changing container UID). If it mentions `Is a directory`, Docker created a folder because you bind-mounted a non-existent `state.json` file | Fix ownership for [the user running the hub](deployment.md#running-the-container-as-your-own-user) and restart. If `state.json` is a directory, remove it and mount the whole data folder instead |
| A camera, printer, monitor, print or plugin vanished after reboot, with a startup warning saying `could not be read and was dropped` | Its entry in `state.json` was malformed (usually after a manual edit). PrintGuard skipped it, kept everything else, and removes it on next save (dropped print files stay on disk until the next boot). Malformed settings reset to defaults with a `was reset` warning | Re-add the item in the dashboard, or stop the hub and restore a backup of `state.json` |
| Windows blocks the desktop app on first run | The Windows executable is currently unsigned | Click **More info** -> **Run anyway** |
| Desktop app opens to "PrintGuard could not start" | The local hub server failed to launch | Check the error summary and log tail shown in the window, or grab the full file from [Getting logs and diagnostics](#getting-logs-and-diagnostics) |
| Desktop app opens to "PrintGuard is still starting" | Startup took longer than 30 seconds (common on first Windows 11 24H2+ launch while Windows ML downloads your GPU provider; pre-2.6.0 showed an error here) | Give it a moment; the dashboard loads automatically once ready. If it hangs for minutes, check the log tail to see what it's waiting on |
| Windows desktop app exits immediately with no window | On machines without a real GPU driver (like VMs), Windows exposes Basic Render Driver, which crashed pre-2.5.0 builds | Update to 2.5.0+ or install a GPU driver |
| Windows tray icon appears, but **Open PrintGuard** does nothing | Windows marks extracted browser downloads with a Zone.Identifier flag that broke pre-2.6.0 webview loading | Update to 2.6.0+. On older versions, open `http://localhost:8000` in your browser, or right-click the zip -> Properties -> tick **Unblock** and re-extract |
| Windows desktop app opens in your regular browser instead of its own window | WebView2 runtime isn't installed (pre-2.6.0 showed a blank white window) | Install the Evergreen runtime from [Microsoft's WebView2 page](https://developer.microsoft.com/microsoft-edge/webview2/), or just keep using your browser |
| Desktop app says `another program holds port 8000` or `another program answers on localhost:8000` | Something other than PrintGuard is already using port 8000 | Stop the other program, or launch PrintGuard with `PORT` set to an unused port |
| Launching the desktop app just opens a browser tab | PrintGuard is already running (or still booting) on that port, so the second instance opens the existing hub and exits. On macOS, clicking the app icon again brings up its existing window | Click **Open PrintGuard** in the tray/menu bar icon. If the browser tab can't connect yet, wait a moment and reload while the first instance finishes booting |
| Windows desktop app fails with `Immediate exit requested: 'video=dummy'` | A bug in 2.4.1 when enumerating cameras | Update to 2.5.0+ |
| Docker container boot-loops | Usually permissions on the `/data` volume | Check your volume mount and ownership, then run `docker logs printguard` (or `docker compose logs`) |

## Cameras and video

| Symptom | Likely cause | Fix |
|---|---|---|
| Monitor shows **no signal** | Hub can't reach the camera or the stream stopped sending frames | Test the URL from the hub machine itself (not your laptop). Inside Docker, `localhost` is the container, so check [networking caveats](printers.md#networking-caveats) and [Stream URLs](cameras.md#stream-urls) |
| USB, MJPEG or Bambu A1/P1 camera has no live preview, though risk scores still update | MediaMTX isn't running, so H.264 re-encoding for the live view is down (on the desktop app this usually means another app holds port `8554`, `1935`, `8888` or `9997`) | Look for the `live view unavailable` warning in the dashboard/logs, free the conflicting port, and live video will come back on its own within seconds |
| Camera shows **offline** in PrintGuard even though it plays elsewhere | URL or credentials changed, or FFmpeg has no decoder for the stream. The exact reason is printed on the camera's entry (including if a hung capture needs a hub restart to release) | Verify the URL plays from the hub host. Camera URLs can't be edited in place, so delete and re-add it. For RTSP feeds, make sure MediaMTX can reach the camera too |
| A camera added as `rtsp://<host-ip>:8554/<path>` went offline after upgrading to 2.6.0 in Docker | Since 2.6.0, reading from port `8554` requires the hub's internal login, which bridge-networked containers only recognise on `localhost` | Delete the camera and re-add it as `rtsp://localhost:8554/<path>`. See [Stream URLs](cameras.md#stream-urls) |
| Adding a camera fails with `no frames from camera` | No video frame arrived within 25 seconds (bad URL, `localhost` in Docker, or wrong credentials). The reason after the colon strips credentials | Test the URL from the hub machine and try again. See [Stream URLs](cameras.md#stream-urls) |
| Adding a camera fails with `no decoder for this stream` (or test image says `could not decode image`) | The URL returns something FFmpeg can fetch but isn't video (like an HTML page or SVG) | Point it at the actual video/MJPEG stream URL |
| Adding a camera fails with `PrintGuard can't use that address` | Bundled MediaMTX rejected the URL syntax/scheme | Check the reason shown and fix the scheme, host or path |
| Feed displays **Tap to play** | Browser blocked autoplay (common on iOS in Low Power Mode) | Tap it. Detection runs server-side regardless of whether the browser plays video |
| **This browser** camera monitors fine but preview stays on "starting stream" | That browser records VP8 instead of H.264, which the HLS player can't play | Use Chrome, Edge or Safari to publish H.264 |
| Stuck on "Connecting to hub" in Safari with **Block All Cookies** enabled | Pre-2.6.0 failed when localStorage was blocked | Update to 2.6.0+ (theme and published camera preferences just won't persist across reloads) |
| **This browser** camera won't start | Browsers only allow webcam access on HTTPS or `localhost` | Serve PrintGuard over HTTPS or open on `localhost`. See [Deployment](deployment.md) |
| USB camera plugged into host never shows up in Docker | Not mounted into the container, or plugged in after startup | Add a `devices:` mapping and run `docker compose up -d`. See [Cameras plugged into the hub](cameras.md#cameras-plugged-into-the-hub) |
| Multiple USB cameras on one machine stutter or drop out | USB controller bandwidth saturation from uncompressed video | Use cameras that support MJPEG (PrintGuard requests MJPEG first on Linux) and split them across separate USB controllers |
| Warning that a camera feed has stalled | Camera stayed connected, though no frame was scored for 30s + the fault grace period (frozen stream or repeated inference failures) | PrintGuard restarts the capture reader every minute automatically and sends a recovery once stable (1 min up to 15 min on relapses). If it keeps repeating, check the camera/network and look in the logs for `inference failed` |
| Adding a camera fails with "WebRTC source does not expose WHEP" | URL points to a proprietary WebRTC page instead of a WHEP endpoint | Use the camera's WHEP, MJPEG or RTSP URL. See [Stream URLs](cameras.md#stream-urls) |
| Dashboard error reading "inference failed" | Model inference errored on a frame | Retries automatically on the next frame. If it keeps firing, [send me the logs](#getting-logs-and-diagnostics) |
| Passed-in USB camera shows offline after restart | Device wasn't present at boot (unplugged, removed from `devices:` or renumbered). Docker may also refuse to start if a `devices:` path is missing | Reconnect the camera and restart (name, crop and tuning are preserved). To remove permanently, drop the `devices:` line, restart and click Remove |
| Warning that a monitor "has no camera" | Its linked camera is gone (e.g. printer changed services or `PRINTGUARD_CAMERAS=off` dropped a passed-in camera) | Pick another camera in the monitor's **Configure** tab, or restore the passed-in device |
| Error ending "No space left on device" | `/data` volume is full, blocking saves and frame storage | Detection, pausing and alerts keep working (the error repeats every 30s). Free up disk space on `/data` |
| Video plays normally, though defect score never updates | Monitor is on standby because the linked printer reports it isn't printing | Intended behaviour. See [failing safely](architecture.md#failing-safely) |
| Warning starting "Cannot tell whether the printer for" | Monitor is watching, though PrintGuard can't read printer status (network issue, rejected key or unknown state) | Intended behaviour: PrintGuard keeps watching, though auto-pause won't work until reconnected. Check **Printers**; the warning sends once the [fault grace period](notifications.md#faults-and-the-grace-period) elapses |
| Smooth with one camera, choppy with several | Inference capacity is split across all active cameras | Check **Capacity** and **Latency**, then see [Hardware](hardware.md#how-much-hardware-you-need) |

## Printers

| Symptom | Likely cause | Fix |
|---|---|---|
| Connection test fails with *all connection attempts failed* | Inside Docker, `localhost` is the container itself | Use `http://host.docker.internal:5000` and make sure the service listens on `0.0.0.0` on Linux. See [Networking caveats](printers.md#networking-caveats) |
| Offline warnings while printer is powered off | Pre-2.6.0 forgot idle state across restarts | Update to 2.6.0+. Note that a brand-new printer added while powered off will still warn until it reports status once |
| Printer shows `offline` while actively printing | Hub lost connection or credentials were rejected | Detection continues by design. Check the log or run **Test connection** under **Printers** to see why; status clears automatically once fixed |
| **Test connection** says the service *rejected the API key* or *rejected the username or password* | OctoPrint, Moonraker or PrusaLink refused your credentials (Moonraker says this when no key is set and the hub IP isn't trusted) | Re-copy the key/password and save. For Moonraker, you can add the hub IP to `trusted_clients` instead. See [Supported print services](printers.md#supported-print-services) |
| **Test connection** says the service *did not answer like its API* or *PrusaLink answered HTTP* `<code`> | Something answered, though not the expected printer API (usually wrong port or a proxy login page) | Register the printer service's direct address |
| Bambu printer shows `offline`, test says it *has sent nothing, so check the serial number* | Access code worked, though the serial number doesn't match so no status messages arrive (powered-off printers time out/refuse instead) | Double-check the serial number under Settings -> Device on the printer |
| Saving/testing fails with *send API key again, since a stored secret is only kept for the address it was saved with* | You changed the address without re-typing the saved secret (also applies to MQTT broker host/port + password) | Re-enter the secret and save. See [Register a printer](printers.md#register-a-printer) |
| Saving/testing says URL *needs http:// or https:// at the start* | Scheme omitted (e.g. `192.168.1.50:5000`) | Prepend `http://` or `https://` |
| Alert fails saying service *did not answer the alert like its API* | URL returned something unexpected (often an auth proxy login page) | Use the service's direct URL or bypass auth for the hub |
| Saving/testing says it *needs* `<field>` *filled in* | A required field was left empty | Fill in the named field |
| Printer test, command or alert says address *redirects to* another URL | PrintGuard never follows redirects so credentials and commands can't be sent to an unconfigured host | Update the printer or alert channel to use the target URL shown in the error. See [Networking caveats](printers.md#networking-caveats) |
| ntfy alerts arrive without images and dashboard reports snapshot refused | Self-hosted ntfy server doesn't have attachments enabled | Configure `attachment-cache-dir` and `base-url` on your ntfy server. See [Notifications](notifications.md) |
| Printer webcam never appears under **Cameras**, with "Could not open the camera" or "Could not list the cameras" | PrintGuard skips webcams it can't open, usually because a relative webcam path resolved to the wrong port (like OctoPrint mapped `5000:80`) | Check [Where a printer's webcam is read from](printers.md#where-a-printers-webcam-is-read-from), fix the address, then click **Refresh** under **Cameras** |
| Adjusting a print file's temperature fails saying *lowering the bed* or *the nozzle would turn it off* | A later layer in the G-code is cooler than the first layer, and your offset would push it to 0°C or below | Pick a slightly higher first-layer temperature or re-slice the file |
| Pause or cancel did nothing | Print service rejected the command | Check the dashboard error, notification text and the printer service's own logs |
| **Print** button is disabled or printer isn't listed | Printer isn't idle, file is tagged for different printers, or printer doesn't support that file extension | Wait for the current print to finish (or cancel it) and check the file's printer tags. See [Sending prints](printers.md#sending-prints) |
| Defect alert says pause/cancel failed on Bambu Lab | Developer Mode is turned off, or access code is wrong | Enable Developer Mode under Settings -> Network on the printer and verify the access code |
| Bambu Lab rejects an uploaded file | Not a sliced `.3mf`, or Developer Mode is off | Export a sliced `.3mf` (with G-code included) from Bambu Studio/OrcaSlicer and turn on Developer Mode |

## Detection and alerts

| Symptom | Likely cause | Fix |
|---|---|---|
| Too many false alarms | Threshold is too low for your camera/lighting, or consecutive frame count is too sensitive | Raise the threshold or consecutive detections on that monitor. See [Choosing values](monitoring.md#choosing-values) |
| Failures caught too late | Threshold or consecutive count is too strict | Lower one or both using your [risk history](monitoring.md#risk-history) as a guide |
| Real failures barely move the risk score | Print is tiny in frame or outside the default centre square | Crop tightly around your build plate under **Cameras**. See [Tuning the camera](monitoring.md#tuning-the-camera) |
| Saving/testing an alert channel says it *needs* `<field>` *filled in* | Required field left blank | Fill in the named field. See [Channels](notifications.md#channels) |
| Alerts never reach your phone | **Push notifications** is off on that monitor (default for new monitors), or the channel is failing | Turn on **Push notifications** in the monitor's **Configure** tab and test the channel under **Settings -> Alerts** |
| Repeated camera drop-out warnings | Unstable camera/network. Each episode sends one warning (repeated every 30 min while it lasts); monitor cooldown only applies to defect alerts | Check camera Wi-Fi/power and (for RTSP/WHEP) MediaMTX connectivity. See [Faults and the grace period](notifications.md#faults-and-the-grace-period) |
| Wi-Fi camera spams disconnect alerts for 5-second blips | Fault grace period is shorter than the camera's reconnect time | Increase **Fault grace period** under **Settings -> Alerts** (up to 15 minutes) |
| Warning that camera dropped out for a percentage of the last 10 minutes | Camera drops and reconnects faster than the grace period repeatedly, leaving gaps in monitoring | Fix the camera's connection/power rather than tweaking notifications; this fires once per unstable episode and every 30 min while ongoing |
| Pushover alerts wake you during quiet hours | Pushover defaults to High priority, which bypasses quiet hours | Change priority to Normal under **Settings -> Alerts**. See [Channels](notifications.md#channels) |
| Reviewed print shows as queued | Hit a [daily limit](feedback.md#limits), or the training inbox is full, closed or unreachable | No action needed; frames stay on your hub and send automatically when ready (or click **Try now**) |
| No review prompt after a print | Monitor has no linked printer (rolls over every 24h), or review prompts are switched off | Check the monitor's **Review** tab (or **History -> Prints**) after the print finishes, or re-enable under **Settings -> Storage** |
| Home Assistant shows no devices, or warning "Home Assistant MQTT unavailable" | Wrong broker credentials/host, broker down, or MQTT discovery disabled in Home Assistant | Check **Settings -> Home Assistant** and your broker logs. See [Home Assistant](api.md#home-assistant) |

## Plugins

| Symptom | Likely cause | Fix |
|---|---|---|
| Plugin says it's waiting on permissions | Freshly installed, or updated with expanded permissions | Enable it in **Settings -> Plugins** and review/accept its permissions. See [Plugins](plugins.md) |
| Plugin stopped itself with an error | Sandbox crashed, timed out or exceeded memory/CPU caps; PrintGuard disables misbehaving plugins to protect the hub | Read the reason on the plugin's page or in the logs, and re-enable once updated/fixed |
| GitHub install fails | Error explains why: `no plugin.json at` means wrong path; `GitHub could not resolve` means invalid repo/branch/tag (or `403`/`429` means GitHub rate-limiting) | Verify the path/ref or retry in a few minutes |
| Install says plugin `only runs on` another platform | Plugin manifest restricts [platforms](plugin-development.md#platforms) (e.g. desktop-only plugin on Docker) | Expected; the plugin doesn't support this host platform |
| Install fails with `takes the plugin past 12288 KB of files` | Exceeds the 12 MB total (or 4 MB per-file) plugin size cap | Ask the plugin author for a smaller package |
| OAuth plugin vanished after updating to 2.6.0 with `could not be read and was dropped` | Its OAuth URLs used plain `http://`, which 2.6.0 blocks | Install an updated version using `https://` |
| Plugin switched off after updating to 2.6.0 saying it `now needs Reach your own network` | Its URLs touch local addresses (like `.home.arpa` or `127.1`), which now require `net:local`. Data and secrets are kept | Open its page and accept the permission |
| Zip import fails saying it has more than one `plugin.json` or duplicate files | Archive contains multiple plugins or duplicated paths | Zip just the single plugin folder |
| Pre-2.6.0 plugin fails on URLs with uppercase path characters (e.g. Telegram `/bot*/sendMessage`) | Older versions lowercased stored URL patterns on install | Reinstall the plugin |
| Plugin shows as `third party` instead of `verified` | Hashes don't match the catalogue, or it isn't in the catalogue | Normal for unreviewed plugins; if it's a catalogue plugin, the catalogue pin needs updating |
| Plugin's network requests fail | Host isn't in its manifest `urls`, `net` isn't granted, or it resolved to a local IP without `net:local` (`may not reach this network`). Redirects are also blocked; other errors report their type like `ConnectTimeout` | Intentional sandbox enforcement |
| Picture-in-picture button does nothing | Feed hasn't started playing yet, or browser blocked PiP | Check the toast message; wait for the video feed to load before clicking |
| Locked out of the hub by a plugin | A `gate` plugin is rejecting requests or crashed (failing closed) | Boot with `PRINTGUARD_PLUGINS=off` and remove or fix the plugin. See [Deployment](deployment.md#plugins) |

## The API

| Symptom | Likely cause | Fix |
|---|---|---|
| Editing a printer, notifier or broker returns `400` with `send <field> again` | Address changed without resending stored secrets | Include the secret alongside the new address. See [The resource model](api.md#the-resource-model) |
| Deleting a non-existent ID returns `400` instead of `404` | Since 2.6.0, deleting an unknown camera, printer, monitor or print ID returns `400` rather than silently succeeding | Re-fetch the list to confirm the ID. See [REST API](api.md#rest-api) |
| Adding a printer or saving a channel returns `400` saying it `needs <field> filled in` | Missing required field | Include the named field in the request body |

## Acceleration

| Symptom | Likely cause | Fix |
|---|---|---|
| Intel GPU isn't being used | Running default tag instead of `-intel`, missing `--device /dev/dri`, or iGPU is older than 11th-gen Tiger Lake | Use `latest-intel` with `--device /dev/dri`. Check **Compute** (`intel gpu` when active) and startup logs for what providers offered. See [Intel GPU](hardware.md#intel-gpu) |
| High CPU usage on a shared server | Detection runs as fast as the host and cameras allow by default | Lower **Detection rate** per camera under **Cameras**. See [Tuning the camera](monitoring.md#tuning-the-camera) |
| NVIDIA GPU isn't being used | Missing NVIDIA Container Toolkit, wrong runtime config, or wrong image tag | Check startup logs for the provider error (hub falls back to CPU). See [NVIDIA GPU](hardware.md#nvidia-gpu) |
| **Compute** shows CPU in the Windows desktop app | No GPU driver installed for DirectML or Windows ML | Install your GPU driver and restart PrintGuard |
| **Compute** shows `microsoft gpu` on Windows 11 24H2+ | Falling back to DirectML because Windows App Runtime 2.x isn't installed | Install the x64 runtime from [Windows App SDK downloads](https://learn.microsoft.com/en-us/windows/apps/windows-app-sdk/downloads) and restart |
| **Compute** shows CPU even though you have an accelerator | Provider didn't expose it, or compiling/running the model on it failed | Check startup logs for `execution providers offer:` and any `cannot run the model, so detection is not using it` warning (also shown on the dashboard). See [Execution providers by platform](hardware.md#execution-providers-by-platform) |
| Speed isn't what you expected | Automatic mode picks the fastest runtime on your machine, and Standard is roughly 2.5x heavier than Light | Check the startup log, or pin a runtime / switch to Light under **Settings -> Detection** |

## Getting logs and diagnostics

| Where | How |
|---|---|
| Docker | `docker logs printguard` (or `docker compose logs -f`) |
| Desktop app | `printguard.log` inside your [data directory](deployment.md#your-data-and-backups) (rotates at 2 MB, keeping `.1` and `.2`) |
| Verbose logs | Set `LOG_LEVEL=DEBUG` for command traces, printer state transitions and tracebacks |
| Full bundle | Click the bug icon in the top bar -> **Download logs** for a zip containing sanitised config, diagnostics and log tails with all credentials stripped |

That same bug dialog can also send an anonymous report straight to me with the scrubbed bundle, your dashboard URL, browser user agent, viewport size and an optional reply email. Nothing leaves your hub unless you submit it or download it yourself.

Still stuck? Open a [GitHub issue](https://github.com/oliverbravery/PrintGuard/issues) and attach that diagnostics zip.
