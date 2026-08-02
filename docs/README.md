<div align="center">

# PrintGuard documentation

**Docs** · [Architecture](architecture.md) · [Printers & cameras](printers.md) · [Hardware](hardware.md) · [Deployment](deployment.md) · [API & MCP](api.md) · [Troubleshooting](troubleshooting.md)

</div>

Start at the [README](../README.md) to install PrintGuard. These pages cover everything after that.

| Page | Read it when you want to |
|---|---|
| [Printers & cameras](printers.md) | Connect OctoPrint, Klipper, Elegoo, Prusa or Bambu Lab, add cameras, and set up alert channels |
| [Hardware](hardware.md) | Pick an image variant, understand the model runtimes, and use a GPU or NPU |
| [Deployment](deployment.md) | Reach a hub from outside your LAN without exposing it, and harden what you run |
| [Troubleshooting](troubleshooting.md) | Fix a specific symptom: a dead feed, a failing printer test, a port already in use |
| [API & MCP](api.md) | Drive the hub from a script or an agent, with scoped access tokens |
| [Architecture](architecture.md) | Understand how one engine runs in two places, or change the code |
| [Contributing](../CONTRIBUTING.md) | Set up a dev environment, run the tests, add an integration or notifier |

## Conventions in these docs

- **Hub mode** is PrintGuard running as a server: the Docker container or the desktop app. **Local mode** is the same engine running inside a browser tab with no server at all. [Architecture](architecture.md) explains why they cannot drift apart.
- A **camera** is a video source and a **printer** is a connection to a print service. A **monitor** binds one of each, the printer optionally, and carries the detection thresholds.
- Commands shown as `docker run` assume the standard image. Compose users can apply the same options in [`docker-compose.yaml`](../docker-compose.yaml).
