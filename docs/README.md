<div align="center">

# PrintGuard documentation

**Docs** · [Printers](printers.md) · [Cameras](cameras.md) · [Monitoring](monitoring.md) · [Notifications](notifications.md) · [Training frames](feedback.md) · [Hardware](hardware.md) · [Deployment](deployment.md) · [API & MCP](api.md) · [Plugins](plugins.md) · [Writing plugins](plugin-development.md) · [Architecture](architecture.md) · [Troubleshooting](troubleshooting.md)

</div>

Start at the [README](../README.md) to install PrintGuard. These pages cover everything after that.

| Page | Read it when you want to |
|---|---|
| [Printers](printers.md) | Connect OctoPrint, Klipper, Elegoo, Prusa or Bambu Lab, send it a print or set its temperatures |
| [Cameras](cameras.md) | Add a printer webcam, a stream URL, a USB camera or a phone |
| [Monitoring](monitoring.md) | Tune a monitor's thresholds, frame its camera and read its risk history |
| [Notifications](notifications.md) | Set up an alert channel, or quieten a camera that keeps dropping out |
| [Training frames](feedback.md) | Send labelled frames to help train the model, and see what's sent and the limits |
| [Hardware](hardware.md) | Pick an image variant, understand the model runtimes, and use a GPU or NPU |
| [Deployment](deployment.md) | Reach a hub from outside your LAN without exposing it, harden it and back it up |
| [API & MCP](api.md) | Drive the hub from a script, an agent or Home Assistant, with scoped access tokens |
| [Plugins](plugins.md) | Install a plugin and understand what it can reach |
| [Writing plugins](plugin-development.md) | Write a plugin and publish it to the catalogue |
| [Architecture](architecture.md) | Understand how the engine, the hub and the dashboard fit together, or change the code |
| [Troubleshooting](troubleshooting.md) | Fix a symptom like a dead feed, a failing printer test or a port already in use |
| [Contributing](../CONTRIBUTING.md) | Set up a dev environment, run the tests, add an integration or notifier |

## Conventions in these docs

- The hub is PrintGuard running as a server, either the Docker container or the desktop app. The dashboard is the page it serves.
- A camera is a video source and a printer is a connection to a print service. A monitor binds one of each, the printer optionally, and carries the detection thresholds.
- Commands shown as `docker run` assume the standard image. Compose users can apply the same options in [`docker-compose.yaml`](../docker-compose.yaml).
