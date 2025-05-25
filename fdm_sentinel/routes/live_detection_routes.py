import asyncio
import logging
import time

from fastapi import APIRouter, Body, Request

from ..utils.detection_utils import _live_detection_loop

router = APIRouter()


@router.post("/live/start")
async def start_live_detection(request: Request, camera_index: int = Body(..., embed=True)):
    """
    Starts live detection for the specified camera index.
    Resets the camera state before starting detection.
    """
    # pylint: disable=C0415,W0621
    from ..app import get_camera_state, update_camera_state
    camera_state = get_camera_state(camera_index)
    if camera_state.live_detection_running:
        return {"message": f"Live detection already running for camera {camera_index}"}
    else:
        camera_state = get_camera_state(camera_index, reset=True)
    await update_camera_state(camera_index, {"start_time": time.time(),
                                       "live_detection_running": True,
                                       "live_detection_task": asyncio.create_task(
                                           _live_detection_loop(request.app.state, camera_index)
                                           )})
    return {"message": f"Live detection started for camera {camera_index}"}

# pylint: disable=unused-argument
@router.post("/live/stop")
async def stop_live_detection(request: Request, camera_index: int = Body(..., embed=True)):
    """
    Stops live detection for the specified camera index.
    """
    # pylint: disable=C0415,W0621
    from ..app import get_camera_state, update_camera_state
    camera_state = get_camera_state(camera_index)
    if not camera_state.live_detection_running:
        return {"message": f"Live detection not running for camera {camera_index}"}
    live_detection_task = camera_state.live_detection_task
    if live_detection_task:
        try:
            await asyncio.wait_for(live_detection_task, timeout=0.25)
            logging.debug("Live detection task for camera %d finished successfully.", camera_index)
        except asyncio.TimeoutError:
            logging.debug("Live detection task for camera %d did not finish in time.", camera_index)
            if live_detection_task:
                live_detection_task.cancel()
        except Exception as e:
            logging.error("Error stopping live detection task for camera %d: %s", camera_index, e)
        finally:
            live_detection_task = None
    await update_camera_state(camera_index, {"start_time": None,
                                    "live_detection_running": False,
                                    "live_detection_task": None})
    return {"message": f"Live detection stopped for camera {camera_index}"}

@router.post("/live/camera", include_in_schema=False)
async def get_camera_state(request: Request, camera_index: int = Body(..., embed=True)):
    """
    Get the state of a specific camera index.
    """
    # pylint: disable=C0415,W0621
    from ..app import get_camera_state as _get_camera_state
    camera_state = _get_camera_state(camera_index)
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
        "sensitivity": camera_state.sensitivity
    }
    return response

@router.get("/live/available_cameras")
async def get_available_cameras(request: Request):
    """
    Returns a list of all available camera indices.
    """
    return {"camera_indices": list(request.app.state.camera_states.keys())}
