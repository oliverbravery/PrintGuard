import os
import json
import torch
from ..models import AlertAction

CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config.json")
SETUP_COMPLETE = False

def load_config():
    global VAPID_SUBJECT, VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_CLAIMS, SETUP_COMPLETE, BASE_URL
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config_data = json.load(f)
                VAPID_SUBJECT = config_data.get("VAPID_SUBJECT", "")
                VAPID_PUBLIC_KEY = config_data.get("VAPID_PUBLIC_KEY", "")
                VAPID_PRIVATE_KEY = config_data.get("VAPID_PRIVATE_KEY", "")
                BASE_URL = config_data.get("BASE_URL", "")
                SETUP_COMPLETE = config_data.get("SETUP_COMPLETE", False)

                if VAPID_SUBJECT and VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY and BASE_URL:
                    SETUP_COMPLETE = True

                if VAPID_SUBJECT:
                    VAPID_CLAIMS = {"sub": VAPID_SUBJECT}
                return
        except Exception as e:
            print(f"Error loading config file: {e}")

    if VAPID_SUBJECT and VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY and BASE_URL:
        SETUP_COMPLETE = True

    if VAPID_SUBJECT:
        VAPID_CLAIMS = {"sub": VAPID_SUBJECT}

def save_config(config_data):
    global VAPID_SUBJECT, VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_CLAIMS, SETUP_COMPLETE, BASE_URL
    VAPID_SUBJECT = config_data.get("VAPID_SUBJECT", VAPID_SUBJECT)
    VAPID_PUBLIC_KEY = config_data.get("VAPID_PUBLIC_KEY", VAPID_PUBLIC_KEY)
    VAPID_PRIVATE_KEY = config_data.get("VAPID_PRIVATE_KEY", VAPID_PRIVATE_KEY)
    BASE_URL = config_data.get("BASE_URL", BASE_URL)
    if VAPID_SUBJECT and VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY and BASE_URL:
        SETUP_COMPLETE = True
        config_data["SETUP_COMPLETE"] = True
    if VAPID_SUBJECT:
        VAPID_CLAIMS = {"sub": VAPID_SUBJECT}
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config_data, f, indent=2)

VAPID_SUBJECT = ""
VAPID_PUBLIC_KEY = ""
VAPID_PRIVATE_KEY = ""
VAPID_CLAIMS = {}
BASE_URL = ""

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
