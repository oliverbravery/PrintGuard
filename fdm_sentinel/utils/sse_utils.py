import json

from ..models import SSEDataType


async def outbound_packet_fetch():
    from ..app import app
    while True:
        packet = await app.state.outbound_queue.get()
        yield packet

async def append_new_outbound_packet(packet, sse_data_type: SSEDataType):
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
    from ..app import get_camera_state
    state = get_camera_state(camera_index)
    detection_history = state.get("detection_history", [])
    total_detections = len(detection_history)
    frame_rate = _calculate_frame_rate(detection_history)
    data = {
        "start_time": state.get("start_time"),
        "last_result": state.get("last_result"),
        "last_time": state.get("last_time"),
        "total_detections": total_detections,
        "frame_rate": frame_rate,
        "error": state.get("error"),
        "live_detection_running": state.get("live_detection_running", False),
        "camera_index": camera_index
    }
    await append_new_outbound_packet(data, SSEDataType.CAMERA_STATE)

async def sse_update_camera_state(camera_index):
    await _sse_update_camera_state_func(camera_index)
