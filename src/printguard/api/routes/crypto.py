import base64
from fastapi import APIRouter
from ...core.config import get_settings
from ...core.crypto import CryptoHandler
from ..crypto_utils import get_crypto_handler

router = APIRouter(prefix="/crypto", tags=["crypto"])

@router.get("/key")
async def get_public_key():
    """Get the server's public key."""
    settings = get_settings()
    handler = get_crypto_handler()
    response = {"public_key": handler.get_public_key_b64()}
    if not settings.crypto_private_key:
        response["warning"] = "Server is using a temporary in-memory key. Set CRYPTO_PRIVATE_KEY in .env for persistence."
    return response

@router.post("/generate")
async def generate_keys():
    """Generate a new key pair for the server."""
    handler = CryptoHandler()
    return {
        "private_key": base64.b64encode(handler.get_private_key_bytes()).decode('utf-8'),
        "public_key": handler.get_public_key_b64(),
        "instruction": "Add the private_key to your .env file as CRYPTO_PRIVATE_KEY"
    }
