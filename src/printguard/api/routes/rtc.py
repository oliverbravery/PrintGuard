import logging
import io
import asyncio
from fastapi import APIRouter, HTTPException, Response
from aiortc import RTCSessionDescription
from ...core.inference import predict
from ...core.model import get_model
from ...core.models import (
    RTCOffer, RTCAnswer, Session, FeedSettings, 
    StreamInfo, PredictionResult, PredictionStatus
)
from ...services.webrtc import create_peer_connection, create_viewer_connection
from ...services.notifications import unsubscribe
from ..crypto_utils import EncryptedRoute

logger = logging.getLogger(__name__)
router = APIRouter(route_class=EncryptedRoute)

_sessions: dict[str, Session] = {}


def register_session(session_id: str, session: Session):
    """Register a session from outside."""
    _sessions[session_id] = session


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


@router.get("/snapshot/{session_id}")
async def rtc_snapshot(session_id: str) -> Response:
    """Get a snapshot from an active stream."""
    logger.debug(f"Snapshot requested for session {session_id}")
    session = _sessions.get(session_id)
    if not session:
        logger.warning(f"Snapshot failed: Session {session_id} not found")
        raise HTTPException(status_code=404, detail="Session not found")
    processor = session.processor
    if not processor:
        logger.warning(f"Snapshot failed: No processor for session {session_id}")
        raise HTTPException(status_code=404, detail="No processor available")
    if processor._latest_frame is None:
        logger.debug(f"No frame available for {session_id}, waiting...")
        try:
            await asyncio.wait_for(processor._frame_ready.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning(f"Snapshot failed: Timed out waiting for frame for session {session_id}")
            raise HTTPException(status_code=404, detail="No frame available")
    frame = processor._latest_frame
    if frame is None:
        logger.warning(f"Snapshot failed: Frame is still None after waiting for session {session_id}")
        raise HTTPException(status_code=404, detail="No frame available")
    try:
        image = frame.to_image()
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return Response(
            content=buffer.getvalue(),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-cache"}
        )
    except Exception as err:
        logger.error("Failed to capture snapshot: %s", err)
        raise HTTPException(status_code=500, detail="Failed to capture snapshot")

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
    if session and session.pc:
        await session.pc.close()
    unsubscribe(session_id)
    return {"status": "closed"}
