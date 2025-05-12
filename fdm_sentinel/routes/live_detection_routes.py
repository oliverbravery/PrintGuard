import asyncio
from fastapi import APIRouter, HTTPException, Request, Body
from fastapi.responses import StreamingResponse
import time
from ..utils.camera_utils import _webcam_generator, _live_detection_loop

router = APIRouter()

@router.get("/live")
async def live_detection_feed(request: Request):
    from ..utils.config import CAMERA_INDEX
    
    if (request.app.state.model is None or
        request.app.state.transform is None or
        request.app.state.device is None or
        request.app.state.prototypes is None):
        raise HTTPException(status_code=503, detail="Model not loaded or not ready.")
    
    return StreamingResponse(
        _webcam_generator(
            request.app.state.model, 
            request.app.state.transform, 
            request.app.state.device, 
            request.app.state.class_names, 
            request.app.state.prototypes, 
            request.app.state.defect_idx,
            CAMERA_INDEX,
            request.app.state
        ), 
        media_type="text/event-stream"
    )

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
    update_camera_state(camera_index, {"start_time": None,
                                       "live_detection_running": False,
                                       "live_detection_task": None})
    
    if live_detection_task:
        try:
            await asyncio.wait_for(live_detection_task, timeout=5.0)
            print(f"Live detection task for camera {camera_index} finished successfully.")
        except asyncio.TimeoutError:
            print(f"Live detection task for camera {camera_index} did not finish in time.")
            if live_detection_task:
                live_detection_task.cancel()
        except Exception as e:
            print(f"Error stopping live detection task for camera {camera_index}: {e}")
        finally:
            live_detection_task = None
    
    return {"message": f"Live detection stopped for camera {camera_index}"}

@router.post("/live/camera", include_in_schema=False)
async def set_camera_index(camera_index: int = Body(..., embed=True)):
    from ..utils import config
    import cv2
    from ..app import get_camera_state

    camera_state = get_camera_state(camera_index)
    
    try:
        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            camera_state["error"] = f"Cannot open camera {camera_index}"
            config.CAMERA_INDEX = camera_index
            return {"message": f"Camera index set to {camera_index}, but camera is not available", "error": camera_state["error"]}
        camera_state["error"] = None
        cap.release()
    except Exception as e:
        camera_state["error"] = f"Error accessing camera {camera_index}: {str(e)}"
        config.CAMERA_INDEX = camera_index
        return {"message": f"Camera index set to {camera_index}, but with error", "error": camera_state["error"]}
    config.CAMERA_INDEX = camera_index
    
    return {"message": f"Camera index set to {camera_index}"}

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

@router.get("/live/status", tags=["live"])
async def live_status(request: Request):
    """
    Returns whether live detection is running and the current camera index.
    Also returns status for all active cameras.
    """
    from ..utils.config import CAMERA_INDEX
    from ..app import get_camera_state
    
    camera_state = get_camera_state(CAMERA_INDEX)
    camera_statuses = {}
    for cam_idx in request.app.state.camera_states:
        cam_state = request.app.state.camera_states[cam_idx]
        camera_statuses[str(cam_idx)] = {
            "running": cam_state["live_detection_running"],
            "last_result": cam_state.get("last_result"),
            "last_time": cam_state.get("last_time"),
            "error": cam_state.get("error")
        }
    
    return {
        "running": camera_state["live_detection_running"],
        "camera_index": CAMERA_INDEX,
        "camera_statuses": camera_statuses
    }
