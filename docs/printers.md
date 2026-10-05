<div align="center">

# Printers

[Docs](README.md) · **Printers** · [Cameras](cameras.md) · [Monitoring](monitoring.md) · [Notifications](notifications.md) · [Training frames](feedback.md) · [Hardware](hardware.md) · [Deployment](deployment.md) · [API & MCP](api.md) · [Plugins](plugins.md) · [Writing plugins](plugin-development.md) · [Architecture](architecture.md) · [Troubleshooting](troubleshooting.md)

</div>

Connecting a print service, sending it files and setting its temperatures.

- [How the pieces fit](#how-the-pieces-fit)
- [Register a printer](#register-a-printer)
- [Supported print services](#supported-print-services)
- [Sending prints](#sending-prints)
- [Temperatures and preheat](#temperatures-and-preheat)
- [Networking caveats](#networking-caveats)

## How the pieces fit

A camera and a printer are registered once each, then bound together by a monitor. One
printer connection can back several monitors, and a monitor without a printer still watches
and alerts. Each of the three carries a name you can change later, from **Edit** in the camera
or printer registry and from a monitor's settings panel.

```mermaid
flowchart LR
    cam["Camera<br/>a video source"] --> mon
    prn["Printer<br/>a print service connection"] -.-> mon
    mon["Monitor<br/>thresholds + defect response"] --> act["Alert · Pause · Cancel"]
    prn -. "job state gates inference" .-> mon
```

The dotted lines are the optional parts. Bind no printer and PrintGuard still alerts you, it
just cannot stop the print. [Cameras](cameras.md) covers the video side,
[monitoring](monitoring.md) the thresholds and [notifications](notifications.md) the alert
channels.

## Register a printer

Open the printer registry, choose the service, fill in the form and press **Test connection**
before saving. Then bind it to a monitor and choose whether a sustained defect alerts you, pauses the
print or cancels it.

Linked printers report job name, progress, temperatures and state on every monitor that uses
them, and they gate inference. Monitoring runs while a printer reports it is printing and stands
down when it reports idle, paused or an error, so an idle printer costs nothing. Losing contact
or a state the adapter cannot read keeps whatever the printer last reported, meaning a printer
switched off after a print stays in standby while one that drops off mid-print keeps being
watched and warns you. See [failing safely](architecture.md#failing-safely).

## Supported print services

| Service | Authentication | [Exposes a camera](cameras.md#printer-cameras) |
|---|---|---|
| [OctoPrint](https://octoprint.org) | API key | Yes, its webcam stream |
| [Klipper via Moonraker](https://moonraker.readthedocs.io) | Optional API key | Yes, its configured webcams |
| [Elegoo](https://github.com/ELEGOO-3D/elegoo-link) | Access code, or Moonraker API key | Centauri chamber camera, or Moonraker's configured webcams |
| [Prusa via PrusaLink](https://help.prusa3d.com/guide/wi-fi-and-prusa-connect-link-setup-core-one-mk4-s-mk3-9-mk3-5-xl-mini_413293) | HTTP Digest, user `maker` | No local stream |
| [Bambu Lab](https://github.com/Doridian/OpenBambuAPI) | Access code and serial | Chamber camera |

<details>
<summary><b>Bambu Lab</b>: LAN Only Mode and Developer Mode</summary>

Bambu printers speak MQTT over TLS rather than HTTP.

1. On the printer, enable **LAN Only Mode**, then **Developer Mode** under
   Network in Settings. This opens the MQTT channel.
2. Note the **access code** shown there, and the **serial number** under Device in Settings.
3. Register the printer with its IP address, serial number and access code.

The chamber camera is registered automatically: RTSP on the X1 and H2 series, or the
proprietary port 6000 protocol on the A1 and P1 series. The form links Bambu's
[Enable LAN Mode](https://wiki.bambulab.com/en/knowledge-sharing/enable-lan-mode) guide.

PrintGuard holds one connection to the printer and reads the reports it pushes. A printer that
pushes nothing for a minute is reconnected and shown offline until it reports again. With
Developer Mode off the printer still reports its state but rejects a pause, cancel, heater
target or print start, and PrintGuard reports that command as failed.

</details>

<details>
<summary><b>Elegoo</b>: two families, Centauri and Neptune/OrangeStorm</summary>

Choose the family that matches your printer:

**Centauri** covers the Centauri Carbon and Centauri Carbon 2. PrintGuard detects which
local protocol the printer speaks and registers its chamber camera automatically.

- Carbon 2: enable **LAN Only Mode** in its network settings and use the access code shown
  there.
- Original Carbon: the IP address is enough.

**Neptune/OrangeStorm** covers the Neptune 4 Pro, Plus and Max, the OrangeStorm Giga, and
any other Elegoo printer running Moonraker. PrintGuard uses the stock Moonraker service on
port `7125`, accepts an API key if you set one and registers the webcams Moonraker lists.

All state, camera and control traffic stays between PrintGuard and the printer on your LAN.
Elegoo's cloud is never involved.

</details>

<details>
<summary><b>Prusa</b>: PrusaLink, not PrusaConnect</summary>

Prusa printers connect over **PrusaLink**, the API that runs on the printer itself on the
MK4, MK4S, MK3.9, MK3.5, MINI, XL and CORE One, or on a Raspberry Pi attached to an MK3 or
MK2.5. It authenticates with HTTP Digest.

1. Enable **PrusaLink** on the printer under Settings, Network, then PrusaLink.
2. Register it with its URL and the password shown there. The username is always `maker`.

PrusaConnect is not used, so no frames or job data leave hardware you own. PrusaLink's
webcam feature pushes snapshots to PrusaConnect rather than serving a local video stream, so
if the printer has a camera, add it separately as a [stream URL](cameras.md#stream-urls).

</details>

## Sending prints

The print library holds sliced files on the hub. Open **Prints** in the header and drop files in
or browse for them.

![The print library: three sliced files with their slicer, print time and filament, with the printers each is tagged for](assets/prints.png)

Each one opens in a panel that draws its toolpath on your device before
the file is uploaded, where you can name it, tag it and correct its first layer nozzle and bed
temperatures. The panel sends the start and end of the file to the hub to read its print time,
filament and temperatures. Every other print temperature the slicer set moves by the same amount, while the
temperatures a start gcode probes or wipes at stay put. A file whose slicer lists no print
temperatures has every one of its set-points moved. Binary gcode keeps the temperatures it
was sliced with.

Each file keeps the preview, estimated time, filament and printer model its slicer wrote into it.
Cura and a few others write no preview, so your browser draws one and adds it to the gcode as
it's uploaded. A file uploaded through the REST API without a preview shows its format
instead. Open a file to orbit its toolpath in 3D, layer by layer.

![A sliced vase in the 3D viewer with a layer slider, its print time, filament and temperatures](assets/print-viewer.png)

Tag a file with the printers it was sliced for and it can only start on one of those. A tag is
only offered for a printer whose service takes the format. A file
with no tags can go to any printer whose service takes the format. Either way the printer has to
report idle at the moment you press **Print**, so nothing lands on top of a running job.

| Service | Takes | How it starts |
|---|---|---|
| OctoPrint | `.gcode`, `.gco`, `.g` | Uploaded to local storage, selected and printed |
| Klipper via Moonraker | `.gcode`, `.gco`, `.g` | Uploaded to the gcodes root and printed |
| Elegoo | `.gcode` | Centauri: uploaded to internal storage and started. Neptune and OrangeStorm: through Moonraker |
| Prusa via PrusaLink | `.gcode`, `.bgcode` | Put onto the first writable storage, the USB stick or local storage on a Raspberry Pi, and printed after upload |
| Bambu Lab | `.3mf` sliced by Bambu Studio or Orca | Uploaded to the printer's storage over FTPS, then the first plate is started over MQTT |

A file the service stores but doesn't start, or a start the printer refuses, is reported as a
failed print.

A file is sent under its library name, cut to 60 characters with anything outside plain letters,
digits, dots and dashes turned into `_`. Rename it first if the printer's own file list matters
to you. PrusaLink replaces a file of the same name already on the printer. A file can be up to
512 MB. Binary gcode has no 3D view and no drawn preview, since its toolpath is
compressed, so it shows the preview PrusaSlicer embedded and nothing else. Its print time and filament can
be blank too, where PrusaSlicer compressed them.

A Bambu print uses the settings sliced into the file, with bed levelling on, flow and vibration
calibration off, and filament from the external spool or the first AMS slot. Starting a 3mf
needs Developer Mode, the same switch the MQTT connection needs. A project exported without its
gcode is refused at upload.

Files live in the data directory under `prints/`, so they survive a restart and travel with the
`/data` volume.

## Temperatures and preheat

A linked printer's nozzle and bed temperatures sit on its monitor's tile and in the monitor's
panel, where a running print also gets a progress bar and the time left. The panel takes a
target for either heater, applied on Enter or when you leave the field, and a row of preheat presets that set both at once.
**Edit** beside them changes the presets, which every printer shares, and **Off** turns every
heater off.

| Service | Reads temperatures | Sets targets |
|---|---|---|
| OctoPrint | Yes | Yes, through its tool and bed endpoints, for the first nozzle |
| Klipper via Moonraker | Yes | Yes, with `SET_HEATER_TEMPERATURE` |
| Elegoo | Yes | Yes, on both families |
| Prusa via PrusaLink | Yes | No, PrusaLink has no endpoint for it |
| Bambu Lab | Yes | Yes, as the `M104` and `M140` lines Bambu Studio sends |

A target is capped at 350 °C for the nozzle and 150 °C for the bed, and the printer's own
firmware applies its limits on top. Temperatures refresh with the printer's state, every five
seconds.

## Networking caveats

The hub makes every request to a print service itself, so the address you register has to be
one the hub can reach, not one your browser can. The browser never calls the printer, so an
`http://` printer works from a hub you open over HTTPS.

### Running in Docker

The hub reaches printer services from inside the container, so
`localhost` means the container, not your host, and a URL like `http://localhost:5000`
fails with *all connection attempts failed*. Use `http://host.docker.internal:5000`. The
shipped [`docker-compose.yaml`](../docker-compose.yaml) maps that name for you. On a Linux
host the print service must also listen on `0.0.0.0` rather than loopback only.

### The desktop app

The app runs on your computer rather than in a container, so `http://localhost:5000` reaches
a print service on the same machine, and anything else is its LAN address.

[Troubleshooting](troubleshooting.md) has more symptoms and fixes.
