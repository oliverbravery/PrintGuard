import os
import json
import torch
from platformdirs import user_data_dir
from ..models import AlertAction, SiteStartupMode
import keyring
import tempfile, os

APP_DATA_DIR = user_data_dir("fdm-sentinel", "fdm-sentinel")
KEYRING_SERVICE_NAME = "fdm-sentinel"
os.makedirs(APP_DATA_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(APP_DATA_DIR, "config.json")
SSL_CERT_FILE = os.path.join(APP_DATA_DIR, "cert.pem")
SSL_CA_FILE = os.path.join(APP_DATA_DIR, "ca.pem")

VAPID_SUBJECT = ""
VAPID_PUBLIC_KEY = ""
VAPID_CLAIMS = {}
SITE_DOMAIN = None

STARTUP_MODE = SiteStartupMode.SETUP
TUNNEL_PROVIDER = None

def store_vapid_private_key(private_key):
    keyring.set_password(KEYRING_SERVICE_NAME, "VAPID_PRIVATE_KEY", private_key)

def get_vapid_private_key():
    return keyring.get_password(KEYRING_SERVICE_NAME, "VAPID_PRIVATE_KEY")

def store_ssl_private_key(private_key):
    keyring.set_password(KEYRING_SERVICE_NAME, "SSL_PRIVATE_KEY", private_key)

def get_ssl_private_key():
    return keyring.get_password(KEYRING_SERVICE_NAME, "SSL_PRIVATE_KEY")

def store_tunnel_api_key(api_key):
    keyring.set_password(KEYRING_SERVICE_NAME, "TUNNEL_API_KEY", api_key)

def get_tunnel_api_key():
    return keyring.get_password(KEYRING_SERVICE_NAME, "TUNNEL_API_KEY")

def get_ssl_private_key_temporary_path():
    private_key = get_ssl_private_key()
    if private_key:
        temp_file = tempfile.NamedTemporaryFile("w+",
                                                delete=False,
                                                suffix=".pem")
        temp_file.write(private_key)
        temp_file.flush()
        os.chmod(temp_file.name, 0o600)
        return temp_file.name
    return None

def load_config():
    global VAPID_SUBJECT, VAPID_PUBLIC_KEY, VAPID_CLAIMS, TUNNEL_PROVIDER, SITE_DOMAIN, STARTUP_MODE
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config_data = json.load(f)
                VAPID_SUBJECT = config_data.get("VAPID_SUBJECT", "")
                VAPID_PUBLIC_KEY = config_data.get("VAPID_PUBLIC_KEY", "")
                STARTUP_MODE = config_data.get("STARTUP_MODE", SiteStartupMode.SETUP)
                SITE_DOMAIN = config_data.get("SITE_DOMAIN", None)
                TUNNEL_PROVIDER = config_data.get("TUNNEL_PROVIDER", None)
                if VAPID_SUBJECT:
                    VAPID_CLAIMS = {"sub": VAPID_SUBJECT}
                return
        except Exception as e:
            print(f"Error loading config file: {e}")
    if VAPID_SUBJECT:
        VAPID_CLAIMS = {"sub": VAPID_SUBJECT}

def save_config(config_data):
    global VAPID_SUBJECT, VAPID_PUBLIC_KEY, VAPID_CLAIMS, TUNNEL_PROVIDER, SITE_DOMAIN, STARTUP_MODE
    VAPID_SUBJECT = config_data.get("VAPID_SUBJECT", VAPID_SUBJECT)
    VAPID_PUBLIC_KEY = config_data.get("VAPID_PUBLIC_KEY", VAPID_PUBLIC_KEY)
    STARTUP_MODE = config_data.get("STARTUP_MODE", STARTUP_MODE)
    SITE_DOMAIN = config_data.get("SITE_DOMAIN", SITE_DOMAIN)
    TUNNEL_PROVIDER = config_data.get("TUNNEL_PROVIDER", TUNNEL_PROVIDER)
    if VAPID_SUBJECT:
        VAPID_CLAIMS = {"sub": VAPID_SUBJECT}
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config_data, f, indent=2)

load_config()

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "model", "best_model.pt")
MODEL_OPTIONS_PATH = os.path.join(BASE_DIR, "model", "opt.json")
PROTOTYPES_DIR = os.path.join(BASE_DIR, "model", "prototypes")

SUCCESS_LABEL = "success"
DEVICE_TYPE = "cuda" if (torch.cuda.is_available()) else (
    "mps" if (torch.backends.mps.is_available()) else "cpu")
SENSITIVITY = 1.0
CAMERA_INDEX = 0
DETECTION_TIMEOUT = 5
DETECTION_THRESHOLD = 3
DETECTION_VOTING_WINDOW = 5
DETECTION_VOTING_THRESHOLD = 2
MAX_CAMERA_HISTORY = 10_000

BRIGHTNESS = 1.0
CONTRAST = 1.0
FOCUS = 1.0

COUNTDOWN_TIME = 60
COUNTDOWN_ACTION = AlertAction.DISMISS

MAX_CAMERAS = 64
CAMERA_INDICES = [int(idx) for idx in os.getenv(
    "CAMERA_INDICES", "").split(",") if idx != ""]
