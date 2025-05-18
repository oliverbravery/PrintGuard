from urllib.parse import urlparse
import logging
from pywebpush import WebPushException, webpush

from ..models import Notification
from ..utils.config import VAPID_CLAIMS, VAPID_PRIVATE_KEY


def send_defect_notification(alert_id, app):
    alert = app.state.alerts.get(alert_id)
    if alert:
        image_data_url = f"data:image/png;base64,{alert.snapshot}"
        notification = Notification(
            title=f"Defect - Camera {alert.camera_index}",
            body=f"Defect detected on camera {alert.camera_index}",
            image_url=image_data_url,
        )
        send_notification(notification, app)

def send_notification(notification: Notification, app):
    for sub in app.state.subscriptions:
        try:
            endpoint = sub.get('endpoint', '')
            parsed_endpoint = urlparse(endpoint)
            audience = f"{parsed_endpoint.scheme}://{parsed_endpoint.netloc}"
            vapid_claims = dict(VAPID_CLAIMS)
            vapid_claims['aud'] = audience
            data_payload_dict = notification.model_dump_json()
            webpush(
                subscription_info=sub,
                data=data_payload_dict,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=vapid_claims
            )
        except WebPushException as ex:
            if ex.response.status_code == 410:
                app.state.subscriptions.remove(sub)
                logging.debug("Subscription expired and removed: %s", sub)
            else:
                logging.error("Push failed: %s", ex)
            return False
        return True
