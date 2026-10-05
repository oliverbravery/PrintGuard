<div align="center">

# Troubleshooting

[Docs](README.md) · [Printers](printers.md) · [Cameras](cameras.md) · [Monitoring](monitoring.md) · [Notifications](notifications.md) · [Training frames](feedback.md) · [Hardware](hardware.md) · [Deployment](deployment.md) · [API & MCP](api.md) · [Plugins](plugins.md) · [Writing plugins](plugin-development.md) · [Architecture](architecture.md) · **Troubleshooting**

</div>

Find the symptom, apply the fix. Every row links to the page that explains the reasoning.

- [Starting up](#starting-up)
- [Cameras and video](#cameras-and-video)
- [Printers](#printers)
- [Detection and alerts](#detection-and-alerts)
- [Plugins](#plugins)
- [Acceleration](#acceleration)
- [Getting logs and diagnostics](#getting-logs-and-diagnostics)

## Starting up

| Symptom | Cause | Fix |
|---|---|---|
| A port already in use at start, `8000` or `8554` | Another PrintGuard already holds the port, often a desktop app or a container you forgot | Find the holder with `lsof -nP -iTCP:8554 -sTCP:LISTEN` on macOS or Linux, or `netstat -ano \| findstr 8554` on Windows, then stop it. |
| The page is one line of text starting "PrintGuard refused a request for", with a `403` | You opened the hub at a name it doesn't know, such as a domain behind a proxy or tunnel. From 2.6.0 it only answers to IP addresses, local names and names you list | Add the `PRINTGUARD_ORIGINS` line the message gives to the hub's environment and restart it. [Host and origin checking](deployment.md#host-and-origin-checking) |
| The page stays on the boot screen, reading "Reconnecting" | The engine WebSocket cannot connect, usually a proxy that does not forward WebSockets, or a rewritten `Origin` | Check the proxy forwards upgrade headers, then see [host and origin checking](deployment.md#host-and-origin-checking) |
| The hub starts with no cameras, printers or settings, and the log says `state.json is damaged` | The state file could not be read, usually after a full disk or a power cut. The hub moved it to `state.json.corrupt` in the [data directory](deployment.md#your-data-and-backups) and started empty | Stop the hub and put a backup in place as `state.json`, or repair the kept file and rename it back. API tokens are in that file too, so until then the API is back to open reads |
| First launch of the Windows desktop app is blocked | The Windows build is unsigned | Choose **More info** and then **Run anyway** |
| The desktop app opens to "PrintGuard could not start" | Its server did not start | The window says what failed and shows the end of the log. [Logs](#getting-logs-and-diagnostics) has where the full one is kept |
| The desktop app opens to "PrintGuard is still starting" | Its server has taken more than 30 seconds to come up, which a first launch on Windows can while Windows ML installs a graphics provider. Versions before 2.6.0 showed "PrintGuard could not start" here | Leave it open. The dashboard replaces the page once the server answers. If it stays for minutes, the end of the log says what it is waiting on |
| The Windows desktop app closes straight away without a window | Without a GPU driver, as in most virtual machines, Windows offers its Basic Render Driver as a GPU and versions before 2.5.0 crashed running the model on it | Update to 2.5.0 or later, or install the GPU driver |
| The Windows desktop app shows its tray icon but **Open PrintGuard** does nothing | Windows marks every file of a zip downloaded in a browser as from the internet, and versions before 2.6.0 could not load the window with that mark | Update to 2.6.0 or later. On an older version open `http://localhost:8000` in a browser, or right-click the zip, choose **Properties**, tick **Unblock** and extract it again |
| The Windows desktop app opens the dashboard in your browser instead of its own window | The PC has no WebView2 runtime, which the window is drawn with. Versions before 2.6.0 showed a blank white window | Install the Evergreen runtime from [Microsoft's WebView2 page](https://developer.microsoft.com/microsoft-edge/webview2/), or carry on in the browser |
| The desktop app shows "PrintGuard could not start" and the log ends in `another program holds port 8000` or `another program answers on localhost:8000` | Something else is serving on the hub's port, often a second copy of PrintGuard. Versions before 2.6.0 on Windows started anyway and could show the other program's page | Quit the other program, or start PrintGuard with `PORT` set to a free port |
| The Windows desktop app shows "PrintGuard could not start" and the log ends in `Immediate exit requested: 'video=dummy'` | 2.4.1 treated the end of its camera listing as a failure | Update to 2.5.0 or later |
| The website has no live demo, or a `#local` bookmark opens the landing page | Local mode, which ran PrintGuard in a browser tab, was removed in 2.5.0 | Install the desktop app or the Docker image from the [quick start](../README.md#quick-start) |
| Container restarts repeatedly | Usually an unwritable `/data` volume | Check the volume mount and its permissions, then read `docker logs printguard` |

## Cameras and video

| Symptom | Cause | Fix |
|---|---|---|
| Tile reads **no signal** | The source is unreachable from the hub, or it stopped producing frames | Open the stream URL from the machine running the hub, not from your laptop. In Docker, remember `localhost` means the container, so see [networking caveats](printers.md#networking-caveats). [Stream URLs](cameras.md#stream-urls) lists what the hub can pull |
| A USB, MJPEG or Bambu A1 or P1 camera has no live view while its monitor still scores frames | PrintGuard re-encodes these cameras into its bundled MediaMTX for the live view, and MediaMTX is not running. On the desktop app that is usually another program holding port `8554`, `1935`, `8888` or `9997`. Versions before 2.6.0 showed the camera as offline and stopped detection | The dashboard and the log have one warning that the camera's `live view unavailable`. Free the port and the live view comes back within a few seconds, with no restart |
| Camera is **offline** in the registry but the feed works elsewhere | Wrong scheme or path, or a source that needs credentials in the URL | Re-test the URL. RTSP sources are pulled by MediaMTX, so it must reach them too |
| A feed shows **Tap to play** | The browser refused to start the video by itself, which iOS does in Low Power Mode. Versions before 2.6.0 stayed on "starting stream" | Tap it. Detection runs on the hub and doesn't depend on the feed playing |
| A **This browser** camera is monitored but its feed stays on "starting stream" | The browser records VP8, which the live view can't play | Publish from Chrome, Edge or Safari, which record H.264 |
| The page stays on "Connecting to hub" in Safari with **Block All Cookies** on | Versions before 2.6.0 stopped when the browser refused them site storage | Update to 2.6.0 or later. The theme and a published camera are then not remembered across reloads |
| **This browser** camera will not start | Browsers only allow camera access on secure pages | Serve the hub over HTTPS or open it on `localhost`. [Deployment](deployment.md) covers both |
| A USB camera plugged into the host never appears | The container was not given it, or it was plugged in after the container started | Add a `devices:` entry for it and `docker compose up -d`. [Cameras plugged into the hub](cameras.md#cameras-plugged-into-the-hub) |
| Several USB cameras on one machine drop out or crawl | They share the bus, and an uncompressed feed can take most of it on its own | Prefer cameras that offer MJPEG, which PrintGuard asks for first, and spread them across separate USB controllers |
| A warning that a camera's feed has stalled | The camera is connected but no new frame has been checked for 30 seconds plus the fault grace period, because the feed froze or the model keeps failing on it | PrintGuard replaces the reader every minute on its own, and says so once a frame is checked again. If it keeps happening, check the camera and its network, and the log for "inference failed" |
| Adding a camera fails with "WebRTC source does not expose WHEP" | The URL is a WebRTC page with its own signalling | Use the camera's WHEP, MJPEG or RTSP URL. [Stream URLs](cameras.md#stream-urls) |
| An error reading "inference failed" on a camera | The model could not run on a frame | It is retried on the next frame. If it repeats, [send me the logs](#getting-logs-and-diagnostics) |
| A passed-in USB camera reads as offline after a restart | Its device was not there when the container started, usually unplugged, missing from `devices:` or renumbered by the host | Bring the device back and restart. The camera keeps its name and tuning. If it is gone for good, remove it under **Cameras** |
| A warning that a monitor "has no camera" | The camera it was bound to is not registered, usually after its printer was moved to another service or a passed-in camera was dropped with `PRINTGUARD_CAMERAS=off` | Pick a camera in the monitor's panel, or pass the camera in again and the monitor watches it. Until then the panel reads "no camera, so nothing is being watched" |
| An error ending "No space left on device" | The data volume is full, so kept frames and settings cannot be written | Detection, printer actions and notifications carry on, and the error repeats every 30 seconds. Free space on the `/data` volume |
| Feed plays but the risk score never moves | The monitor is in standby because its printer positively reports "not printing" | This is by design. See [failing safely](architecture.md#failing-safely) |
| A warning starting "Cannot tell whether the printer for" | The service reports a state PrintGuard cannot read and has never reported one it could, so the monitor cannot be stood down | This is by design. It keeps watching, a defect cannot pause the print, and the monitor's panel says which state it is getting. The warning goes out once the [fault grace period](notifications.md#faults-and-the-grace-period) has passed |
| Video is smooth for one camera and choppy for several | The host's sustainable capacity is shared across cameras | Check the **capacity** and **latency** readouts, then [Hardware](hardware.md#how-much-hardware-you-need) |

## Printers

| Symptom | Cause | Fix |
|---|---|---|
| Test fails with *all connection attempts failed* | The hub is in a container, so `localhost` is the container | Use `http://host.docker.internal:5000`, and make the service listen on `0.0.0.0` on Linux hosts. [Details](printers.md#networking-caveats) |
| Warnings that the printer and camera are offline while the printer is switched off | Before 2.6.0 a restart forgot the printer had been idle, so it watched and warned until the printer came back | Update to 2.6.0. A printer added while switched off still warns, since it has never reported a status |
| Printer shows `offline` but is printing | The hub cannot reach the service | Monitoring keeps running by design. Fix reachability, then the state clears itself |
| A command fails saying its address *redirects to* another, *which drops the POST* | The registered address answers with a 301 or 302, usually `http://` to `https://`, and a redirected command arrives as a read | Edit the printer and register the address named in the error. The same applies to an ntfy or webhook address. [Details](printers.md#networking-caveats) |
| ntfy alerts arrive without a picture, and the dashboard says the snapshot was refused | Your ntfy server has attachments switched off | Set `attachment-cache-dir` and `base-url` on the ntfy server. [Details](notifications.md) |
| A printer's webcam is registered but stays offline | The service reports a relative stream path and its web interface isn't on the port PrintGuard resolves it to | [Where a printer's webcam is read from](printers.md#where-a-printers-webcam-is-read-from) |
| Pause or cancel did nothing | The service rejected the action | The failure is in the alert, the dashboard error feed and the notification. Check the service's own logs |
| **Print** is greyed out, or a printer is missing from the list | The chosen printer is not idle, or the file is tagged for other printers, which leaves this one out of the list | Wait for the job to finish or cancel it, and tag this printer from the file's row. [Sending prints](printers.md#sending-prints) |
| A defect alert says the pause or cancel failed on a Bambu printer | Developer Mode is off, so the printer rejects commands from the LAN, or the access code is wrong | Enable Developer Mode on the printer, under Network in its settings, and check the access code under **Printers** |
| A Bambu printer refuses a file | It is not a sliced 3mf, or Developer Mode is off | Export the plate from Bambu Studio or Orca with the gcode included, and enable Developer Mode on the printer, under Network in its settings |

## Detection and alerts

| Symptom | Cause | Fix |
|---|---|---|
| Too many false alerts | The threshold is too low for your camera and lighting | Raise the threshold on that monitor, and raise the consecutive count so brief blips are ridden out. [Choosing values](monitoring.md#choosing-values) |
| Failures caught too late | The opposite | Lower the threshold or the consecutive count. Read the [risk history](monitoring.md#risk-history) to pick a value |
| Real failures barely move the score | The print is small in the frame, or off to one side of the square the model watches | Crop the camera to a square the print fills, see [tuning the camera](monitoring.md#tuning-the-camera) |
| No notifications arrive | **Push notifications** is off on that monitor, which is how a new monitor starts, or the channel itself is failing | Turn it on in the monitor's panel and send a test alert from **Settings**. Delivery failures raise an `error` event rather than passing silently |
| Warnings about a camera that keeps dropping out | The feed is unstable. One unstable episode is one warning, repeated every thirty minutes while it lasts, and the monitor's cooldown only covers defect alerts | Check the camera's own connection and, for RTSP or WHEP, that MediaMTX holds the pull. [Faults and the grace period](notifications.md#faults-and-the-grace-period) |
| A wireless camera still notifies when it drops out for a few seconds | The fault grace period is shorter than the camera takes to reconnect | Raise **Fault grace period** in the Alerts tab in Settings. It goes up to fifteen minutes, and the dashboard still shows the drop-out as it happens |
| A warning that the camera dropped out for a share of the last ten minutes | It reconnects quickly enough to clear the grace period every time, so the print is only being watched part of the time | Chase the connection rather than the notification. This one fires once for the unstable episode and again every thirty minutes while it lasts |
| Pushover alerts arrive during quiet hours | Priority defaults to High, which bypasses them, and it covers every notice including warnings and recoveries | Set it to Normal in the Alerts tab in Settings. [Channels](notifications.md#channels) |
| A reviewed print says it's queued | A [daily limit](feedback.md#limits) on training frames was hit, the inbox is full or closed, or it couldn't be reached | Nothing. The frames stay on the hub and send by themselves at the time shown, or press **Try now** |
| No prompt to review frames after a print | The monitor has no printer, so it only closes a print every 24 hours, or the prompt is switched off | Open the print from **Prints** on the monitor's detailed history page, or turn the prompt on in **Settings**, under **Advanced** |
| Home Assistant shows nothing, or a warning reads "Home Assistant MQTT unavailable" | The broker settings are wrong or the broker is down, or discovery is disabled in Home Assistant | Check the Home Assistant tab in Settings and the broker's own log. [Home Assistant](api.md#home-assistant) |

## Plugins

| Symptom | Cause | Fix |
|---|---|---|
| A plugin says it is waiting on permissions | It was installed, or updated to ask for more, and you haven't accepted what it asks for | Enable it in the Plugins tab in Settings and accept the list. [Plugins](plugins.md) |
| A plugin stopped on its own, with a reason | Its sandbox failed, hung or ran out of memory. PrintGuard disables a plugin rather than letting it affect anything else | The reason is on the plugin in the Plugins tab in Settings and in the log. Re-enable it once its author has fixed it |
| Installing from a repository fails | The path holds no `plugin.json`, the reference does not exist, or GitHub is rate-limiting an unauthenticated request | Check the path points at the plugin's own folder, and try again in a few minutes |
| A plugin installs as third party rather than verified | The catalogue vouches for different bytes, or does not list it at all | Expected for anything unreviewed. If it should be verified, its catalogue entry needs re-pinning |
| A plugin's requests fail | The host is not one its manifest declared, or **Reach the internet** is not granted. An address on your own network needs **Reach your own network** as well. A redirect is not followed either | All deliberate. Only its declared hosts are reachable |
| Nothing floats when a plugin's pop-out is pressed | The feed had not started, or the browser refused it | The toast names the reason. A feed that says "starting stream" has nothing to float yet, so wait for the picture |
| Locked out of the hub by a plugin | A plugin holding **Authorise every request** is refusing them, or it failed and the hub refuses everything until it is dealt with | Restart with `PRINTGUARD_PLUGINS=off` and remove it or enable it again. [Deployment](deployment.md#plugins) |

## Acceleration

| Symptom | Cause | Fix |
|---|---|---|
| An Intel GPU is not used | The standard image leaves the Intel GPU runtime out, the render device was not passed in, or the GPU predates Tiger Lake | Use the `latest-intel` tag and pass `--device /dev/dri`. **compute** reads `intel gpu` when the GPU is in use, and the log lists what the providers offered at start. [Intel GPU](hardware.md#intel-gpu) |
| PrintGuard keeps a shared host's processor busy | Detection runs as often as the hardware and the cameras allow | Lower **Detection rate** on each camera under **Cameras**. A defect takes longer to confirm at a lower rate. [Tuning the camera](monitoring.md#tuning-the-camera) |
| An NVIDIA GPU is not used | Missing Container Toolkit, the container started without the NVIDIA runtime, or the wrong tag | The log names the provider it could not load, then falls back to the CPU. [NVIDIA GPU](hardware.md#nvidia-gpu) |
| **compute** names a CPU in the Windows desktop app | The PC has no GPU driver, so there is nothing for DirectML or Windows ML to run on | Install the GPU's driver, then restart PrintGuard |
| **compute** reads `microsoft gpu` on Windows 11 24H2 or newer | DirectML is in use because Windows ML needs the Windows App Runtime 2.x. Versions before 2.5.0 stopped at a prompt to install it instead of starting | Run the x64 installer from [Windows App SDK downloads](https://learn.microsoft.com/en-us/windows/apps/windows-app-sdk/downloads), then restart PrintGuard |
| **compute** names a CPU on a machine with an accelerator | No provider was handed the accelerator, or it was offered and could not run the model. Versions before 2.6.0 failed to start in the second case | The log lists what the providers offered at start, and a warning in the dashboard and the log that a device `cannot run the model, so detection is not using it` names one that failed and why. [Execution providers by platform](hardware.md#execution-providers-by-platform) |
| Throughput differs from what you expected | Automatic mode picks whichever runtime benchmarks faster on the host | The choice is logged at start. Pin one in the Advanced tab in Settings |

## Getting logs and diagnostics

| Where | How |
|---|---|
| Container | `docker logs printguard`, or `docker compose logs -f` |
| Desktop app | A rotating log file in the app's data directory, path set by `LOG_FILE` |
| More detail | Set `LOG_LEVEL=DEBUG` for command traces and exception tracebacks |
| Everything at once | The bug icon in the header, then **Download logs**, which gives you a zip of the sanitised diagnostics bundle and both log tails, with credentials stripped |

The same bug dialog sends a report straight to me, anonymously, with the same
scrubbed contents, the address the dashboard is open at, your browser's user agent and window
size, and an optional email for follow-up. Nothing leaves the machine unless you
submit it or download it yourself.

If you are stuck, open an [issue](https://github.com/oliverbravery/PrintGuard/issues) and
attach that zip.
