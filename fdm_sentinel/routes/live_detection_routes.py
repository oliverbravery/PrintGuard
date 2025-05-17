import asyncio
from fastapi import APIRouter, Request, Body
import time
from ..utils.detection_utils import _live_detection_loop

router = APIRouter()


@router.post("/live/start")
async def start_live_detection(request: Request, camera_index: int = Body(..., embed=True)):
    """
    Starts live detection for the specified camera index.
    Resets the camera state before starting detection.
    """
    from ..app import get_camera_state, update_camera_state
    camera_state = get_camera_state(camera_index)
    if camera_state["live_detection_running"]:
        return {"message": f"Live detection already running for camera {camera_index}"}
    else:
        camera_state = get_camera_state(camera_index, reset=True)
    await update_camera_state(camera_index, {"start_time": time.time(),
                                       "live_detection_running": True,
                                       "live_detection_task": asyncio.create_task(
                                           _live_detection_loop(request.app.state, camera_index)
                                           )})
    return {"message": f"Live detection started for camera {camera_index}"}

@router.post("/live/stop")
async def stop_live_detection(request: Request, camera_index: int = Body(..., embed=True)):
    """
    Stops live detection for the specified camera index.
    """
    from ..app import get_camera_state, update_camera_state
    camera_state = get_camera_state(camera_index)
    if not camera_state["live_detection_running"]:
        return {"message": f"Live detection not running for camera {camera_index}"}
    live_detection_task = camera_state["live_detection_task"]
    if live_detection_task:
        try:
            await asyncio.wait_for(live_detection_task, timeout=0.25)
            print(f"Live detection task for camera {camera_index} finished successfully.")
        except asyncio.TimeoutError:
            print(f"Live detection task for camera {camera_index} did not finish in time.")
            if live_detection_task:
                live_detection_task.cancel()
        except Exception as e:
            print(f"Error stopping live detection task for camera {camera_index}: {e}")
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
    from ..app import get_camera_state as _get_camera_state
    camera_state = _get_camera_state(camera_index)
    response = {
        "start_time": camera_state.get("start_time"),
        "last_result": camera_state.get("last_result"),
        "last_time": camera_state.get("last_time"),
        "detection_times": list(camera_state.get("detection_times", [])),
        "error": camera_state.get("error"),
        "live_detection_running": camera_state.get("live_detection_running"),
        "brightness": camera_state.get("brightness"),
        "contrast": camera_state.get("contrast"),
        "focus": camera_state.get("focus"),
        "countdown_time": camera_state.get("countdown_time"),
        "warning_intervals": camera_state.get("warning_intervals"),
        "majority_vote_threshold": camera_state.get("majority_vote_threshold"),
        "majority_vote_window": camera_state.get("majority_vote_window"),
        "current_alert_id": camera_state.get("current_alert_id"),
        "sensitivity": camera_state.get("sensitivity")
    }
    return response
