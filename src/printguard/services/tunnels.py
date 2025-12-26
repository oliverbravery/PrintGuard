"""Unified tunnel management."""

import logging
import asyncio
from ..core.config import Settings, TunnelProvider
from .tunnel import setup_tunnel as setup_cloudflare, run_tunnel as run_cloudflare
from .ngrok import setup_ngrok_tunnel

logger = logging.getLogger(__name__)

async def stop_active_tunnel(app):
    """Stop any active tunnel and clean up state."""
    if hasattr(app.state, "tunnel_process") and app.state.tunnel_process:
        process = app.state.tunnel_process
        logger.info(f"Stopping tunnel process (PID: {process.pid})...")
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            process.kill()
        app.state.tunnel_process = None
    
    app.state.tunnel_type = None
    app.state.tunnel_url = None
    app.state.tunnel_id = None

async def setup_active_tunnel(app, settings: Settings):
    """Set up the configured tunnel provider."""
    await stop_active_tunnel(app)
    
    provider = settings.tunnel_provider
    
    if provider == TunnelProvider.LOCAL:
        logger.info("Using local connection (no tunnel).")
        return True

    if provider == TunnelProvider.CLOUDFLARE:
        if settings.cloudflare_tunnel_id and settings.cloudflare_tunnel_secret and settings.cloudflare_account_id:
            logger.info("Using persisted Cloudflare tunnel configuration...")
            tunnel_id = settings.cloudflare_tunnel_id
            tunnel_secret = settings.cloudflare_tunnel_secret
            account_id = settings.cloudflare_account_id
            
            process = await run_cloudflare(tunnel_id, tunnel_secret, account_id, settings.webui_port)
            if process:
                app.state.tunnel_process = process
                app.state.tunnel_type = "cloudflare"
                app.state.tunnel_id = tunnel_id
                app.state.tunnel_url = f"https://{settings.cloudflare_subdomain}.{settings.cloudflare_domain}"
                logger.info(f"Cloudflare tunnel {tunnel_id} started successfully from persisted config.")
                return True
            else:
                logger.warning("Failed to start tunnel from persisted config, falling back to setup...")

        if not (settings.cloudflare_api_token and settings.cloudflare_domain):
            logger.error("Cloudflare provider selected but API token or domain missing.")
            return False
            
        logger.info("Attempting Cloudflare tunnel setup...")
        tunnel_info = await setup_cloudflare(
            api_token=settings.cloudflare_api_token,
            domain_name=settings.cloudflare_domain,
            tunnel_name=settings.cloudflare_tunnel_name,
            subdomain=settings.cloudflare_subdomain
        )
        if tunnel_info:
            tunnel_id, tunnel_secret = tunnel_info
            app.state.tunnel_type = "cloudflare"
            app.state.tunnel_id = tunnel_id
            
            # Start the tunnel process
            account_id = getattr(app.state, "cf_account_id", "")
            process = await run_cloudflare(tunnel_id, tunnel_secret, account_id, settings.webui_port)
            if process:
                app.state.tunnel_process = process
                logger.info(f"Cloudflare tunnel {tunnel_id} started successfully.")
                app.state.tunnel_url = f"https://{settings.cloudflare_subdomain}.{settings.cloudflare_domain}"
                return True
            else:
                logger.error("Failed to start Cloudflare tunnel process.")
                return False

    if provider == TunnelProvider.NGROK:
        if not settings.ngrok_authtoken:
            logger.error("ngrok provider selected but authtoken missing.")
            return False

        logger.info("Attempting ngrok tunnel setup...")
        url = await setup_ngrok_tunnel(
            authtoken=settings.ngrok_authtoken,
            domain=settings.ngrok_domain,
            edge=settings.ngrok_edge,
            port=settings.webui_port
        )
        if url:
            app.state.tunnel_type = "ngrok"
            app.state.tunnel_url = url
            return True

    logger.warning(f"Unknown or unconfigured tunnel provider: {provider}")
    return False
