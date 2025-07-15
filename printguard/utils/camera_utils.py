import asyncio
import concurrent.futures
import logging

import cv2

from ..models import CameraState
from .camera_state_manager import get_camera_state_manager


def open_camera(camera_uuid) -> cv2.VideoCapture:
    """
    Open the camera and return a VideoCapture object.
    
    Args:
        camera_uuid (str): The UUID of the camera.

    Returns:
        cv2.VideoCapture: The VideoCapture object for the camera.
    """
    # get the source from the saved camera state
    camera_state = get_camera_state_sync(camera_uuid)
    if not camera_state or not camera_state.source:
        raise ValueError(f"Camera with UUID {camera_uuid} does not have a valid source.")
    cap = cv2.VideoCapture(camera_state.source, cv2.CAP_ANY)
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open camera with UUID {camera_uuid}")
    return cap

async def get_camera_state(camera_uuid, reset=False):
    """Get this camera's state, handling async context appropriately.

    Args:
        camera_uuid (str): The UUID of the camera.
        reset (bool): If True, resets the camera state to its default.

    Returns:
        CameraState: The state of the camera.
    """
    manager = get_camera_state_manager()
    try:
        def sync_get_state():
            return asyncio.run(manager.get_camera_state(camera_uuid, reset))
        return await asyncio.to_thread(sync_get_state)
    except Exception as e:
        logging.error("Error in camera state access for camera %d: %s", camera_uuid, e)
        return CameraState()

def get_camera_state_sync(camera_uuid, reset=False):
    """Synchronous wrapper for get_camera_state for contexts that cannot use async/await.

    Args:
        camera_uuid (str): The UUID of the camera.
        reset (bool): If True, resets the camera state to its default.

    Returns:
        CameraState: The state of the camera.
    """
    try:
        try:
            asyncio.get_running_loop()
            def run_in_new_loop():
                return asyncio.run(get_camera_state(camera_uuid, reset))
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_new_loop)
                return future.result(timeout=5.0)
        except RuntimeError:
            return asyncio.run(get_camera_state(camera_uuid, reset))
    except Exception as e:
        logging.error("Error in synchronous camera state access for camera %d: %s", camera_uuid, e)
        return CameraState()

async def update_camera_detection_history(camera_uuid, pred, time_val):
    """Append a detection to the camera's detection history.

    Args:
        camera_uuid (str): The UUID of the camera.
        pred (str): The prediction (detection) label.
        time_val (float): The timestamp of the detection.

    Returns:
        Optional[CameraState]: The updated camera state, or None if not found.
    """
    manager = get_camera_state_manager()
    return await manager.update_camera_detection_history(camera_uuid, pred, time_val)

async def update_camera_state(camera_uuid, new_states):
    """Update the camera's state with thread safety and persistence.

    Args:
        camera_uuid (str): The UUID of the camera.
        new_states (dict): A dictionary of states to update.
            Example: {"state_key": new_value}

    Returns:
        Optional[CameraState]: The updated camera state, or None if not found.
    """
    manager = get_camera_state_manager()
    return await manager.update_camera_state(camera_uuid, new_states)
