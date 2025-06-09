import asyncio
import logging
import os
import subprocess
import time
from contextlib import asynccontextmanager

import cv2
from fastapi import FastAPI, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, StreamingResponse
from .models import (CameraState, SiteStartupMode,
                     TunnelProvider, SavedConfig,
                     OperatingSystem, SavedKey)
from .routes.alert_routes import router as alert_router
from .routes.detection_routes import router as detection_router
from .routes.live_detection_routes import router as live_detection_router
from .routes.notification_routes import router as notification_router
from .routes.sse_routes import router as sse_router
from .routes.setup_routes import router as setup_router
from .routes.debug_routes import router as debug_router
from .utils.config import (get_ssl_private_key_temporary_path,
                           SSL_CERT_FILE, PROTOTYPES_DIR,
                           MODEL_PATH, MODEL_OPTIONS_PATH,
                           DEVICE_TYPE, SUCCESS_LABEL,
                           CAMERA_INDICES, MAX_CAMERAS,
                           CAMERA_INDEX, get_config,
                           update_config, get_key)
from .utils.cloudflare_utils import CloudflareOSCommands
from .utils.inference_lib import (compute_prototypes, load_model,
                                  make_transform, setup_device)

def get_current_os() -> OperatingSystem:
    config = get_config()
    stored_os = config.get(SavedConfig.USER_OPERATING_SYSTEM)
    if stored_os:
        return OperatingSystem(stored_os)

def start_cloudflare_tunnel() -> bool:
    try:
        current_os = get_current_os()
        if not current_os:
            raise ValueError("Current OS not set in config.")
        tunnel_token = get_key(SavedKey.TUNNEL_TOKEN)
        if not tunnel_token:
            raise ValueError("Tunnel token not found. Please complete tunnel setup first.")
        start_command = CloudflareOSCommands.get_start_command(current_os, "", tunnel_token, 8000)
        logging.debug("Starting Cloudflare tunnel with command: %s", start_command)
        result = subprocess.run(start_command, shell=True,
                             capture_output=True, text=True,
                             timeout=30, check=False)
        if result.returncode == 0:
            logging.debug("Cloudflare tunnel started successfully")
            return True
        else:
            logging.warning("Non-privileged start failed: %s", result.stderr)
            logging.info("User may need to manually run command with elevated privileges")
            return True
    except subprocess.TimeoutExpired:
        logging.error("Timeout starting Cloudflare tunnel")
        return False
    except (OSError, ValueError) as e:
        logging.error("Error starting Cloudflare tunnel: %s", e)
        return False
    except Exception as e:
        logging.error("Unexpected error starting Cloudflare tunnel: %s", e)
        return False

def stop_cloudflare_tunnel() -> bool:
    try:
        current_os = get_current_os()
        if not current_os:
            raise ValueError("Current OS not set in config.")
        stop_command = CloudflareOSCommands.get_stop_command(current_os)
        logging.debug("Stopping Cloudflare tunnel with command: %s", stop_command)
        result = subprocess.run(stop_command, shell=True,
                             capture_output=True, text=True,
                             timeout=30, check=False)
        if result.returncode == 0:
            logging.debug("Cloudflare tunnel stopped successfully")
            return True
        else:
            logging.warning("Non-privileged stop failed: %s", result.stderr)
            logging.info("User may need to manually run command with elevated privileges")
            return True
    except subprocess.TimeoutExpired:
        logging.error("Timeout stopping Cloudflare tunnel")
        return False
    except (OSError, ValueError) as e:
        logging.error("Error stopping Cloudflare tunnel: %s", e)
        return False
    except Exception as e:
        logging.error("Unexpected error stopping Cloudflare tunnel: %s", e)
        return False

# pylint: disable=W0621
def get_camera_state(camera_index, reset=False):
    if camera_index not in app.state.camera_states or reset:
        app.state.camera_states[camera_index] = CameraState()
    return app.state.camera_states[camera_index]

# pylint: disable=W0621
async def update_camera_state(camera_index, new_states):
    camera_state_ref = app.state.camera_states.get(camera_index)
    if camera_state_ref:
        lock = camera_state_ref.lock
        async with lock:
            for key, value in new_states.items():
                if hasattr(camera_state_ref, key):
                    setattr(camera_state_ref, key, value)
                else:
                    logging.warning("Key '%s' not found in camera state for index %d.",
                                    key,
                                    camera_index)
        return camera_state_ref
    logging.warning("Camera index '%d' not found in camera states during update.", camera_index)
    return None

def detect_available_cameras(max_cameras=MAX_CAMERAS):
    available_cameras = []
    for i in range(max_cameras):
        # pylint: disable=E1101
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            available_cameras.append(i)
            cap.release()
    return available_cameras

def setup_camera_indices():
    available_cameras = detect_available_cameras()
    available_cameras.extend(CAMERA_INDICES)
    if not available_cameras:
        get_camera_state(CAMERA_INDEX)
        logging.warning("No cameras detected. Using default camera index %d", CAMERA_INDEX)
    else:
        for camera_index in available_cameras:
            get_camera_state(camera_index)
        logging.debug("Detected %d cameras: %s", len(available_cameras), available_cameras)

@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    # pylint: disable=C0415
    from .utils.setup_utils import startup_mode_requirements_met
    startup_mode = startup_mode_requirements_met()
    if startup_mode is SiteStartupMode.SETUP:
        logging.warning("Starting in setup mode. Detection model and device will not be initialized.")
        yield
        return
    logging.debug("Setting up device...")
    app_instance.state.device = setup_device(DEVICE_TYPE)
    logging.debug("Using device: %s", app_instance.state.device)
    try:
        logging.debug("Loading model...")
        app_instance.state.model, _ = load_model(MODEL_PATH,
                                                MODEL_OPTIONS_PATH,
                                                app_instance.state.device)
        app_instance.state.transform = make_transform()
        logging.debug("Model loaded successfully.")
        logging.debug("Building prototypes...")
        try:
            prototypes, class_names, defect_idx = compute_prototypes(
                app_instance.state.model, PROTOTYPES_DIR, app_instance.state.transform,
                app_instance.state.device, SUCCESS_LABEL
            )
            app_instance.state.prototypes = prototypes
            app_instance.state.class_names = class_names
            app_instance.state.defect_idx = defect_idx
            logging.debug("Prototypes built successfully.")
        except NameError:
            logging.warning("Skipping prototype building.")
        except ValueError as e:
            logging.error("Error building prototypes: %s", e)
    except RuntimeError as e:
        logging.error("Error during startup: %s", e)
        app_instance.state.model = None
        raise
    logging.debug("Setting up camera indices...")
    setup_camera_indices()
    logging.debug("Camera indices set up successfully.")
    yield

app = FastAPI(
    title="Standalone Web Push Notification API",
    description="API to register subscriptions and send web push notifications, including scheduled recurring notifications.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.model = None
app.state.transform = None
app.state.device = None
app.state.prototypes = None
app.state.class_names = ['success', 'failure']
app.state.defect_idx = -1
app.state.alerts = {}
app.state.outbound_queue = asyncio.Queue()
app.state.subscriptions = []

app.state.camera_states = {}

if app.debug:
    logging.basicConfig(level=logging.DEBUG)

async def update_camera_detection_history(camera_index, pred, time_val):
    """
    Append a detection to a camera's detection history.
    """
    camera_state_ref = get_camera_state(camera_index)
    if camera_state_ref:
        lock = camera_state_ref.lock
        async with lock:
            camera_state_ref.detection_history.append((time_val, pred))
        return camera_state_ref
    logging.warning("Camera index '%d' not found when trying to update detection history.",
                    camera_index)
    return None

base_dir = os.path.dirname(__file__)
static_dir = os.path.join(base_dir, "static")
templates_dir = os.path.join(base_dir, "templates")
app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=templates_dir)

@app.get("/", include_in_schema=False)
async def serve_index(request: Request):
    camera_index = list(app.state.camera_states.keys())[0] if (
        app.state.camera_states
        ) else CAMERA_INDEX
    return templates.TemplateResponse("index.html", {
        "camera_states": app.state.camera_states,
        "request": request,
        "camera_index": camera_index,
        "current_time": time.time(),
    })

# pylint: disable=unused-argument
@app.post("/", include_in_schema=False)
async def update_settings(request: Request,
                          camera_index: int = Form(...),
                          sensitivity: float = Form(...),
                          brightness: float = Form(...),
                          contrast: float = Form(...),
                          focus: float = Form(...),
                          countdown_time: int = Form(...),
                          majority_vote_threshold: int = Form(...),
                          majority_vote_window: int = Form(...),
                          ):
    await update_camera_state(camera_index, {
        "sensitivity": sensitivity,
        "brightness": brightness,
        "contrast": contrast,
        "focus": focus,
        "countdown_time": countdown_time,
        "majority_vote_threshold": majority_vote_threshold,
        "majority_vote_window": majority_vote_window,
    })
    return RedirectResponse("/", status_code=303)

def generate_frames(camera_index: int):
    # pylint: disable=E1101
    cap = cv2.VideoCapture(camera_index)
    while True:
        camera_state = get_camera_state(camera_index)
        contrast = camera_state.contrast
        brightness = camera_state.brightness
        focus = camera_state.focus

        success, frame = cap.read()
        if not success:
            break
        frame = cv2.convertScaleAbs(frame, alpha=contrast, beta=int((brightness - 1.0) * 255))
        if focus and focus != 1.0:
            blurred = cv2.GaussianBlur(frame, (0, 0), sigmaX=focus)
            frame = cv2.addWeighted(frame, 1.0 + focus, blurred, -focus, 0)
        _, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
    cap.release()

@app.get('/camera_feed/{camera_index}', include_in_schema=False)
async def camera_feed(camera_index: int):
    return StreamingResponse(generate_frames(camera_index),
                             media_type='multipart/x-mixed-replace; boundary=frame')

@app.get("/onboarding", include_in_schema=False)
async def serve_onboarding(request: Request):
    return templates.TemplateResponse("onboarding.html", {
        "request": request
    })

app.include_router(detection_router, tags=["detection"])
app.include_router(live_detection_router, tags=["live_detection"])
app.include_router(alert_router, tags=["alerts"])
app.include_router(notification_router, tags=["notifications"])
app.include_router(sse_router, tags=["sse"])
app.include_router(setup_router, tags=["setup"])
app.include_router(debug_router, tags=["debug"])

def run():
    # pylint: disable=C0415
    import uvicorn
    from .utils.setup_utils import (startup_mode_requirements_met,
                                    setup_ngrok_tunnel)
    startup_mode = startup_mode_requirements_met()
    config = get_config()
    site_domain = config.get(SavedConfig.SITE_DOMAIN, "")
    tunnel_provider = config.get(SavedConfig.TUNNEL_PROVIDER, None)
    stop_cloudflare_tunnel()
    match startup_mode:
        case SiteStartupMode.SETUP:
            logging.warning("Starting in setup mode. Available at http://localhost:8000/setup")
            uvicorn.run(app, host="0.0.0.0", port=8000)
        case SiteStartupMode.LOCAL:
            logging.warning("Starting in local mode. Available at %s", site_domain)
            ssl_private_key_path = get_ssl_private_key_temporary_path()
            uvicorn.run(app,
                        host="0.0.0.0",
                        port=8000,
                        ssl_certfile=SSL_CERT_FILE,
                        ssl_keyfile=ssl_private_key_path)
        case SiteStartupMode.TUNNEL:
            match tunnel_provider:
                case TunnelProvider.NGROK:
                    logging.warning("Starting in tunnel mode with ngrok. Available at %s", site_domain)
                    tunnel_setup = setup_ngrok_tunnel(close=False)
                    if not tunnel_setup:
                        logging.error("Failed to establish ngrok tunnel. Starting in SETUP mode.")
                        update_config({SavedConfig.STARTUP_MODE: SiteStartupMode.SETUP})
                        run()
                    else:
                        uvicorn.run(app, host="0.0.0.0", port=8000)
                case TunnelProvider.CLOUDFLARE:
                    logging.warning("Starting in tunnel mode with Cloudflare.")
                    if start_cloudflare_tunnel():
                        logging.warning("Cloudflare tunnel started. Available at %s", site_domain)
                        uvicorn.run(app, host="0.0.0.0", port=8000)
                    else:
                        logging.error("Failed to start Cloudflare tunnel. Starting in SETUP mode.")
                        update_config({SavedConfig.STARTUP_MODE: SiteStartupMode.SETUP})
                        run()

if __name__ == "__main__":
    run()
