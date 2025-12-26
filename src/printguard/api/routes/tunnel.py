import logging
from fastapi import APIRouter, Request, Security
from ...core.models import TunnelStatus, DependencyStatus
from ...core.config import get_settings, TunnelProvider
from ...core.utils import update_env_file
from ..crypto_utils import EncryptedRoute
from ..auth_utils import get_current_identity
from ...services.tunnels import stop_active_tunnel
from ...services.tunnel import is_cloudflared_installed
from ...services.ngrok import is_ngrok_installed

logger = logging.getLogger(__name__)
router = APIRouter(route_class=EncryptedRoute)

@router.get("/status")
async def get_tunnel_status(request: Request, _: any = Security(get_current_identity, scopes=["printer:read"])) -> TunnelStatus:
    """Get current tunnel status."""
    settings = get_settings()
    tunnel_type = getattr(request.app.state, "tunnel_type", None)
    tunnel_url = getattr(request.app.state, "tunnel_url", None)
    
    # Check if process is still alive
    is_active = tunnel_type is not None
    if is_active and tunnel_type == "cloudflare":
        process = getattr(request.app.state, "tunnel_process", None)
        if process and process.returncode is not None:
            # Process has exited
            is_active = False
            request.app.state.tunnel_type = None
            logger.error(f"Cloudflare tunnel process exited with code {process.returncode}")

    return TunnelStatus(
        provider=settings.tunnel_provider,
        is_active=is_active,
        url=tunnel_url
    )

@router.get("/check-dependencies")
async def check_dependencies(_: any = Security(get_current_identity, scopes=["admin"])) -> DependencyStatus:
    """Check if external tunnel tools are installed."""
    return DependencyStatus(
        ngrok_installed=is_ngrok_installed(),
        cloudflared_installed=is_cloudflared_installed()
    )

@router.post("/disable")
async def disable_tunnel(request: Request, _: any = Security(get_current_identity, scopes=["admin"])) -> dict:
    """Disable any active tunnel and revert to local mode."""
    settings = get_settings()
    settings.tunnel_provider = TunnelProvider.LOCAL
    
    # Persist settings to .env
    update_env_file({
        "TUNNEL_PROVIDER": TunnelProvider.LOCAL.value
    })
    
    await stop_active_tunnel(request.app)
    return {"status": "success", "message": "Reverted to local mode"}
