import logging
from fastapi import APIRouter, Depends, Query, HTTPException
from ..models import CFAccount, CFZone, CFTunnelRequest, CFTunnelResponse
from ..tunnel import CloudflareManager
from .utils import check_cloudflared, check_local_mode

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/accounts", dependencies=[Depends(check_cloudflared), Depends(check_local_mode)])
async def list_cf_accounts(api_token: str = Query(...)) -> list[CFAccount]:
    """List Cloudflare accounts."""
    try:
        manager = CloudflareManager(api_token)
        accounts = await manager.list_accounts()
        return [CFAccount(id=a.id, name=a.name) for a in accounts]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/zones", dependencies=[Depends(check_cloudflared), Depends(check_local_mode)])
async def list_cf_zones(api_token: str = Query(...)) -> list[CFZone]:
    """List Cloudflare zones."""
    try:
        manager = CloudflareManager(api_token)
        zones = await manager.list_zones()
        return [CFZone(id=z.id, name=z.name) for z in zones]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/tunnel", dependencies=[Depends(check_cloudflared), Depends(check_local_mode)])
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
