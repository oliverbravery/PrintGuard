import logging

from fastapi import APIRouter, Request

from ..models import SavedConfig, SavedKey
from ..utils.config import get_config, get_key, update_config

router = APIRouter()

@router.get("/notification/public_key")
async def get_public_key():
    """Retrieve the VAPID public key for push notification subscriptions.

    Returns:
        dict: VAPID public key for client-side push notification setup,
              or error message if key is not configured.
    """
    config = get_config()
    vapid_public_key = config.get(SavedConfig.VAPID_PUBLIC_KEY, None)
    if not vapid_public_key:
        logging.error("VAPID public key is not set in the configuration.")
        return {"error": "VAPID public key not configured"}
    return {"publicKey": vapid_public_key}

@router.post("/notification/subscribe")
async def subscribe(request: Request):
    """Subscribe a client to push notifications.

    Args:
        request (Request): The FastAPI request object containing subscription data.

    Returns:
        dict: Success status indicating whether subscription was added successfully.
    """
    try:
        subscription = await request.json()
        logging.debug("Received subscription request: %s", subscription.get('endpoint', 'no endpoint'))
        if not subscription.get('endpoint') or not subscription.get('keys'):
            logging.error("Invalid subscription format - missing endpoint or keys")
            return {"success": False, "error": "Invalid subscription format"}
        for existing_sub in request.app.state.subscriptions:
            if existing_sub.get('endpoint') == subscription.get('endpoint'):
                request.app.state.subscriptions.remove(existing_sub)
                logging.debug("Removed existing subscription for same endpoint")
                break
        request.app.state.subscriptions.append(subscription)
        config = get_config() or {}
        config[SavedConfig.PUSH_SUBSCRIPTIONS] = request.app.state.subscriptions
        update_config(config)
        logging.debug("Successfully added subscription. Total subscriptions: %d", len(request.app.state.subscriptions))
        return {"success": True}
    # pylint: disable=W0718
    except Exception as e:
        logging.error("Subscription error: %s", str(e))
        return {"success": False, "error": f"Server error: {str(e)}"}

@router.post("/notification/unsubscribe")
async def unsubscribe(request: Request):
    """Unsubscribe all clients from push notifications.

    Args:
        request (Request): The FastAPI request object containing app state.

    Returns:
        dict: Success status indicating all subscriptions were cleared.
    """
    request.app.state.subscriptions.clear()
    config = get_config() or {}
    config[SavedConfig.PUSH_SUBSCRIPTIONS] = []
    update_config(config)
    logging.debug("All push subscriptions cleared and persisted.")
    return {"success": True}

@router.get("/notification/debug")
async def notification_debug(request: Request):
    """Get debug information about notification configuration and subscriptions.

    Args:
        request (Request): The FastAPI request object containing app state.

    Returns:
        dict: Debug information including subscription count, VAPID configuration,
              and subscription details for troubleshooting.
    """
    config = get_config()
    debug_info = {
        "subscriptions_count": len(request.app.state.subscriptions),
        "subscriptions": [
            {
                "endpoint": sub.get('endpoint', 'unknown')[:50] + "..." if len(sub.get('endpoint', '')) > 50 else sub.get('endpoint', 'unknown'),
                "has_keys": bool(sub.get('keys'))
            }
            for sub in request.app.state.subscriptions
        ],
        "vapid_config": {
            "has_public_key": bool(config.get(SavedConfig.VAPID_PUBLIC_KEY)),
            "has_subject": bool(config.get(SavedConfig.VAPID_SUBJECT)),
            "has_private_key": bool(get_key(SavedKey.VAPID_PRIVATE_KEY)),
            "subject": config.get(SavedConfig.VAPID_SUBJECT, "not set")
        }
    }
    return debug_info
