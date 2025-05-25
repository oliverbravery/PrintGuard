import logging

from fastapi import APIRouter, Request

from ..models import SavedConfig
from ..utils.config import get_config

router = APIRouter()

@router.get("/notification/public_key")
async def get_public_key():
    config = get_config()
    vapid_public_key = config.get(SavedConfig.VAPID_PUBLIC_KEY, None)
    if not vapid_public_key:
        logging.error("VAPID public key is not set in the configuration.")
        return {"error": "VAPID public key not configured"}
    return {"publicKey": vapid_public_key}

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
        logging.debug("New push subscription: %s", subscription.get('endpoint'))
        return {"success": True}
    # pylint: disable=W0718
    except Exception as e:
        logging.error("Subscription error: %s", str(e))
        return {"success": False, "error": f"Server error: {str(e)}"}

