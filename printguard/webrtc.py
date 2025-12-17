"""WebRTC video processing."""

import asyncio
from typing import Callable, Optional

from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaRelay
from av import VideoFrame

from .notifications import notify_defect

relay = MediaRelay()
pcs: set[RTCPeerConnection] = set()


class VideoProcessor:
    """Process video frames and run predictions using always-latest-frame pattern."""
    
    def __init__(self, predict_fn: Callable, model_info: dict, sensitivity: float = 1.0, session_id: Optional[str] = None):
        self.predict_fn = predict_fn
        self.model_info = model_info
        self.sensitivity = sensitivity
        self.session_id = session_id
        self.last_result: dict | None = None
        self._latest_frame: VideoFrame | None = None
        self._frame_ready = asyncio.Event()
        self._running = True
        self._last_notified_class: str | None = None
    
    async def _receive_frames(self, track):
        """Continuously receive frames and keep only the latest."""
        while self._running:
            try:
                frame: VideoFrame = await track.recv()
                self._latest_frame = frame
                self._frame_ready.set()
            except Exception:
                self._running = False
                self._frame_ready.set()
                break
    
    async def _run_inference(self):
        """Process the latest available frame."""
        while self._running:
            await self._frame_ready.wait()
            if not self._running:
                break
            frame = self._latest_frame
            self._frame_ready.clear()
            if frame is None:
                continue
            image = frame.to_image()
            self.last_result = await asyncio.to_thread(
                self.predict_fn, image, self.model_info, self.sensitivity
            )
            if self.last_result and self.session_id:
                class_name = self.last_result.get("class_name", "")
                if class_name.lower() != "normal" and class_name != self._last_notified_class:
                    self._last_notified_class = class_name
                    notify_defect(self.session_id, class_name, self.last_result.get("confidence", 0))
                elif class_name.lower() == "normal":
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
    sensitivity: float = 1.0,
    session_id: Optional[str] = None
) -> tuple[RTCPeerConnection, VideoProcessor]:
    """Create WebRTC peer connection with video processing."""
    pc = RTCPeerConnection()
    pcs.add(pc)
    processor = VideoProcessor(predict_fn, model_info, sensitivity, session_id)
    
    @pc.on("connectionstatechanged")
    async def on_state_change():
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)
    
    @pc.on("track")
    def on_track(track):
        if track.kind == "video":
            asyncio.create_task(processor.process(relay.subscribe(track)))
    
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return pc, processor


async def cleanup():
    """Close all peer connections."""
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()
