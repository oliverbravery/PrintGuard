# 3D Print Sentinel - Print Failure Detection

A system that uses computer vision to detect failures in 3D printing and sends web push notifications when a defect is detected.

## Key Features

- **Real-time 3D Print Monitoring**: Uses machine learning to detect defects in your 3D prints
- **Push Notifications**: Get instant alerts when a print fails
- **Multiple Camera Support**: Monitor multiple printers simultaneously
- **Easy Setup**: Works with standard webcams and USB cameras

## Generating VAPID Keys
You need VAPID keys for the web push notification system. Generate them using the Node.js `web-push` CLI:
```bash
npm install -g web-push

web-push generate-vapid-keys --json
```
This prints something like:
```json
{
  "publicKey": "<your_public_key>",
  "privateKey": "<your_private_key>"
}
```
Copy these values into your `.env` as `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY`.

## SSL Certificate
For local development, you can use a self-signed certificate. Here's how to create one:
```bash
openssl req -x509 -newkey rsa:2048 -keyout .key.pem -out .cert.pem -days 365 -nodes
```
This generates a `.key.pem` and `.cert.pem` file. Use these in your server setup.

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
   uvicorn app:app --reload
   ```

## How It Works

The Print Sentinel uses a Prototypical Neural Network to analyze images from your 3D printer's camera feed. When it detects signs of printing failure like:
- Spaghetti mess
- Layer shifting
- Warping or curling
- Print detachment

It immediately sends a push notification to your devices so you can intervene.

## API Endpoints

The system includes a notification API to handle web push notifications:

### GET /publicKey

Get the VAPID public key needed for push subscriptions.

Response:
```json
{
  "public_key": "<VAPID_PUBLIC_KEY>"
}
```

### POST /subscribe

Register a new notification subscription.

Body:
```json
{
  "endpoint": "<endpoint_url>",
  "keys": { "p256dh": "...", "auth": "..." }
}
```
Response:
```json
{ "subscription_id": "1" }
```

### POST /unsubscribe/{subscription_id}

Unsubscribe an existing subscription.

### POST /send/{subscription_id}

Send a one-off notification. Body:
```json
{
  "title": "Hello",
  "body": "Test",
  "url": "https://example.com"
}
```

### POST /schedule

Schedule a recurring notification using a cron expression. Body:
```json
{
  "subscription_id": "1",
  "message": { "title": "Daily Update", "body": "Here's your daily update!", "url": "https://example.com" },
  "cron": "0 9 * * *"
}
```

This will send every day at 9am.

## Example Client Usage

```js
const publicKey = await fetch('/publicKey').then(res => res.json()).then(data => data.public_key);

// Subscribe
const subscription = await registration.pushManager.subscribe({
  userVisibleOnly: true,
  applicationServerKey: publicKey,
});

await fetch('/subscribe', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(subscription),
});

// Send one-off
await fetch('/send/1', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ title: 'Hi', body: 'Test' }),
});

// Schedule daily at 9
await fetch('/schedule', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ subscription_id: '1', message: { title: 'Daily', body: 'Hello' }, cron: '0 9 * * *' }),
});
```

## Demo Website

After starting the API server, you can open the included demo UI:

1. Make sure your API is running on `http://localhost:8000`:
   ```bash
   uvicorn app:app --reload
   ```
2. In your browser (Chrome, Safari, Edge), navigate to:
   ```
   https://localhost:8000/
   ```
3. Click **Subscribe to Notifications** and grant permission when prompted.
4. Use the built-in controls to start the print monitoring.
5. You can test the notification system by clicking the "Send Test Notification" button.

## UI Features

The main interface includes:
- Live camera feed with camera selection dropdown
- Start/Stop controls for print monitoring
- Status display showing current detection state
- Settings page for configuring detection parameters

## Advanced Features

- **Multiple Camera Support**: Monitor several printers by selecting different cameras
- **Custom Scheduling**: Set up recurring notifications using cron expressions
- **Alert History**: View past detected failures with timestamps and images
- **Configurable Sensitivity**: Adjust detection thresholds in settings

## Technical Notes

- Uses FastAPI and a prototypical neural network for defect detection
- In-memory storage is used for demo purposes; consider a persistent DB for production
- Handle errors and retries in production environments
- Ensure HTTPS in production for service workers to function properly
- Model detection uses pre-trained weights located in the model directory
