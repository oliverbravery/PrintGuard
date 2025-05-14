from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse
from ..utils.alert_utils import alert_generator

router = APIRouter()

@router.get("/alert/sse")
async def alert_sse(request: Request):
    async def send_alerts():
        async for alert in alert_generator():
            if await request.is_disconnected():
                break
            yield alert
    return EventSourceResponse(send_alerts())
