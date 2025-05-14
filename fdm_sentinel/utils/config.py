import os
import torch
from dotenv import load_dotenv

load_dotenv()

raw_subject = os.getenv("VAPID_SUBJECT", "")
VAPID_SUBJECT = raw_subject.split('#')[0].strip()
if not VAPID_SUBJECT:
    raise RuntimeError(
        "Missing or invalid VAPID_SUBJECT in .env (e.g. mailto:you@example.com)"
    )

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_CLAIMS = {"sub": VAPID_SUBJECT}

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "model", "best_model.pt")
MODEL_OPTIONS_PATH = os.path.join(BASE_DIR, "model", "opt.json")
PROTOTYPES_DIR = os.path.join(BASE_DIR, "model", "prototypes")

SUCCESS_LABEL = "success"
DEVICE_TYPE = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
SENSITIVITY = 1.0
CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))
DETECTION_TIMEOUT = int(os.getenv("DETECTION_TIMEOUT", "5"))  # minutes
BASE_URL = os.getenv("BASE_URL", "https://localhost:8000")
DETECTION_THRESHOLD = int(os.getenv("DETECTION_THRESHOLD", "3"))
DETECTION_VOTING_WINDOW = int(os.getenv("DETECTION_VOTING_WINDOW", "5"))  # total detections in a window
DETECTION_VOTING_THRESHOLD = int(os.getenv("DETECTION_VOTING_THRESHOLD", "2"))  # number of votes
MAX_CAMERA_HISTORY = int(os.getenv("MAX_CAMERA_HISTORY", "10000"))

## Camera adjustment defaults
BRIGHTNESS = float(os.getenv("BRIGHTNESS", "1.0"))
CONTRAST = float(os.getenv("CONTRAST", "1.0"))
FOCUS = float(os.getenv("FOCUS", "1.0"))

## Countdown timer and warning intervals
COUNTDOWN_TIME = int(os.getenv("COUNTDOWN_TIME", "60"))  # seconds
WARNING_INTERVALS = [int(x) for x in os.getenv("WARNING_INTERVALS", "30,15").split(",")]

## Page constants
DETECTION_POLLING_RATE = float(os.getenv("DETECTION_POLLING_RATE", "0.25"))  # seconds
