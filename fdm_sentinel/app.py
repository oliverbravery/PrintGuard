from contextlib import asynccontextmanager
from collections import deque
from fastapi import (
    FastAPI, Request
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os
import time
from .utils.inference_lib import (
    compute_prototypes, load_model, make_transform, setup_device
)
from .utils.config import (
    MODEL_PATH, MODEL_OPTIONS_PATH, PROTOTYPES_DIR, SUCCESS_LABEL, DEVICE_TYPE,
    VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, MAX_CAMERA_HISTORY
)
from .routes.notification_routes import router as notification_router
from .routes.alert_routes import router as alert_router
from .routes.detection_routes import router as detection_router
from .routes.live_detection_routes import router as live_detection_router
from .routes.settings_routes import settings_router
from .utils import config

@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    print("Setting up device...")
    app_instance.state.device = setup_device(DEVICE_TYPE)
    print(f"Using device: {app_instance.state.device}")
    try:
        print("Loading model...")
        app_instance.state.model, _ = load_model(MODEL_PATH, MODEL_OPTIONS_PATH, app_instance.state.device)
        app_instance.state.transform = make_transform()
        print("Model loaded successfully.")
        print("Building prototypes...")
        try:
            prototypes, class_names, defect_idx = compute_prototypes(
                app_instance.state.model, PROTOTYPES_DIR, app_instance.state.transform, 
                app_instance.state.device, SUCCESS_LABEL
            )
            app_instance.state.prototypes = prototypes
            app_instance.state.class_names = class_names
            app_instance.state.defect_idx = defect_idx
            print("Prototypes built successfully.")
        except NameError:
            print("Skipping prototype building: Potentially missing 'args' if not run as main script or if function expects it.")
        except ValueError as e:
            print(f"Error building prototypes: {e}")

    except RuntimeError as e:
        print(f"Error during startup: {e}")
        app_instance.state.model = None
        raise
    yield
    print("Shutting down...")

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
app.state.class_names = ['Successful', 'Defective']
app.state.defect_idx = -1
app.state.alerts = {}

app.state.camera_states = {}

def get_camera_state(camera_index, reset=False):
    """
    Get or create a state object for a specific camera index.
    This function is exported for use by other modules.
    """
    if camera_index not in app.state.camera_states or reset:
        app.state.camera_states[camera_index] = {
            "current_alert_id": None,
            "detection_history": deque(maxlen=MAX_CAMERA_HISTORY),
            "live_detection_running": False,
            "live_detection_task": None,
            "last_result": None,
            "last_time": None,
            "start_time": None,
            "error": None,
            "brightness": config.BRIGHTNESS,
            "contrast": config.CONTRAST,
            "focus": config.FOCUS,
            "sensitivity": config.SENSITIVITY,
            "countdown_time": config.COUNTDOWN_TIME,
            "warning_intervals": ",".join(str(x) for x in config.WARNING_INTERVALS),
            "majority_vote_threshold": config.DETECTION_VOTING_THRESHOLD,
            "majority_vote_window": config.DETECTION_VOTING_WINDOW, 
        }
    return app.state.camera_states[camera_index]

def update_camera_state(camera_index, new_states):
    """
    Update states of a specific camera index.
    new_states should be a dictionary only containing the keys to be updated.
    """
    if camera_index in app.state.camera_states:
        camera_state = app.state.camera_states[camera_index]
        for key, value in new_states.items():
            if key in camera_state:
                camera_state[key] = value
            else:
                print(f"Warning: Key '{key}' not found in camera state.")
    else:
        print(f"Warning: Camera index '{camera_index}' not found in camera states.")
    return app.state.camera_states[camera_index]

def update_camera_detection_history(camera_index, pred, time):
    """
    Append a detection to a camera's detection history.
    """
    camera_state = get_camera_state(camera_index)
    if camera_state:
        camera_state["detection_history"].append((time, pred))
        return camera_state
    else:
        print(f"Warning: Camera index '{camera_index}' not found in camera states.")
        return None

get_camera_state(config.CAMERA_INDEX)
get_camera_state(1)

base_dir = os.path.dirname(__file__)
static_dir = os.path.join(base_dir, "static")
templates_dir = os.path.join(base_dir, "templates")
app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=templates_dir)

@app.get("/", include_in_schema=False)
async def serve_index(request: Request):
    camera_index = list(app.state.camera_states.keys())[0] if app.state.camera_states else config.CAMERA_INDEX
    return templates.TemplateResponse("index.html", {
        "camera_states": app.state.camera_states,
        "request": request,
        "camera_index": camera_index,
        "current_time": time.time(),
    })

@app.get("/sw.js", include_in_schema=False)
async def serve_sw():
    sw_path = os.path.join(static_dir, "js", "sw.js")
    return FileResponse(sw_path, media_type="application/javascript")

app.include_router(notification_router, prefix="/notifications", tags=["notifications"])
app.include_router(alert_router) 
app.include_router(detection_router)
app.include_router(live_detection_router)
app.include_router(settings_router, prefix="", tags=["settings"])

def run():
    import uvicorn
    if not all([VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY]):
        print("Warning: VAPID keys not configured. Push notifications will fail.")
    uvicorn.run(app, host="0.0.0.0", port=8000, ssl_certfile=".cert.pem", ssl_keyfile=".key.pem")

if __name__ == "__main__":
    run()
