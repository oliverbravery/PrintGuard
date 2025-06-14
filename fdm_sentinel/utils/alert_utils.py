import base64
import io
import logging

from PIL import Image

from ..models import SSEDataType
from .sse_utils import append_new_outbound_packet


async def append_new_alert(alert):
    # pylint: disable=import-outside-toplevel
    from ..app import app
    app.state.alerts[alert.id] = alert
    await append_new_outbound_packet(alert_to_response_json(alert), SSEDataType.ALERT)

async def dismiss_alert(alert_id):
    # pylint: disable=import-outside-toplevel
    from ..app import app, update_camera_state
    if alert_id in app.state.alerts:
        del app.state.alerts[alert_id]
        camera_index = int(alert_id.split('_')[0])
        await update_camera_state(camera_index, {"current_alert_id": None})
        return True
    return False

async def cancel_print(alert_id):
    # pylint: disable=import-outside-toplevel
    from ..app import get_camera_state
    from ..utils.printer_services.octoprint import OctoPrintClient
    try:
        camera_index = int(alert_id.split('_')[0])
        camera_state = get_camera_state(camera_index)
        if hasattr(camera_state, 'printer_config') and camera_state.printer_config:
            printer_config = camera_state.printer_config
            if printer_config['printer_type'] == 'octoprint':
                client = OctoPrintClient(
                    printer_config['base_url'],
                    printer_config['api_key']
                )
                client.cancel_job()
                logging.info("Print cancelled for printer %s on camera %d",
                           printer_config['name'], camera_index)
        return await dismiss_alert(alert_id)
    except Exception as e:
        logging.error("Error cancelling print for alert %s: %s", alert_id, e)
        return await dismiss_alert(alert_id)

def alert_to_response_json(alert):
    img_bytes = alert.snapshot
    if isinstance(img_bytes, str):
        img_bytes = base64.b64decode(img_bytes)
    buffer = io.BytesIO()
    Image.open(io.BytesIO(img_bytes)).save(buffer, format="JPEG")
    alert.snapshot = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return alert.model_dump_json()
