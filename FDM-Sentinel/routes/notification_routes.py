from fastapi import APIRouter, BackgroundTasks

from utils.notification_utils import (
    Subscription, Message, ScheduleRequest,
    subscribe_client, unsubscribe_client, send_notification_now, schedule_notification,
    get_public_key, get_debug_subscriptions
)

router = APIRouter()

@router.post("/subscribe", tags=["notifications"])
async def route_subscribe_ep(sub: Subscription):
    return subscribe_client(sub)

@router.post("/unsubscribe/{subscription_id}", tags=["notifications"])
async def route_unsubscribe_ep(subscription_id: str):
    return unsubscribe_client(subscription_id)

@router.post("/send/{subscription_id}", tags=["notifications"])
async def route_send_now_ep(subscription_id: str, msg: Message, background_tasks: BackgroundTasks):
    return send_notification_now(subscription_id, msg, background_tasks)

@router.post("/schedule", tags=["notifications"])
async def route_schedule_ep(request: ScheduleRequest):
    return schedule_notification(request)

@router.get("/publicKey", tags=["notifications"])
async def route_public_key_ep():
    return get_public_key()

@router.get("/debug/subscriptions", include_in_schema=False, tags=["debug"])
async def route_debug_subscriptions_ep():
    return get_debug_subscriptions()
