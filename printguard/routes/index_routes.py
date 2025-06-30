import time
import logging

from fastapi import Form, Request, APIRouter
from fastapi.exceptions import HTTPException
from fastapi.responses import RedirectResponse

from ..utils.config import (STREAM_MAX_FPS, STREAM_TUNNEL_FPS,
                            STREAM_JPEG_QUALITY, STREAM_MAX_WIDTH,
                            DETECTION_INTERVAL_MS, PRINTER_STAT_POLLING_RATE_MS,
                            TUNNEL_STAT_POLLING_RATE_MS, CAMERA_INDEX,
                            update_config, get_config)
from ..utils.camera_utils import update_camera_state, setup_camera_indices
from ..utils.camera_state_manager import get_camera_state_manager
from ..utils.stream_utils import stream_optimizer
from ..models import FeedSettings, SavedConfig

router = APIRouter()

@router.get("/", include_in_schema=False)
async def serve_index(request: Request):
    """Serve the main index page with camera states and configuration.

    Args:
        request (Request): The FastAPI request object.

    Returns:
        TemplateResponse: Rendered index.html template with camera states and settings.
    """
    # pylint: disable=import-outside-toplevel
    from ..app import templates
    camera_state_manager = get_camera_state_manager()
    camera_indices = await camera_state_manager.get_all_camera_indices()
    if not camera_indices:
        logging.warning("No camera indices found, attempting to initialize cameras...")
        await setup_camera_indices()
        camera_indices = await camera_state_manager.get_all_camera_indices()
    camera_states = {}
    for cam_idx in camera_indices:
        camera_states[cam_idx] = await camera_state_manager.get_camera_state(cam_idx)
    camera_index = camera_indices[0] if camera_indices else CAMERA_INDEX
    return templates.TemplateResponse("index.html", {
        "camera_states": camera_states,
        "request": request,
        "camera_index": camera_index,
        "current_time": time.time(),
    })

# pylint: disable=unused-argument
@router.post("/", include_in_schema=False)
async def update_settings(request: Request,
                          camera_index: int = Form(...),
                          sensitivity: float = Form(...),
                          brightness: float = Form(...),
                          contrast: float = Form(...),
                          focus: float = Form(...),
                          countdown_time: int = Form(...),
                          countdown_action: str = Form(...),
                          majority_vote_threshold: int = Form(...),
                          majority_vote_window: int = Form(...),
                          ):
    """Update camera settings and detection parameters.

    Args:
        request (Request): The FastAPI request object.
        camera_index (int): Index of the camera to update settings for.
        sensitivity (float): Detection sensitivity level.
        brightness (float): Camera brightness setting.
        contrast (float): Camera contrast setting.
        focus (float): Camera focus setting.
        countdown_time (int): Alert countdown duration in seconds.
        countdown_action (str): Action to take when countdown expires.
        majority_vote_threshold (int): Number of detections needed for majority vote.
        majority_vote_window (int): Time window for majority vote calculation.

    Returns:
        RedirectResponse: Redirect to the main index page.
    """
    await update_camera_state(camera_index, {
        "sensitivity": sensitivity,
        "brightness": brightness,
        "contrast": contrast,
        "focus": focus,
        "countdown_time": countdown_time,
        "countdown_action": countdown_action,
        "majority_vote_threshold": majority_vote_threshold,
        "majority_vote_window": majority_vote_window,
    })
    return RedirectResponse("/", status_code=303)


@router.post("/save-feed-settings", include_in_schema=False)
async def save_feed_settings(settings: FeedSettings):
    """Save camera feed and detection settings to configuration.

    Args:
        settings (FeedSettings): Feed configuration settings including FPS,
                                quality, detection intervals, and polling rates.

    Returns:
        dict: Success status and message indicating settings were saved.

    Raises:
        HTTPException: If saving settings fails due to validation or storage errors.
    """
    try:
        config_data = {
            SavedConfig.STREAM_MAX_FPS: settings.stream_max_fps,
            SavedConfig.STREAM_TUNNEL_FPS: settings.stream_tunnel_fps,
            SavedConfig.STREAM_JPEG_QUALITY: settings.stream_jpeg_quality,
            SavedConfig.STREAM_MAX_WIDTH: settings.stream_max_width,
            SavedConfig.DETECTION_INTERVAL_MS: settings.detection_interval_ms,
            SavedConfig.PRINTER_STAT_POLLING_RATE_MS: settings.printer_stat_polling_rate_ms,
            SavedConfig.TUNNEL_STAT_POLLING_RATE_MS: settings.tunnel_stat_polling_rate_ms
        }
        update_config(config_data)
        stream_optimizer.invalidate_cache()
        logging.debug("Feed settings saved successfully.")
        return {"success": True, "message": "Feed settings saved successfully."}
    except Exception as e:
        logging.error("Error saving feed settings: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save feed settings: {str(e)}"
        )

@router.get("/get-feed-settings", include_in_schema=False)
async def get_feed_settings():
    """Retrieve current camera feed and detection settings.

    Returns:
        dict: Current feed settings including FPS, quality, detection intervals,
              polling rates, and calculated detections per second.

    Raises:
        HTTPException: If loading settings fails due to configuration errors.
    """
    try:
        config = get_config()
        # pylint:disable=import-outside-toplevel
        settings = {
            "stream_max_fps": config.get(SavedConfig.STREAM_MAX_FPS, STREAM_MAX_FPS),
            "stream_tunnel_fps": config.get(SavedConfig.STREAM_TUNNEL_FPS, STREAM_TUNNEL_FPS),
            "stream_jpeg_quality": config.get(SavedConfig.STREAM_JPEG_QUALITY, STREAM_JPEG_QUALITY),
            "stream_max_width": config.get(SavedConfig.STREAM_MAX_WIDTH, STREAM_MAX_WIDTH),
            "detection_interval_ms": config.get(SavedConfig.DETECTION_INTERVAL_MS, DETECTION_INTERVAL_MS),
            "printer_stat_polling_rate_ms": config.get(SavedConfig.PRINTER_STAT_POLLING_RATE_MS, PRINTER_STAT_POLLING_RATE_MS),
            "tunnel_stat_polling_rate_ms": config.get(SavedConfig.TUNNEL_STAT_POLLING_RATE_MS, TUNNEL_STAT_POLLING_RATE_MS)
        }
        settings["detections_per_second"] = round(1000 / settings["detection_interval_ms"])
        return {"success": True, "settings": settings}
    except Exception as e:
        logging.error("Error loading feed settings: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load feed settings: {str(e)}"
        )
