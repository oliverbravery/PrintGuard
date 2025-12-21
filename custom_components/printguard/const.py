"""Constants for the PrintGuard integration."""

DOMAIN = "printguard"

# Server configuration
CONF_URL = "url"
CONF_TOKEN = "token"

# Printer configuration
CONF_PRINTERS = "printers"
CONF_PRINTER_NAME = "name"
CONF_CAMERA = "camera"
CONF_START_ENTITY = "start_entity"
CONF_PAUSE_ENTITY = "pause_entity"
CONF_RESUME_ENTITY = "resume_entity"
CONF_STOP_ENTITY = "stop_entity"

# Notification configuration
CONF_NOTIFY_SERVICE = "notify_service"
CONF_ENABLE_NOTIFICATIONS = "enable_notifications"

# Crypto configuration
CONF_SERVER_PUBLIC_KEY = "server_public_key"
CONF_CLIENT_PRIVATE_KEY = "client_private_key"
CONF_CLIENT_PUBLIC_KEY = "client_public_key"

# Events
EVENT_DEFECT_DETECTED = f"{DOMAIN}_defect_detected"

# Platforms to set up
PLATFORMS = ["sensor", "binary_sensor", "button", "camera", "event"]

# Polling interval (seconds)
SCAN_INTERVAL_SECONDS = 10
