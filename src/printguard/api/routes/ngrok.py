from fastapi import APIRouter, Depends, HTTPException, Security, Request
from ...core.models import NgrokTunnelRequest, NgrokTunnelResponse
from ...services.ngrok import setup_ngrok_tunnel
from ...services.tunnels import stop_active_tunnel
from ...core.config import get_settings, TunnelProvider
from ...core.utils import update_env_file
from .utils import check_ngrok
from ..crypto_utils import EncryptedRoute
from ..auth_utils import get_current_identity

router = APIRouter(route_class=EncryptedRoute)

@router.post("/tunnel", dependencies=[Depends(check_ngrok)])
async def create_ngrok_tunnel(request: Request, body: NgrokTunnelRequest, _: any = Security(get_current_identity, scopes=["tunnel:manage"])) -> NgrokTunnelResponse:
    """Create an ngrok tunnel."""
    settings = get_settings()
    
    # Update settings
    settings.tunnel_provider = TunnelProvider.NGROK
    settings.ngrok_authtoken = body.authtoken
    settings.ngrok_domain = body.domain or ""
    settings.ngrok_edge = body.edge or ""
    
    # Persist settings to .env
    update_env_file({
        "TUNNEL_PROVIDER": TunnelProvider.NGROK.value,
        "NGROK_AUTHTOKEN": body.authtoken,
        "NGROK_DOMAIN": body.domain or "",
        "NGROK_EDGE": body.edge or ""
    })
    
    await stop_active_tunnel(request.app)
    url = await setup_ngrok_tunnel(
        authtoken=body.authtoken,
        domain=body.domain,
        edge=body.edge,
        port=settings.webui_port
    )
    if not url:
        raise HTTPException(status_code=400, detail="Failed to set up ngrok tunnel")
    
    request.app.state.tunnel_type = "ngrok"
    request.app.state.tunnel_url = url
    
    return NgrokTunnelResponse(url=url)
