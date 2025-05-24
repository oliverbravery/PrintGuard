import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

import cv2
from fastapi import FastAPI, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, StreamingResponse
from .models import CameraState
from .routes.alert_routes import router as alert_router
from .routes.detection_routes import router as detection_router
from .routes.live_detection_routes import router as live_detection_router
from .routes.notification_routes import router as notification_router
from .routes.sse_routes import router as sse_router
from .routes.setup_routes import router as setup_router
from .utils import config
from .utils.config import (DEVICE_TYPE, MODEL_OPTIONS_PATH, MODEL_PATH,
                           PROTOTYPES_DIR, SUCCESS_LABEL, SSL_CERT_FILE,
                           get_ssl_private_key)
from .utils.inference_lib import (compute_prototypes, load_model,
                                  make_transform, setup_device)
from .utils.setup_utils import verify_setup_complete, is_setup_complete


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    if is_setup_complete():
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
                logging.warning("Skipping prototype building: Potentially missing 'args' if not run as main script or if function expects it.")
            except ValueError as e:
                logging.error("Error building prototypes: %s", e)

        except RuntimeError as e:
            logging.error("Error during startup: %s", e)
            app_instance.state.model = None
            raise
    else:
        logging.info("Setup not complete. Limited functionality available until setup is complete.")
    yield

    logging.debug("Shutting down...")

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

@app.middleware("http")
async def check_setup_status(request: Request, call_next):
    redirect = await verify_setup_complete(request)
    if redirect:
        return redirect
    response = await call_next(request)
    return response

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

# pylint: disable=W0621
def get_camera_state(camera_index, reset=False):
    """
    Get or create a state object for a specific camera index.
    This function is exported for use by other modules.
    """
    if camera_index not in app.state.camera_states or reset:
        app.state.camera_states[camera_index] = CameraState()
    return app.state.camera_states[camera_index]

# pylint: disable=W0621
async def update_camera_state(camera_index, new_states):
    """
    Update states of a specific camera index.
    new_states should be a dictionary only containing the keys to be updated.
    """
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
    else:
        logging.warning("Camera index '%d' not found when trying to update detection history.",
                        camera_index)
        return None

def detect_available_cameras(max_cameras=config.MAX_CAMERAS):
    available_cameras = []
    for i in range(max_cameras):
        # pylint: disable=E1101
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            available_cameras.append(i)
            cap.release()
    return available_cameras

available_cameras = detect_available_cameras()
available_cameras.extend(config.CAMERA_INDICES)
if not available_cameras:
    get_camera_state(config.CAMERA_INDEX)
    logging.warning("No cameras detected. Using default camera index %d", config.CAMERA_INDEX)
else:
    for camera_index in available_cameras:
        get_camera_state(camera_index)
    logging.debug("Detected %d cameras: %s", len(available_cameras), available_cameras)

base_dir = os.path.dirname(__file__)
static_dir = os.path.join(base_dir, "static")
templates_dir = os.path.join(base_dir, "templates")
app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=templates_dir)

@app.get("/", include_in_schema=False)
async def serve_index(request: Request):
    camera_index = list(app.state.camera_states.keys())[0] if (
        app.state.camera_states
        ) else config.CAMERA_INDEX
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

def run():
    # pylint: disable=C0415
    import uvicorn
    from .utils.setup_utils import is_setup_complete
    setup_complete = is_setup_complete()
    if not setup_complete:
        logging.warning("Setup not complete. Starting server in HTTP mode on port 8000.")
        logging.debug("Please visit http://localhost:8000/setup to complete setup.")
        uvicorn.run(app, host="0.0.0.0", port=8000)
    elif setup_complete:
        logging.warning("Setup complete and SSL certificates found. Starting server in HTTPS mode on port 8000.")
        uvicorn.run(app, host="0.0.0.0", port=8000, ssl_certfile=SSL_CERT_FILE, ssl_keyfile=get_ssl_private_key())
    else:
        raise RuntimeError(
            "Setup is complete but SSL certificates are not available. "
            "Please generate or upload SSL certificates to continue."
        )

if __name__ == "__main__":
    run()
