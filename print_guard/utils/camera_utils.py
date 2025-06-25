import asyncio
import concurrent.futures
import logging

import cv2

from ..models import CameraState
from .camera_state_manager import get_camera_state_manager
from .config import CAMERA_INDEX, CAMERA_INDICES, MAX_CAMERAS


async def get_camera_state(camera_index, reset=False):
    """Get camera state for the given index - automatically handles context appropriately"""
    manager = get_camera_state_manager()
    try:
        def sync_get_state():
            return asyncio.run(manager.get_camera_state(camera_index, reset))
        return await asyncio.to_thread(sync_get_state)
    except Exception as e:
        logging.error("Error in camera state access for camera %d: %s", camera_index, e)
        return CameraState()

def get_camera_state_sync(camera_index, reset=False):
    """Synchronous wrapper for contexts that cannot use async/await"""
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
    """Update camera state with thread safety and persistence"""
    manager = get_camera_state_manager()
    return await manager.update_camera_state(camera_index, new_states)

def detect_available_cameras(max_cameras=MAX_CAMERAS):
    available_cameras = []
    for i in range(max_cameras):
        # pylint: disable=E1101
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            available_cameras.append(i)
            cap.release()
    return available_cameras

async def setup_camera_indices():
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
    """
    Append a detection to a camera's detection history.
    """
    manager = get_camera_state_manager()
    return await manager.update_camera_detection_history(camera_index, pred, time_val)
