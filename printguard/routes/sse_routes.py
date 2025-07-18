from fastapi import APIRouter, Request, Body
from sse_starlette.sse import EventSourceResponse
from ..utils.sse_utils import outbound_packet_fetch, stop_and_remove_polling_task
from ..utils.printer_utils import start_printer_state_polling

router = APIRouter()

@router.get("/sse")
async def sse_connect(request: Request):
    """Establish Server-Sent Events connection for real-time updates.

    Args:
        request (Request): The FastAPI request object for connection management.

    Returns:
        EventSourceResponse: SSE stream for real-time data updates.
    """
    async def send_packet():
        async for packet in outbound_packet_fetch():
            if await request.is_disconnected():
                break
            yield packet
    return EventSourceResponse(send_packet())

@router.post("/sse/start-polling")
async def start_polling(request: Request, camera_uuid: str = Body(..., embed=True)):
    """Start polling for printer state updates on a specific camera.

    Args:
        request (Request): The FastAPI request object.
        camera_uuid (str): UUID of the camera to start polling for.

    Returns:
        dict: Confirmation message that polling was started.
    """
    await start_printer_state_polling(camera_uuid)
    return {"message": "Polling started for camera UUID {}".format(camera_uuid)}

@router.post("/sse/stop-polling")
async def stop_polling(request: Request, camera_uuid: str = Body(..., embed=True)):
    """Stop polling for printer state updates on a specific camera.

    Args:
        request (Request): The FastAPI request object.
        camera_uuid (str): UUID of the camera to stop polling for.

    Returns:
        dict: Confirmation message that polling was stopped.
    """
    stop_and_remove_polling_task(camera_uuid)
    return {"message": "Polling stopped for camera UUID {}".format(camera_uuid)}
