import asyncio
import uuid
import logging
import cv2

from .alert_utils import append_new_alert, cancel_print, dismiss_alert
from ..models import Alert, AlertAction

def _passed_majority_vote(camera_state):
    detection_history = camera_state.detection_history
    majority_vote_window = camera_state.majority_vote_window
    majority_vote_threshold = camera_state.majority_vote_threshold
    results_to_retreive = min(len(detection_history), majority_vote_window)
    detection_window_results = detection_history[-results_to_retreive:]
    failed_detections = [res for res in detection_window_results if res[1] == 'failure']
    return len(failed_detections) >= majority_vote_threshold

async def _send_alert(alert):
    await append_new_alert(alert)

async def _terminate_alert_after_cooldown(alert):
    # pylint: disable=C0415
    from ..app import app, get_camera_state
    await asyncio.sleep(alert.countdown_time)
    if app.state.alerts.get(alert.id, None) is not None:
        camera_state = get_camera_state(alert.camera_index)
        if not camera_state:
            return
        match camera_state.countdown_action:
            case AlertAction.DISMISS:
                await dismiss_alert(alert.id)
            case AlertAction.CANCEL_PRINT:
                await cancel_print(alert.id)

async def _create_alert_and_notify(camera_state_ref, camera_index, frame, timestamp_arg):
    # pylint: disable=C0415
    from .notification_utils import send_defect_notification
    from ..app import update_camera_state, app
    alert_id = f"{camera_index}_{str(uuid.uuid4())}"
    # pylint: disable=E1101
    _, img_buf = cv2.imencode('.jpg', frame)
    alert = Alert(
        id=alert_id,
        camera_index=camera_index,
        timestamp=timestamp_arg,
        snapshot=img_buf.tobytes(),
        title=f"Defect - Camera {camera_index}",
        message=f"Defect detected on camera {camera_index}",
        countdown_time=camera_state_ref.countdown_time,
    )
    asyncio.create_task(_terminate_alert_after_cooldown(alert))
    await update_camera_state(camera_index, {"current_alert_id": alert_id})
    send_defect_notification(alert_id, app)
    return alert

async def _live_detection_loop(app_state, camera_index):
    # pylint: disable=C0415
    from fdm_sentinel.app import (get_camera_state,
                                  update_camera_state,
                                  update_camera_detection_history)
    from .stream_utils import create_optimized_detection_loop
    update_functions = {
        'update_camera_state': update_camera_state,
        'update_camera_detection_history': update_camera_detection_history,
    }
    camera_state_ref = get_camera_state(camera_index)
    try:
        await create_optimized_detection_loop(
            app_state,
            camera_index,
            get_camera_state,
            update_functions
        )
    except Exception as e:
        logging.error("Error in optimized detection loop for camera %d: %s", camera_index, e)
        await update_camera_state(camera_index, {
            "error": f"Detection loop error: {str(e)}", 
            "live_detection_running": False
        })
