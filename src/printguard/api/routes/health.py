from fastapi import APIRouter
from ..crypto_utils import EncryptedRoute

router = APIRouter(route_class=EncryptedRoute)

@router.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}
