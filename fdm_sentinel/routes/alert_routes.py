from fastapi import APIRouter, Body, Request
from sse_starlette.sse import EventSourceResponse
from ..utils.alert_utils import (alert_generator,
                                 dismiss_alert,
                                 cancel_print,
                                 get_unseen_alerts,
                                 alert_to_response_json)
from ..models import AlertAction

router = APIRouter()

@router.get("/alert/sse")
async def alert_sse(request: Request):
    async def send_alerts():
        seen_alerts = request.cookies.get("seen_alerts", "").split(",") if request.cookies.get("seen_alerts") else []
        unseen_alerts = get_unseen_alerts(seen_alerts, request.app)
        for alert in unseen_alerts:
            yield alert_to_response_json(alert)
            
        async for alert in alert_generator():
            if await request.is_disconnected():
                break
            yield alert_to_response_json(alert)
    return EventSourceResponse(send_alerts())

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
            response = dismiss_alert(alert_id)
        case AlertAction.CANCEL_PRINT:
            response = cancel_print(alert_id)
    if not response:
        response = {"message": f"Alert {alert_id} not found."}
    return response
