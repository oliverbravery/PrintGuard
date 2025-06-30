import asyncio
import logging
from typing import Dict, Optional
from pydantic import ValidationError
from ..models import CameraState
from .config import get_config, update_config, SavedConfig


class CameraStateManager:
    """Manages the state of all cameras in the application."""
    def __init__(self):
        """Initializes the CameraStateManager, loading states from the configuration."""
        self._states: Dict[int, CameraState] = {}
        self._lock: Optional[asyncio.Lock] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._load_states_from_config()

    @property
    def lock(self) -> asyncio.Lock:
        """Provides a lock for thread-safe operations on camera states.

        Returns:
            asyncio.Lock: The lock instance for the current event loop.
        """
        loop = asyncio.get_running_loop()
        if self._lock is None or self._loop is not loop:
            self._lock = asyncio.Lock()
            self._loop = loop
        return self._lock

    def _load_states_from_config(self):
        """Loads camera states from the application's configuration file."""
        config = get_config() or {}
        saved_states = config.get(SavedConfig.CAMERA_STATES, {})
        for camera_index_str, state_data in saved_states.items():
            try:
                camera_index = int(camera_index_str)
                self._states[camera_index] = CameraState(**state_data)
            except (ValueError, TypeError, ValidationError) as e:
                logging.warning("Failed to load camera state for index %s: %s", camera_index_str, e)
                try:
                    camera_index = int(camera_index_str)
                    self._states[camera_index] = CameraState()
                    logging.info("Created fresh camera state for index %s", camera_index_str)
                except ValueError:
                    logging.error("Invalid camera index in config: %s", camera_index_str)

    def _save_states_to_config(self):
        """Saves the current camera states to the application's configuration file."""
        try:
            states_data = {}
            for camera_index, state in self._states.items():
                state_dict = state.model_dump(exclude={'live_detection_task'})
                if 'detection_history' in state_dict and len(state_dict['detection_history']) > 1000:
                    state_dict['detection_history'] = state_dict['detection_history'][-1000:]
                states_data[str(camera_index)] = state_dict
            update_config({SavedConfig.CAMERA_STATES: states_data})
        except Exception as e:
            logging.error("Failed to save camera states to config: %s", e)

    async def get_camera_state(self, camera_index: int, reset: bool = False) -> CameraState:
        """Get camera state for the given index, creating if it doesn't exist

        Args:
            camera_index (int): The index of the camera.
            reset (bool): If True, resets the camera state to its default.

        Returns:
            CameraState: The state of the camera.
        """
        async with self.lock:
            if camera_index not in self._states or reset:
                self._states[camera_index] = CameraState()
                self._save_states_to_config()
            return self._states[camera_index]

    async def update_camera_state(self, camera_index: int,
                                  new_states: Dict) -> Optional[CameraState]:
        """Updates the state of a specific camera.

        Args:
            camera_index (int): The index of the camera to update.
            new_states (Dict): A dictionary containing the state updates.
                Example:
                {
                    "state_key": new_value,
                    ...
                }

        Returns:
            Optional[CameraState]: The updated camera state, or None if not found.
        """
        async with self.lock:
            if camera_index not in self._states:
                self._states[camera_index] = CameraState()
            camera_state_ref = self._states.get(camera_index)
            if camera_state_ref:
                for key, value in new_states.items():
                    if hasattr(camera_state_ref, key):
                        setattr(camera_state_ref, key, value)
                    else:
                        logging.warning("Key '%s' not found in camera state for index %d.",
                                        key, camera_index)
                self._save_states_to_config()
                return camera_state_ref
        return None

    async def update_camera_detection_history(self, camera_index: int,
                                              pred: str, time_val: float) -> Optional[CameraState]:
        """Updates the detection history for a camera.

        Args:
            camera_index (int): The index of the camera.
            pred (str): The prediction (detection) label.
            time_val (float): The timestamp of the detection.

        Returns:
            Optional[CameraState]: The updated camera state, or None if not found.
        """
        async with self.lock:
            if camera_index not in self._states:
                self._states[camera_index] = CameraState()
            camera_state_ref = self._states.get(camera_index)
            if camera_state_ref:
                camera_state_ref.detection_history.append((time_val, pred))
                max_history = 10000
                if len(camera_state_ref.detection_history) > max_history:
                    camera_state_ref.detection_history = camera_state_ref.detection_history[-max_history:]
                if len(camera_state_ref.detection_history) % 100 == 0:
                    self._save_states_to_config()
                return camera_state_ref
        return None

    async def get_all_camera_indices(self) -> list:
        """Retrieves a list of all camera indices.

        Returns:
            list: A list of all camera indices.
        """
        async with self.lock:
            return list(self._states.keys())

_camera_state_manager = None

def get_camera_state_manager() -> CameraStateManager:
    """Get the global camera state manager instance"""
    global _camera_state_manager
    if _camera_state_manager is None:
        _camera_state_manager = CameraStateManager()
    return _camera_state_manager
