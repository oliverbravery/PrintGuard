"""Republishes browser camera recordings to MediaMTX over RTSP.

The browser streams MediaRecorder chunks (fragmented WebM or MP4) over a
WebSocket; packets are remuxed — never transcoded — into an RTSP push, so
a published camera behaves like any other MediaMTX stream.
"""

from __future__ import annotations

import queue
import time
from fractions import Fraction

import av


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
