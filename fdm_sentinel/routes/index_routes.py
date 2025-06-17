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


@router.post("/save-feed-settings", include_in_schema=False)
async def save_feed_settings(settings: FeedSettings):
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
