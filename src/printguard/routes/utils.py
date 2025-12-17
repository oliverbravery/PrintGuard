from fastapi import HTTPException
from ..config import get_settings, TunnelProvider
from ..tunnel import is_cloudflared_installed
from ..ngrok import is_ngrok_installed

def check_local_mode():
    """Dependency to ensure we are in local mode before allowing tunnel setup."""
    settings = get_settings()
    if settings.tunnel_provider != TunnelProvider.LOCAL:
        raise HTTPException(
            status_code=403,
            detail=f"Tunnel setup via API is only allowed when TUNNEL_PROVIDER is 'local'. Current mode: {settings.tunnel_provider}"
        )

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
