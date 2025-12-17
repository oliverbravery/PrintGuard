from fastapi import APIRouter, Request
from ...core.models import TunnelStatus
from ...core.config import get_settings, TunnelProvider

router = APIRouter()

@router.get("/status")
async def get_tunnel_status(request: Request) -> TunnelStatus:
    """Get current tunnel status."""
    settings = get_settings()
    tunnel_type = getattr(request.app.state, "tunnel_type", None)
    tunnel_url = getattr(request.app.state, "tunnel_url", None)
    return TunnelStatus(
        provider=settings.tunnel_provider,
        is_active=tunnel_type is not None,
        url=tunnel_url
    )

@router.post("/disable")
async def disable_tunnel(request: Request) -> dict:
    """Disable any active tunnel and revert to local mode."""
    settings = get_settings()
    settings.tunnel_provider = TunnelProvider.LOCAL
    request.app.state.tunnel_type = None
    request.app.state.tunnel_url = None
    return {"status": "success", "message": "Reverted to local mode"}
