import asyncio
from fastapi import APIRouter, HTTPException, Request, Body, WebSocket
from fastapi.responses import StreamingResponse
import time
from ..utils.camera_utils import _live_detection_loop
from ..utils.config import DETECTION_POLLING_RATE

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
    update_camera_state(camera_index, {"start_time": time.time(),
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
    print(f"camera_state: {camera_state}")
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
    update_camera_state(camera_index, {"start_time": None,
                                    "live_detection_running": False,
                                    "live_detection_task": None})
    
    return {"message": f"Live detection stopped for camera {camera_index}"}

@router.get("/live/alerts")
async def live_alerts_feed(request: Request):
    async def events():
        import asyncio, json
        last_ids = set()
        def any_camera_running():
            return any(
                cam_state.get("live_detection_running", False)
                for cam_state in request.app.state.camera_states.values()
            )
        
        while any_camera_running():
            new_ids = set(request.app.state.alerts.keys()) - last_ids
            for alert_id in new_ids:
                info = request.app.state.alerts[alert_id]
                alert_data = {
                    'alert_id': alert_id, 
                    'timestamp': info['timestamp']
                }
                if 'camera_index' in info:
                    alert_data['camera_index'] = info['camera_index']
                
                yield f"data: {json.dumps(alert_data)}\n\n"
                last_ids.add(alert_id)
                
            await asyncio.sleep(0.5)
    return StreamingResponse(events(), media_type="text/event-stream")

@router.post("/live/camera", include_in_schema=False)
async def get_camera_state(request: Request, camera_index: int = Body(..., embed=True)):
    """
    Get the state of a specific camera index.
    """
    from ..app import get_camera_state as _get_camera_state  # avoid name clash
    camera_state = _get_camera_state(camera_index)
    response = {
        "start_time": camera_state.get("start_time"),
        "last_result": camera_state.get("last_result"),
        "last_time": camera_state.get("last_time"),
        "detection_times": list(camera_state.get("detection_times", [])),
        "error": camera_state.get("error"),
    }
    return response

def _calculate_frame_rate(detection_history):
    """
    Calculate average frame rate from detection history.
    detection_history: list of (timestamp, prediction) tuples
    Returns: average frames per second (float)
    """
    if len(detection_history) < 2:
        return 0.0
    times = [t for t, _ in detection_history]
    duration = times[-1] - times[0]
    return (len(times) - 1) / duration if duration > 0 else 0.0

@router.websocket("/ws/camera/{camera_index}")
async def camera_ws(websocket: WebSocket, camera_index: int):
    from ..app import get_camera_state as _get_camera_state
    await websocket.accept()
    while True:
        state = _get_camera_state(camera_index)
        detection_history = state.get("detection_history", [])
        total_detections = len(detection_history)
        frame_rate = _calculate_frame_rate(detection_history)
        data = {
            "start_time": state.get("start_time"),
            "last_result": state.get("last_result"),
            "last_time": state.get("last_time"),
            "total_detections": total_detections,
            "frame_rate": frame_rate,
            "error": state.get("error"),
        }
        await websocket.send_json(data)
        import asyncio; await asyncio.sleep(DETECTION_POLLING_RATE)
