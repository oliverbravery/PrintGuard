from fastapi import APIRouter, Request, Body
from ..utils.camera_utils import get_camera_state

router = APIRouter()

@router.post("/camera/state", include_in_schema=False)
async def get_camera_state_ep(request: Request, camera_index: int = Body(..., embed=True)):
    camera_state = await get_camera_state(camera_index)
    detection_times = [t for t, _ in camera_state.detection_history] if (
        camera_state.detection_history
        ) else []
    response = {
        "start_time": camera_state.start_time,
        "last_result": camera_state.last_result,
        "last_time": camera_state.last_time,
        "detection_times": detection_times,
        "error": camera_state.error,
        "live_detection_running": camera_state.live_detection_running,
        "brightness": camera_state.brightness,
        "contrast": camera_state.contrast,
        "focus": camera_state.focus,
        "countdown_time": camera_state.countdown_time,
        "majority_vote_threshold": camera_state.majority_vote_threshold,
        "majority_vote_window": camera_state.majority_vote_window,
        "current_alert_id": camera_state.current_alert_id,
        "sensitivity": camera_state.sensitivity,
        "printer_id": camera_state.printer_id,
        "printer_config": camera_state.printer_config,
        "countdown_action": camera_state.countdown_action
    }
    return response
