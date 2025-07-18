import logging
import threading
import time
from typing import Dict, Optional, List, Callable
import cv2
import numpy as np

from .camera_utils import get_camera_state_sync


class SharedVideoStream:
    """A shared video stream that allows multiple consumers to access the same camera source."""

    def __init__(self, camera_uuid: str, source: str):
        # pylint: disable=E1101
        self.camera_uuid = camera_uuid
        self.source = source
        self.cap: Optional[cv2.VideoCapture] = None
        self.latest_frame: Optional[np.ndarray] = None
        self.frame_lock = threading.Lock()
        self.consumers: List[Callable] = []
        self.is_running = False
        self.thread: Optional[threading.Thread] = None
        self.last_frame_time = 0
        self.frame_count = 0

    def start(self):
        """Start the video stream capture thread."""
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        logging.debug("Started shared video stream for camera %s", self.camera_uuid)

    def stop(self):
        """Stop the video stream capture thread."""
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=1.0)
        if self.cap and self.cap.isOpened():
            self.cap.release()
        logging.debug("Stopped shared video stream for camera %s", self.camera_uuid)

    def _capture_loop(self):
        """Main capture loop that runs in a separate thread."""
        # pylint: disable=E1101
        try:
            source = self.source
            if isinstance(source, str) and source.isdigit():
                source = int(source)
            self.cap = cv2.VideoCapture(source, cv2.CAP_ANY)
            if not self.cap.isOpened():
                logging.error("Failed to open camera source %s for shared stream", source)
                return
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if isinstance(source, str) and source.startswith('rtp://'):
                self.cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
            consecutive_failures = 0
            max_consecutive_failures = 10
            while self.is_running:
                ret, frame = self.cap.read()
                if not ret:
                    consecutive_failures += 1
                    logging.warning("Failed to read frame from camera %s (failure %d/%d)",
                                  self.camera_uuid, consecutive_failures, max_consecutive_failures)
                    if consecutive_failures >= max_consecutive_failures:
                        logging.error(
                            "Too many consecutive failures for camera %s, stopping stream",
                            self.camera_uuid)
                        break
                    time.sleep(0.1)
                    continue
                else:
                    consecutive_failures = 0
                with self.frame_lock:
                    self.latest_frame = frame.copy()
                    self.last_frame_time = time.time()
                    self.frame_count += 1
                time.sleep(0.001)
        except (cv2.error, OSError, ValueError) as e:
            logging.error("Error in shared video stream for camera %s: %s", self.camera_uuid, e)
        finally:
            if self.cap and self.cap.isOpened():
                self.cap.release()

    def get_frame(self) -> Optional[np.ndarray]:
        """Get the latest frame from the shared stream."""
        with self.frame_lock:
            if self.latest_frame is not None:
                return self.latest_frame.copy()
            return None

    def is_frame_available(self) -> bool:
        """Check if a frame is available."""
        with self.frame_lock:
            return self.latest_frame is not None

    def get_frame_info(self) -> Dict:
        """Get information about the current frame."""
        with self.frame_lock:
            return {
                'frame_count': self.frame_count,
                'last_frame_time': self.last_frame_time,
                'has_frame': self.latest_frame is not None,
                'is_running': self.is_running,
                'is_healthy': self.is_running and time.time() - self.last_frame_time < 5.0
            }


class SharedVideoStreamManager:
    """Manages shared video streams for multiple cameras."""

    def __init__(self):
        self.streams: Dict[str, SharedVideoStream] = {}
        self.lock = threading.Lock()

    def get_stream(self, camera_uuid: str, source: str) -> SharedVideoStream:
        """Get or create a shared video stream for a camera."""
        with self.lock:
            if camera_uuid not in self.streams:
                self.streams[camera_uuid] = SharedVideoStream(camera_uuid, source)
            else:
                existing_stream = self.streams[camera_uuid]
                if (not existing_stream.is_running
                    or not existing_stream.thread
                    or not existing_stream.thread.is_alive()):
                    logging.info("Restarting shared video stream for camera %s", camera_uuid)
                    existing_stream.stop()
                    self.streams[camera_uuid] = SharedVideoStream(camera_uuid, source)
            stream = self.streams[camera_uuid]
            if not stream.is_running:
                stream.start()
            return stream

    def release_stream(self, camera_uuid: str):
        """Release a shared video stream."""
        with self.lock:
            if camera_uuid in self.streams:
                self.streams[camera_uuid].stop()
                del self.streams[camera_uuid]

    def cleanup_all(self):
        """Clean up all shared video streams."""
        with self.lock:
            for stream in self.streams.values():
                stream.stop()
            self.streams.clear()

    def get_stream_health(self, camera_uuid: str) -> Dict:
        """Get health information for a specific stream."""
        with self.lock:
            if camera_uuid in self.streams:
                return self.streams[camera_uuid].get_frame_info()
            return {'is_running': False, 'is_healthy': False, 'has_frame': False}

_shared_stream_manager = SharedVideoStreamManager()

def get_shared_stream_manager() -> SharedVideoStreamManager:
    """Get the global shared stream manager."""
    return _shared_stream_manager

def get_shared_camera_frame(camera_uuid: str) -> Optional[np.ndarray]:
    """Get a frame from the shared camera stream."""
    try:
        camera_state = get_camera_state_sync(camera_uuid)
        if not camera_state or not camera_state.source:
            return None
        manager = get_shared_stream_manager()
        stream = manager.get_stream(camera_uuid, camera_state.source)
        max_wait = 50
        wait_count = 0
        while not stream.is_frame_available() and wait_count < max_wait:
            time.sleep(0.1)
            wait_count += 1
        return stream.get_frame()
    except (ImportError, AttributeError) as e:
        logging.error("Error getting shared camera frame for %s: %s", camera_uuid, e)
        return None
