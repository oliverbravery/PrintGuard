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
    """Handle alert response actions including dismiss, cancel, and pause.

    Args:
        request (Request): The FastAPI request object.
        alert_id (str): Unique identifier of the alert to act upon.
        action (AlertAction): The action to perform on the alert.

    Returns:
        dict: Response containing the result of the action or error message.
    """
    alert = get_alert(alert_id)
    camera_uuid = alert.camera_uuid if alert else None
    if not alert or camera_uuid is None:
        return {"message": f"Alert {alert_id} not found."}
    response = None
    match action:
        case AlertAction.DISMISS:
            response = await dismiss_alert(alert_id)
        case AlertAction.CANCEL_PRINT | AlertAction.PAUSE_PRINT:
            suspend_print_job(camera_uuid, action)
            return await dismiss_alert(alert_id)
    if not response:
        response = {"message": f"Alert {alert_id} not found."}
    return response

@router.get("/alert/active")
async def get_active_alerts(request: Request):
    """Retrieve all currently active alerts.

    Args:
        request (Request): The FastAPI request object containing app state.

    Returns:
        dict: Dictionary containing a list of active alerts with their details.
    """
    alerts = []
    for alert in request.app.state.alerts.values():
        alerts.append(json.loads(alert_to_response_json(alert)))
    return {"active_alerts": alerts}
