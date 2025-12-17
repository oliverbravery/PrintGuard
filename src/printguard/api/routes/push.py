from fastapi import APIRouter
from ...core.models import PushSubscription
from ...services.notifications import subscribe, unsubscribe, VAPID_PUBLIC_KEY

router = APIRouter()

@router.post("/subscribe")
async def push_subscribe(data: PushSubscription) -> dict:
    """Subscribe to push notifications for a session."""
    subscribe(data.session_id, data.subscription, data.device_name)
    return {"status": "subscribed"}

@router.delete("/{session_id}")
async def push_unsubscribe(session_id: str) -> dict:
    """Unsubscribe from push notifications."""
    unsubscribe(session_id)
    return {"status": "unsubscribed"}

@router.get("/vapid-key")
async def get_vapid_key() -> dict:
    """Get VAPID public key for push subscription."""
    return {"publicKey": VAPID_PUBLIC_KEY}
