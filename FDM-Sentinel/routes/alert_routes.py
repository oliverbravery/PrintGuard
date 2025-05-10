import io
from fastapi import APIRouter, HTTPException, Request, WebSocket
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates

import utils.config as config

from utils.camera_utils import websocket_camera_feed_handler, alerts

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/alert/{alert_id}", include_in_schema=False)
async def alert_page_ep(request: Request, alert_id: str):
    if alert_id not in alerts:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert_info = alerts[alert_id]
    context = {
        "request": request,
        "alert_id": alert_id,
        "countdown_time": config.COUNTDOWN_TIME,
        "warning_intervals": config.WARNING_INTERVALS,
        "start_time": alert_info['timestamp']
    }
    return templates.TemplateResponse("alert_page.html", context)

@router.post("/alert/{alert_id}/dismiss", include_in_schema=False)
async def dismiss_alert_ep(alert_id: str, request: Request):
    app_state = request.app.state
    if alert_id not in alerts:
        raise HTTPException(status_code=404, detail="Alert not found to dismiss.")
    camera_index = alerts[alert_id].get('camera_index')
    
    if camera_index is not None and camera_index in app_state.camera_states:
        camera_state = app_state.camera_states[camera_index]
        if camera_state.get('current_alert_id') == alert_id:
            camera_state['current_alert_id'] = None
        if 'detection_times' in camera_state and hasattr(camera_state['detection_times'], 'clear'):
            camera_state['detection_times'].clear()
    else:
        if getattr(app_state, 'current_alert_id', None) == alert_id:
            app_state.current_alert_id = None
        if hasattr(app_state, 'detection_times') and hasattr(app_state.detection_times, 'clear'):
            app_state.detection_times.clear()
    
    del alerts[alert_id]
    print(f"Alert {alert_id} dismissed and removed. Camera index: {camera_index}")
    return {"message": f"Alert {alert_id} dismissed."}

@router.get("/alert/{alert_id}/snapshot", include_in_schema=False)
async def alert_snapshot_ep(alert_id: str):
    if alert_id not in alerts or 'snapshot' not in alerts[alert_id]:
        raise HTTPException(status_code=404, detail="Snapshot not found for this alert.")
    data = alerts[alert_id]['snapshot']
    return StreamingResponse(io.BytesIO(data), media_type='image/jpeg')

@router.websocket("/ws/camera_feed")
async def websocket_camera_feed_ep(websocket: WebSocket):
    await websocket_camera_feed_handler(websocket)
