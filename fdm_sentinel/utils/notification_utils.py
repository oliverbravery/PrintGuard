from urllib.parse import urlparse
import logging
import json
from pywebpush import WebPushException, webpush

from ..models import Notification, SavedKey, SavedConfig
from ..utils.config import get_key, get_config


def send_defect_notification(alert_id, app):
    logging.debug("Attempting to send defect notification for alert ID: %s", alert_id)
    alert = app.state.alerts.get(alert_id)
    if alert:
        logging.debug("Alert found for ID %s, preparing notification", alert_id)
        notification = Notification(
            title=f"Defect - Camera {alert.camera_index}",
            body=f"Defect detected on camera {alert.camera_index}",
        )
        logging.debug("Created notification object without image payload, sending to %d subscriptions",
                      len(app.state.subscriptions))
        send_notification(notification, app)
    else:
        logging.error("No alert found for ID: %s", alert_id)

def send_notification(notification: Notification, app):
    logging.debug("Starting notification send process")
    config = get_config()
    vapid_subject = config.get(SavedConfig.VAPID_SUBJECT, None)
    if not vapid_subject:
        logging.error("VAPID subject is not set in the configuration.")
        return False
    vapid_private_key = get_key(SavedKey.VAPID_PRIVATE_KEY)
    if not vapid_private_key:
        logging.error("VAPID private key is not set in the configuration.")
        return False
    logging.debug("VAPID configuration found. Subject: %s", vapid_subject)
    logging.debug("Number of subscriptions: %d", len(app.state.subscriptions))
    vapid_claims = {
        "sub": vapid_subject,
        "aud": None,
    }
    success_count = 0
    if not app.state.subscriptions:
        logging.warning("No push subscriptions available to send notifications")
        return False
    for i, sub in enumerate(app.state.subscriptions.copy()):
        logging.debug("Sending notification to subscription %d/%d",
                      i+1, len(app.state.subscriptions))
        try:
            endpoint = sub.get('endpoint', '')
            if not endpoint:
                logging.error("Subscription %d has no endpoint", i+1)
                continue
            parsed_endpoint = urlparse(endpoint)
            audience = f"{parsed_endpoint.scheme}://{parsed_endpoint.netloc}"
            aud_vapid_claims = dict(vapid_claims)
            aud_vapid_claims['aud'] = audience
            payload_dict = {
                'title': notification.title,
                'body': notification.body
            }
            data_payload = json.dumps(payload_dict)
            logging.debug("Sending to endpoint: %s", endpoint)
            webpush(
                subscription_info=sub,
                data=data_payload,
                vapid_private_key=vapid_private_key,
                vapid_claims=aud_vapid_claims
            )
            success_count += 1
            logging.debug("Successfully sent notification to subscription %d", i+1)
        except WebPushException as ex:
            logging.error("WebPush failed for subscription %d: %s", i+1, ex)
            if ex.response and ex.response.status_code == 410:
                app.state.subscriptions.remove(sub)
                logging.info("Subscription expired and removed: %s", sub.get('endpoint', 'unknown'))
            else:
                logging.error("Push failed: %s", ex)
        except Exception as e:
            logging.error("Unexpected error sending notification to subscription %d: %s", i+1, e)

    logging.debug("Notification send complete. Success count: %d/%d", success_count, len(app.state.subscriptions))
    return success_count > 0
