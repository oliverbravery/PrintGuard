import json
import logging
import os
import tempfile

import keyring
import keyring.errors
import torch
from platformdirs import user_data_dir

from ..models import AlertAction, SavedKey, SavedConfig

APP_DATA_DIR = user_data_dir("fdm-sentinel", "fdm-sentinel")
KEYRING_SERVICE_NAME = "fdm-sentinel"
os.makedirs(APP_DATA_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(APP_DATA_DIR, "config.json")
SSL_CERT_FILE = os.path.join(APP_DATA_DIR, "cert.pem")
SSL_CA_FILE = os.path.join(APP_DATA_DIR, "ca.pem")

def get_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                return config_data
        except Exception as e:
            logging.error("Error loading config file: %s", e)

def update_config(updates: dict):
    config = get_config()
    if config is not None:
        for key, value in updates.items():
            config[key] = value
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)

def init_config():
    if not os.path.exists(CONFIG_FILE):
        default_config = {
            SavedConfig.VAPID_PUBLIC_KEY: None,
            SavedConfig.VAPID_SUBJECT: None,
            SavedConfig.STARTUP_MODE: None,
            SavedConfig.SITE_DOMAIN: None,
            SavedConfig.TUNNEL_PROVIDER: None,
            SavedConfig.PUSH_SUBSCRIPTIONS: []
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=2)
        logging.debug("Default config file created at %s", CONFIG_FILE)

def store_key(key: SavedKey, value: str):
    keyring.set_password(KEYRING_SERVICE_NAME, key.value, value)

def get_key(key: SavedKey):
    return keyring.get_password(KEYRING_SERVICE_NAME, key.value)

def get_ssl_private_key_temporary_path():
    private_key = get_key(SavedKey.SSL_PRIVATE_KEY)
    if private_key:
        temp_file = tempfile.NamedTemporaryFile("w+",
                                                delete=False,
                                                suffix=".pem")
        temp_file.write(private_key)
        temp_file.flush()
        os.chmod(temp_file.name, 0o600)
        return temp_file.name
    return None

def reset_all_keys():
    for key in SavedKey:
        try:
            keyring.delete_password(KEYRING_SERVICE_NAME, key.value)
        except keyring.errors.PasswordDeleteError:
            pass

def reset_config():
    default_config = {
        SavedConfig.VAPID_PUBLIC_KEY: None,
        SavedConfig.VAPID_SUBJECT: None,
        SavedConfig.STARTUP_MODE: None,
        SavedConfig.SITE_DOMAIN: None,
        SavedConfig.TUNNEL_PROVIDER: None,
        SavedConfig.PUSH_SUBSCRIPTIONS: []
    }
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(default_config, f, indent=2)

def reset_ssl_files():
    for ssl_file in [SSL_CERT_FILE, SSL_CA_FILE]:
        if os.path.exists(ssl_file):
            os.remove(ssl_file)

def reset_all():
    reset_all_keys()
    reset_config()
    reset_ssl_files()
    logging.debug("All saved keys, config, and SSL files have been reset")

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

DETECTIONS_PER_SECOND = 15

STREAM_MAX_FPS = 30
STREAM_TUNNEL_FPS = 10
STREAM_JPEG_QUALITY = 85
STREAM_TUNNEL_JPEG_QUALITY = 60
STREAM_MAX_WIDTH = 1280
STREAM_TUNNEL_MAX_WIDTH = 640
DETECTION_INTERVAL_MS = 1000 / DETECTIONS_PER_SECOND
DETECTION_TUNNEL_INTERVAL_MS = 1000 / DETECTIONS_PER_SECOND

PRINTER_STAT_POLLING_RATE_MS = 2000
TUNNEL_STAT_POLLING_RATE_MS = 5000
STANDARD_STAT_POLLING_RATE_MS = 250

MAX_CAMERAS = 64
CAMERA_INDICES = [int(idx) for idx in os.getenv(
    "CAMERA_INDICES", "").split(",") if idx != ""]
