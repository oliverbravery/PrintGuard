from fastapi import APIRouter, Request, Body, HTTPException
from fastapi.responses import StreamingResponse
from ..utils.camera_utils import (
    get_camera_state,
    find_available_serial_cameras,
    add_camera
)
from ..utils.stream_utils import generate_frames

router = APIRouter()

@router.post("/camera/state", include_in_schema=False)
async def get_camera_state_ep(request: Request, camera_uuid: str = Body(..., embed=True)):
    """Get the current state of a specific camera.

    Args:
        request (Request): The FastAPI request object.
        camera_uuid (str): UUID of the camera to retrieve state for.

    Returns:
        dict: Dictionary containing comprehensive camera state information including
              detection history, settings, error status, and printer configuration.
    """
    camera_state = await get_camera_state(camera_uuid)
    detection_times = [t for t, _ in camera_state.detection_history] if (
        camera_state.detection_history
        ) else []
    response = {
        "nickname": camera_state.nickname,
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

@router.get('/camera/feed/{camera_uuid}', include_in_schema=False)
async def camera_feed(camera_uuid: str):
    """Stream live camera feed for a specific camera.

    Args:
        camera_uuid (str): UUID of the camera to stream from.

    Returns:
        StreamingResponse: MJPEG streaming response with camera frames.
    """
    return StreamingResponse(generate_frames(camera_uuid),
                             media_type='multipart/x-mixed-replace; boundary=frame')

@router.post("/camera/add")
async def add_camera_ep(request: Request):
    """Add a new camera."""
    data = await request.json()
    nickname = data.get('nickname')
    source = data.get('source')
    if not nickname or not source:
        raise HTTPException(status_code=400, detail="Missing camera nickname or source.")
    camera = await add_camera(source=source, nickname=nickname)
    return {"camera_uuid": camera['camera_uuid'], "nickname": camera['nickname'], "source": camera['source']}

@router.get("/camera/serial_devices")
async def get_serial_devices_ep():
    """Get a list of available serial devices."""
    devices = find_available_serial_cameras()
    return devices
