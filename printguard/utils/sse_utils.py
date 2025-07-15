import asyncio
import json
import logging
import time

from ..models import (SSEDataType, PrinterState,
                      PollingTask, SavedConfig)
from ..utils.config import get_config, MIN_SSE_DISPATCH_DELAY_MS

_last_dispatch_times = {}

async def outbound_packet_fetch():
    """Async generator yielding outbound SSE packets for clients.

    Yields:
        str: Serialized JSON packet from application outbound queue.
    """
    # pylint: disable=C0415
    from ..app import app
    while True:
        packet = await app.state.outbound_queue.get()
        yield packet

async def append_new_outbound_packet(packet, sse_data_type: SSEDataType):
    """Append a new Server-Sent Event packet to the outbound queue.

    Args:
        packet (str): The JSON-serialized data payload.
        sse_data_type (SSEDataType): The type of SSE event.
    """
    config = get_config()
    min_sse_dispatch_delay = config.get(SavedConfig.MIN_SSE_DISPATCH_DELAY_MS, MIN_SSE_DISPATCH_DELAY_MS)
    current_time = time.time() * 1000
    last_dispatch_time = _last_dispatch_times.get(sse_data_type, 0)
    time_since_last_dispatch = current_time - last_dispatch_time
    if time_since_last_dispatch < min_sse_dispatch_delay:
        logging.debug("Throttling SSE dispatch for %s (time since last: %.1fms)",
                     sse_data_type.value, time_since_last_dispatch)
        return
    # pylint: disable=C0415
    from ..app import app
    pkt = {"data": {"event": sse_data_type.value, "data": packet}}
    pkt_json = json.dumps(pkt)
    await app.state.outbound_queue.put(pkt_json)
    _last_dispatch_times[sse_data_type] = current_time

async def append_new_outbound_packet_force(packet, sse_data_type: SSEDataType):
    """Force append a new Server-Sent Event packet to the outbound queue, bypassing throttling.

    Args:
        packet (str): The JSON-serialized data payload.
        sse_data_type (SSEDataType): The type of SSE event.
    """
    # pylint: disable=C0415
    from ..app import app
    pkt = {"data": {"event": sse_data_type.value, "data": packet}}
    pkt_json = json.dumps(pkt)
    await app.state.outbound_queue.put(pkt_json)
    current_time = time.time() * 1000
    _last_dispatch_times[sse_data_type] = current_time

def reset_throttle_for_data_type(sse_data_type: SSEDataType):
    """Reset the throttle timer for a specific SSE data type.

    Args:
        sse_data_type (SSEDataType): The type of SSE event to reset throttling for.
    """
    if sse_data_type in _last_dispatch_times:
        del _last_dispatch_times[sse_data_type]
        logging.debug("Reset throttle for SSE data type: %s", sse_data_type.value)

def _calculate_frame_rate(detection_history):
    """Calculate frames per second based on detection timestamps.

    Args:
        detection_history (list of tuples): Each tuple is (timestamp, label).

    Returns:
        float: The calculated frame rate, or 0.0 if insufficient data.
    """
    if len(detection_history) < 2:
        return 0.0
    times = [t for t, _ in detection_history]
    duration = times[-1] - times[0]
    return (len(times) - 1) / duration if duration > 0 else 0.0

async def _sse_update_camera_state_func(camera_uuid):
    """Build and send a camera state update SSE packet.

    Args:
        camera_uuid (str): The UUID of the camera.
    """
    # pylint: disable=import-outside-toplevel
    from .camera_utils import get_camera_state
    state = await get_camera_state(camera_uuid)
    detection_history = state.detection_history
    total_detections = len(detection_history)
    frame_rate = _calculate_frame_rate(detection_history)
    data = {
        "start_time": state.start_time,
        "last_result": state.last_result,
        "last_time": state.last_time,
        "total_detections": total_detections,
        "frame_rate": frame_rate,
        "error": state.error,
        "live_detection_running": state.live_detection_running,
        "camera_uuid": camera_uuid
    }
    await append_new_outbound_packet(data, SSEDataType.CAMERA_STATE)

async def sse_update_printer_state(printer_state: PrinterState):
    """Send an SSE update with the current printer state.

    Args:
        printer_state (PrinterState): The printer state object.
    """
    try:
        await asyncio.wait_for(
            append_new_outbound_packet(printer_state.model_dump(), SSEDataType.PRINTER_STATE),
            timeout=5.0
        )
    except asyncio.TimeoutError:
        logging.warning("SSE printer state update timed out")
    except (ValueError, TypeError, AttributeError) as e:
        logging.error("Error in SSE printer state update: %s", e)
    except Exception as e:
        logging.error("Unexpected error in SSE printer state update: %s", e)

async def sse_update_camera_state(camera_uuid):
    """Send an SSE update with the current camera state.

    Args:
        camera_uuid (str): The UUID of the camera.
    """
    try:
        await asyncio.wait_for(_sse_update_camera_state_func(camera_uuid), timeout=5.0)
    except asyncio.TimeoutError:
        logging.warning("SSE camera state update timed out for camera %s", camera_uuid)
    except (ValueError, TypeError, AttributeError) as e:
        logging.error("Error in SSE camera state update for camera %s: %s", camera_uuid, e)
    except Exception as e:  # pylint: disable=broad-except
        logging.error("Unexpected error in SSE camera state update for camera %s: %s",
                      camera_uuid, e)

def get_polling_task(camera_uuid):
    """Retrieve the current polling task for a camera.

    Args:
        camera_uuid (str): The UUID of the camera.

    Returns:
        PollingTask or None: The polling task if exists, otherwise None.
    """
    # pylint: disable=C0415
    from ..app import app
    return app.state.polling_tasks.get(camera_uuid) or None

def stop_and_remove_polling_task(camera_uuid):
    """Stop and remove a polling task for a specified camera.

    Args:
        camera_uuid (str): The UUID of the camera.
    """
    # pylint: disable=C0415
    from ..app import app
    task = get_polling_task(camera_uuid)
    if task:
        task.stop_event.set()
        if task.task and not task.task.done():
            task.task.cancel()
        logging.debug("Stopped polling task for camera UUID %s", camera_uuid)
        del app.state.polling_tasks[camera_uuid]
    else:
        logging.warning("No polling task found for camera UUID %s to stop.", camera_uuid)

def add_polling_task(camera_uuid, task: PollingTask):
    """Add or replace a polling task for a camera.

    Args:
        camera_uuid (str): The UUID of the camera.
        task (PollingTask): The task object containing the asyncio.Task and stop_event.
    """
    # pylint: disable=C0415
    from ..app import app
    if camera_uuid in app.state.polling_tasks:
        stop_and_remove_polling_task(camera_uuid)
    app.state.polling_tasks[camera_uuid] = task
    logging.debug("Added polling task for camera UUID %s", camera_uuid)
