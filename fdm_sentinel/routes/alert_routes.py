import json
from fastapi import APIRouter, Body, Request
from ..models import AlertAction
from ..utils.alert_utils import (alert_to_response_json, cancel_print,
                                 dismiss_alert)

router = APIRouter()

@router.post("/alert/dismiss")
async def alert_response(request: Request, 
                         alert_id: str = Body(..., embed=True),
                         action: AlertAction = Body(..., embed=True)):
    alert = request.app.state.alerts.get(alert_id, None)
    if not alert:
        return {"message": f"Alert {alert_id} not found."}
    response = None
    match action:
        case AlertAction.DISMISS:
            response = await dismiss_alert(alert_id)
        case AlertAction.CANCEL_PRINT:
            response = await cancel_print(alert_id)
    if not response:
        response = {"message": f"Alert {alert_id} not found."}
    return response

@router.get("/alert/active")
async def get_active_alerts(request: Request):
    alerts = []
    for alert in request.app.state.alerts.values():
        alerts.append(json.loads(alert_to_response_json(alert)))
    return {"active_alerts": alerts}
