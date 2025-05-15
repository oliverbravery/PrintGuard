import json
from fastapi import APIRouter, Request
from ..utils.config import (
    VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_CLAIMS
)
from pywebpush import webpush, WebPushException
from urllib.parse import urlparse

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
async def push(message: str, request: Request):
    for sub in request.app.state.subscriptions:
        try:
            endpoint = sub.get('endpoint', '')
            parsed_endpoint = urlparse(endpoint)
            audience = f"{parsed_endpoint.scheme}://{parsed_endpoint.netloc}"
            vapid_claims = dict(VAPID_CLAIMS)
            vapid_claims['aud'] = audience
            data_payload_dict = {"body": message}
            data_payload_json_str = json.dumps(data_payload_dict)
            webpush(
                subscription_info=sub,
                data=data_payload_json_str,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=vapid_claims
            )
        except WebPushException as ex:
            if ex.response.status_code == 410:
                request.app.state.subscriptions.remove(sub)
                print("Subscription expired and removed:", sub)
            else:
                print("Push failed:", ex)
    return {"success": True}
