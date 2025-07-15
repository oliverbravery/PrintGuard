import asyncio
import logging
import time
from typing import Dict, Tuple

import cv2
import numpy as np
from PIL import Image

from .model_utils import _run_inference
from .sse_utils import sse_update_camera_state
from .detection_utils import (_passed_majority_vote, _create_alert_and_notify,
                              _send_alert)
from .camera_utils import get_camera_state_sync
from .shared_video_stream import get_shared_camera_frame
from ..models import SavedConfig, SiteStartupMode
from .config import (get_config, STREAM_MAX_FPS, STREAM_TUNNEL_FPS,
                     STREAM_JPEG_QUALITY, STREAM_TUNNEL_JPEG_QUALITY,
                     STREAM_MAX_WIDTH, STREAM_TUNNEL_MAX_WIDTH,
                     DETECTION_INTERVAL_MS, DETECTION_TUNNEL_INTERVAL_MS)


class StreamOptimizer:
    """Optimizes video stream frames and detection loops based on configuration."""

    def __init__(self):
        """Initialize the stream optimizer with empty cache and timing."""
        self._config_cache = {}
        self._last_config_check = 0
        self._config_check_interval = 30.0

    def invalidate_cache(self):
        """Clear cached streaming settings to force re-read from configuration."""
        self._last_config_check = 0
        self._config_cache.clear()

    def _get_current_settings(self) -> Dict:
        """Retrieve or update current stream settings from configuration.

        Returns:
            Dict: A dictionary containing stream settings:
                {
                    'max_fps': int,
                    'jpeg_quality': int,
                    'max_width': int,
                    'detection_interval_ms': float,
                    'is_tunnel_mode': bool,
                    'startup_mode': SiteStartupMode,
                    'tunnel_provider': Optional[str]
                }
        """
        current_time = time.time()
        if (current_time - self._last_config_check) > self._config_check_interval:
            config = get_config()
            startup_mode = config.get(SavedConfig.STARTUP_MODE, SiteStartupMode.LOCAL)
            tunnel_provider = config.get(SavedConfig.TUNNEL_PROVIDER, None)
            optimize_for_tunnel = config.get(SavedConfig.STREAM_OPTIMIZE_FOR_TUNNEL, None)
            if optimize_for_tunnel is None:
                is_tunnel_mode = startup_mode == (SiteStartupMode.TUNNEL
                                                  and tunnel_provider is not None)
            else:
                is_tunnel_mode = optimize_for_tunnel
            if is_tunnel_mode:
                default_fps = config.get(SavedConfig.STREAM_TUNNEL_FPS, STREAM_TUNNEL_FPS)
                default_quality = STREAM_TUNNEL_JPEG_QUALITY
                default_width = STREAM_TUNNEL_MAX_WIDTH
                default_detection_interval = DETECTION_TUNNEL_INTERVAL_MS
            else:
                default_fps = config.get(SavedConfig.STREAM_MAX_FPS, STREAM_MAX_FPS)
                default_quality = STREAM_JPEG_QUALITY
                default_width = STREAM_MAX_WIDTH
                default_detection_interval = DETECTION_INTERVAL_MS
            self._config_cache = {
                'max_fps': default_fps,
                'jpeg_quality': config.get(SavedConfig.STREAM_JPEG_QUALITY, default_quality),
                'max_width': config.get(SavedConfig.STREAM_MAX_WIDTH, default_width),
                'detection_interval_ms': config.get(SavedConfig.DETECTION_INTERVAL_MS,
                                                    default_detection_interval),
                'is_tunnel_mode': is_tunnel_mode,
                'startup_mode': startup_mode,
                'tunnel_provider': tunnel_provider
            }
            self._last_config_check = current_time
        return self._config_cache

    def get_stream_settings(self) -> Dict:
        """Get the cached stream settings."""
        return self._get_current_settings()

    def should_limit_fps(self, last_frame_time: float) -> bool:
        """Determine if streaming should pause to respect max FPS.

        Args:
            last_frame_time (float): Timestamp of the last streamed frame.

        Returns:
            bool: True if waiting is needed, False otherwise.
        """
        settings = self._get_current_settings()
        max_fps = settings['max_fps']
        if max_fps <= 0:
            return False
        min_frame_interval = 1.0 / max_fps
        return (time.time() - last_frame_time) < min_frame_interval

    def optimize_frame(self, frame: np.ndarray) -> Tuple[np.ndarray, Dict]:
        """Resize frame based on max width and return associated settings.

        Args:
            frame (np.ndarray): The original image frame.

        Returns:
            Tuple[np.ndarray, Dict]: The resized frame and current stream settings.
        """
        settings = self._get_current_settings()
        max_width = settings['max_width']
        height, width = frame.shape[:2]
        if width > max_width:
            ratio = max_width / width
            new_width = max_width
            new_height = int(height * ratio)
            # pylint: disable=E1101
            frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)
        return frame, settings

    def encode_frame(self, frame: np.ndarray) -> bytes:
        """Encode frame to JPEG with configured quality.

        Args:
            frame (np.ndarray): The frame to encode.

        Returns:
            bytes: The JPEG-encoded byte string.
        """
        settings = self._get_current_settings()
        jpeg_quality = settings['jpeg_quality']
        # pylint: disable=E1101
        encode_params = [
            cv2.IMWRITE_JPEG_QUALITY, jpeg_quality,
            cv2.IMWRITE_JPEG_OPTIMIZE, 1,
        ]
        if settings['is_tunnel_mode']:
            encode_params.extend([cv2.IMWRITE_JPEG_PROGRESSIVE, 1])
        success, buffer = cv2.imencode('.jpg', frame, encode_params)
        if not success:
            _, buffer = cv2.imencode('.jpg', frame)
        return buffer.tobytes()

    def get_detection_interval(self) -> float:
        """Get the time interval between detections in seconds."""
        return self._get_current_settings()['detection_interval_ms'] / 1000.0

    def log_optimization_info(self):
        """Log current stream optimization settings for debugging."""
        settings = self._get_current_settings()
        mode_info = f"tunnel ({settings['tunnel_provider']})" if (
            settings['is_tunnel_mode']) else "local"
        logging.debug("Stream optimization settings for %s mode:", mode_info)
        logging.debug("  Max FPS: %d", settings['max_fps'])
        logging.debug("  JPEG Quality: %d", settings['jpeg_quality'])
        logging.debug("  Max Width: %d", settings['max_width'])
        logging.debug("  Detection Interval: %dms", settings['detection_interval_ms'])

stream_optimizer = StreamOptimizer()


def create_optimized_frame_generator(camera_uuid: str, camera_state_getter):
    """Generator yielding optimized JPEG frames for streaming using shared video stream.

    Args:
        camera_uuid (str): The UUID of the camera.
        camera_state_getter (callable): Function to retrieve CameraState.

    Yields:
        bytes: Multipart JPEG frame data.
    """
    # pylint: disable=E1101
    last_frame_time = 0
    frame_count = 0
    if frame_count == 0:
        stream_optimizer.log_optimization_info()
    try:
        while True:
            if stream_optimizer.should_limit_fps(last_frame_time):
                time.sleep(0.001)
                continue
            camera_state = camera_state_getter(camera_uuid)
            contrast = camera_state.contrast
            brightness = camera_state.brightness
            focus = camera_state.focus
            frame = get_shared_camera_frame(camera_uuid)
            if frame is None:
                logging.warning("Failed to get frame from shared camera stream %s", camera_uuid)
                time.sleep(0.1)
                continue
            frame = cv2.convertScaleAbs(frame, alpha=contrast, beta=int((brightness - 1.0) * 255))
            if focus and focus != 1.0:
                blurred = cv2.GaussianBlur(frame, (0, 0), sigmaX=focus)
                frame = cv2.addWeighted(frame, 1.0 + focus, blurred, -focus, 0)
            frame, settings = stream_optimizer.optimize_frame(frame)
            frame_bytes = stream_optimizer.encode_frame(frame)
            last_frame_time = time.time()
            frame_count += 1
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            if frame_count % 300 == 0:
                settings = stream_optimizer.get_stream_settings()
                logging.debug("Camera %s: Streamed %d frames, mode: %s",
                            camera_uuid, frame_count,
                            "tunnel" if settings['is_tunnel_mode'] else "local")
    except Exception as e:
        logging.error("Error in optimized frame generation for camera %s: %s", camera_uuid, e)

async def create_optimized_detection_loop(app_state, camera_uuid, get_camera_state_sync_func,
                                          update_functions):
    """
    Asynchronous loop for real-time defect detection with optimizations using shared video stream.

    Args:
        app_state: Model and transformation context for detection.
        camera_uuid (str): The UUID of the camera.
        get_camera_state_sync_func (callable): Function to get camera state synchronously.
        update_functions (dict): A mapping of update function names to coroutines,
            e.g., {'update_camera_state': ..., 'update_camera_detection_history': ...}.
    """
    detection_count = 0
    stream_optimizer.log_optimization_info()
    # pylint: disable=E1101
    try:
        while True:
            camera_state_ref = get_camera_state_sync_func(camera_uuid)
            if not camera_state_ref.live_detection_running:
                break
            frame = get_shared_camera_frame(camera_uuid)
            if frame is None:
                logging.warning("Failed to get frame from shared camera stream %s", camera_uuid)
                await update_functions['update_camera_state'](camera_uuid, {
                    "error": "Failed to get frame from shared stream",
                    "live_detection_running": False
                })
                break
            contrast = camera_state_ref.contrast
            brightness = camera_state_ref.brightness
            focus = camera_state_ref.focus
            frame = cv2.convertScaleAbs(frame, alpha=contrast, beta=int((brightness - 1.0) * 255))
            if focus and focus != 1.0:
                blurred = cv2.GaussianBlur(frame, (0, 0), sigmaX=focus)
                frame = cv2.addWeighted(frame, 1.0 + focus, blurred, -focus, 0)
            detection_frame, _ = stream_optimizer.optimize_frame(frame)
            image = Image.fromarray(cv2.cvtColor(detection_frame, cv2.COLOR_BGR2RGB))
            tensor = app_state.transform(image).unsqueeze(0).to(app_state.device)
            try:
                prediction = await _run_inference(app_state.model,
                                                tensor,
                                                app_state.prototypes,
                                                app_state.defect_idx,
                                                app_state.device)
                numeric = prediction[0] if isinstance(prediction, list) else prediction
            except Exception as e:
                logging.debug("Detection inference error for camera %s: %s", camera_uuid, e)
                numeric = None
            label = app_state.class_names[numeric] if (
                isinstance(numeric, int)
                and 0 <= numeric < len(app_state.class_names)
                ) else str(numeric)
            current_timestamp = time.time()
            await update_functions['update_camera_detection_history'](camera_uuid,
                                                                      label,
                                                                      current_timestamp)
            await update_functions['update_camera_state'](camera_uuid, {
                "last_result": label,
                "last_time": current_timestamp
            })
            asyncio.create_task(sse_update_camera_state(camera_uuid))
            detection_count += 1
            if isinstance(numeric, int) and numeric == app_state.defect_idx:
                do_alert = False
                camera_lock = camera_state_ref.lock
                async with camera_lock:
                    if (camera_state_ref.current_alert_id is None
                        and _passed_majority_vote(camera_state_ref)):
                        camera_state_ref.current_alert_id = True
                        do_alert = True
                if do_alert:
                    alert = await _create_alert_and_notify(camera_state_ref,
                                                         camera_uuid,
                                                         frame,
                                                         current_timestamp)
                    asyncio.create_task(_send_alert(alert))
            detection_interval = stream_optimizer.get_detection_interval()
            await asyncio.sleep(detection_interval)
            if detection_count % 100 == 0:
                settings = stream_optimizer.get_stream_settings()
                logging.debug("Camera %s: Completed %d detections, interval: %.3fs, mode: %s",
                            camera_uuid, detection_count, detection_interval,
                            "tunnel" if settings['is_tunnel_mode'] else "local")
    finally:
        pass

def generate_frames(camera_uuid: str):
    """Fallback frame generator if optimized generator fails, using shared video stream.

    Args:
        camera_uuid (str): The UUID of the camera.

    Yields:
        bytes: Multipart JPEG frame data.
    """
    try:
        for frame_data in create_optimized_frame_generator(camera_uuid, get_camera_state_sync):
            yield frame_data
    # pylint: disable=E1101
    except Exception as e:
        logging.error("Error in optimized frame generation for camera %s: %s", camera_uuid, e)
        try:
            while True:
                camera_state = get_camera_state_sync(camera_uuid)
                contrast = camera_state.contrast
                brightness = camera_state.brightness
                focus = camera_state.focus
                frame = get_shared_camera_frame(camera_uuid)
                if frame is None:
                    logging.warning("Failed to get frame from shared camera stream %s", camera_uuid)
                    time.sleep(0.1)
                    continue
                frame = cv2.convertScaleAbs(frame,
                                            alpha=contrast,
                                            beta=int((brightness - 1.0) * 255))
                if focus and focus != 1.0:
                    blurred = cv2.GaussianBlur(frame, (0, 0), sigmaX=focus)
                    frame = cv2.addWeighted(frame, 1.0 + focus, blurred, -focus, 0)
                _, buffer = cv2.imencode('.jpg', frame)
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        except Exception as fallback_e:
            logging.error("Error in fallback frame generation for camera %s: %s",
                          camera_uuid,
                          fallback_e)
