from fastapi import APIRouter, Request, Body
from sse_starlette.sse import EventSourceResponse
from ..utils.sse_utils import outbound_packet_fetch, stop_and_remove_polling_task
from ..utils.printer_utils import start_printer_state_polling

router = APIRouter()

@router.get("/sse")
async def sse_connect(request: Request):
    async def send_packet():
        async for packet in outbound_packet_fetch():
            if await request.is_disconnected():
                break
            yield packet
    return EventSourceResponse(send_packet())

@router.post("/sse/start-polling")
async def start_polling(request: Request, camera_index: int = Body(..., embed=True)):
    await start_printer_state_polling(camera_index)
    return {"message": "Polling started for camera index {}".format(camera_index)}

@router.post("/sse/stop-polling")
async def stop_polling(request: Request, camera_index: int = Body(..., embed=True)):
    stop_and_remove_polling_task(camera_index)
    return {"message": "Polling stopped for camera index {}".format(camera_index)}
