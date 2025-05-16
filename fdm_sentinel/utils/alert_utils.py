from PIL import Image
import base64
import io
from .sse_utils import append_new_outbound_packet
from ..models import SSEDataType

async def outbound_queue_unseen_alerts(req):
    seen_alerts = req.cookies.get("seen_alerts", "").split(",") if req.cookies.get("seen_alerts") else []
    unseen_alerts = get_unseen_alerts(seen_alerts, req.app)
    for alert in unseen_alerts:
        await append_new_outbound_packet(alert_to_response_json(alert), SSEDataType.ALERT)

async def append_new_alert(alert):
    from ..app import app
    app.state.alerts[alert.id] = alert
    await append_new_outbound_packet(alert_to_response_json(alert), SSEDataType.ALERT)
    
def get_unseen_alerts(known_alert_ids, app):
    known_alert_ids = set(known_alert_ids or [])
    return [alert for alert_id, alert in app.state.alerts.items()
            if alert_id not in known_alert_ids]

async def dismiss_alert(alert_id):
    from ..app import app, update_camera_state
    if alert_id in app.state.alerts:
        del app.state.alerts[alert_id]
        camera_index = int(alert_id.split('_')[0])
        await update_camera_state(camera_index, {"current_alert_id": None})
        return True
    return False

async def cancel_print(alert_id):
    # logic here to cancel the print job
    # associated with the printer linked to the
    # alerts camera. The printer will be 
    # stored in the camera state.
    return await dismiss_alert(alert_id)

def alert_to_response_json(alert):
    img_bytes = alert.snapshot
    if isinstance(img_bytes, str):
        img_bytes = base64.b64decode(img_bytes)
    buffer = io.BytesIO()
    Image.open(io.BytesIO(img_bytes)).save(buffer, format="JPEG")
    alert.snapshot = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return alert.model_dump_json()
