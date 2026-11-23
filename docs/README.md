<div align="center">

# PrintGuard documentation

**Docs** · [Printers](printers.md) · [Cameras](cameras.md) · [Monitoring](monitoring.md) · [Notifications](notifications.md) · [Training frames](feedback.md) · [Hardware](hardware.md) · [Deployment](deployment.md) · [API & MCP](api.md) · [Plugins](plugins.md) · [Writing plugins](plugin-development.md) · [Architecture](architecture.md) · [Troubleshooting](troubleshooting.md)

</div>

Start with the [README](../README.md) to get PrintGuard installed. Everything after that lives here.

| Page | Read this if you want to |
|---|---|
| [Printers](printers.md) | Connect OctoPrint, Klipper, Creality, Elegoo, Prusa, Bambu Lab or Ultimaker, send prints or control temperatures |
| [Cameras](cameras.md) | Add a printer webcam, stream URL, USB webcam or your phone/laptop camera |
| [Monitoring](monitoring.md) | Dial in thresholds, crop and tune a camera, or read risk history |
| [Notifications](notifications.md) | Set up an alert channel or stop a flaky Wi-Fi camera from spamming disconnect alerts |
| [Training frames](feedback.md) | Share labelled frames after a print to help train future models, and see exactly what's sent |
| [Hardware](hardware.md) | Pick between the Standard, Light and Legacy models, choose an image tag or enable GPU/NPU acceleration |
| [Deployment](deployment.md) | Access your hub safely from outside your home network, harden it or back up its data |
| [API & MCP](api.md) | Connect Home Assistant over MQTT, or control PrintGuard from a script or AI agent with scoped tokens |
| [Plugins](plugins.md) | Install plugins and see how permissions and the sandbox keep them locked down |
| [Writing plugins](plugin-development.md) | Build your own plugin and submit it to the catalogue |
| [Architecture](architecture.md) | See how the engine, hub and dashboard fit together before changing the code |
| [Troubleshooting](troubleshooting.md) | Fix a dead feed, a failing printer connection or a port conflict |
| [Contributing](../CONTRIBUTING.md) | Set up a local dev environment, run tests or add a new printer or alert channel |

## A few terms used throughout these docs

- The **hub** is the PrintGuard server itself (either the Docker container or the desktop app). The **dashboard** is the web interface it serves.
- A **camera** is any video source and a **printer** is a connection to a print service. A **monitor** links one camera and (optionally) one printer together, along with its detection thresholds and alert actions.
- Any `docker run` commands assume the default image. If you're using Docker Compose, apply the same flags in [`docker-compose.yaml`](../docker-compose.yaml).
