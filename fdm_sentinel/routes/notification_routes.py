from fastapi import APIRouter, Request
from ..utils.config import (
    VAPID_PUBLIC_KEY
)
from ..utils.notification_utils import send_notification
from ..models import Notification

router = APIRouter()

@router.get("/notification/public_key")
async def get_public_key():
    return {"publicKey": VAPID_PUBLIC_KEY}

@router.post("/notification/subscribe")
async def subscribe(request: Request):
    try:
        subscription = await request.json()
        if not subscription.get('endpoint') or not subscription.get('keys'):
            return {"success": False, "error": "Invalid subscription format"}
        for existing_sub in request.app.state.subscriptions:
            if existing_sub.get('endpoint') == subscription.get('endpoint'):
                request.app.state.subscriptions.remove(existing_sub)
                break
        request.app.state.subscriptions.append(subscription)
        print(f"New push subscription: {subscription.get('endpoint')}")
        return {"success": True}
    except Exception as e:
        print(f"Subscription error: {str(e)}")
        return {"success": False, "error": f"Server error: {str(e)}"}

@router.post("/notification/push")
async def push(notification: Notification, request: Request):
    success = send_notification(notification, request.app)
    return {"success": success}
