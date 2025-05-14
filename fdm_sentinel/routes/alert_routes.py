from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse
from ..utils.alert_utils import alert_generator
from PIL import Image
import base64
import io

router = APIRouter()

@router.get("/alert/sse")
async def alert_sse(request: Request):
    async def send_alerts():
        async for alert in alert_generator():
            if await request.is_disconnected():
                break
            img_bytes = alert.snapshot
            buffer = io.BytesIO()
            Image.open(io.BytesIO(img_bytes)).save(buffer, format="JPEG")
            alert.snapshot = base64.b64encode(buffer.getvalue()).decode("utf-8")
            yield alert.to_json()
    return EventSourceResponse(send_alerts())
