import base64
import io
import json

from PIL import Image

from .camera_utils import update_camera_state


def append_new_alert(alert):
    """Appends a new alert to the application's state.

    Args:
        alert (Alert): The alert object to be added.
            The alert object should have the following structure:
            {
                "id": str,
                "snapshot": bytes,
                "title": str,
                "message": str,
                "timestamp": float,
                "countdown_time": float,
                "camera_uuid": str,
                "has_printer": bool,
                "countdown_action": str
            }
    """
    # pylint: disable=import-outside-toplevel
    from ..app import app
    app.state.alerts[alert.id] = alert

def get_alert(alert_id):
    """Retrieves a single alert by its ID from the application's state.

    Args:
        alert_id (str): The ID of the alert to retrieve.

    Returns:
        Alert: The alert object if found, otherwise None.
    """
    # pylint: disable=import-outside-toplevel
    from ..app import app
    alert = app.state.alerts.get(alert_id, None)
    return alert

async def dismiss_alert(alert_id):
    """Dismisses an alert by its ID, removing it from the application's state.

    Args:
        alert_id (str): The ID of the alert to dismiss.

    Returns:
        bool: True if the alert was successfully dismissed, False otherwise.
    """
    # pylint: disable=import-outside-toplevel
    from ..app import app
    if alert_id in app.state.alerts:
        del app.state.alerts[alert_id]
        camera_uuid = alert_id.split('_')[0]
        await update_camera_state(camera_uuid, {"current_alert_id": None})
        return True
    return False

def alert_to_response_json(alert):
    """Converts an Alert object to a JSON string for API responses.

    The snapshot image is base64 encoded within the JSON.

    Args:
        alert (Alert): The alert object to convert.

    Returns:
        str: A JSON string representing the alert.
            The structure is:
            {
                "id": str,
                "snapshot": str (base64 encoded image),
                "title": str,
                "message": str,
                "timestamp": float,
                "countdown_time": float,
                "camera_uuid": str,
                "has_printer": bool,
                "countdown_action": str
            }
    """
    img_bytes = alert.snapshot
    if isinstance(img_bytes, str):
        img_bytes = base64.b64decode(img_bytes)
    buffer = io.BytesIO()
    Image.open(io.BytesIO(img_bytes)).save(buffer, format="JPEG")
    base64_snapshot = base64.b64encode(buffer.getvalue()).decode("utf-8")
    alert_dict = alert.model_dump()
    alert_dict['snapshot'] = base64_snapshot
    return json.dumps(alert_dict)
