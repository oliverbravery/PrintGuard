"""API routes."""

import asyncio
import logging
from typing import Annotated

from aiortc import RTCSessionDescription
from fastapi import APIRouter, File, Query, UploadFile, HTTPException, Depends

from .inference import predict
from .model import get_model
from .models import (
    RTCOffer, RTCAnswer, PushSubscription, Session, FeedSettings, 
    StreamInfo, PredictionResult, PredictionStatus,
    CFAccount, CFZone, CFTunnelRequest, CFTunnelResponse,
    NgrokTunnelRequest, NgrokTunnelResponse
)
from .notifications import subscribe, unsubscribe, VAPID_PUBLIC_KEY
from .webrtc import create_peer_connection, create_viewer_connection
from .tunnel import CloudflareManager, is_cloudflared_installed
from .ngrok import setup_ngrok_tunnel, is_ngrok_installed
from .config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()

def check_cloudflared():
    """Dependency to check if cloudflared is installed."""
    if not is_cloudflared_installed():
        raise HTTPException(
            status_code=503, 
            detail="cloudflared binary not found on system. Please install it to use Cloudflare features."
        )

def check_ngrok():
    """Dependency to check if ngrok is installed."""
    if not is_ngrok_installed():
        raise HTTPException(
            status_code=503, 
            detail="ngrok-python package not found. Please install it to use ngrok features."
        )

_sessions: dict[str, Session] = {}


@router.post("/predict")
async def predict_image(
    file: Annotated[UploadFile, File(description="Image to classify")],
    sensitivity: Annotated[float, Query(ge=0.1, le=10.0)] = 1.0
) -> PredictionResult:
    """Predict print defect class for an uploaded image."""
    contents = await file.read()
    model_info = get_model()
    result = await asyncio.to_thread(predict, contents, model_info, sensitivity)
    return PredictionResult(**result)


@router.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}


@router.get("/rtc/streams")
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


@router.post("/rtc/view/{session_id}")
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


@router.post("/rtc/offer")
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


@router.put("/rtc/settings/{session_id}")
async def rtc_update_settings(session_id: str, settings: FeedSettings) -> dict:
    """Update settings for a session."""
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    session.settings = settings
    session.processor.settings = settings
    return {"status": "updated"}


@router.get("/rtc/result/{session_id}")
async def rtc_result(session_id: str) -> PredictionResult | dict:
    """Get latest prediction result for a session."""
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    result = session.processor.last_result
    if result:
        return PredictionResult(**result, status=PredictionStatus.SUCCESS)
    return PredictionResult(status=PredictionStatus.WAITING)


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


@router.get("/cloudflare/accounts", dependencies=[Depends(check_cloudflared)])
async def list_cf_accounts(api_token: str = Query(...)) -> list[CFAccount]:
    """List Cloudflare accounts."""
    try:
        manager = CloudflareManager(api_token)
        accounts = await manager.list_accounts()
        return [CFAccount(id=a.id, name=a.name) for a in accounts]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/cloudflare/zones", dependencies=[Depends(check_cloudflared)])
async def list_cf_zones(api_token: str = Query(...)) -> list[CFZone]:
    """List Cloudflare zones."""
    try:
        manager = CloudflareManager(api_token)
        zones = await manager.list_zones()
        return [CFZone(id=z.id, name=z.name) for z in zones]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/cloudflare/tunnel", dependencies=[Depends(check_cloudflared)])
async def create_cf_tunnel(
    request: CFTunnelRequest, 
    api_token: str = Query(...)
) -> CFTunnelResponse:
    """Create a Cloudflare tunnel and DNS record."""
    try:
        manager = CloudflareManager(api_token)
        # 1. Create or get the Tunnel
        tunnel = await manager.create_tunnel(request.account_id, request.tunnel_name)
        # 2. Create or update the DNS Record
        await manager.create_dns_record(request.zone_id, request.subdomain, tunnel.id)
        # 3. Get Zone name for the URL
        zones = await manager.list_zones()
        zone_name = next((z.name for z in zones if z.id == request.zone_id), "unknown")
        secret = getattr(tunnel, "tunnel_secret", "already-configured") or "already-configured"
        return CFTunnelResponse(
            tunnel_id=tunnel.id,
            tunnel_secret=secret,
            url=f"https://{request.subdomain}.{zone_name}"
        )
    except Exception as e:
        logger.error(f"Cloudflare tunnel setup failed: {e}")
        raise HTTPException(
            status_code=400, 
            detail=f"Cloudflare error: {str(e)}"
        )


@router.post("/ngrok/tunnel", dependencies=[Depends(check_ngrok)])
async def create_ngrok_tunnel(request: NgrokTunnelRequest) -> NgrokTunnelResponse:
    """Create an ngrok tunnel."""
    settings = get_settings()
    url = await setup_ngrok_tunnel(
        authtoken=request.authtoken,
        domain=request.domain,
        edge=request.edge,
        port=settings.port
    )
    if not url:
        raise HTTPException(status_code=400, detail="Failed to set up ngrok tunnel")
    return NgrokTunnelResponse(url=url)


@router.get("/push/vapid-key")
async def get_vapid_key() -> dict:
    """Get VAPID public key for push subscription."""
    return {"publicKey": VAPID_PUBLIC_KEY}

