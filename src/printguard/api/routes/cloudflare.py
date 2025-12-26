import logging
from fastapi import APIRouter, Depends, Query, HTTPException, Security, Request
from ...core.models import CFAccount, CFZone, CFTunnelRequest, CFTunnelResponse, CFExistenceResponse
from ...services.tunnel import CloudflareManager, run_tunnel
from ...services.tunnels import stop_active_tunnel
from ...core.config import get_settings, TunnelProvider
from ...core.utils import generate_random_string, update_env_file
from .utils import check_cloudflared
from ..crypto_utils import EncryptedRoute
from ..auth_utils import get_current_identity

logger = logging.getLogger(__name__)
router = APIRouter(route_class=EncryptedRoute)

@router.get("/validate-token", dependencies=[Depends(check_cloudflared)])
async def validate_cf_token(api_token: str = Query(...), _: any = Security(get_current_identity, scopes=["tunnel:manage"])) -> dict:
    """Validate a Cloudflare API token."""
    try:
        manager = CloudflareManager(api_token)
        await manager.list_accounts()
        return {"status": "success", "valid": True}
    except Exception as e:
        return {"status": "error", "valid": False, "detail": str(e)}

@router.get("/check-existence", dependencies=[Depends(check_cloudflared)])
async def check_existence(
    account_id: str = Query(...),
    zone_id: str = Query(...),
    tunnel_name: str = Query(...),
    subdomain: str = Query(...),
    api_token: str = Query(...),
    _: any = Security(get_current_identity, scopes=["tunnel:manage"])
) -> CFExistenceResponse:
    """Check if tunnel or DNS record already exists."""
    try:
        manager = CloudflareManager(api_token)
        tunnel = await manager.get_tunnel_by_name(account_id, tunnel_name)
        
        zones = await manager.list_zones()
        zone_name = next((z.name for z in zones if z.id == zone_id), "")
        full_name = f"{subdomain}.{zone_name}" if zone_name else subdomain
        
        dns_record = await manager.get_dns_record(zone_id, full_name)
        
        return CFExistenceResponse(
            tunnel_exists=tunnel is not None,
            dns_exists=dns_record is not None
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/accounts", dependencies=[Depends(check_cloudflared)])
async def list_cf_accounts(api_token: str = Query(...), _: any = Security(get_current_identity, scopes=["tunnel:manage"])) -> list[CFAccount]:
    """List Cloudflare accounts."""
    try:
        manager = CloudflareManager(api_token)
        accounts = await manager.list_accounts()
        return [CFAccount(id=a.id, name=a.name) for a in accounts]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/zones", dependencies=[Depends(check_cloudflared)])
async def list_cf_zones(api_token: str = Query(...), _: any = Security(get_current_identity, scopes=["tunnel:manage"])) -> list[CFZone]:
    """List Cloudflare zones."""
    try:
        manager = CloudflareManager(api_token)
        zones = await manager.list_zones()
        return [CFZone(id=z.id, name=z.name) for z in zones]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/tunnel", dependencies=[Depends(check_cloudflared)])
async def create_cf_tunnel(
    request: Request,
    body: CFTunnelRequest, 
    api_token: str = Query(...),
    _: any = Security(get_current_identity, scopes=["tunnel:manage"])
) -> CFTunnelResponse:
    """Create a Cloudflare tunnel and DNS record."""
    try:
        manager = CloudflareManager(api_token)
        
        # 1. Get Zone name for DNS record construction
        zones = await manager.list_zones()
        zone_name = next((z.name for z in zones if z.id == body.zone_id), None)
        if not zone_name:
            raise HTTPException(status_code=400, detail="Cloudflare Zone not found")
            
        full_dns_name = f"{body.subdomain}.{zone_name}"

        # 2. Create or get the Tunnel
        tunnel = await manager.create_tunnel(body.account_id, body.tunnel_name, overwrite=body.overwrite_tunnel)
        
        secret = getattr(tunnel, "tunnel_secret", "")
        # If we didn't get a secret (re-using tunnel), we MUST reset it to be able to run it via token
        if not secret:
            logger.info(f"Re-using existing tunnel {tunnel.id}, resetting secret to enable token-based run")
            secret = await manager.reset_tunnel_secret(body.account_id, tunnel.id)

        # 3. Create or update the DNS Record
        await manager.create_dns_record(body.zone_id, full_dns_name, tunnel.id, overwrite=body.overwrite_dns)
        
        url = f"https://{full_dns_name}"
        
        # 4. Update settings and start the tunnel
        settings = get_settings()
        settings.tunnel_provider = TunnelProvider.CLOUDFLARE
        settings.cloudflare_api_token = api_token
        settings.cloudflare_domain = zone_name
        settings.cloudflare_tunnel_name = body.tunnel_name
        settings.cloudflare_subdomain = body.subdomain
        settings.cloudflare_tunnel_id = tunnel.id
        settings.cloudflare_tunnel_secret = secret
        settings.cloudflare_account_id = body.account_id
        
        # Persist settings to .env
        update_env_file({
            "TUNNEL_PROVIDER": TunnelProvider.CLOUDFLARE.value,
            "CLOUDFLARE_API_TOKEN": api_token,
            "CLOUDFLARE_DOMAIN": zone_name,
            "CLOUDFLARE_TUNNEL_NAME": body.tunnel_name,
            "CLOUDFLARE_SUBDOMAIN": body.subdomain,
            "CLOUDFLARE_TUNNEL_ID": tunnel.id,
            "CLOUDFLARE_TUNNEL_SECRET": secret,
            "CLOUDFLARE_ACCOUNT_ID": body.account_id
        })
        
        await stop_active_tunnel(request.app)
        process = await run_tunnel(tunnel.id, secret, body.account_id, settings.webui_port)
        if process:
            request.app.state.tunnel_process = process
            request.app.state.tunnel_type = "cloudflare"
            request.app.state.tunnel_url = url
            request.app.state.tunnel_id = tunnel.id
            request.app.state.tunnel_secret = secret
            request.app.state.cf_account_id = body.account_id
        else:
            raise HTTPException(status_code=500, detail="Tunnel created but failed to start process")

        return CFTunnelResponse(
            tunnel_id=tunnel.id,
            tunnel_secret=secret,
            url=url
        )
    except Exception as e:
        logger.error(f"Cloudflare tunnel setup failed: {e}")
        raise HTTPException(
            status_code=400, 
            detail=f"Cloudflare error: {str(e)}"
        )
