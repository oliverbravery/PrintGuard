import logging
import cv2
from ..models import CameraState
from .config import (CAMERA_INDICES, MAX_CAMERAS,
                    CAMERA_INDEX)

def get_camera_state(camera_index, reset=False):
    # pylint: disable=import-outside-toplevel
    from ..app import app
    if camera_index not in app.state.camera_states or reset:
        app.state.camera_states[camera_index] = CameraState()
    return app.state.camera_states[camera_index]

# pylint: disable=W0621
async def update_camera_state(camera_index, new_states):
    # pylint: disable=import-outside-toplevel
    from ..app import app
    camera_state_ref = app.state.camera_states.get(camera_index)
    if camera_state_ref:
        lock = camera_state_ref.lock
        async with lock:
            for key, value in new_states.items():
                if hasattr(camera_state_ref, key):
                    setattr(camera_state_ref, key, value)
                else:
                    logging.warning("Key '%s' not found in camera state for index %d.",
                                    key,
                                    camera_index)
        return camera_state_ref
    logging.warning("Camera index '%d' not found in camera states during update.", camera_index)
    return None

def detect_available_cameras(max_cameras=MAX_CAMERAS):
    available_cameras = []
    for i in range(max_cameras):
        # pylint: disable=E1101
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            available_cameras.append(i)
            cap.release()
    return available_cameras

def setup_camera_indices():
    available_cameras = detect_available_cameras()
    available_cameras.extend(CAMERA_INDICES)
    if not available_cameras:
        get_camera_state(CAMERA_INDEX)
        logging.warning("No cameras detected. Using default camera index %d", CAMERA_INDEX)
    else:
        for camera_index in available_cameras:
            get_camera_state(camera_index)
        logging.debug("Detected %d cameras: %s", len(available_cameras), available_cameras)

async def update_camera_detection_history(camera_index, pred, time_val):
    """
    Append a detection to a camera's detection history.
    """
    camera_state_ref = get_camera_state(camera_index)
    if camera_state_ref:
        lock = camera_state_ref.lock
        async with lock:
            camera_state_ref.detection_history.append((time_val, pred))
        return camera_state_ref
    logging.warning("Camera index '%d' not found when trying to update detection history.",
                    camera_index)
    return None

def get_camera_printer_config(camera_index):
    camera_state = get_camera_state(camera_index)
    if camera_state and hasattr(camera_state, 'printer_config') and camera_state.printer_config:
        return camera_state.printer_config
    return None

def get_camera_printer_id(camera_index):
    camera_state = get_camera_state(camera_index)
    if camera_state and hasattr(camera_state, 'printer_id') and camera_state.printer_id:
        return camera_state.printer_id
    return None

async def set_camera_printer(camera_index, printer_id, printer_config):
    return await update_camera_state(camera_index, {
        "printer_id": printer_id,
        "printer_config": printer_config
    })

async def remove_camera_printer(camera_index):
    return await update_camera_state(camera_index, {
        "printer_id": None,
        "printer_config": None
    })
