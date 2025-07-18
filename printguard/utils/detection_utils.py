import asyncio
import uuid
import logging
import cv2

from .alert_utils import (dismiss_alert, alert_to_response_json,
                          get_alert, append_new_alert)
from .sse_utils import append_new_outbound_packet
from .camera_utils import (get_camera_state, get_camera_state_sync,
                           update_camera_state, update_camera_detection_history)
from .printer_utils import get_printer_config, suspend_print_job
from .notification_utils import send_defect_notification
from ..models import Alert, AlertAction, SSEDataType

def _passed_majority_vote(camera_state):
    """Determine if failures in detection history meet the majority threshold.

    Args:
        camera_state (CameraState): The camera state containing detection history,
            which includes a list of tuples `(timestamp, label)`.

    Returns:
        bool: True if the number of 'failure' labels in the most recent
              `majority_vote_window` entries is at least `majority_vote_threshold`.
    """
    detection_history = camera_state.detection_history
    majority_vote_window = camera_state.majority_vote_window
    majority_vote_threshold = camera_state.majority_vote_threshold
    results_to_retreive = min(len(detection_history), majority_vote_window)
    detection_window_results = detection_history[-results_to_retreive:]
    failed_detections = [res for res in detection_window_results if res[1] == 'failure']
    return len(failed_detections) >= majority_vote_threshold

async def _send_alert(alert):
    """Send an alert to clients via Server-Sent Events.

    Args:
        alert (Alert): The alert object to send.
    """
    await append_new_outbound_packet(alert_to_response_json(alert), SSEDataType.ALERT)

async def _terminate_alert_after_cooldown(alert):
    """Wait for the alert's countdown, then dismiss or act on the print job.

    Args:
        alert (Alert): The alert object with `countdown_time` and `countdown_action`.
    """
    await asyncio.sleep(alert.countdown_time)
    if get_alert(alert.id) is not None:
        camera_uuid = alert.camera_uuid
        camera_state = await get_camera_state(camera_uuid)
        if not camera_state:
            return
        match camera_state.countdown_action:
            case AlertAction.DISMISS:
                await dismiss_alert(alert.id)
            case AlertAction.CANCEL_PRINT | AlertAction.PAUSE_PRINT:
                suspend_print_job(camera_uuid, camera_state.countdown_action)
                return await dismiss_alert(alert.id)

async def _create_alert_and_notify(camera_state_ref, camera_uuid, frame, timestamp_arg):
    """Create a new Alert object and notify all subsystems.

    Args:
        camera_state_ref (CameraState): The state reference for the camera.
        camera_uuid (str): The UUID of the camera.
        frame (ndarray): The image frame where a defect was detected.
        timestamp_arg (float): The timestamp of detection.

    Returns:
        Alert: The newly created alert.
    """
    alert_id = f"{camera_uuid}_{str(uuid.uuid4())}"
    # pylint: disable=E1101
    _, img_buf = cv2.imencode('.jpg', frame)
    has_printer = get_printer_config(camera_uuid) is not None
    alert = Alert(
        id=alert_id,
        camera_uuid=camera_uuid,
        timestamp=timestamp_arg,
        snapshot=img_buf.tobytes(),
        title=f"Defect - Camera {camera_state_ref.nickname}",
        message=f"Defect detected on camera {camera_state_ref.nickname}",
        countdown_time=camera_state_ref.countdown_time,
        countdown_action=camera_state_ref.countdown_action,
        has_printer=has_printer,
    )
    append_new_alert(alert)
    asyncio.create_task(_terminate_alert_after_cooldown(alert))
    await update_camera_state(camera_uuid, {"current_alert_id": alert_id})
    await send_defect_notification(alert_id)
    return alert

async def _live_detection_loop(app_state, camera_uuid):
    """Continuously run detection on camera frames and generate alerts using shared video stream.

    This loop reads frames from the shared video stream, runs inference, updates state, 
    and dispatches alerts when defects are detected based on majority vote.

    Args:
        app_state: The application state holding model, transforms, and other context.
        camera_uuid (str): The UUID of the camera to process.
    """
    # pylint: disable=C0415
    from .stream_utils import create_optimized_detection_loop
    update_functions = {
        'update_camera_state': update_camera_state,
        'update_camera_detection_history': update_camera_detection_history,
    }
    try:
        await create_optimized_detection_loop(
            app_state,
            camera_uuid,
            get_camera_state_sync,
            update_functions
        )
    except Exception as e:
        logging.error("Error in optimized detection loop for camera %s: %s", camera_uuid, e)
        await update_camera_state(camera_uuid, {
            "error": f"Detection loop error: {str(e)}",
            "live_detection_running": False
        })
