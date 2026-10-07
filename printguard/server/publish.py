"""Pushes camera video to MediaMTX over RTSP.

Browser recordings (fragmented WebM/MP4 over a WebSocket) are remuxed - never
transcoded - by remux(). Sources MediaMTX cannot pull itself, such as MJPEG
over HTTP, are transcoded to H.264 by H264Push. Either way the result behaves
like any other MediaMTX stream and reaches viewers as HLS.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from fractions import Fraction
from typing import Callable

import av
from av.video.frame import PictureType
from av.video.reformatter import VideoReformatter

logger = logging.getLogger(__name__)


MAX_QUEUED_BYTES = 32 * 1024 * 1024
PUSH_TIMEOUT_US = 3_000_000
"""How long a connection to MediaMTX may wait on the socket, so a listener that
accepts and never answers fails like a refused connection does."""
PUSH_QUEUED_FRAMES = 3
"""Frames waiting to be encoded for a live view. A push that falls behind drops
the oldest, since a live view wants the freshest frame and capture must not wait."""


class ChunkStream:
    """Blocking file-like view over WebSocket chunks for PyAV.

    The remux reads at the speed the recording plays, so a sender faster than
    that is refused once ``MAX_QUEUED_BYTES`` wait to be read, rather than
    having the hub hold all of it. The socket's thread counts what it feeds
    and the remux's thread what it takes, so neither count is written twice.
    """

    def __init__(self) -> None:
        self._chunks: queue.Queue[bytes | None] = queue.Queue()
        self._buffer = bytearray()
        self._eof = False
        self._fed = 0
        self._taken = 0

    def feed(self, chunk: bytes | None) -> None:
        """Queues a chunk, where None marks the end of the stream.

        Raises:
            OverflowError: When more is already waiting than the stream holds.
        """
        if chunk is not None:
            if self._fed - self._taken > MAX_QUEUED_BYTES:
                raise OverflowError("the recording arrives faster than it plays")
            self._fed += len(chunk)
        self._chunks.put(chunk)

    def read(self, size: int = -1) -> bytes:
        while not self._eof and (size < 0 or len(self._buffer) < size):
            chunk = self._chunks.get()
            if chunk is None:
                self._eof = True
            else:
                self._taken += len(chunk)
                self._buffer.extend(chunk)
        cut = len(self._buffer) if size < 0 else size
        out = bytes(self._buffer[:cut])
        del self._buffer[:cut]
        return out


RTP_CLOCK = 90000
KEYFRAME_INTERVAL_S = 1.0


def remux(source: ChunkStream, rtsp_url: str) -> None:
    """Pushes the video packets of a recorded stream to MediaMTX."""
    with av.open(source, mode="r") as recording:
        video = recording.streams.video[0]
        rate = video.guessed_rate or video.average_rate
        fps = int(rate) if rate and 1 <= rate <= 60 else 30
        step = RTP_CLOCK // fps
        clock = Fraction(1, RTP_CLOCK)
        with av.open(rtsp_url, mode="w", format="rtsp", options={"rtsp_transport": "tcp", "timeout": str(PUSH_TIMEOUT_US)}) as push:
            out_stream = push.add_stream_from_template(video)
            out_stream.time_base = clock
            start = time.monotonic()
            index = 0
            for packet in recording.demux(video):
                if packet.dts is None:
                    continue
                packet.stream = out_stream
                packet.time_base = clock
                packet.pts = packet.dts = index * step
                packet.duration = step
                lag = index / fps - (time.monotonic() - start)
                if lag > 0:
                    time.sleep(lag)
                push.mux(packet)
                index += 1


class H264Push:
    """Transcodes decoded frames to H.264 and pushes them to a MediaMTX path.

    Republishes sources MediaMTX cannot pull itself (e.g. MJPEG over HTTP) so
    viewers receive them as HLS. Timestamps follow the wall clock and a
    keyframe is forced every KEYFRAME_INTERVAL_S, keeping HLS segments short
    regardless of the source's real, often variable, frame rate.

    Encoding, connecting and writing all happen on a thread of this push's own,
    and ``send`` only queues, so a live view that stops answering costs the
    caller nothing: capture is what feeds detection. A push that fails is
    dropped and opened again from the next frame after ``retry_after`` seconds,
    the frames in between being discarded. ``outcome`` is called from the
    thread with the error each failed attempt ended in, and with None each time
    a frame went out.

    Conversion to the encoder's pixel format goes through one reused
    single-threaded scaler: PyAV's per-frame ``reformat`` builds a fresh
    scaler whose default thread count spawns a slice-thread pool per call,
    which at a camera's frame rate churns hundreds of OS threads a second
    faster than they are reaped, until the process can no longer start one.
    """

    def __init__(
        self, rtsp_url: str, fps: int, retry_after: float, outcome: Callable[[Exception | None], None] = lambda error: None
    ) -> None:
        self._rtsp_url = rtsp_url
        self._fps = fps
        self._retry_after = retry_after
        self._outcome = outcome
        self._clock = Fraction(1, RTP_CLOCK)
        self._reformatter = VideoReformatter()
        self._push: av.container.OutputContainer | None = None
        self._stream: av.video.stream.VideoStream | None = None
        self._start = 0.0
        self._last_key = 0.0
        self._retry_at = 0.0
        self._frames: deque[av.VideoFrame] = deque(maxlen=PUSH_QUEUED_FRAMES)
        self._ready = threading.Event()
        self._closing = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def send(self, frame: av.VideoFrame) -> None:
        """Queues a frame for the live view without waiting on it."""
        self._frames.append(frame)
        self._ready.set()

    def close(self) -> None:
        """Drops the frames still queued and closes the session, so the next push opens a new one."""
        self._closing = True
        self._ready.set()
        self._thread.join(PUSH_TIMEOUT_US / 1e6 + 2)

    def _run(self) -> None:
        while not self._closing:
            self._ready.wait()
            self._ready.clear()
            while self._frames and not self._closing:
                frame = self._frames.popleft()
                if time.monotonic() < self._retry_at:
                    continue
                try:
                    self._encode(frame)
                except Exception as exc:
                    self._close_push()
                    self._retry_at = time.monotonic() + self._retry_after
                    self._outcome(exc)
                else:
                    self._outcome(None)
        self._close_push()

    def _encode(self, frame: av.VideoFrame) -> None:
        """Encodes and muxes one decoded frame, opening the push lazily."""
        now = time.monotonic()
        if self._push is None:
            self._push = av.open(
                self._rtsp_url, mode="w", format="rtsp", options={"rtsp_transport": "tcp", "timeout": str(PUSH_TIMEOUT_US)}
            )
            self._stream = self._push.add_stream("libx264", rate=self._fps)
            self._stream.width, self._stream.height = frame.width, frame.height
            self._stream.pix_fmt = "yuv420p"
            self._stream.codec_context.options = {"preset": "ultrafast", "tune": "zerolatency"}
            self._stream.codec_context.time_base = self._clock
            self._start = now
            self._last_key = now - KEYFRAME_INTERVAL_S
        out = self._reformatter.reformat(frame, format="yuv420p", threads=1)
        out.pts = int((now - self._start) / self._clock)
        out.time_base = self._clock
        if now - self._last_key >= KEYFRAME_INTERVAL_S:
            out.pict_type = PictureType.I
            self._last_key = now
        for packet in self._stream.encode(out):
            self._push.mux(packet)

    def _close_push(self) -> None:
        """Flushes the encoder and closes the RTSP push, so the next frame opens a new one."""
        if self._push is None:
            return
        push, self._push = self._push, None
        try:
            try:
                for packet in self._stream.encode(None):
                    push.mux(packet)
            finally:
                push.close()
        except Exception:
            logger.debug("push did not close cleanly", exc_info=True)
