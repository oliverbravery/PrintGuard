from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}
