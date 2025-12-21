"""WebRTC video processing."""

import asyncio
import logging
from typing import Callable, Optional

from aiortc import RTCDataChannel, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaRelay
from av import VideoFrame
from PIL import ImageEnhance

from .notifications import notify_defect
from ..core.models import FeedSettings, PredictionResult, PredictionStatus, PredictionClass

logger = logging.getLogger(__name__)

relay = MediaRelay()
pcs: set[RTCPeerConnection] = set()


class VideoProcessor:
    """Process video frames and run predictions using always-latest-frame pattern."""
    
    def __init__(self, predict_fn: Callable, model_info: dict, settings: "FeedSettings", session_id: Optional[str] = None):
        self.predict_fn = predict_fn
        self.model_info = model_info
        self.settings = settings
        self.session_id = session_id
        self.last_result: dict | None = None
        self.data_channels: set[RTCDataChannel] = set()
        self.relayed_track = None
        self._latest_frame: VideoFrame | None = None
        self._frame_ready = asyncio.Event()
        self._running = True
        self._last_notified_class: str | None = None
    
    def add_data_channel(self, channel: RTCDataChannel):
        """Add a data channel to send results to."""
        self.data_channels.add(channel)

        @channel.on("statechange")
        def on_statechange():
            if channel.readyState == "closed":
                self.data_channels.discard(channel)
    
    async def _receive_frames(self, track):
        """Continuously receive frames and keep only the latest."""
        logger.info(f"Started receiving frames for session {self.session_id}")
        frame_count = 0
        while self._running:
            try:
                if frame_count == 0:
                    logger.info(f"Waiting for first frame from track for session {self.session_id}")
                frame: VideoFrame = await track.recv()
                if frame_count == 0:
                    logger.info(f"Received first frame for session {self.session_id}")
                self._latest_frame = frame
                self._frame_ready.set()
                frame_count += 1
                if frame_count % 100 == 0:
                    logger.debug(f"Received {frame_count} frames for session {self.session_id}")
            except Exception as e:
                logger.error(f"Error receiving frames for session {self.session_id}: {e}", exc_info=True)
                self._running = False
                self._frame_ready.set()
                break
        logger.info(f"Stopped receiving frames for session {self.session_id}")
    
    async def _run_inference(self):
        """Process the latest available frame."""
        logger.info(f"Started inference loop for session {self.session_id}")
        while self._running:
            await self._frame_ready.wait()
            if not self._running:
                break
            frame = self._latest_frame
            self._frame_ready.clear()
            if frame is None:
                continue
            self._inference_count = getattr(self, "_inference_count", 0) + 1
            if self._inference_count % 100 == 0:
                logger.debug(f"Running inference {self._inference_count} for session {self.session_id}")
            image = frame.to_image()
            if self.settings.resolution:
                image = image.resize(self.settings.resolution)
            if self.settings.brightness != 1.0:
                image = ImageEnhance.Brightness(image).enhance(self.settings.brightness)
            if self.settings.contrast != 1.0:
                image = ImageEnhance.Contrast(image).enhance(self.settings.contrast)
            self.last_result = await asyncio.to_thread(
                self.predict_fn, image, self.model_info, self.settings.sensitivity
            )
            if self.last_result:
                result_model = PredictionResult(**self.last_result, status=PredictionStatus.SUCCESS)
                message = result_model.model_dump_json()
                for dc in list(self.data_channels):
                    if dc.readyState == "open":
                        dc.send(message)
                if self.session_id:
                    class_name = result_model.class_name
                    if class_name and class_name != PredictionClass.NORMAL and class_name != self._last_notified_class:
                        self._last_notified_class = class_name
                        notify_defect(self.session_id, str(class_name), result_model.confidence or 0)
                    elif class_name == PredictionClass.NORMAL:
                        self._last_notified_class = None
    
    async def process(self, track):
        """Process incoming video track with two concurrent tasks."""
        receiver_task = asyncio.create_task(self._receive_frames(track))
        inference_task = asyncio.create_task(self._run_inference())
        await asyncio.gather(receiver_task, inference_task)


async def create_peer_connection(
    offer: RTCSessionDescription,
    predict_fn: Callable,
    model_info: dict,
    settings: "FeedSettings",
    session_id: Optional[str] = None
) -> tuple[RTCPeerConnection, VideoProcessor]:
    """Create WebRTC peer connection with video processing."""
    pc = RTCPeerConnection()
    pcs.add(pc)
    processor = VideoProcessor(predict_fn, model_info, settings, session_id)

    @pc.on("connectionstatechanged")
    async def on_state_change():
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)

    @pc.on("datachannel")
    def on_datachannel(channel):
        processor.add_data_channel(channel)

    @pc.on("track")
    def on_track(track):
        if track.kind == "video":
            relayed_track = relay.subscribe(track)
            processor.relayed_track = relayed_track
            asyncio.create_task(processor.process(relayed_track))

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return pc, processor


async def start_track_processing(
    track,
    predict_fn: Callable,
    model_info: dict,
    settings: "FeedSettings",
    session_id: Optional[str] = None
) -> VideoProcessor:
    """Start processing a MediaStreamTrack directly."""
    processor = VideoProcessor(predict_fn, model_info, settings, session_id)
    relayed_track = relay.subscribe(track)
    processor.relayed_track = relayed_track
    asyncio.create_task(processor.process(relayed_track))
    return processor


async def create_viewer_connection(
    offer: RTCSessionDescription,
    processor: VideoProcessor
) -> RTCPeerConnection:
    """Create a viewer WebRTC connection for an existing processor."""
    pc = RTCPeerConnection()
    pcs.add(pc)

    @pc.on("connectionstatechanged")
    async def on_state_change():
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)

    if processor.relayed_track:
        pc.addTrack(processor.relayed_track)
    dc = pc.createDataChannel("results")
    processor.add_data_channel(dc)
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return pc


async def cleanup():
    """Close all peer connections."""
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()
