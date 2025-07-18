# PrintGuard - Local 3D Printing Failure Detection and Monitoring
[![PyPI - Version](https://img.shields.io/pypi/v/printguard?style=for-the-badge&logo=pypi&logoColor=white&logoSize=auto&color=yellow)](https://pypi.org/project/printguard/)
[![GitHub Repo stars](https://img.shields.io/github/stars/oliverbravery/printguard?style=for-the-badge&logo=github&logoColor=white&logoSize=auto&color=yellow)](https://github.com/oliverbravery/printguard)

PrintGuard offers local, **real-time print failure detection** for **3D printing** on edge devices. A **web interface** enables users to **monitor multiple printer-facing cameras**, **connect to printers** through compatible services (i.e. [Octoprint](https://octoprint.org)) and **receive failure notifications** when the **computer vision** fault detection model designed for local edge deployment detects an issue and **automatically suspend or terminate the print job**.

> _The machine learning model's training code and technical research paper can be found [here](https://github.com/oliverbravery/Edge-FDM-Fault-Detection)._

## Features
- **Web Interface**: A user-friendly web interface to monitor print jobs and camera feeds.
- **Live Print Failure Detection**: Uses a custom computer vision model to detect print failures in real-time on edge devices.
- **Multiple Inference Backends**: Supports PyTorch & ONNX Runtime for optimized performance across different deployment scenarios.
- **Notifications**: Sends notifications subscribable on desktop and mobile devices via web push notifications to notify of detected print failures.
- **Camera Integration**: Supports multiple camera feeds and simultaneous failure detection.
- **Printer Integration**: Integrates with printers through services like Octoprint, allowing users to link cameras to specific printers for automatic print termination or suspension when a failure is detected.
- **Local and Remote Access**: Can be accessed locally or remotely via secure tunnels (e.g. ngrok, Cloudflare Tunnel) or within a local network utilising the setup page for easy configuration.

## Table of Contents
- [Features](#features)
- [Installation](#installation)
    - [PyPI Installation](#pypi-installation)
    - [Docker Installation](#docker-installation)
- [Initial Configuration](#initial-configuration)
- [Usage](#usage)
- [Technical Documentation](/docs/overview.md)

## Installation

### PyPI Installation
> _The project is currently in pre-release, so the `--pre` flag is required for installation._

PrintGuard is installable via [pip](https://pypi.org/project/printguard/). The following command will install the latest version:
```bash
pip install --pre printguard
```
To start the web interface, run:
```bash
printguard
```

### Docker Installation
PrintGuard is also available as a Docker image, which can be pulled from GitHub Container Registry (GHCR):
```bash
docker pull ghcr.io/oliverbravery/printguard:latest
```

Alternatively, you can build the Docker image from the source, specifying the platforms you want to build for:
```bash
docker buildx build \
  --platform linux/amd64,linux/arm64,linux/arm/v7 \
  -t oliverbravery/printguard:local \
  --load \
  .
```

To run the Docker container, use the following command. Note that the container requires a volume for persistent data storage and an environment variable for the secret key. Use the `--privileged` flag to allow access to the host's camera devices.

To run the Docker container pulled from GHCR, use the following command:
```bash
docker run \
  -p 8000:8000 \
  -v "$(pwd)/data:/data" \
  --privileged \
  ghcr.io/oliverbravery/printguard:latest
```

To run the Docker container built from the source, use the following command:
```bash
docker run \
  -p 8000:8000 \
  -v "$(pwd)/data:/data" \
  --privileged \
  oliverbravery/printguard:local
```

## Initial Configuration
After installation, you will need to configure PrintGuard. First, visit the setup page at `http://localhost:8000/setup`. The setup page allows users to configure network access to the locally hosted site, including seamless options for exposing it via popular reverse proxies for a streamlined setup. All setups require you to choose to either automatically generate or import self-signed SSL certificates for secure access, alongside VAPID keys which are required for web push notifications.

> [Cloudflare](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) - A secure way to expose your local web interface to the internet via reverse proxies, providing a reliable and secure connection without needing to open ports on your router. Cloudflare tunnels are free to use and offer a simple setup process however, a domain connected to your Cloudflare account is required. Restricted access to your PrintGuard site can be setup through [Cloudflare Access](https://one.dash.cloudflare.com/), configurable in the setup page. During setup, your API key is used to create a tunnel to your local server and insert a DNS record for the tunnel, allowing you to access your PrintGuard instance via your custom domain or subdomain.

> [Ngrok](https://ngrok.com/) - Reverse proxy tool which allows you to expose the local web interface to the internet for access outside of your local network, offering a secure tunnel to your local server with minimal configuration through both free and paid plans. The setup uses your ngrok API to create a tunnel to your local server and link it to your free static ngrok domain aquired during setup, allowing access to PrintGuard via a custom, static subdomain.

> Local Network Access - If you prefer not to expose your web interface to the internet, you can configure PrintGuard to be accessible only within your local network.

## Usage
 | | |
 | --- | --- |
 | ![PrintGuard Web Interface](docs/media/images/interface-index.png) | The main interface of PrintGuard. All cameras are selectable in the bottom left camera list. The live camera view displayed in the top right shows the feed of the currently selected camera. The current detection status, total detections and frame rate are displayed in the bottom right alongside a button to toggle live detection for the selected camera on or off. |
  | ![PrintGuard Camera Settings](docs/media/images/interface-camera-settings.png) | The camera settings page is accessible via the settings button in the bottom right of the main interface. It allows you to configure camera settings, including camera brightness and contrast, detection thresholds, link a printer to the camera via services such as Octoprint, and configure alert and notification settings for that camera. You can also opt into web push notifications for real-time alerts here. |
  | ![PrintGuard Setup Settings](docs/media/images/interface-setup-settings.png) | Accessible via the configure setup button in the settings menu, the setup page allows configuration of camera feed streaming settings such as resolution and frame rate, as well as polling intervals and detection rates. |
  | ![PrintGuard Alerts and Notifications](docs/media/images/interface-alerts-notifications.png) | When a failure is detected a notification is dispatched to subscribed devices via web push notifications, allowing users to get real-time alerts and updates about their print. On the web interface, an alert modal appears showing a snapshot of the failure and buttons to dismiss the alert or suspend/cancel the print job. If the alert is not addressed within the customisable countdown time, the printer will automatically be suspended, cancelled or resumed based on user settings. |
  | | |