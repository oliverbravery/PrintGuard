import base64
import io
import json

from PIL import Image

from .camera_utils import update_camera_state


def append_new_alert(alert):
    # pylint: disable=import-outside-toplevel
    from ..app import app
    app.state.alerts[alert.id] = alert

def get_alert(alert_id):
    # pylint: disable=import-outside-toplevel
    from ..app import app
    alert = app.state.alerts.get(alert_id, None)
    return alert

async def dismiss_alert(alert_id):
    # pylint: disable=import-outside-toplevel
    from ..app import app
    if alert_id in app.state.alerts:
        del app.state.alerts[alert_id]
        camera_index = int(alert_id.split('_')[0])
        await update_camera_state(camera_index, {"current_alert_id": None})
        return True
    return False

def alert_to_response_json(alert):
    img_bytes = alert.snapshot
    if isinstance(img_bytes, str):
        img_bytes = base64.b64decode(img_bytes)
    buffer = io.BytesIO()
    Image.open(io.BytesIO(img_bytes)).save(buffer, format="JPEG")
    base64_snapshot = base64.b64encode(buffer.getvalue()).decode("utf-8")
    alert_dict = alert.model_dump()
    alert_dict['snapshot'] = base64_snapshot
    return json.dumps(alert_dict)
