from urllib.parse import urlparse
import logging
from pywebpush import WebPushException, webpush

from ..models import Notification, SavedKey, SavedConfig
from ..utils.config import get_key, get_config


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
    config = get_config()
    vapid_subject = config.get(SavedConfig.VAPID_SUBJECT, None)
    if not vapid_subject:
        logging.error("VAPID subject is not set in the configuration.")
        return False
    vapid_claims = {
        "sub": vapid_subject,
        "aud": None,
    }
    success_count = 0
    for sub in app.state.subscriptions.copy():
        try:
            endpoint = sub.get('endpoint', '')
            parsed_endpoint = urlparse(endpoint)
            audience = f"{parsed_endpoint.scheme}://{parsed_endpoint.netloc}"
            aud_vapid_claims = dict(vapid_claims)
            aud_vapid_claims['aud'] = audience
            data_payload_dict = notification.model_dump_json()
            webpush(
                subscription_info=sub,
                data=data_payload_dict,
                vapid_private_key=get_key(SavedKey.VAPID_PRIVATE_KEY),
                vapid_claims=aud_vapid_claims
            )
            success_count += 1
        except WebPushException as ex:
            if ex.response.status_code == 410:
                app.state.subscriptions.remove(sub)
                logging.debug("Subscription expired and removed: %s", sub)
            else:
                logging.error("Push failed: %s", ex)
        except Exception as e:
            logging.error("Unexpected error sending notification: %s", e)
    return success_count > 0
