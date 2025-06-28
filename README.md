# PrintGuard - Local 3D Printing Failure Detection and Monitoring
PrintGuard offers local, **real-time print failure detection** for **3D printing** on edge devices. A **web interface** enables users to **monitor multiple printer-facing cameras**, **connect to printers** through compatible services (i.e. [Octoprint](https://octoprint.org)) and **receive failure notifications** when the **computer vision** fault detection model designed for local edge deployment detects an issue and **automatically suspend or terminate the print job**.

## Features
- **Web Interface**: A user-friendly web interface to monitor print jobs and camera feeds.
- **Live Print Failure Detection**: Uses a custom computer vision model to detect print failures in real-time on edge devices.
- **Notifications**: Sends notifications subscribable on desktop and mobile devices via web push notifications to notify of detected print failures.
- **Camera Integration**: Supports multiple camera feeds and simultaneous failure detection.
- **Printer Integration**: Integrates with printers through services like Octoprint, allowing users to link cameras to specific printers for automatic print termination or suspension when a failure is detected.
- **Local and Remote Access**: Can be accessed locally or remotely via secure tunnels (e.g. ngrok, Cloudflare Tunnel) or within a local network utilising the setup page for easy configuration.

## Table of Contents
- [Features](#features)
- [Installation](#installation)
- [Initial Configuration](#initial-configuration)
- [Usage](#usage)
- [Technical Documentation](/docs/overview.md)

## Installation
PrintGuard is installable via [pip](https://pypi.org/project/printguard/). The following command will install the latest version:
```bash
pip install printguard
```
To start the web interface, run:
```bash
printguard
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
  | | |