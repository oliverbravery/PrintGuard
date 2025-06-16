import asyncio
import json
import logging

from ..models import SSEDataType, PrinterState
from .camera_utils import get_camera_state


async def outbound_packet_fetch():
    # pylint: disable=C0415
    from ..app import app
    while True:
        packet = await app.state.outbound_queue.get()
        yield packet

async def append_new_outbound_packet(packet, sse_data_type: SSEDataType):
    # pylint: disable=C0415
    from ..app import app
    pkt = {"data": {"event": sse_data_type.value, "data": packet}}
    pkt_json = json.dumps(pkt)
    await app.state.outbound_queue.put(pkt_json)

def _calculate_frame_rate(detection_history):
    if len(detection_history) < 2:
        return 0.0
    times = [t for t, _ in detection_history]
    duration = times[-1] - times[0]
    return (len(times) - 1) / duration if duration > 0 else 0.0

async def _sse_update_camera_state_func(camera_index):
    state = get_camera_state(camera_index)
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
        "camera_index": camera_index
    }
    await append_new_outbound_packet(data, SSEDataType.CAMERA_STATE)

async def sse_update_printer_state(printer_state: PrinterState):
    try:
        await asyncio.wait_for(
            append_new_outbound_packet(printer_state.model_dump(), SSEDataType.PRINTER_STATE),
            timeout=5.0
        )
    except asyncio.TimeoutError:
        logging.warning("SSE printer state update timed out for printer %s", printer_state.printer_id)
    except Exception as e:
        logging.error("Error in SSE printer state update for printer %s: %s", printer_state.printer_id, e)

async def sse_update_camera_state(camera_index):
    try:
        await asyncio.wait_for(_sse_update_camera_state_func(camera_index), timeout=5.0)
    except asyncio.TimeoutError:
        logging.warning("SSE camera state update timed out for camera %d", camera_index)
    except Exception as e:
        logging.error("Error in SSE camera state update for camera %d: %s", camera_index, e)

