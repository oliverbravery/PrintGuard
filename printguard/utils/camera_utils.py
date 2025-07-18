import asyncio
import concurrent.futures
import logging
import uuid
import sys
import glob

import cv2

from ..models import CameraState
from .camera_state_manager import get_camera_state_manager


async def add_camera(source, nickname):
    """
    Adds a new camera, assigns a UUID, and stores it.

    Args:
        source (str): The camera source (e.g., device path or RTSP URL).
        nickname (str): A user-friendly name for the camera.

    Returns:
        dict: A dictionary containing the new camera's UUID, nickname, and source.
    """
    manager = get_camera_state_manager()
    camera_uuid = str(uuid.uuid4())
    new_camera_state = CameraState(
        nickname=nickname,
        source=source,
    )
    await manager.update_camera_state(camera_uuid, new_camera_state.model_dump())
    return {"camera_uuid": camera_uuid, "nickname": nickname, "source": source}

async def remove_camera(camera_uuid: str) -> bool:
    """
    Removes a camera completely.

    Args:
        camera_uuid (str): The UUID of the camera to remove.

    Returns:
        bool: True if the camera was removed successfully, False otherwise.
    """
    manager = get_camera_state_manager()
    return await manager.remove_camera(camera_uuid)

def find_available_serial_cameras() -> list[str]:
    """
    Finds all available camera devices and returns their paths or indices.

    This function is designed to be cross-platform and works on Linux, macOS,
    Windows, and within Docker containers where devices are correctly mapped.

    On Linux, it first attempts to find device paths like '/dev/video*'.
    If that fails or on other platforms (macOS, Windows), it probes for
    camera indices by trying to open them sequentially.

    Returns:
        list[str]: A list of strings, where each string is either a device
                   path (on Linux) or a camera index. An empty list is
                   returned if no cameras are found.
    """
    logging.debug("INFO: Running on platform: %s", sys.platform)
    if sys.platform.startswith('linux'):
        logging.debug("INFO: Detected Linux platform. Searching for /dev/video* devices.")
        device_paths = glob.glob('/dev/video*')
        if device_paths:
            logging.debug("INFO: Found device paths: %s", device_paths)
            return sorted(device_paths)
        else:
            logging.warning("WARN: No /dev/video* devices found. Falling back to index probing.")
    api_preference = cv2.CAP_ANY
    if sys.platform == "win32":
        api_preference = cv2.CAP_DSHOW
    available_indices = []
    index = 0
    while len(available_indices) < 10:
        cap = cv2.VideoCapture(index, api_preference)
        if cap.isOpened():
            logging.debug("INFO: Camera found at index: %s", index)
            available_indices.append(str(index))
            cap.release()
        else:
            logging.debug("INFO: No camera found at index: %s", index)
            cap.release()
            break
        index += 1
    return available_indices

def open_camera(camera_uuid) -> cv2.VideoCapture:
    """
    Open the camera and return a VideoCapture object.
    
    Args:
        camera_uuid (str): The UUID of the camera.

    Returns:
        cv2.VideoCapture: The VideoCapture object for the camera.
    """
    camera_state = get_camera_state_sync(camera_uuid)
    if not camera_state or not camera_state.source:
        raise ValueError(f"Camera with UUID {camera_uuid} does not have a valid source.")
    source = camera_state.source
    if isinstance(source, str) and source.isdigit():
        source = int(source)

    cap = cv2.VideoCapture(source, cv2.CAP_ANY)
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
