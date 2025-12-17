"""ngrok tunnel setup utility."""

import logging
from typing import Optional

try:
    import ngrok
except ImportError:
    ngrok = None

logger = logging.getLogger(__name__)

def is_ngrok_installed() -> bool:
    """Check if the ngrok python library is installed."""
    return ngrok is not None

async def setup_ngrok_tunnel(
    authtoken: str,
    domain: Optional[str] = None,
    edge: Optional[str] = None,
    port: int = 8000
) -> Optional[str]:
    """Set up an ngrok tunnel.
    
    Args:
        authtoken: ngrok authtoken.
        domain: Optional custom domain.
        edge: Optional ngrok edge.
        port: Local port to tunnel to.
        
    Returns:
        Optional[str]: The public URL of the tunnel if successful, else None.
    """
    if not is_ngrok_installed():
        logger.error("ngrok-python package is not installed. Run 'pip install ngrok'")
        return None

    try:
        ngrok.set_auth_token(authtoken)
        kwargs = {"addr": port}
        if domain:
            kwargs["domain"] = domain
        if edge:
            kwargs["edge"] = edge
        listener = await ngrok.forward(**kwargs)
        logger.info(f"ngrok tunnel established at: {listener.url()}")
        return listener.url()
    except Exception as e:
        logger.exception(f"Failed to set up ngrok tunnel: {e}")
        return None
