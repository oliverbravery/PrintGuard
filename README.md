# FDM Sentinel - Print Failure Detection

A FastAPI-powered service using a Prototypical Neural Network to monitor 3D prints and send web push notifications on defect detection.

## Key Features

- **Real-time 3D Print Monitoring**: Uses machine learning to detect defects in your 3D prints
- **Push Notifications**: Get instant alerts when a print fails through web push notifications
- **Multiple Camera Support**: Monitor multiple printers simultaneously
- **Easy Setup**: Works with standard webcams and USB cameras

## Install

Install the package from PyPI:
```bash
pip install fdm-sentinel
```

Or install locally in editable mode:
```bash
git clone https://github.com/oliverbravery/FDM-Sentinel.git
cd FDM-Sentinel
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

### SSL & VAPID

For local HTTPS and service worker support, generate a self-signed cert:
```bash
# using homebrew
brew install mkcert
brew install nss
mkcert -install
mkcert -key-file .key.pem -cert-file .cert.pem localhost 127.0.0.1 ::1
```

Generate VAPID keys:
```bash
npm install -g web-push
web-push generate-vapid-keys --json
```

Copy `publicKey` and `privateKey` into `.env`:
```
VAPID_PUBLIC_KEY=<your_public_key>
VAPID_PRIVATE_KEY=<your_private_key>
VAPID_SUBJECT=mailto:you@example.com
```

## Setup

1. Clone the repository

2. Create a `.env` file in the project root:
   ```env
   VAPID_PUBLIC_KEY=your_public_key
   VAPID_PRIVATE_KEY=your_private_key
   VAPID_SUBJECT=mailto:your_email@example.com  # Subject email for VAPID claims
   ```

3. Install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

4. Run the server:
   ```bash
   uvicorn fdm_sentinel.app:app --reload --ssl-certfile .cert.pem --ssl-keyfile .key.pem
   ```

## How It Works

The Print Sentinel uses a Prototypical Neural Network to analyze images from your 3D printer's camera feed. When it detects signs of printing failure like:
- Spaghetti mess
- Layer shifting
- Warping or curling
- Print detachment

It immediately sends a push notification to your devices so you can intervene.

## Website

A simple browser-based UI is included. After starting the server with:
```bash
uvicorn fdm_sentinel.app:app --reload --ssl-certfile .cert.pem --ssl-keyfile .key.pem
```

Navigate to:
```
https://localhost:8000/
```

- Click **Subscribe to Notifications** and grant permission.
- Use **Start Monitoring** to begin live detection.
- Adjust settings via **Settings**.
- Alerts appear in the UI and via push notifications.

### UI Features

The main interface includes:
- Live camera feed with camera selection dropdown
- Start/Stop controls for print monitoring
- Status display showing current detection state
- Settings page for configuring detection parameters

### Advanced Features

- **Multiple Camera Support**: Monitor several printers by selecting different cameras
- **Custom Scheduling**: Set up recurring notifications using cron expressions
- **Alert History**: View past detected failures with timestamps and images
- **Configurable Sensitivity**: Adjust detection thresholds in settings

### Technical Notes

- Uses FastAPI and a prototypical neural network for defect detection
- In-memory storage is used for demo purposes; consider a persistent DB for production
- Handle errors and retries in production environments
- Ensure HTTPS in production for service workers to function properly
- Model detection uses pre-trained weights located in the model directory

## API Endpoints

### Detection
**POST** `/detect`
Detect print failures using a camera image:
```json
{ "files": ["img_1.png", "img_2.png"] }
```

### Public Key
**GET** `/notifications/publicKey`
Returns the VAPID public key for subscribing:
```json
{ "public_key": "<VAPID_PUBLIC_KEY>" }
```

### Subscribe / Unsubscribe
**POST** `/notifications/subscribe`
Register a push subscription:
```json
{ "endpoint": "<endpoint_url>", "keys": { "p256dh": "...", "auth": "..." } }
```

**POST** `/notifications/unsubscribe/{subscription_id}`
Remove an existing subscription.

### Send Notification
**POST** `/notifications/send/{subscription_id}`
Send an immediate push notification:
```json
{ "title": "Alert", "body": "Defect detected", "url": "https://..." }
```

### Schedule Notification
**POST** `/notifications/schedule`
Schedule recurring notifications via cron expression:
```json
{ "subscription_id": "<id>", "message": { "title": "Daily", "body": "Update" }, "cron": "0 9 * * *" }
```

### Live Detection
**GET** `/live`
Open a server-sent events stream of detection results.

**POST** `/live/start`
Start continuous live detection on configured camera.

**POST** `/live/stop`
Stop live detection.

**GET** `/live/alerts`
Stream detected alert IDs and timestamps.

**GET** `/live/status`
Get current live detection status and camera info.

### Settings UI
**GET** `/settings`
Open a web form to configure sensitivity, camera index, brightness, contrast, focus, and warning intervals.
