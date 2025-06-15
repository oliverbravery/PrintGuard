import base64
import io
import json
import logging

from PIL import Image

from ..models import SSEDataType
from .sse_utils import append_new_outbound_packet
from .printer_services.octoprint import OctoPrintClient


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
    from ..app import get_camera_printer_config
    try:
        camera_index = int(alert_id.split('_')[0])
        printer_config = get_camera_printer_config(camera_index)
        if printer_config:
            if printer_config['printer_type'] == 'octoprint':
                client = OctoPrintClient(
                    printer_config['base_url'],
                    printer_config['api_key']
                )
                try:
                    job_info = client.get_job_info()
                    if job_info.state == "Printing":
                        client.cancel_job()
                        logging.debug("Print cancelled for printer %s on camera %d",
                                   printer_config['name'], camera_index)
                    else:
                        logging.debug("Print job not active (state: %s) for printer %s on camera %d, dismissing alert",
                                   job_info.state, printer_config['name'], camera_index)
                except Exception as e:
                    logging.warning(
                        "Could not check job status before cancelling for printer %s: %s",
                        printer_config['name'], e)
                    try:
                        client.cancel_job()
                        logging.debug(
                            "Print cancel attempted for printer %s on camera %d",
                            printer_config['name'], camera_index)
                    except Exception as cancel_e:
                        logging.error("Error cancelling print for printer %s: %s",
                                    printer_config['name'], cancel_e)
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
    base64_snapshot = base64.b64encode(buffer.getvalue()).decode("utf-8")
    alert_dict = alert.model_dump()
    alert_dict['snapshot'] = base64_snapshot
    return json.dumps(alert_dict)
