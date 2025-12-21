from fastapi import APIRouter, Depends, HTTPException
from ...core.models import NgrokTunnelRequest, NgrokTunnelResponse
from ...services.ngrok import setup_ngrok_tunnel
from ...core.config import get_settings
from .utils import check_ngrok, check_local_mode
from ..crypto_utils import EncryptedRoute

router = APIRouter(route_class=EncryptedRoute)

@router.post("/tunnel", dependencies=[Depends(check_ngrok), Depends(check_local_mode)])
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
