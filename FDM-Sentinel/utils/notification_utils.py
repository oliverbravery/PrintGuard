import json
import uuid
from typing import Dict

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import BackgroundTasks, HTTPException
from pydantic import BaseModel
from pywebpush import WebPushException, webpush

from utils.config import VAPID_PRIVATE_KEY, VAPID_CLAIMS, VAPID_PUBLIC_KEY

subscriptions: Dict[str, dict] = {}
scheduler = BackgroundScheduler()
scheduler.start()

class Subscription(BaseModel):
    endpoint: str
    keys: dict

class Message(BaseModel):
    title: str
    body: str
    url: str = None

class ScheduleRequest(BaseModel):
    subscription_id: str
    message: Message
    cron: str

def subscribe_client(sub: Subscription):
    sub_id = str(uuid.uuid4())
    subscriptions[sub_id] = sub.dict()
    return {"subscription_id": sub_id}

def unsubscribe_client(subscription_id: str):
    if subscription_id in subscriptions:
        del subscriptions[subscription_id]
        jobs_to_remove = [job for job in scheduler.get_jobs() if job.args and isinstance(job.args, tuple) and len(job.args) > 0 and job.args[0] == subscription_id]
        for job in jobs_to_remove:
            scheduler.remove_job(job.id)
        return {"message": "Unsubscribed"}
    raise HTTPException(status_code=404, detail="Subscription not found")

def send_notification_now(subscription_id: str, msg: Message, background_tasks: BackgroundTasks):
    if subscription_id not in subscriptions:
        raise HTTPException(status_code=404, detail="Subscription not found")

    def send(sub_info, message_data):
        try:
            webpush(
                subscription_info=sub_info,
                data=message_data,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS
            )
        except WebPushException as ex:
            print(f"WebPush failed: {ex}")

    background_tasks.add_task(send, subscriptions[subscription_id], msg.json())
    return {"message": "Notification sent"}

def schedule_notification(request: ScheduleRequest):
    if request.subscription_id not in subscriptions:
        raise HTTPException(status_code=404, detail="Subscription not found")

    def job_function(sub_id, message_data):
        if sub_id in subscriptions:
            try:
                webpush(
                    subscription_info=subscriptions[sub_id],
                    data=message_data,
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims=VAPID_CLAIMS
                )
            except WebPushException as ex:
                print(f"Scheduled WebPush failed for {sub_id}: {ex}")
        else:
            print(f"Subscription {sub_id} not found for scheduled job.")

    trigger = CronTrigger.from_crontab(request.cron)
    scheduler.add_job(job_function, trigger, args=[request.subscription_id, request.message.json()], id=f"job_{request.subscription_id}_{uuid.uuid4().hex[:6]}")
    return {"message": "Scheduled"}

def get_public_key():
    return {"public_key": VAPID_PUBLIC_KEY}

def get_debug_subscriptions():
    return subscriptions

def send_defect_notification(alert_id: str, base_url: str, camera_index=None): 
    alert_url = f"{base_url}/alert/{alert_id}"
    snapshot_url = f"{alert_url}/snapshot"
    camera_info = f" (Camera {camera_index})" if camera_index is not None else ""
    
    for sub_id, sub_info in subscriptions.items():
        try:
            payload = {
                "title": f"3D Print Alert{camera_info}",
                "body": f"Defect detected on camera {camera_index}" if camera_index is not None else "Defect detected",
                "url": alert_url,
                "image": snapshot_url
            }
            print(f"Sending alert to {sub_id} - {payload}")
            data = json.dumps(payload)
            webpush(
                subscription_info=sub_info,
                data=data,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS
            )
            print(f"Sent alert to {sub_id}")
        except WebPushException as ex:
            print(f"Live notification failed for {sub_id}: {ex}")
