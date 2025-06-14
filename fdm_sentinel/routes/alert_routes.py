from fastapi import APIRouter, Body, Request
from ..utils.alert_utils import dismiss_alert, cancel_print
from ..models import AlertAction

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
    active_alerts = [alert for alert in request.app.state.alerts.values()]
    return {"active_alerts": active_alerts}
