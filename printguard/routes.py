"""API routes."""

import asyncio
from typing import Annotated

from aiortc import RTCSessionDescription
from fastapi import APIRouter, File, Query, UploadFile

from .inference import predict
from .model import get_model
from .models import RTCOffer, PushSubscription, Session
from .notifications import subscribe, unsubscribe, VAPID_PUBLIC_KEY
from .webrtc import create_peer_connection

router = APIRouter()

_sessions: dict[str, Session] = {}



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
    pc, processor = await create_peer_connection(
        sdp, predict, model_info, offer.sensitivity, offer.session_id
    )
    _sessions[offer.session_id] = Session(
        pc=pc, processor=processor, device_name=offer.device_name
    )
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
    result = session.processor.last_result
    return result if result else {"status": "waiting"}


@router.delete("/rtc/{session_id}")
async def rtc_close(session_id: str) -> dict:
    """Close a WebRTC session."""
    session = _sessions.pop(session_id, None)
    if session:
        await session.pc.close()
    unsubscribe(session_id)
    return {"status": "closed"}


@router.post("/push/subscribe")
async def push_subscribe(data: PushSubscription) -> dict:
    """Subscribe to push notifications for a session."""
    subscribe(data.session_id, data.subscription, data.device_name)
    return {"status": "subscribed"}


@router.delete("/push/{session_id}")
async def push_unsubscribe(session_id: str) -> dict:
    """Unsubscribe from push notifications."""
    unsubscribe(session_id)
    return {"status": "unsubscribed"}


@router.get("/push/vapid-key")
async def get_vapid_key() -> dict:
    """Get VAPID public key for push subscription."""
    return {"publicKey": VAPID_PUBLIC_KEY}

