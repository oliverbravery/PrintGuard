import asyncio
import time
import uuid

import cv2
from PIL import Image

from .config import BASE_URL
from .model_utils import _run_inference
from .alert_utils import append_new_alert, cancel_print, dismiss_alert

from ..models import Alert, AlertAction

def _passed_majority_vote(camera_state):
    detection_history = camera_state["detection_history"]
    majority_vote_window = camera_state["majority_vote_window"]
    majority_vote_threshold = camera_state["majority_vote_threshold"]
    results_to_retreive = min(len(detection_history), majority_vote_window)
    detection_window_results = detection_history[-results_to_retreive:]
    failed_detections = [res for res in detection_window_results if res[1] == 'failure']
    return len(failed_detections) >= majority_vote_threshold

async def _send_alert(alert):
    await append_new_alert(alert)

async def _terminate_alert_after_cooldown(alert):
    from ..app import app, get_camera_state
    await asyncio.sleep(alert.countdown_time)
    if app.state.alerts.get(alert.id, None) is not None:
        camera_state = get_camera_state(alert.camera_index)
        if not camera_state:
            return
        match camera_state["countdown_action"]:
            case AlertAction.DISMISS:
                await dismiss_alert(alert.id)
            case AlertAction.CANCEL_PRINT:
                await cancel_print(alert.id)

async def _create_alert_and_notify(camera_state_ref, camera_index, frame, timestamp_arg):
    from .notification_utils import send_defect_notification
    from ..app import update_camera_state
    alert_id = f"{camera_index}_{str(uuid.uuid4())}"
    _, img_buf = cv2.imencode('.jpg', frame)
    alert = Alert(
        id=alert_id,
        camera_index=camera_index,
        timestamp=timestamp_arg,
        snapshot=img_buf.tobytes(),
        title=f"Defect - Camera {camera_index}",
        message=f"Defect detected on camera {camera_index}",
        countdown_time=camera_state_ref["countdown_time"],
    )
    asyncio.create_task(_terminate_alert_after_cooldown(alert))
    await update_camera_state(camera_index, {"current_alert_id": alert_id})
    send_defect_notification(alert_id, BASE_URL, camera_index=camera_index)
    return alert

async def _live_detection_loop(app_state, camera_index):
    from fdm_sentinel.app import get_camera_state, update_camera_state, update_camera_detection_history
    camera_state_ref = get_camera_state(camera_index)
    camera_lock = camera_state_ref["lock"]

    try:
        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            print(f"Cannot open camera at index {camera_index}")
            await update_camera_state(camera_index, {"error": f"Cannot open camera {camera_index}", "live_detection_running": False})
            return
        await update_camera_state(camera_index, {"error": None})

        while camera_state_ref["live_detection_running"]:
            ret, frame = cap.read()
            if not ret:
                await update_camera_state(camera_index, {"error": "Failed to read frame", "live_detection_running": False})
                break
            contrast = camera_state_ref["contrast"]
            brightness = camera_state_ref["brightness"]
            focus = camera_state_ref["focus"]
            frame = cv2.convertScaleAbs(frame, alpha=contrast, beta=int((brightness - 1.0) * 255))
            if focus and focus != 1.0:
                blurred = cv2.GaussianBlur(frame, (0, 0), sigmaX=focus)
                frame = cv2.addWeighted(frame, 1.0 + focus, blurred, -focus, 0)
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            tensor = app_state.transform(image).unsqueeze(0).to(app_state.device)
            try:
                prediction = await _run_inference(app_state.model, tensor, app_state.prototypes, app_state.defect_idx, app_state.device)
                numeric = prediction[0] if isinstance(prediction, list) else prediction
            except Exception as e:
                print(f"Live loop inference error for camera {camera_index}: {e}")
                numeric = None

            label = app_state.class_names[numeric] if isinstance(numeric, int) and 0 <= numeric < len(app_state.class_names) else str(numeric)
            current_timestamp = time.time()
            
            await update_camera_detection_history(camera_index, label, current_timestamp)
            await update_camera_state(camera_index, {"last_result": label, "last_time": current_timestamp})
            
            if isinstance(numeric, int) and numeric == app_state.defect_idx:
                do_alert = False
                async with camera_lock:
                    if camera_state_ref["current_alert_id"] is None and _passed_majority_vote(camera_state_ref):
                        camera_state_ref["current_alert_id"] = True
                        do_alert = True
                if do_alert:
                    alert = await _create_alert_and_notify(camera_state_ref, camera_index, frame, current_timestamp)
                    asyncio.create_task(_send_alert(alert))
    finally:
        if 'cap' in locals() and cap.isOpened():
            cap.release()