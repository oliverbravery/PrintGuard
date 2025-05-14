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
                dismiss_alert(alert.id)
            case AlertAction.CANCEL_PRINT:
                cancel_print(alert.id)

def _create_alert_and_notify(camera_state, camera_index, frame, time):
    from utils.notification_utils import send_defect_notification
    from ..app import update_camera_state
    alert_id = f"{camera_index}_{str(uuid.uuid4())}"
    _, img_buf = cv2.imencode('.jpg', frame)
    alert = Alert(
        id=alert_id,
        camera_index=camera_index,
        timestamp=time,
        snapshot=img_buf.tobytes(),
        title=f"Defect - Camera {camera_index}",
        message=f"Defect detected on camera {camera_index}",
        countdown_time=camera_state["countdown_time"],
    )
    asyncio.create_task(_terminate_alert_after_cooldown(alert))
    update_camera_state(camera_index, {"current_alert_id": alert_id})
    send_defect_notification(alert_id, BASE_URL, camera_index=camera_index)
    return alert

async def _live_detection_loop(app_state, camera_index):
    from fdm_sentinel.app import get_camera_state, update_camera_state, update_camera_detection_history
    camera_state = get_camera_state(camera_index)
    try:
        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            print(f"Cannot open camera at index {camera_index}")
            camera_state["error"] = f"Cannot open camera {camera_index}"
            camera_state["live_detection_running"] = False
            return
        update_camera_state(camera_index, {"error": None})

        while camera_state["live_detection_running"]:
            ret, frame = cap.read()
            if not ret:
                break
            contrast = camera_state["contrast"]
            brightness = camera_state["brightness"]
            focus = camera_state["focus"]
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
            now = time.time()
            update_camera_detection_history(camera_index, label, now)
            update_camera_state(camera_index, {"last_result": label, "last_time": now})
            if isinstance(numeric, int) and numeric == app_state.defect_idx and camera_state["current_alert_id"] is None:
                if _passed_majority_vote(camera_state):
                    alert = _create_alert_and_notify(camera_state, camera_index, frame, now)
                    asyncio.create_task(_send_alert(alert))
    finally:
        cap.release()