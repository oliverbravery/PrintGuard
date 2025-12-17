"""API routes."""

import asyncio
from typing import Annotated

from aiortc import RTCSessionDescription
from fastapi import APIRouter, File, Query, UploadFile
from pydantic import BaseModel

from .inference import predict
from .model import get_model
from .webrtc import create_peer_connection

router = APIRouter()

_sessions: dict[str, dict] = {}

class RTCOffer(BaseModel):
    sdp: str
    type: str
    session_id: str
    sensitivity: float = 1.0

@router.post("/predict")
async def predict_image(
    file: Annotated[UploadFile, File(description="Image to classify")],
    sensitivity: Annotated[float, Query(ge=0.1, le=10.0)] = 1.0
) -> dict:
    """Predict print defect class for an uploaded image."""
    contents = await file.read()
    model_info = get_model()
    result = await asyncio.to_thread(predict, contents, model_info, sensitivity)
    return result


@router.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}


@router.post("/rtc/offer")
async def rtc_offer(offer: RTCOffer) -> dict:
    """Accept WebRTC offer and return answer."""
    model_info = get_model()
    sdp = RTCSessionDescription(sdp=offer.sdp, type=offer.type)
    pc, processor = await create_peer_connection(sdp, predict, model_info, offer.sensitivity)
    _sessions[offer.session_id] = {"pc": pc, "processor": processor}
    return {
        "sdp": pc.localDescription.sdp,
        "type": pc.localDescription.type
    }


@router.get("/rtc/result/{session_id}")
async def rtc_result(session_id: str) -> dict:
    """Get latest prediction result for a session."""
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    result = session["processor"].last_result
    return result if result else {"status": "waiting"}


@router.delete("/rtc/{session_id}")
async def rtc_close(session_id: str) -> dict:
    """Close a WebRTC session."""
    session = _sessions.pop(session_id, None)
    if session:
        await session["pc"].close()
    return {"status": "closed"}

