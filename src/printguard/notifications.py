"""Web push notifications."""

import json

from pywebpush import webpush, WebPushException

from .models import SessionSubscription, PushSubscriptionInfo

VAPID_PRIVATE_KEY = ""
VAPID_PUBLIC_KEY = ""
VAPID_CLAIMS = {"sub": "mailto:admin@example.com"}

_subscriptions: dict[str, SessionSubscription] = {}


def set_vapid_keys(private_key: str, public_key: str, email: str = "mailto:admin@example.com"):
    """Set VAPID keys for push notifications."""
    global VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY, VAPID_CLAIMS
    VAPID_PRIVATE_KEY = private_key
    VAPID_PUBLIC_KEY = public_key
    VAPID_CLAIMS = {"sub": email}


def subscribe(session_id: str, subscription: PushSubscriptionInfo, device_name: str):
    """Register a push subscription for a session."""
    _subscriptions[session_id] = SessionSubscription(
        subscription=subscription, device_name=device_name
    )


def unsubscribe(session_id: str):
    """Remove a push subscription."""
    _subscriptions.pop(session_id, None)


def get_device_name(session_id: str) -> str:
    """Get device name for a session."""
    sub = _subscriptions.get(session_id)
    return sub.device_name if sub else "Unknown Camera"


def send_notification(session_id: str, title: str, body: str) -> bool:
    """Send push notification for a session."""
    if not VAPID_PRIVATE_KEY:
        return False
    sub = _subscriptions.get(session_id)
    if not sub:
        return False
    try:
        webpush(
            subscription_info=sub.subscription.model_dump(),
            data=json.dumps({"title": title, "body": body}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims=VAPID_CLAIMS
        )
        return True
    except WebPushException:
        return False


def notify_defect(session_id: str, defect_class: str, confidence: float):
    """Send notification when defect is detected."""
    device_name = get_device_name(session_id)
    send_notification(
        session_id,
        title=f"Print Error Detected",
        body=f"{device_name}: {defect_class} ({confidence:.0%} confidence)"
    )
