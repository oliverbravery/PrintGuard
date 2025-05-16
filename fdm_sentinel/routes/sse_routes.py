from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse
from ..utils.sse_utils import outbound_packet_fetch

router = APIRouter()

@router.get("/sse")
async def sse_connect(request: Request):
    async def send_packet():
        async for packet in outbound_packet_fetch():
            if await request.is_disconnected():
                break
            yield packet
    return EventSourceResponse(send_packet())