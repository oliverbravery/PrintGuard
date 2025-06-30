import asyncio
import concurrent.futures
import logging

import cv2

from ..models import CameraState
from .camera_state_manager import get_camera_state_manager
from .config import CAMERA_INDEX, CAMERA_INDICES, MAX_CAMERAS


async def get_camera_state(camera_index, reset=False):
    """Get camera state for the given index, handling async context appropriately.

    Args:
        camera_index (int): The index of the camera.
        reset (bool): If True, resets the camera state to its default.

    Returns:
        CameraState: The state of the camera.
    """
    manager = get_camera_state_manager()
    try:
        def sync_get_state():
            return asyncio.run(manager.get_camera_state(camera_index, reset))
        return await asyncio.to_thread(sync_get_state)
    except Exception as e:
        logging.error("Error in camera state access for camera %d: %s", camera_index, e)
        return CameraState()

def get_camera_state_sync(camera_index, reset=False):
    """Synchronous wrapper for get_camera_state for contexts that cannot use async/await.

    Args:
        camera_index (int): The index of the camera.
        reset (bool): If True, resets the camera state to its default.

    Returns:
        CameraState: The state of the camera.
    """
    try:
        try:
            asyncio.get_running_loop()
            def run_in_new_loop():
                return asyncio.run(get_camera_state(camera_index, reset))
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_new_loop)
                return future.result(timeout=5.0)
        except RuntimeError:
            return asyncio.run(get_camera_state(camera_index, reset))   
    except Exception as e:
        logging.error("Error in synchronous camera state access for camera %d: %s", camera_index, e)
        return CameraState()

async def update_camera_state(camera_index, new_states):
    """Update camera state with thread safety and persistence.

    Args:
        camera_index (int): The index of the camera to update.
        new_states (dict): A dictionary of states to update.
            Example: {"state_key": new_value}

    Returns:
        Optional[CameraState]: The updated camera state, or None if not found.
    """
    manager = get_camera_state_manager()
    return await manager.update_camera_state(camera_index, new_states)

def detect_available_cameras(max_cameras=MAX_CAMERAS):
    """Detects available cameras connected to the system.

    Args:
        max_cameras (int): The maximum number of camera indices to check.

    Returns:
        list: A list of available camera indices.
    """
    available_cameras = []
    for i in range(max_cameras):
        # pylint: disable=E1101
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            available_cameras.append(i)
            cap.release()
    return available_cameras

async def setup_camera_indices():
    """Initializes camera states for all detected cameras."""
    available_cameras = detect_available_cameras()
    available_cameras.extend(CAMERA_INDICES)
    if not available_cameras:
        await get_camera_state(CAMERA_INDEX)
        logging.warning("No cameras detected. Using default camera index %d", CAMERA_INDEX)
    else:
        for camera_index in available_cameras:
            await get_camera_state(camera_index)
        logging.debug("Detected %d cameras: %s", len(available_cameras), available_cameras)

async def update_camera_detection_history(camera_index, pred, time_val):
    """Append a detection to a camera's detection history.

    Args:
        camera_index (int): The index of the camera.
        pred (str): The prediction (detection) label.
        time_val (float): The timestamp of the detection.

    Returns:
        Optional[CameraState]: The updated camera state, or None if not found.
    """
    manager = get_camera_state_manager()
    return await manager.update_camera_detection_history(camera_index, pred, time_val)
