import logging
from fastapi import APIRouter, HTTPException
from aiortc import RTCSessionDescription
from ..inference import predict
from ..model import get_model
from ..models import (
    RTCOffer, RTCAnswer, Session, FeedSettings, 
    StreamInfo, PredictionResult, PredictionStatus
)
from ..webrtc import create_peer_connection, create_viewer_connection
from ..notifications import unsubscribe

logger = logging.getLogger(__name__)
router = APIRouter()

_sessions: dict[str, Session] = {}

@router.get("/streams")
async def rtc_list_streams() -> list[StreamInfo]:
    """List active WebRTC streams."""
    return [
        StreamInfo(
            session_id=session_id,
            device_name=session.device_name,
            settings=session.settings
        )
        for session_id, session in _sessions.items()
    ]

@router.post("/view/{session_id}")
async def rtc_view(session_id: str, offer: RTCOffer) -> RTCAnswer:
    """View a live stream from another session."""
    source_session = _sessions.get(session_id)
    if not source_session:
        raise HTTPException(status_code=404, detail="Session not found")

    sdp = RTCSessionDescription(sdp=offer.sdp, type=offer.type)
    pc = await create_viewer_connection(sdp, source_session.processor)

    return RTCAnswer(
        sdp=pc.localDescription.sdp,
        type=pc.localDescription.type
    )

@router.post("/offer")
async def rtc_offer(offer: RTCOffer) -> RTCAnswer:
    """Accept WebRTC offer and return answer."""
    model_info = get_model()
    sdp = RTCSessionDescription(sdp=offer.sdp, type=offer.type)
    pc, processor = await create_peer_connection(
        sdp, predict, model_info, offer.settings, offer.session_id
    )
    _sessions[offer.session_id] = Session(
        pc=pc, processor=processor, device_name=offer.device_name, settings=offer.settings
    )
    return RTCAnswer(
        sdp=pc.localDescription.sdp,
        type=pc.localDescription.type
    )

@router.put("/settings/{session_id}")
async def rtc_update_settings(session_id: str, settings: FeedSettings) -> dict:
    """Update settings for a session."""
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    session.settings = settings
    session.processor.settings = settings
    return {"status": "updated"}

@router.get("/result/{session_id}")
async def rtc_result(session_id: str) -> PredictionResult | dict:
    """Get latest prediction result for a session."""
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    result = session.processor.last_result
    if result:
        return PredictionResult(**result, status=PredictionStatus.SUCCESS)
    return PredictionResult(status=PredictionStatus.WAITING)

@router.delete("/{session_id}")
async def rtc_close(session_id: str) -> dict:
    """Close a WebRTC session."""
    session = _sessions.pop(session_id, None)
    if session:
        await session.pc.close()
    unsubscribe(session_id)
    return {"status": "closed"}
