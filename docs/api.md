# API Documentation  
> This is the API documentation for PrintGuard. For installation and usage guides, see the [README](../README.md).

## Pages
- [Overview](overview.md)
- [API Documentation](api.md)
- [Setup Documentation](setup.md)

## Table of Contents
- [Setup Endpoints](#setup-endpoints)
- [SSE Endpoints](#sse-endpoints)
- [Camera Endpoints](#camera-endpoints)  
- [Detection Endpoints](#detection-endpoints)  
- [Printer Endpoints](#printer-endpoints)  
- [Notification Endpoints](#notification-endpoints)  
- [Alert Endpoints](#alert-endpoints)  
- [Feed Settings Endpoints](#feed-settings-endpoints)

---

## Setup Endpoints

### GET /setup
**Description:** Serve the setup page.
**Response:** HTML content of the setup page.

### POST /setup/generate-vapid-keys
**Description:** Generate VAPID keys for web push notifications.
**Response:**
```json
{
    "public_key": "string",
    "private_key": "string",
    "subject": "string"
}
```

### POST /setup/save-vapid-settings
**Description:** Save VAPID settings.
**Request Body:**
```json
{
    "public_key": "string",
    "private_key": "string",
    "subject": "string",
    "base_url": "string"
}
```
**Response:** JSON confirmation message.

### POST /setup/generate-ssl-cert
**Description:** Generate a self-signed SSL certificate using stored domain, saving the certificate and key.
**Response:** JSON confirmation message.

### POST /setup/upload-ssl-cert
**Description:** Upload an SSL certificate which will be securely stored.
**Request Body:** `multipart/form-data` with `cert_file` and `key_file`.
**Response:** JSON confirmation message.

### POST /setup/save-tunnel-settings
**Description:** Save tunnel settings.
**Request Body:**
```json
{
    "provider": "ngrok | cloudflare",
    "token": "string",
    "domain": "string",
    "email": "string (required for global API key only)"
}
```
**Response:** JSON confirmation message.

### POST /setup/initialize-ngrok-tunnel
**Description:** Initialises a ngrok tunnel with the configured settings.
**Response:** Redirects to the setup page.

### POST /setup/complete
**Description:** Mark setup as complete.
**Request Body:**
```json
{
    "startup_mode": "setup | local | tunnel",
    "tunnel_provider": "ngrok | cloudflare (optional)"
}
```
**Response:** JSON confirmation message.

### GET /setup/cloudflare/accounts-zones
**Description:** Get Cloudflare accounts and zones.
**Response:**
```json
{
    "success": "boolean",
    "accounts": {},
    "zones": {}
}
```

### POST /setup/cloudflare/create-tunnel
**Description:** Create a Cloudflare tunnel.
**Request Body:**
```json
{
    "account_id": "string",
    "zone_id": "string",
    "subdomain": "string"
}
```
**Response:**
```json
{
    "success": "boolean",
    "url": "string",
    "tunnel_token": "string"
}
```

### POST /setup/cloudflare/save-os
**Description:** Save Cloudflare OS preferences.
**Request Body:**
```json
{
    "operating_system": "macos | windows | linux"
}
```
**Response:**
```json
{
    "success": "boolean",
    "tunnel_token": "string",
    "operating_system": "string",
    "setup_commands": []
}
```

### GET /setup/cloudflare/add-device
**Description:** Serve the Cloudflare add device page.
**Response:** HTML content of the add device page.

### GET /setup/cloudflare/organisation
**Description:** Get Cloudflare organisation.
**Response:**
```json
{
    "success": "boolean",
    "team_name": "string",
    "site_domain": "string"
}
```

---

## SSE Endpoints

### GET /sse
**Description:** Establish a Server-Sent Events connection for downstream communication.
**Response:** A stream of events.
```json
{
    "data": {
        "event": "alert | camera_state | printer_state",
        "data": { <the data packet> }
    }
}
```

### POST /sse/start-polling
**Description:** Start polling for printer state for a given camera.  
**Request Body:**  
```json
{ "camera_index": "integer" }
```
**Response:**  
```json
{ "message": "Polling started for camera index <camera_index>" }
```

### POST /sse/stop-polling
**Description:** Stop polling for printer state for a given camera.  
**Request Body:**  
```json
{ "camera_index": "integer" }
```
**Response:**  
```json
{ "message": "Polling stopped for camera index <camera_index>" }
```

---

## Camera Endpoints

### POST /camera/state
**Description:** Get the state of a camera.  
**Request Body:**  
```json
{ "camera_index": "integer" }
```
**Response:**  
```json
{
    "start_time": "float",
    "last_result": "string",
    "last_time": "float",
    "detection_times": [],
    "error": "string",
    "live_detection_running": "boolean",
    "brightness": "float",
    "contrast": "float",
    "focus": "float",
    "countdown_time": "integer",
    "majority_vote_threshold": "integer",
    "majority_vote_window": "integer",
    "current_alert_id": "string",
    "sensitivity": "float",
    "printer_id": "string",
    "printer_config": {},
    "countdown_action": "string"
}
```

### GET /camera/feed/{camera_index}
**Description:** Get the camera feed.  
**Path Param:** `camera_index: integer`  
**Response:** A multipart response with the video stream.

---

## Detection Endpoints

### POST /detect
**Description:** Perform batch or streaming defect detection on uploaded images.
**Request (multipart/form-data):**
- `files`: array of image files to analyze
- `stream`: boolean query parameter (default `false`)
**Response:**
- If `stream=false`:
```json
[
  { "filename": "string", "result": "string" },
]
```
- If `stream=true`: NDJSON stream of events:
```json
{ "filename": "string", "result": "string" }
```

### POST /detect/live/start
**Description:** Start live detection on a camera feed.
**Request Body:**
```json
{ "camera_index": "integer" }
```
**Response:**
```json
{ "message": "Live detection started for camera <camera_index>" }
```

### POST /detect/live/stop
**Description:** Stop live detection on a camera feed.
**Request Body:**
```json
{ "camera_index": "integer" }
```
**Response:**
```json
{ "message": "Live detection stopped for camera <camera_index>" }
```

---

## Printer Endpoints

### POST /printer/add/{camera_index}
**Description:** Add and configure a printer for a camera.
**Path Param:** `camera_index: integer`
**Request Body:**
```json
{
    "name": "string",
    "printer_type": "octoprint",
    "camera_index": "integer",
    "base_url": "string",
    "api_key": "string"
}
```
**Response:**
```json
{
    "success": true,
    "printer_id": "string"
}
```

### POST /printer/remove/{camera_index}
**Description:** Remove the configured printer from a camera.
**Path Param:** `camera_index: integer`
**Response:**
```json
{ "success": true, "message": "Printer removed from camera <camera_index>" }
```

### POST /printer/cancel/{camera_index}
**Description:** Cancel the current print job on the configured printer.
**Path Param:** `camera_index: integer`
**Response:**
```json
{ "success": true, "message": "Print job cancelled for camera <camera_index>" }
```

### POST /printer/pause/{camera_index}
**Description:** Pause the current print job on the configured printer.
**Path Param:** `camera_index: integer`
**Response:**
```json
{ "success": true, "message": "Print job paused for camera <camera_index>" }
```

---

## Notification Endpoints

### GET /notification/public_key
**Description:** Retrieve the VAPID public key for web push subscriptions.
**Response:**
```json
{ "publicKey": "VAPID_PUBLIC_KEY" }
```

### POST /notification/subscribe
**Description:** Subscribe to push notifications.
**Request Body:** JSON Web Push subscription object.
**Response:**
```json
{ "success": true }
```

### POST /notification/unsubscribe
**Description:** Unsubscribe all push notifications.
**Response:**
```json
{ "success": true }
```

### GET /notification/debug
**Description:** Debug current push subscription state and VAPID configuration.
**Response:**
```json
{
  "subscriptions_count": "integer",
  "subscriptions": [ 
        { 
        "endpoint": "string", 
        "has_keys": "boolean" 
        } 
    ],
  "vapid_config": { 
    "has_public_key": "boolean",
    "has_subject": "boolean",
    "has_private_key": "boolean",
    "subject": "string"
  }
}
```

---

## Alert Endpoints

### POST /alert/dismiss
**Description:** Dismiss an alert or perform an action.
**Request Body:**
```json
{
    "alert_id": "string",
    "action": "dismiss | cancel_print | pause_print"
}
```
**Response:** Confirmation message.

### GET /alert/active
**Description:** Get all active alerts.  
**Response:**  
```json
{
    "active_alerts": [
        {
            "id": "string",
            "snapshot": "string (base64)",
            "title": "string",
            "message": "string",
            "timestamp": "float",
            "countdown_time": "float",
            "camera_index": "integer",
            "has_printer": "boolean",
            "countdown_action": "string"
        }
    ]
}
```

---

## Feed Settings Endpoints

### POST /save-feed-settings
**Description:** Save the feed settings.
**Request Body:**
```json
{
    "stream_max_fps": "integer",
    "stream_tunnel_fps": "integer",
    "stream_jpeg_quality": "integer",
    "stream_max_width": "integer",
    "detections_per_second": "integer",
    "detection_interval_ms": "integer",
    "printer_stat_polling_rate_ms": "integer",
    "min_sse_dispatch_delay_ms": "integer"
}
```
**Response:**
```json
{
    "success": "boolean",
    "message": "Feed settings saved successfully."
}
```

### GET /get-feed-settings
**Description:** Get the current feed settings.
**Response:**
```json
{
    "success": "boolean",
    "settings": {
        "stream_max_fps": "integer",
        "stream_tunnel_fps": "integer",
        "stream_jpeg_quality": "integer",
        "stream_max_width": "integer",
        "detections_per_second": "integer",
        "detection_interval_ms": "integer",
        "printer_stat_polling_rate_ms": "integer",
        "min_sse_dispatch_delay_ms": "integer"
    }
}
```