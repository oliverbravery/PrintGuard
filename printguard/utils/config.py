import json
import logging
import os
import tempfile
import fcntl
import threading
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

import keyring
import keyring.errors
import torch
from platformdirs import user_data_dir

from .model_downloader import get_model_downloader
from ..models import AlertAction, SavedKey, SavedConfig

# Config version - increment this when the config structure changes
CONFIG_VERSION = "1.0.0"

def is_running_in_docker():
    """Check if the application is running inside a Docker container."""
    return os.path.exists('/.dockerenv')

if is_running_in_docker():
    APP_DATA_DIR = "/data"
else:
    APP_DATA_DIR = user_data_dir("printguard", "printguard")

KEYRING_SERVICE_NAME = "printguard"
os.makedirs(APP_DATA_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(APP_DATA_DIR, "config.json")
SECRETS_FILE = os.path.join(APP_DATA_DIR, "secrets.json")
LOCK_FILE = os.path.join(APP_DATA_DIR, "config.lock")
SSL_CERT_FILE = os.path.join(APP_DATA_DIR, "cert.pem")
SSL_CA_FILE = os.path.join(APP_DATA_DIR, "ca.pem")

_config_lock = threading.RLock()
_file_lock = None

def acquire_lock():
    """Acquire a thread and file lock for safe configuration file access.

    Ensures exclusive access to the config file by acquiring a threading lock
    and a file-based lock at `LOCK_FILE`.
    """
    # pylint: disable=global-statement
    global _file_lock
    _config_lock.acquire()
    _file_lock = open(LOCK_FILE, 'w')
    try:
        fcntl.flock(_file_lock, fcntl.LOCK_EX)
    except IOError as e:
        logging.warning("Failed to acquire file lock: %s", e)


def release_lock():
    """Release the configuration file exclusivity locks.

    Releases both the file-based lock and the threading lock.
    """
    # pylint: disable=global-statement
    global _file_lock
    if _file_lock:
        fcntl.flock(_file_lock, fcntl.LOCK_UN)
        _file_lock.close()
        _file_lock = None
    _config_lock.release()

def _get_config_nolock():
    """Load configuration from disk without acquiring any locks.

    Returns:
        dict or None: The JSON-loaded configuration, or None if file doesn't exist or load fails.
    """
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error("Error loading config file: %s", e)
    return None

def get_config():
    """Thread-safe retrieval of the application configuration.

    Acquires locks before reading the config file.

    Returns:
        dict or None: The loaded configuration dictionary, or None if not initialized.
    """
    acquire_lock()
    try:
        return _get_config_nolock()
    finally:
        release_lock()

def update_config(updates: dict):
    """Thread-safe update of configuration values in the config file.

    Args:
        updates (dict): A mapping of config keys to their new values.
    """
    acquire_lock()
    try:
        config = _get_config_nolock() or {}
        for key, value in updates.items():
            config[key] = value
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
    finally:
        release_lock()

def init_config():
    """Initialize the configuration file with default keys if missing.
    
    Checks if the config file exists and has the correct version.
    If the version doesn't match or is missing, deletes the config file and recreates it.
    Creates `config.json` with default entries for all SavedConfig keys.
    """
    acquire_lock()
    try:
        config_needs_reset = False
        if os.path.exists(CONFIG_FILE):
            try:
                existing_config = _get_config_nolock()
                if existing_config is None:
                    logging.info("Config file is corrupted or empty, recreating")
                    config_needs_reset = True
                else:
                    config_version = existing_config.get(SavedConfig.VERSION)
                    if config_version != CONFIG_VERSION:
                        logging.info(
                            "Config version mismatch (config: %s, expected: %s), recreating config",
                            config_version, CONFIG_VERSION)
                        config_needs_reset = True
            except Exception as e:
                logging.warning("Error reading config file: %s, recreating", e)
                config_needs_reset = True
        else:
            config_needs_reset = True
        if config_needs_reset:
            if os.path.exists(CONFIG_FILE):
                os.remove(CONFIG_FILE)
                logging.info("Deleted old config file")
            default_config = {
                SavedConfig.VERSION: CONFIG_VERSION,
                SavedConfig.VAPID_PUBLIC_KEY: None,
                SavedConfig.VAPID_SUBJECT: None,
                SavedConfig.STARTUP_MODE: None,
                SavedConfig.SITE_DOMAIN: None,
                SavedConfig.TUNNEL_PROVIDER: None,
                SavedConfig.PUSH_SUBSCRIPTIONS: [],
                SavedConfig.CAMERA_STATES: {}
            }
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=2)
            logging.info("Created new config file with version %s at %s",
                         CONFIG_VERSION,
                         CONFIG_FILE)
    finally:
        release_lock()

def _get_encryption_key(salt):
    """Derives an encryption key from the PRINTGUARD_SECRET_KEY environment variable."""
    secret_key = os.environ.get("PRINTGUARD_SECRET_KEY")
    if not secret_key:
        return None
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))
    return Fernet(key)

def _get_secrets_nolock():
    """Load secrets from disk without acquiring any locks.

    Returns:
        dict or None: The JSON-loaded secrets, or None if the file doesn't exist or fails to load.
    """
    if os.path.exists(SECRETS_FILE):
        try:
            with open(SECRETS_FILE, 'rb') as f:
                file_content = f.read()
            if not file_content:
                return {}
            secret_key = os.environ.get("PRINTGUARD_SECRET_KEY")
            if secret_key:
                salt = file_content[:16]
                encrypted_data = file_content[16:]
                fernet = _get_encryption_key(salt)
                if fernet:
                    decrypted_data = fernet.decrypt(encrypted_data)
                    return json.loads(decrypted_data)
            else:
                return json.loads(file_content)
        except Exception as e:
            logging.error("Error loading secrets file: %s", e)
    return None

def store_key(key: SavedKey, value: str):
    """Store a secret value in the system keyring or a secure file if in Docker.

    Args:
        key (SavedKey): The key identifier for storage.
        value (str): The secret value to store.
    """
    if is_running_in_docker():
        acquire_lock()
        try:
            secrets = _get_secrets_nolock() or {}
            secrets[key.value] = value
            data_to_write = json.dumps(secrets, indent=2).encode('utf-8')
            secret_key = os.environ.get("PRINTGUARD_SECRET_KEY")
            if secret_key:
                if os.path.exists(SECRETS_FILE) and os.path.getsize(SECRETS_FILE) > 16:
                    with open(SECRETS_FILE, 'rb') as f:
                        salt = f.read(16)
                else:
                    salt = os.urandom(16)
                fernet = _get_encryption_key(salt)
                if fernet:
                    encrypted_data = fernet.encrypt(data_to_write)
                    data_to_write = salt + encrypted_data
            with open(SECRETS_FILE, 'wb') as f:
                f.write(data_to_write)
            os.chmod(SECRETS_FILE, 0o600)
        finally:
            release_lock()
    else:
        keyring.set_password(KEYRING_SERVICE_NAME, key.value, value)

def get_key(key: SavedKey):
    """Retrieve a secret value from the system keyring or a secure file if in Docker.

    Args:
        key (SavedKey): The key identifier to look up.

    Returns:
        str or None: The stored secret, or None if not found.
    """
    if is_running_in_docker():
        acquire_lock()
        try:
            secrets = _get_secrets_nolock()
            return secrets.get(key.value) if secrets else None
        finally:
            release_lock()
    else:
        return keyring.get_password(KEYRING_SERVICE_NAME, key.value)

def get_ssl_private_key_temporary_path():
    """Write the SSL private key from keyring to a temp file.

    Returns:
        str or None: The path to the temporary PEM file, or None if no key found.
    """
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
    """Delete all stored keys in the system keyring for the application."""
    if is_running_in_docker():
        acquire_lock()
        try:
            if os.path.exists(SECRETS_FILE):
                os.remove(SECRETS_FILE)
        finally:
            release_lock()
    else:
        for key in SavedKey:
            try:
                keyring.delete_password(KEYRING_SERVICE_NAME, key.value)
            except keyring.errors.PasswordDeleteError:
                pass

def reset_config():
    """Reset the configuration file to default values.

    Overwrites `config.json` with default empty fields for all SavedConfig options.
    """
    acquire_lock()
    try:
        default_config = {
            SavedConfig.VERSION: CONFIG_VERSION,
            SavedConfig.VAPID_PUBLIC_KEY: None,
            SavedConfig.VAPID_SUBJECT: None,
            SavedConfig.STARTUP_MODE: None,
            SavedConfig.SITE_DOMAIN: None,
            SavedConfig.TUNNEL_PROVIDER: None,
            SavedConfig.PUSH_SUBSCRIPTIONS: [],
            SavedConfig.CAMERA_STATES: {}
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=2)
    finally:
        release_lock()

def reset_ssl_files():
    """Remove existing SSL certificate and CA files from the app data directory."""
    for ssl_file in [SSL_CERT_FILE, SSL_CA_FILE]:
        if os.path.exists(ssl_file):
            os.remove(ssl_file)

def reset_all():
    """Reset keyring, config, and SSL files to a clean state.

    Invokes `reset_all_keys`, `reset_config`, and `reset_ssl_files` sequentially.
    """
    reset_all_keys()
    reset_config()
    reset_ssl_files()
    logging.debug("All saved keys, config, and SSL files have been reset")

BASE_DIR = os.path.dirname(os.path.dirname(__file__))

def get_model_path() -> str:
    """Get the model path for the detected backend."""
    try:
        return get_model_downloader().get_model_path()
    except ImportError:
        return os.path.join(BASE_DIR, "model", "model.onnx")

def get_model_options_path() -> str:
    """Get the model options path."""
    try:
        return get_model_downloader().get_options_path()
    except ImportError:
        return os.path.join(BASE_DIR, "model", "opt.json")

def get_prototypes_dir() -> str:
    """Get the prototypes directory path."""
    try:
        return get_model_downloader().get_prototypes_path()
    except ImportError:
        return os.path.join(BASE_DIR, "model", "prototypes")

SUCCESS_LABEL = "success"
DEVICE_TYPE = "cuda" if (torch.cuda.is_available()) else (
    "mps" if (torch.backends.mps.is_available()) else "cpu")
SENSITIVITY = 1.0
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
MIN_SSE_DISPATCH_DELAY_MS = 100
STANDARD_STAT_POLLING_RATE_MS = 250
