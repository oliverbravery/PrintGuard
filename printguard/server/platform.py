"""Server implementation of the platform contract for hub mode."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from importlib import metadata
from functools import partial
from pathlib import Path
from typing import Any, Callable

import av
import httpx
import numpy as np
from ai_edge_litert.interpreter import Interpreter

from ..engine import vision
from ..engine.platform import Frame
from .bambu_camera import open_bambu_jpeg_stream
from .mediamtx import MediaMTX
from .publish import H264Push

FPS_SAMPLE_FRAMES = 25
MEASURE_WARMUP_S = 1.0
OPEN_WAIT_S = 8.0
RECONNECT_DELAY_S = 3.0
MJPEG_LIVE_OPTIONS = {"analyzeduration": "0", "probesize": "32"}


class AVSource:
    """Continuously decodes a stream, keeping only the freshest frame.

    The source is either a URL string MediaMTX or ffmpeg can open, or a factory
    returning a fresh readable MJPEG byte stream (used for sources that speak a
    bespoke protocol, e.g. Bambu's chamber camera). When publish_url is set,
    each decoded frame is also transcoded to H.264 and pushed there, so sources
    MediaMTX cannot pull itself reach viewers as HLS.
    """

    def __init__(self, source: str | Callable[[], Any], publish_url: str | None = None) -> None:
        self._source = source
        self._publish_url = publish_url
        self.fps = 0.0
        self.online = False
        self._latest: Frame | None = None
        self._seq = 0
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _open(self) -> tuple[Any, Any]:
        """Opens the container, returning it and any pipe to close afterwards.

        Callable sources are live MJPEG pipes; MJPEG_LIVE_OPTIONS caps the probe
        so av.open identifies the stream from its first frame instead of draining
        the pipe to fill PyAV's multi-megabyte default and never returning.
        """
        if not isinstance(self._source, str):
            pipe = self._source()
            return av.open(pipe, format="mjpeg", options=MJPEG_LIVE_OPTIONS), pipe
        options = {}
        if self._source.startswith("rtsp://"):
            options["rtsp_transport"] = "tcp"
        elif self._source.startswith(("http://", "https://")):
            options["timeout"] = "5000000"
        return av.open(self._source, options=options, timeout=5.0), None

    def _run(self) -> None:
        while not self._stop:
            push: H264Push | None = None
            pipe: Any = None
            try:
                container, pipe = self._open()
                stream = container.streams.video[0]
                declared = float(stream.average_rate or 0)
                if not self.fps and 0 < declared <= 240:
                    self.fps = min(60.0, declared)
                if self._publish_url:
                    rate = stream.guessed_rate or stream.average_rate
                    push = H264Push(self._publish_url, int(rate) if rate and 0 < rate <= 60 else 15)
                warmup_until = time.monotonic() + MEASURE_WARMUP_S
                samples: list[float] = []
                for frame in container.decode(stream):
                    if self._stop:
                        break
                    self._seq += 1
                    self._latest = Frame(rgb=frame.to_ndarray(format="rgb24"), seq=float(self._seq), ts=time.time())
                    self.online = True
                    if push is not None:
                        push.send(frame)
                    if not self.fps and time.monotonic() >= warmup_until:
                        samples.append(time.monotonic())
                        if len(samples) == FPS_SAMPLE_FRAMES and samples[-1] > samples[0]:
                            self.fps = max(1.0, min(60.0, (len(samples) - 1) / (samples[-1] - samples[0])))
                container.close()
            except Exception:
                pass
            finally:
                if push is not None:
                    push.close()
                if pipe is not None:
                    pipe.close()
            self.online = False
            if not self._stop:
                time.sleep(RECONNECT_DELAY_S)

    async def grab(self) -> Frame | None:
        """Returns the freshest decoded frame without copying."""
        return self._latest

    def close(self) -> None:
        """Stops the reader thread."""
        self._stop = True
        self.online = False


class ServerPlatform:
    """Hub mode platform: LiteRT on CPU threads, frames via MediaMTX."""

    mode = "hub"
    update_repo = "oliverbravery/PrintGuard"

    def __init__(self, model_dir: Path, data_dir: Path, mediamtx_api: str, mediamtx_rtsp: str) -> None:
        self.version = metadata.version("printguard")
        self.workers = max(1, (os.cpu_count() or 2) - 1)
        self._executor = ThreadPoolExecutor(max_workers=self.workers)
        self._thread_local = threading.local()
        self._model_path = str(model_dir / "encoder_float32.tflite")
        meta = json.loads((model_dir / "metadata.json").read_text())
        protos = json.loads((model_dir / "prototypes.json").read_text())["prototypes"]
        self.assets = vision.assets_from_dicts(meta, protos)
        self._state_path = data_dir / "state.json"
        data_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.AsyncClient(follow_redirects=True)
        self.mediamtx = MediaMTX(mediamtx_api, mediamtx_rtsp, self._client)

    async def close(self) -> None:
        """Releases the HTTP client and inference workers."""
        await self._client.aclose()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _interpreter(self) -> Interpreter:
        interpreter = getattr(self._thread_local, "interpreter", None)
        if interpreter is None:
            interpreter = Interpreter(model_path=self._model_path)
            interpreter.allocate_tensors()
            self._thread_local.interpreter = interpreter
        return interpreter

    def _infer_sync(self, rgb: np.ndarray) -> dict[str, Any]:
        interpreter = self._interpreter()
        tensor = vision.preprocess(rgb, self.assets)
        interpreter.set_tensor(interpreter.get_input_details()[0]["index"], tensor)
        interpreter.invoke()
        embedding = interpreter.get_tensor(interpreter.get_output_details()[0]["index"])[0].copy()
        return vision.classify(embedding, self.assets)

    async def infer(self, rgb: np.ndarray) -> dict[str, Any]:
        """Runs the model on a worker thread."""
        return await asyncio.get_running_loop().run_in_executor(self._executor, self._infer_sync, rgb)

    async def discover_cameras(self) -> list[dict[str, Any]]:
        """Lists active MediaMTX paths as attachable sources."""
        try:
            paths = await self.mediamtx.list_paths()
        except Exception:
            return []
        return [{"kind": "path", "path": name, "label": name} for name in paths]

    async def open_camera(self, camera_id: str, source: dict[str, Any]) -> AVSource:
        """Attaches to a stream, getting URL sources into MediaMTX for viewers.

        RTSP/RTMP URLs are pulled by MediaMTX; HTTP/MJPEG ones, which it cannot
        pull, are read directly and transcoded back into MediaMTX so both
        inference and viewers see them.
        """
        publish_url: str | None = None
        target: str | Callable[[], Any]
        if source["kind"] == "url":
            source_url = source["url"]
            if source_url.startswith(("http://", "https://")):
                target = source_url
                publish_url = self.mediamtx.rtsp_url(camera_id)
            else:
                await self.mediamtx.ensure_path(camera_id, source_url, source.get("fingerprint"))
                target = self.mediamtx.rtsp_url(camera_id)
        elif source["kind"] == "path":
            target = self.mediamtx.rtsp_url(source["path"])
        elif source["kind"] == "bambu":
            target = partial(open_bambu_jpeg_stream, source["host"], source["access_code"])
            publish_url = self.mediamtx.rtsp_url(camera_id)
        else:
            raise ValueError(f"hub mode cannot open source kind {source['kind']!r}")
        av_source = AVSource(target, publish_url)
        deadline = time.monotonic() + OPEN_WAIT_S
        while time.monotonic() < deadline and not (av_source.online and av_source.fps > 0):
            await asyncio.sleep(0.2)
        if not av_source.online:
            av_source.close()
            await self.release_camera(camera_id, source)
            raise RuntimeError(f"no frames from camera {camera_id}")
        return av_source

    async def release_camera(self, camera_id: str, source: dict[str, Any]) -> None:
        """Removes the MediaMTX path created for a URL-backed camera."""
        if source["kind"] == "url" and not source["url"].startswith(("http://", "https://")):
            try:
                await self.mediamtx.remove_path(camera_id)
            except Exception:
                pass

    async def http(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        data: bytes | None = None,
        timeout: float = 10.0,
    ) -> tuple[int, Any]:
        """Performs an HTTP request with httpx."""
        resp = await self._client.request(method, url, headers=headers, json=json, content=data, timeout=timeout)
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, resp.text

    async def encode_jpeg(self, rgb: np.ndarray) -> bytes | None:
        """Encodes a frame as JPEG using PyAV's mjpeg encoder."""
        def encode() -> bytes:
            even = rgb[: rgb.shape[0] // 2 * 2, : rgb.shape[1] // 2 * 2]
            frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(even), format="rgb24")
            codec = av.CodecContext.create("mjpeg", "w")
            codec.width, codec.height = frame.width, frame.height
            codec.pix_fmt = "yuvj420p"
            codec.time_base = Fraction(1, 30)
            packets = codec.encode(frame.reformat(format="yuvj420p")) + codec.encode(None)
            return b"".join(bytes(p) for p in packets)

        try:
            return await asyncio.get_running_loop().run_in_executor(self._executor, encode)
        except Exception:
            return None

    def load_state(self) -> dict[str, Any]:
        """Reads persisted engine state from the data directory."""
        try:
            return json.loads(self._state_path.read_text())
        except (OSError, ValueError):
            return {}

    def save_state(self, state: dict[str, Any]) -> None:
        """Atomically writes engine state to the data directory."""
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.replace(self._state_path)
