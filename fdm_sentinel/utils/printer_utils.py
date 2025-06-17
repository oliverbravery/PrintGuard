import asyncio
import logging

import requests

from ..models import PollingTask, SavedConfig, AlertAction
from .camera_utils import get_camera_state_sync, update_camera_state
from .config import PRINTER_STAT_POLLING_RATE_MS, get_config
from .printer_services.octoprint import OctoPrintClient
from .sse_utils import add_polling_task, sse_update_printer_state

def get_printer_config(camera_index):
    camera_state = get_camera_state_sync(camera_index)
    if camera_state and hasattr(camera_state, 'printer_config') and camera_state.printer_config:
        return camera_state.printer_config
    return None

def get_printer_id(camera_index):
    camera_state = get_camera_state_sync(camera_index)
    if camera_state and hasattr(camera_state, 'printer_id') and camera_state.printer_id:
        return camera_state.printer_id
    return None

async def set_printer(camera_index, printer_id, printer_config):
    return await update_camera_state(camera_index, {
        "printer_id": printer_id,
        "printer_config": printer_config
    })

async def remove_printer(camera_index):
    return await update_camera_state(camera_index, {
        "printer_id": None,
        "printer_config": None
    })

async def poll_printer_state_func(client, interval, stop_event):
    while not stop_event.is_set():
        try:
            current_printer_state = client.get_printer_state()
            await sse_update_printer_state(current_printer_state)
        except (requests.exceptions.RequestException, ConnectionError,
                TimeoutError, ValueError) as e:
            logging.warning("Error polling printer state: %s", str(e))
        except Exception as e:
            logging.error("Unexpected error polling printer state: %s", str(e))
        await asyncio.sleep(interval)

async def start_printer_state_polling(camera_index):
    stop_event = asyncio.Event()
    camera_printer_config = get_printer_config(camera_index)
    if not camera_printer_config:
        logging.warning("No printer configuration found for camera index %d", camera_index)
        return
    config = get_config()
    printer_polling_rate = float(config.get(
        SavedConfig.PRINTER_STAT_POLLING_RATE_MS, PRINTER_STAT_POLLING_RATE_MS
        ) / 1000)
    client = OctoPrintClient(
        camera_printer_config.get('base_url'),
        camera_printer_config.get('api_key')
    )
    task = asyncio.create_task(poll_printer_state_func(client, printer_polling_rate, stop_event))
    add_polling_task(camera_index, PollingTask(task=task, stop_event=stop_event))
    logging.debug("Started printer state polling for camera index %d", camera_index)

def suspend_print_job(camera_index, action: AlertAction):
    """
    Pauses or cancels a print job based on the action provided in the alert.
    """
    printer_config = get_printer_config(camera_index)
    if printer_config:
        if printer_config['printer_type'] == 'octoprint':
            client = OctoPrintClient(
                printer_config['base_url'],
                printer_config['api_key']
            )
            try:
                job_info = client.get_job_info()
                if job_info.state != "Printing":
                    return True
                match action:
                    case AlertAction.CANCEL_PRINT:
                        client.cancel_job()
                        logging.debug("Print cancelled for printer %s on camera %d",
                                        printer_config['name'], camera_index)
                        return True
                    case AlertAction.PAUSE_PRINT:
                        client.pause_job()
                        logging.debug("Print paused for printer %s on camera %d",
                                        printer_config['name'], camera_index)
                        return True
                    case _:
                        logging.debug("No action taken for printer %s on camera %d as %s",
                                        printer_config['name'], camera_index, action)
                        return True
            except Exception as e:
                logging.error("Error suspending print job for printer %s on camera %d: %s",
                                printer_config['name'], camera_index, e)
                return False
    logging.error("No printer configuration found for camera index %d", camera_index)
    return False
