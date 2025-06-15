import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import StreamingResponse
from .models import (SiteStartupMode,
                     TunnelProvider, SavedConfig)
from .routes.alert_routes import router as alert_router
from .routes.detection_routes import router as detection_router
from .routes.notification_routes import router as notification_router
from .routes.sse_routes import router as sse_router
from .routes.setup_routes import router as setup_router
from .routes.index_routes import router as index_router
from .routes.camera_routes import router as camera_router
from .utils.config import (get_ssl_private_key_temporary_path,
                           SSL_CERT_FILE, PROTOTYPES_DIR,
                           MODEL_PATH, MODEL_OPTIONS_PATH,
                           DEVICE_TYPE, SUCCESS_LABEL,
                           get_config, update_config)
from .utils.inference_lib import (compute_prototypes, load_model,
                                  make_transform, setup_device)
from .utils.cloudflare_utils import (start_cloudflare_tunnel, stop_cloudflare_tunnel)
from .utils.camera_utils import setup_camera_indices

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
config = get_config() or {}
app.state.subscriptions = config.get(SavedConfig.PUSH_SUBSCRIPTIONS, [])

app.state.camera_states = {}

if app.debug:
    logging.basicConfig(level=logging.DEBUG)

base_dir = os.path.dirname(__file__)
static_dir = os.path.join(base_dir, "static")
templates_dir = os.path.join(base_dir, "templates")
app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=templates_dir)

@app.get('/camera_feed/{camera_index}', include_in_schema=False)
async def camera_feed(camera_index: int):
    # pylint: disable=import-outside-toplevel
    from .utils.stream_utils import generate_frames
    return StreamingResponse(generate_frames(camera_index),
                             media_type='multipart/x-mixed-replace; boundary=frame')

app.include_router(detection_router, tags=["detection"])
app.include_router(alert_router, tags=["alerts"])
app.include_router(notification_router, tags=["notifications"])
app.include_router(sse_router, tags=["sse"])
app.include_router(setup_router, tags=["setup"])
app.include_router(index_router, tags=["index"])
app.include_router(camera_router, tags=["camera"])

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
