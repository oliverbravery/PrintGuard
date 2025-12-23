import logging
import io
import asyncio
from fastapi import APIRouter, HTTPException, Response, Security
from aiortc import RTCSessionDescription
from ...core.inference import predict
from ...core.model import get_model
from ...core.models import (
    RTCOffer, RTCAnswer, FeedSettings, 
    StreamInfo, PredictionResult, PredictionStatus
)
from ...services.webrtc import create_peer_connection, create_viewer_connection
from ...services.streams import stream_manager
from ...services.notifications import unsubscribe
from ..crypto_utils import EncryptedRoute
from ..auth_utils import get_current_identity

logger = logging.getLogger(__name__)
router = APIRouter(route_class=EncryptedRoute)


@router.get("/streams")
async def rtc_list_streams(_: any = Security(get_current_identity, scopes=["rtc:stream"])) -> list[StreamInfo]:
    """List active WebRTC streams."""
    return [
        StreamInfo(
            session_id=source.source_id,
            device_name=source.device_name,
            settings=source.settings
        )
        for source in stream_manager.list_sources()
    ]


@router.get("/snapshot/{session_id}")
async def rtc_snapshot(session_id: str, _: any = Security(get_current_identity, scopes=["rtc:stream"])) -> Response:
    """Get a snapshot from an active stream."""
    logger.debug(f"Snapshot requested for session {session_id}")
    source = stream_manager.get_source(session_id)
    if not source:
        logger.warning(f"Snapshot failed: Session {session_id} not found")
        raise HTTPException(status_code=404, detail="Session not found")
    processor = source.processor
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
async def rtc_view(session_id: str, offer: RTCOffer, _: any = Security(get_current_identity, scopes=["rtc:stream"])) -> RTCAnswer:
    """View a live stream from another session."""
    source = stream_manager.get_source(session_id)
    if not source:
        raise HTTPException(status_code=404, detail="Session not found")
    sdp = RTCSessionDescription(sdp=offer.sdp, type=offer.type)
    pc = await create_viewer_connection(sdp, source.processor)
    stream_manager.add_subscriber(session_id, pc)
    return RTCAnswer(
        sdp=pc.localDescription.sdp,
        type=pc.localDescription.type
    )

@router.post("/offer")
async def rtc_offer(offer: RTCOffer, _: any = Security(get_current_identity, scopes=["rtc:stream"])) -> RTCAnswer:
    """Accept WebRTC offer and return answer."""
    model_info = get_model()
    sdp = RTCSessionDescription(sdp=offer.sdp, type=offer.type)
    pc, processor = await create_peer_connection(
        sdp, predict, model_info, offer.settings, offer.session_id
    )
    if processor.relayed_track:
        stream_manager.register_source(
            offer.session_id, 
            processor.relayed_track, 
            processor,
            pc=pc,
            device_name=offer.device_name,
            settings=offer.settings
        )
        if offer.printer_id:
            stream_manager.add_alias(offer.session_id, offer.printer_id)
    return RTCAnswer(
        sdp=pc.localDescription.sdp,
        type=pc.localDescription.type
    )

@router.put("/settings/{session_id}")
async def rtc_update_settings(session_id: str, settings: FeedSettings, _: any = Security(get_current_identity, scopes=["rtc:stream"])) -> dict:
    """Update settings for a session."""
    source = stream_manager.get_source(session_id)
    if not source:
        return {"error": "Session not found"}
    source.settings = settings
    source.processor.settings = settings
    return {"status": "updated"}

@router.get("/result/{session_id}")
async def rtc_result(session_id: str, _: any = Security(get_current_identity, scopes=["rtc:stream"])) -> PredictionResult | dict:
    """Get latest prediction result for a session."""
    source = stream_manager.get_source(session_id)
    if not source:
        return {"error": "Session not found"}
    result = source.processor.last_result
    if result:
        return PredictionResult(**result, status=PredictionStatus.SUCCESS)
    return PredictionResult(status=PredictionStatus.WAITING)


@router.delete("/{session_id}")
async def rtc_close(session_id: str, _: any = Security(get_current_identity, scopes=["rtc:stream"])) -> dict:
    """Close a WebRTC session."""
    await stream_manager.close_source(session_id)
    unsubscribe(session_id)
    return {"status": "closed"}
