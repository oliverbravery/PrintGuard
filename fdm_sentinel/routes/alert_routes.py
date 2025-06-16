import json
from fastapi import APIRouter, Body, Request
from ..models import AlertAction
from ..utils.alert_utils import (alert_to_response_json, dismiss_alert,
                                 get_alert)
from ..utils.printer_utils import suspend_print_job

router = APIRouter()

@router.post("/alert/dismiss")
async def alert_response(request: Request, 
                         alert_id: str = Body(..., embed=True),
                         action: AlertAction = Body(..., embed=True)):
    alert = get_alert(alert_id)
    camera_index = alert.camera_index if alert else None
    if not alert or camera_index is None:
        return {"message": f"Alert {alert_id} not found."}
    response = None
    match action:
        case AlertAction.DISMISS:
            response = await dismiss_alert(alert_id)
        case AlertAction.CANCEL_PRINT | AlertAction.PAUSE_PRINT:
            suspend_print_job(camera_index, action)
            return await dismiss_alert(alert_id)
    if not response:
        response = {"message": f"Alert {alert_id} not found."}
    return response

@router.get("/alert/active")
async def get_active_alerts(request: Request):
    alerts = []
    for alert in request.app.state.alerts.values():
        alerts.append(json.loads(alert_to_response_json(alert)))
    return {"active_alerts": alerts}
