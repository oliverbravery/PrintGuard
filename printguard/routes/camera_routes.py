import logging
import time
import uuid

import cv2  # pylint: disable=E0401
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..utils.camera_utils import (add_camera, find_available_serial_cameras,
                                  get_camera_state)
from ..utils.camera_utils import remove_camera as remove_camera_util
from ..utils.shared_video_stream import get_shared_stream_manager
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

@router.post("/camera/remove")
async def remove_camera_ep(request: Request):
    """Remove a camera."""
    data = await request.json()
    camera_uuid = data.get('camera_uuid')
    if not camera_uuid:
        raise HTTPException(status_code=400, detail="Missing camera_uuid.")
    success = await remove_camera_util(camera_uuid)
    if not success:
        raise HTTPException(status_code=404, detail="Camera not found.")
    return {"message": "Camera removed successfully."}

@router.get("/camera/serial_devices")
async def get_serial_devices_ep():
    """Get a list of available serial devices."""
    devices = find_available_serial_cameras()
    return devices

def generate_preview_frames(source: str):
    """Generate frames for camera preview using shared video stream.
    
    Args:
        source (str): The camera source (device path or RTSP URL).
        
    Yields:
        bytes: Multipart JPEG frame data.
    """
    preview_uuid = f"preview_{uuid.uuid4()}"
    manager = get_shared_stream_manager()
    try:
        stream = manager.get_stream(preview_uuid, source)
        max_wait = 50
        wait_count = 0
        while not stream.is_frame_available() and wait_count < max_wait:
            time.sleep(0.1)
            wait_count += 1
        if not stream.is_frame_available():
            logging.error("Failed to get initial frame from source: %s", source)
            return
        while True:
            frame = stream.get_frame()
            if frame is None:
                logging.warning("Failed to get frame from source: %s", source)
                time.sleep(0.1)
                continue
            _, buffer = cv2.imencode('.jpg', frame)
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            time.sleep(0.2) 
    except (cv2.error, OSError, RuntimeError) as e:
        logging.error("Error in preview frame generation for source %s: %s", source, e)
    finally:
        try:
            manager.release_stream(preview_uuid)
        except (AttributeError, RuntimeError) as cleanup_error:
            logging.error("Error cleaning up preview stream %s: %s", preview_uuid, cleanup_error)

@router.get('/camera/preview', include_in_schema=False)
async def camera_preview(source: str):
    """Stream live camera preview for a specific source without registration.

    Args:
        source (str): Camera source (device path or RTSP URL).

    Returns:
        StreamingResponse: MJPEG streaming response with camera frames.
    """
    return StreamingResponse(generate_preview_frames(source),
                             media_type='multipart/x-mixed-replace; boundary=frame')
