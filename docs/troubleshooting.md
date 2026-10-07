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
- [The API](#the-api)
- [Acceleration](#acceleration)
- [Getting logs and diagnostics](#getting-logs-and-diagnostics)

## Starting up

| Symptom | Cause | Fix |
|---|---|---|
| A port already in use at start, `8000` or `8554` | Another PrintGuard already holds the port, often a desktop app or a container you forgot | Find the holder with `lsof -nP -iTCP:8554 -sTCP:LISTEN` on macOS or Linux, or `netstat -ano \| findstr 8554` on Windows, then stop it. |
| The page is one line of text starting "PrintGuard refused a request for", with a `403` | You opened the hub at a name it doesn't know, such as a domain behind a proxy or tunnel. From 2.6.0 it only answers to IP addresses, local names and names you list | Add the `PRINTGUARD_ORIGINS` line the message gives to the hub's environment and restart it. [Host and origin checking](deployment.md#host-and-origin-checking) |
| The page stays on the boot screen, reading "Connecting to hub" and then "The hub is not answering" | The engine WebSocket cannot connect, usually a proxy that does not forward WebSockets, or one that rewrites or strips `Origin`. From 2.6.0 a WebSocket with no `Origin` is refused | Check the proxy forwards upgrade headers and `Origin`, then see [host and origin checking](deployment.md#host-and-origin-checking) |
| A name listed in `PRINTGUARD_ORIGINS` still gets the `403`, and the log says the entry `is ignored because it has no scheme` or `is ignored because it is not an address` | The entry was written as a bare name, such as `hub.example.com`, or with a scheme other than `http` or `https`, a port that is not a number or an unclosed `[` | Write it with its `http` or `https` scheme and a real port, `https://hub.example.com`, and restart. [Host and origin checking](deployment.md#host-and-origin-checking) |
| The hub starts with no cameras, printers or settings, and the log says `state.json is damaged` | The state file would not parse, usually after a full disk or a power cut, or it parsed to something the hub never saves, such as a section of the wrong type. The hub moved it to `state.json.corrupt` in the [data directory](deployment.md#your-data-and-backups) and started empty. If that file is damaged in turn the hub keeps it as `state.json.corrupt.1` and so on, and never replaces the first | Stop the hub and put a backup in place as `state.json`, or repair the kept file and rename it back. API tokens are in that file too, so until then the API is back to open reads |
| The hub stops at start and the log says `state.json could not be read`, `could not be moved aside` or `could not be created` | The data directory or the file belongs to another user, usually after a restore or a change of the container's user. The log names the directory and its owner | Give the data directory back to [the user the hub runs as](deployment.md#running-the-container-as-your-own-user) and start it again |
| A camera, printer, monitor, print or plugin is gone after a start, and the log and a startup warning on the dashboard say `could not be read and was dropped` | Its entry in `state.json` was not one the hub could read, usually after the file was edited by hand. The hub left it out and loaded the rest, and the next save drops it from the file. A setting that couldn't be read is put back to its default instead, with a warning that says `was reset` | Add it again in the dashboard, or stop the hub and put a backup of `state.json` in place |
| First launch of the Windows desktop app is blocked | The Windows build is unsigned | Choose **More info** and then **Run anyway** |
| The desktop app opens to "PrintGuard could not start" | Its server did not start | The window says what failed and shows the end of the log. [Logs](#getting-logs-and-diagnostics) has where the full one is kept |
| The desktop app opens to "PrintGuard is still starting" | Its server has taken more than 30 seconds to come up, which a first launch on Windows can while Windows ML installs a graphics provider. Versions before 2.6.0 showed "PrintGuard could not start" here | Leave it open. The dashboard replaces the page once the server answers. If it stays for minutes, the end of the log says what it is waiting on |
| The Windows desktop app closes straight away without a window | Without a GPU driver, as in most virtual machines, Windows offers its Basic Render Driver as a GPU and versions before 2.5.0 crashed running the model on it | Update to 2.5.0 or later, or install the GPU driver |
| The Windows desktop app shows its tray icon but **Open PrintGuard** does nothing | Windows marks every file of a zip downloaded in a browser as from the internet, and versions before 2.6.0 could not load the window with that mark | Update to 2.6.0 or later. On an older version open `http://localhost:8000` in a browser, or right-click the zip, choose **Properties**, tick **Unblock** and extract it again |
| The Windows desktop app opens the dashboard in your browser instead of its own window | The PC has no WebView2 runtime, which the window is drawn with. Versions before 2.6.0 showed a blank white window | Install the Evergreen runtime from [Microsoft's WebView2 page](https://developer.microsoft.com/microsoft-edge/webview2/), or carry on in the browser |
| The desktop app shows "PrintGuard could not start" and the log on that page says `another program holds port 8000` or `another program answers on localhost:8000` | Another program, not PrintGuard, is serving on the hub's port. Versions before 2.6.0 on Windows started anyway and could show that program's page | Quit the other program, or start PrintGuard with `PORT` set to a free port |
| Opening the desktop app only opens a dashboard in the browser | PrintGuard is already running on that port, as another copy of the app or as a container, or a copy is still starting. The new copy opens that dashboard and exits. Versions before 2.6.0 showed "PrintGuard could not start" instead. On macOS, opening the app again from Finder or the Dock shows its window | Use **Open PrintGuard** in the tray or menu bar icon for the app window. A browser tab that cannot connect means the first copy is still starting, so reload it in a minute |
| The Windows desktop app shows "PrintGuard could not start" and the log ends in `Immediate exit requested: 'video=dummy'` | 2.4.1 treated the end of its camera listing as a failure | Update to 2.5.0 or later |
| The website has no live demo, or a `#local` bookmark opens the landing page | Local mode, which ran PrintGuard in a browser tab, was removed in 2.5.0 | Install the desktop app or the Docker image from the [quick start](../README.md#quick-start) |
| Container restarts repeatedly | Usually a `/data` volume the hub's user can't read or write | Check the volume mount and its owner, then read `docker logs printguard`, or `docker compose logs` if you started it with compose |

## Cameras and video

| Symptom | Cause | Fix |
|---|---|---|
| Tile reads **no signal** | The source is unreachable from the hub, or it stopped producing frames | Open the stream URL from the machine running the hub, not from your laptop. In Docker, remember `localhost` means the container, so see [networking caveats](printers.md#networking-caveats). [Stream URLs](cameras.md#stream-urls) lists what the hub can pull |
| A USB, MJPEG or Bambu A1 or P1 camera has no live view while its monitor still scores frames | PrintGuard re-encodes these cameras into its bundled MediaMTX for the live view, and MediaMTX is not running. On the desktop app that is usually another program holding port `8554`, `1935`, `8888` or `9997`. Versions before 2.6.0 showed the camera as offline and stopped detection | The dashboard and the log have one warning that the camera's `live view unavailable`. Free the port and the live view comes back within a few seconds, with no restart |
| Camera is **offline** in the registry but the feed works elsewhere | The address or credentials it was added with no longer work, or it has no decoder for the stream. The reason it failed to open, such as `no decoder for this stream` or that its last capture stopped answering and PrintGuard needs restarting to free it, is on its entry in the registry and in the camera rail | Check the URL plays from the machine running the hub. A camera's address can't be edited, so remove it and add it again. RTSP sources are pulled by MediaMTX, so it must reach them too |
| Adding a camera fails with `no frames from camera` and an id | Nothing arrived within 25 seconds, usually a wrong URL, `localhost` inside Docker or credentials the camera refuses. A stream only registers once it has delivered a frame, and the text after the colon is the reason, without credentials | Open the URL from the machine running the hub, then add it again. [Stream URLs](cameras.md#stream-urls) |
| Adding a camera fails with `no decoder for this stream`, or a test image with `could not decode image` | The address serves something FFmpeg can read but not decode as video, such as an SVG | Use the camera's video or MJPEG address |
| Adding a camera fails with `PrintGuard can't use that address` | The bundled MediaMTX refused the address. The reason follows, with credentials removed | Correct the scheme, host or path it names |
| A feed shows **Tap to play** | The browser refused to start the video by itself, which iOS does in Low Power Mode. Versions before 2.6.0 stayed on "starting stream" | Tap it. Detection runs on the hub and doesn't depend on the feed playing |
| A **This browser** camera is monitored but its feed stays on "starting stream" | The browser records VP8, which the live view can't play | Publish from Chrome, Edge or Safari, which record H.264 |
| The page stays on "Connecting to hub" in Safari with **Block All Cookies** on | Versions before 2.6.0 stopped when the browser refused them site storage | Update to 2.6.0 or later. The theme and a published camera are then not remembered across reloads |
| **This browser** camera will not start | Browsers only allow camera access on secure pages | Serve the hub over HTTPS or open it on `localhost`. [Deployment](deployment.md) covers both |
| A USB camera plugged into the host never appears | The container was not given it, or it was plugged in after the container started | Add a `devices:` entry for it and `docker compose up -d`. [Cameras plugged into the hub](cameras.md#cameras-plugged-into-the-hub) |
| Several USB cameras on one machine drop out or crawl | They share the bus, and an uncompressed feed can take most of it on its own | Prefer cameras that offer MJPEG, which PrintGuard asks for first on Linux, and spread them across separate USB controllers |
| A warning that a camera's feed has stalled | The camera is connected but no new frame has been checked for 30 seconds plus the fault grace period, because the feed froze or the model keeps failing on it | PrintGuard replaces the reader every minute on its own, and announces the recovery once the feed has held for a minute, or longer after repeated relapses up to 15 minutes. If it keeps happening, check the camera and its network, and the log for "inference failed" |
| Adding a camera fails with "WebRTC source does not expose WHEP" | The URL is a WebRTC page with its own signalling | Use the camera's WHEP, MJPEG or RTSP URL. [Stream URLs](cameras.md#stream-urls) |
| An error reading "inference failed" on a camera | The model could not run on a frame | It is retried on the next frame. If it repeats, [send me the logs](#getting-logs-and-diagnostics) |
| A passed-in USB camera reads as offline after a restart | Its device was not there when the container started, usually unplugged, missing from `devices:` or renumbered by the host. Docker may refuse to start the container at all while a `devices:` path is missing | Bring the device back and restart. The camera keeps its name and tuning. If it is gone for good, remove it under **Cameras** |
| A warning that a monitor "has no camera" | The camera it was bound to is not registered, usually after its printer was moved to another service or a passed-in camera was dropped with `PRINTGUARD_CAMERAS=off` | Pick a camera in the monitor's panel, or pass the camera in again and the monitor watches it. Until then the panel reads "no camera, so nothing is being watched" |
| An error ending "No space left on device" | The data volume is full, so kept frames and settings cannot be written | Detection, printer actions and notifications carry on, and the error repeats every 30 seconds. Free space on the `/data` volume |
| Feed plays but the risk score never moves | The monitor is in standby because its printer positively reports "not printing" | This is by design. See [failing safely](architecture.md#failing-safely) |
| A warning starting "Cannot tell whether the printer for" | The monitor is watching and its printer can't be read. Usually the hub can't reach the service or its key was rejected, and sometimes the service reports a state PrintGuard doesn't know | This is by design. It keeps watching, a defect cannot pause the print, and the monitor's panel says what it is getting from the printer. Fix the connection under **Printers**. The warning goes out once the [fault grace period](notifications.md#faults-and-the-grace-period) has passed |
| Video is smooth for one camera and choppy for several | The host's sustainable capacity is shared across cameras | Check the **capacity** and **latency** readouts, then [Hardware](hardware.md#how-much-hardware-you-need) |

## Printers

| Symptom | Cause | Fix |
|---|---|---|
| Test fails with *all connection attempts failed* | The hub is in a container, so `localhost` is the container | Use `http://host.docker.internal:5000`, and make the service listen on `0.0.0.0` on Linux hosts. [Details](printers.md#networking-caveats) |
| Warnings that the printer and camera are offline while the printer is switched off | Before 2.6.0 a restart forgot the printer had been idle, so it watched and warned until the printer came back | Update to 2.6.0. A printer added while switched off still warns, since it has never reported a status |
| Printer shows `offline` but is printing | The hub cannot reach the service, or the service rejected its key or password | Monitoring keeps running by design. The log has the reason the read failed, and **Test connection** names a rejected key. Fix it, then the state clears itself |
| **Test connection** says the service *rejected the API key*, or *rejected the username or password* | OctoPrint, Moonraker or PrusaLink answered and turned the credentials down. Moonraker says the same when no key was entered, and versions before 2.6.0 only showed the printer as offline | Copy the key or password from the service again and save the printer. For Moonraker you can add the hub's address to `trusted_clients` instead, as [printers](printers.md#supported-print-services) describes |
| **Test connection** says the service *did not answer like its API*, or *PrusaLink answered HTTP* and a code | The address answers, but not as OctoPrint, Moonraker or PrusaLink do, usually a wrong port or a proxy in front. The log says `could not be read` with the same reason | Register the address of the service itself |
| A Bambu printer shows `offline`, and **Test connection** says it *has sent nothing, so check the serial number* | The printer accepted the access code, but the serial number doesn't match, so nothing is published for it. A switched-off printer fails differently, with the connection refused or timed out | Copy the serial number again from Settings, then Device on the printer |
| Saving or testing a printer fails with *send API key again, since a stored secret is only kept for the address it was saved with* | The address changed and the key or password field was left blank. The same applies to the MQTT broker's host or port and its password | Type the key or password again, then save. [Register a printer](printers.md#register-a-printer) |
| Saving or testing a printer fails saying it *needs* a field *filled in* | A field the service can't be reached without was left blank | Fill in the field the message names |
| A printer test, a command or an alert fails saying its address *redirects to* another | The registered address answers with a redirect, usually `http://` to `https://`. A redirect is never followed, so a key or a command can't be sent on to an address you didn't register | Edit the printer or the channel and register the address named in the error, including a Discord webhook or an ntfy address. [Details](printers.md#networking-caveats) |
| ntfy alerts arrive without a picture, and the dashboard says the snapshot was refused | Your ntfy server has attachments switched off | Set `attachment-cache-dir` and `base-url` on the ntfy server. [Details](notifications.md) |
| A printer's webcam never appears under **Cameras**, with a warning starting "Could not open the camera" or "Could not list the cameras" | A webcam that won't open isn't registered. Usually the service reports a relative stream path and its web interface isn't on the port PrintGuard resolves it to, such as an OctoPrint container published as `5000:80` | Fix the address as [where a printer's webcam is read from](printers.md#where-a-printers-webcam-is-read-from) describes, then press **Refresh** under **Cameras**. Printers are only asked for their webcams when one is added or edited and on Refresh |
| Pause or cancel did nothing | The service rejected the action | The failure is in the alert, the dashboard error feed and the notification. Check the service's own logs |
| **Print** is greyed out, or a printer is missing from the list | The chosen printer is not idle, the file is tagged for other printers, or the printer's service doesn't take the file's format. Either of the last two leaves it out of the list | Wait for the job to finish or cancel it, and tag this printer from the file's row. [Sending prints](printers.md#sending-prints) |
| A defect alert says the pause or cancel failed on a Bambu printer | Developer Mode is off, so the printer rejects commands from the LAN, or the access code is wrong | Enable Developer Mode on the printer, under Network in its settings, and check the access code under **Printers** |
| A Bambu printer refuses a file | It is not a sliced 3mf, or Developer Mode is off | Export the plate from Bambu Studio or Orca with the gcode included, and enable Developer Mode on the printer, under Network in its settings |

## Detection and alerts

| Symptom | Cause | Fix |
|---|---|---|
| Too many false alerts | The threshold is too low for your camera and lighting | Raise the threshold on that monitor, and raise the consecutive count so brief blips are ridden out. [Choosing values](monitoring.md#choosing-values) |
| Failures caught too late | The opposite | Lower the threshold or the consecutive count. Read the [risk history](monitoring.md#risk-history) to pick a value |
| Real failures barely move the score | The print is small in the frame, or off to one side of the square the model watches | Crop the camera to a square the print fills, see [tuning the camera](monitoring.md#tuning-the-camera) |
| Saving or testing an alert channel fails saying it *needs* a field *filled in* | From 2.6.0 a channel with a blank field it can't send without, such as the ntfy topic URL or either Pushover key, is refused | Fill in the field the message names. [Channels](notifications.md#channels) |
| No notifications arrive | **Push notifications** is off on that monitor, which is how a new monitor starts, or the channel itself is failing | Turn it on in the monitor's panel and send a test alert from **Settings**. Delivery failures raise an `error` event rather than passing silently |
| Warnings about a camera that keeps dropping out | The feed is unstable. One unstable episode is one warning, repeated every thirty minutes while it lasts, and the monitor's cooldown only covers defect alerts | Check the camera's own connection and, for RTSP or WHEP, that MediaMTX holds the pull. [Faults and the grace period](notifications.md#faults-and-the-grace-period) |
| A wireless camera still notifies when it drops out for a few seconds | The fault grace period is shorter than the camera takes to reconnect | Raise **Fault grace period** in the Alerts tab in Settings. It goes up to fifteen minutes, and the dashboard still shows the drop-out as it happens |
| A warning that the camera dropped out for a share of the last ten minutes | It reconnects quickly enough to clear the grace period every time, so the print is only being watched part of the time | Chase the connection rather than the notification. This one fires once for the unstable episode and again every thirty minutes while it lasts |
| Pushover alerts arrive during quiet hours | Priority defaults to High, which bypasses them, and it covers every defect alert and fault warning. Recoveries go at Normal at most | Set it to Normal in the Alerts tab in Settings. [Channels](notifications.md#channels) |
| A reviewed print says it's queued | A [daily limit](feedback.md#limits) on training frames was hit, the inbox is full or closed, or it couldn't be reached | Nothing. The frames stay on the hub and send by themselves at the time shown, or press **Try now** |
| No prompt to review frames after a print | The monitor has no printer, so it only closes a print every 24 hours, or the prompt is switched off | Open the print from **Prints** on the monitor's detailed history page, once it has finished, since a print still running isn't listed, or turn the prompt on in **Settings**, under **Advanced** |
| Home Assistant shows nothing, or a warning reads "Home Assistant MQTT unavailable" | The broker settings are wrong or the broker is down, or discovery is disabled in Home Assistant | Check the Home Assistant tab in Settings and the broker's own log. [Home Assistant](api.md#home-assistant) |

## Plugins

| Symptom | Cause | Fix |
|---|---|---|
| A plugin says it is waiting on permissions | It was installed, or updated to ask for more, and you haven't accepted what it asks for | Enable it in the Plugins tab in Settings and accept the list. [Plugins](plugins.md) |
| A plugin stopped on its own, with a reason | Its sandbox failed, hung or ran out of memory. PrintGuard disables a plugin rather than letting it affect anything else | The reason is on the plugin in the Plugins tab in Settings and in the log. Re-enable it once its author has fixed it |
| Installing from a repository fails | The error names the cause. `no plugin.json at` means the path isn't the plugin's own folder. `GitHub could not resolve` means the repository, branch or tag wasn't found, or with a `403` or `429` in the brackets that GitHub is rate-limiting the hub's address | Check the path and the reference, or try again in a few minutes |
| Installing fails saying the plugin `only runs on` something else | Its manifest lists the [platforms](plugin-development.md#platforms) it runs on, and this hub isn't one | Nothing to fix on your side. A plugin for the desktop app won't install on Docker |
| Installing fails saying a file `takes the plugin past 12288 KB of files` | The files a plugin ships may come to 12 MB, and one file to 4 MB | Ask its author for a smaller bundle |
| A plugin that signs you in to a service is gone after updating to 2.6.0, and the log and a startup warning say `A saved plugin` and `could not be read and was dropped` | Its sign-in addresses were plain `http`, which 2.6.0 refuses | Install a version of the plugin that signs in over `https` |
| A plugin installed before 2.6.0 can't reach an address with a capital letter in its path, such as Telegram's `/bot*/sendMessage` | The pattern was stored in lower case when the plugin was installed | Reinstall the plugin |
| A plugin installs as third party rather than verified | The catalogue vouches for different bytes, or does not list it at all | Expected for anything unreviewed. If it should be verified, its catalogue entry needs re-pinning |
| A plugin's requests fail | The host is not one its manifest declared, or **Reach the internet** is not granted. An address on your own network needs **Reach your own network** as well. A redirect is not followed either | All deliberate. Only its declared hosts are reachable |
| Nothing floats when a plugin's pop-out is pressed | The feed had not started, or the browser refused it | The toast names the reason. A feed that says "starting stream" has nothing to float yet, so wait for the picture |
| Locked out of the hub by a plugin | A plugin holding **Authorise every request** is refusing them, or it failed and the hub refuses everything until it is dealt with | Restart with `PRINTGUARD_PLUGINS=off` and remove it or enable it again. [Deployment](deployment.md#plugins) |

## The API

| Symptom | Cause | Fix |
|---|---|---|
| Editing a printer, a channel or the broker answers `400` with `send` a field `again` | The edit changed the address and left a stored key or password out. A stored secret is only kept for the address it was saved with | Send the secret with the new address. [The resource model](api.md#the-resource-model) |
| Removing an id that doesn't exist answers `400`, not `404` | From 2.6.0 removing a camera, printer, monitor, print or token nothing matches is refused. It used to answer as if it had worked | Read the list again for the id. [REST API](api.md#rest-api) |
| Registering a printer or saving a channel answers `400` saying it `needs` a field `filled in` | A required field is blank | Send the field the message names |

## Acceleration

| Symptom | Cause | Fix |
|---|---|---|
| An Intel GPU is not used | The standard image leaves the Intel GPU runtime out, the render device was not passed in, or the GPU predates Tiger Lake | Use the `latest-intel` tag and pass `--device /dev/dri`. **compute** reads `intel gpu` when the GPU is in use, and the log lists what the providers offered at start. [Intel GPU](hardware.md#intel-gpu) |
| PrintGuard keeps a shared host's processor busy | Detection runs as often as the hardware and the cameras allow | Lower **Detection rate** on each camera under **Cameras**. A defect takes longer to confirm at a lower rate. [Tuning the camera](monitoring.md#tuning-the-camera) |
| An NVIDIA GPU is not used | Missing Container Toolkit, the container started without the NVIDIA runtime, or the wrong tag | The log names the provider it could not load, then falls back to the CPU. [NVIDIA GPU](hardware.md#nvidia-gpu) |
| **compute** names a CPU in the Windows desktop app | The PC has no GPU driver, so there is nothing for DirectML or Windows ML to run on | Install the GPU's driver, then restart PrintGuard |
| **compute** reads `microsoft gpu` on Windows 11 24H2 or newer | DirectML is in use because Windows ML needs the Windows App Runtime 2.x. Versions before 2.5.0 stopped at a prompt to install it instead of starting | Run the x64 installer from [Windows App SDK downloads](https://learn.microsoft.com/en-us/windows/apps/windows-app-sdk/downloads), then restart PrintGuard |
| **compute** names a CPU on a machine with an accelerator | No provider was handed the accelerator, or it was offered and could not run the model. Versions before 2.6.0 failed to start in the second case | The log lists what the providers offered at start, and a warning that a device `cannot run the model, so detection is not using it` names one that failed and why. The dashboard shows it as a startup warning, once per page load, and it is kept until the hub restarts. [Execution providers by platform](hardware.md#execution-providers-by-platform) |
| Throughput differs from what you expected | Automatic mode picks whichever runtime benchmarks faster on the host | The choice is logged at start. Pin one in the Advanced tab in Settings |

## Getting logs and diagnostics

| Where | How |
|---|---|
| Container | `docker logs printguard`, or `docker compose logs -f` |
| Desktop app | `printguard.log` in the app's [data directory](deployment.md#your-data-and-backups), rotated at 2 MB with two older ones kept as `.1` and `.2` |
| More detail | Set `LOG_LEVEL=DEBUG` for command traces, printer state changes and exception tracebacks |
| Everything at once | The bug icon in the header, then **Download logs**, which gives you a zip of the sanitised diagnostics bundle and both log tails, with credentials stripped |

The same bug dialog sends a report straight to me, anonymously, with the same
scrubbed contents, the address the dashboard is open at, your browser's user agent and window
size, and an optional email for follow-up. Nothing leaves the machine unless you
submit it or download it yourself.

If you are stuck, open an [issue](https://github.com/oliverbravery/PrintGuard/issues) and
attach that zip.
