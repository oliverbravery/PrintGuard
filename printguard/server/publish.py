"""Pushes camera video to MediaMTX over RTSP.

Browser recordings (fragmented WebM/MP4 over a WebSocket) are remuxed — never
transcoded — by remux(). Sources MediaMTX cannot pull itself, such as MJPEG
over HTTP, are transcoded to H.264 by H264Push. Either way the result behaves
like any other MediaMTX stream and reaches viewers as HLS.
"""

from __future__ import annotations

import queue
import time
from fractions import Fraction

import av
from av.video.frame import PictureType


class ChunkStream:
    """Blocking file-like view over WebSocket chunks for PyAV."""

    def __init__(self) -> None:
        self._chunks: queue.Queue[bytes | None] = queue.Queue()
        self._buffer = bytearray()
        self._eof = False

    def feed(self, chunk: bytes | None) -> None:
        """Queues a chunk; None marks end of stream."""
        self._chunks.put(chunk)

    def read(self, size: int = -1) -> bytes:
        while not self._eof and (size < 0 or len(self._buffer) < size):
            chunk = self._chunks.get()
            if chunk is None:
                self._eof = True
            else:
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
        fps = int(rate) if rate and 0 < rate <= 60 else 30
        step = RTP_CLOCK // fps
        clock = Fraction(1, RTP_CLOCK)
        with av.open(rtsp_url, mode="w", format="rtsp", options={"rtsp_transport": "tcp"}) as push:
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
    """

    def __init__(self, rtsp_url: str, fps: int) -> None:
        self._rtsp_url = rtsp_url
        self._fps = fps
        self._clock = Fraction(1, RTP_CLOCK)
        self._push: av.container.OutputContainer | None = None
        self._stream: av.video.stream.VideoStream | None = None
        self._start = 0.0
        self._last_key = 0.0

    def send(self, frame: av.VideoFrame) -> None:
        """Encodes and muxes one decoded frame, opening the push lazily."""
        now = time.monotonic()
        if self._push is None:
            self._push = av.open(self._rtsp_url, mode="w", format="rtsp", options={"rtsp_transport": "tcp"})
            self._stream = self._push.add_stream("libx264", rate=self._fps)
            self._stream.width, self._stream.height = frame.width, frame.height
            self._stream.pix_fmt = "yuv420p"
            self._stream.codec_context.options = {"preset": "ultrafast", "tune": "zerolatency"}
            self._stream.codec_context.time_base = self._clock
            self._start = now
            self._last_key = now - KEYFRAME_INTERVAL_S
        out = frame.reformat(format="yuv420p")
        out.pts = int((now - self._start) / self._clock)
        out.time_base = self._clock
        if now - self._last_key >= KEYFRAME_INTERVAL_S:
            out.pict_type = PictureType.I
            self._last_key = now
        for packet in self._stream.encode(out):
            self._push.mux(packet)

    def close(self) -> None:
        """Flushes the encoder and closes the RTSP push."""
        if self._push is None:
            return
        try:
            for packet in self._stream.encode(None):
                self._push.mux(packet)
        except Exception:
            pass
        self._push.close()
        self._push = None
