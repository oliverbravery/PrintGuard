"""Server implementation of the platform contract for hub mode."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import subprocess
import sys
import threading
import time
from fractions import Fraction
from functools import partial
from importlib import metadata
from pathlib import Path
from typing import Any, Callable

import av
import httpx
import numpy as np
from ..engine import vision
from ..engine.platform import Frame
from .bambu_camera import open_bambu_jpeg_stream
from .inference import Inference
from .mediamtx import MediaMTX, pull_source
from .publish import H264Push

FPS_SAMPLE_FRAMES = 25
MEASURE_WARMUP_S = 1.0
OPEN_WAIT_S = 25.0
CAMERA_CONSENT_WAIT_S = 60.0
RECONNECT_DELAY_S = 3.0
DEMAND_IDLE_S = 10.0
MJPEG_LIVE_OPTIONS = {"analyzeduration": "0", "probesize": "32"}
DEVICE_OPEN_OPTIONS = ({"framerate": "30"}, {"framerate": "15"}, {})
"""Frame rates tried, most common first, when a device's own capture formats
cannot be read ahead of time (Windows/Linux); macOS pins a real size and rate
from AVFoundation in _device_open_options."""
DEVICE_SIZE_CAP = 1280 * 720
DEVICE_PIXEL_FORMATS = {"420v": "nv12", "420f": "nv12", "yuvs": "yuyv422", "2vuy": "uyvy422"}
"""AVFoundation format subtypes mapped to ffmpeg pixel formats. avfoundation
defaults to yuv420p, which it silently downgrades to the packed uyvy422 formats
— often capped to a few fps — so the biplanar nv12 formats that carry a device's
full frame rate are requested by name instead."""

logger = logging.getLogger(__name__)


def _video_devices() -> list[tuple[str, str]]:
    """Names the host's attachable video capture devices as (device_id, label).

    libavdevice only exposes device discovery through its log stream, so the
    names are parsed from a capture of the listing call's messages, raised to
    INFO for the duration. Screens are excluded - a capture of the host's own
    display is never a printer camera. Listing needs no camera permission;
    only opening a device does.
    """
    if sys.platform.startswith("linux"):
        devices = []
        for node in sorted(Path("/dev").glob("video*")):
            name_file = Path("/sys/class/video4linux") / node.name / "name"
            try:
                devices.append((str(node), name_file.read_text().strip()))
            except OSError:
                devices.append((str(node), node.name))
        return devices
    import av.logging

    spec, container_format = ("", "avfoundation") if sys.platform == "darwin" else ("video=dummy", "dshow")
    previous = av.logging.get_level()
    av.logging.set_level(av.logging.INFO)
    try:
        with av.logging.Capture(local=True) as logs:
            try:
                av.open(spec, format=container_format, options={"list_devices": "true"})
            except OSError:
                pass
    finally:
        av.logging.set_level(previous)
    logger.debug("device listing captured %d lines: %r", len(logs), [message for _lv, _n, message in logs])
    names: list[str] = []
    in_video_section = False
    for _level, _name, message in logs:
        line = message.strip()
        if sys.platform == "darwin":
            if line.endswith("video devices:"):
                in_video_section = True
            elif line.endswith("audio devices:"):
                in_video_section = False
            elif in_video_section and (match := re.match(r"\[\d+\] (.+)", line)) and not match[1].startswith("Capture screen"):
                names.append(match[1])
        elif match := re.match(r'"(.+)" \(video', line):
            names.append(match[1])
    return [(name, name) for name in names]


def _device_input(device_id: str) -> tuple[str, str]:
    """Maps a video device to the host's libavdevice demuxer and input string."""
    if sys.platform == "darwin":
        return "avfoundation", device_id
    if sys.platform == "win32":
        return "dshow", f"video={device_id}"
    return "v4l2", device_id


def _device_open_options(device_id: str) -> tuple[dict[str, str], ...]:
    """Capture options to try when opening a device, most specific first.

    ffmpeg's avfoundation ignores the requested frame rate when no size is given
    and settles on the device's last-listed format - routinely its top
    resolution pinned to a handful of fps - so 30/15fps requests come back as
    EAGAIN. On macOS the real formats are read from AVFoundation and the largest
    size within a sane cap that offers a usable rate is pinned explicitly; other
    platforms negotiate over common frame rates.
    """
    if sys.platform != "darwin":
        return DEVICE_OPEN_OPTIONS
    import objc
    from Foundation import NSBundle

    NSBundle.bundleWithPath_("/System/Library/Frameworks/AVFoundation.framework").load()
    capture_device = objc.lookUpClass("AVCaptureDevice")
    device = next((d for d in capture_device.devicesWithMediaType_("vide") if d.localizedName() == device_id), None)
    if device is None:
        return DEVICE_OPEN_OPTIONS
    modes: list[tuple[int, int, int, str]] = []
    for fmt in device.formats():
        description = str(fmt.description())
        size = re.search(r"(\d+)x(\d+),\s*\{", description)
        subtype = re.search(r"'vide'/'(\w{4})'", description)
        rate = max((float(r.maxFrameRate()) for r in fmt.videoSupportedFrameRateRanges()), default=0.0)
        pixel_format = DEVICE_PIXEL_FORMATS.get(subtype[1]) if subtype else None
        if size and rate > 0 and pixel_format:
            modes.append((int(size[1]), int(size[2]), min(int(rate), 30), pixel_format))
    if not modes:
        return DEVICE_OPEN_OPTIONS
    within_cap = [mode for mode in modes if mode[0] * mode[1] <= DEVICE_SIZE_CAP] or modes
    width, height, framerate, pixel_format = max(within_cap, key=lambda mode: (mode[2], mode[0] * mode[1]))
    pinned = {"video_size": f"{width}x{height}", "framerate": str(framerate), "pixel_format": pixel_format}
    return (pinned, {"framerate": str(framerate)}, {})


def _macos_capture_input_usable(objc_module: Any, capture_device: Any) -> bool:
    """Whether an authorised-looking consent state actually permits capture.

    Creating a capture input is the very call libavdevice fails on when a
    recorded grant no longer matches this build's code signature. It starts
    no session, so probing never lights the camera-active indicator.
    """
    device = capture_device.defaultDeviceWithMediaType_("vide")
    if device is None:
        return True
    objc_module.registerMetaDataForSelector(
        b"AVCaptureDeviceInput", b"deviceInputWithDevice:error:", {"arguments": {3: {"type_modifier": b"o"}}}
    )
    created, _error = objc_module.lookUpClass("AVCaptureDeviceInput").deviceInputWithDevice_error_(device, None)
    return created is not None


def _authorize_macos_camera() -> None:
    """Settles the macOS camera-consent state, raising when capture is refused.

    libavdevice never raises the consent prompt: opening a device while consent
    is undetermined starts a session that delivers no frames, and once refused
    the capture input fails instantly with EAGAIN. So consent is settled through
    AVFoundation first, blocking until the user answers. A grant recorded for a
    previous build still reads as authorised while capture is refused - each
    unsigned build re-signs ad hoc with a new identity - so an authorised state
    is probed with a real capture input, and a refusal resets this app's own
    consent entry to let the prompt be asked afresh. Other platforms gate
    camera capture without a per-process consent step.
    """
    if sys.platform != "darwin":
        return
    import objc
    from Foundation import NSBundle

    NSBundle.bundleWithPath_("/System/Library/Frameworks/AVFoundation.framework").load()
    capture_device = objc.lookUpClass("AVCaptureDevice")
    status = capture_device.authorizationStatusForMediaType_("vide")
    if status == 3:
        if _macos_capture_input_usable(objc, capture_device):
            return
        bundle_id = NSBundle.mainBundle().bundleIdentifier()
        if bundle_id:
            subprocess.run(["tccutil", "reset", "Camera", str(bundle_id)], check=False, capture_output=True)
        status = capture_device.authorizationStatusForMediaType_("vide")
    if status == 0:
        objc.registerMetaDataForSelector(
            b"AVCaptureDevice",
            b"requestAccessForMediaType:completionHandler:",
            {"arguments": {3: {"callable": {"retval": {"type": b"v"}, "arguments": {0: {"type": b"^v"}, 1: {"type": b"Z"}}}}}},
        )
        answered = threading.Event()
        granted: list[bool] = [False]

        def record(allowed: bool) -> None:
            granted[0] = bool(allowed)
            answered.set()

        capture_device.requestAccessForMediaType_completionHandler_("vide", record)
        if answered.wait(CAMERA_CONSENT_WAIT_S) and granted[0]:
            return
    raise RuntimeError(
        "macOS camera access is not granted — allow PrintGuard under System Settings → Privacy & Security → Camera"
    )


class AVSource:
    """Continuously decodes a stream, keeping only the freshest frame.

    The source is either a URL string MediaMTX or ffmpeg can open, or a factory
    returning a fresh readable MJPEG byte stream (used for sources that speak a
    bespoke protocol, e.g. Bambu's chamber camera). When publish_url is set,
    each decoded frame is also transcoded to H.264 and pushed there, so sources
    MediaMTX cannot pull itself reach viewers as HLS.
    """

    def __init__(
        self,
        source: str | Callable[[], Any],
        publish_url: str | None = None,
        container_format: str | None = None,
        open_options: tuple[dict[str, str], ...] | None = None,
    ) -> None:
        self._source = source
        self._publish_url = publish_url
        self._container_format = container_format
        self._open_options = open_options or DEVICE_OPEN_OPTIONS
        self.fps = 0.0
        self.online = False
        self.last_error: str | None = None
        self._latest: tuple[av.VideoFrame, float, float] | None = None
        self._latest_rgb: Frame | None = None
        self._seq = 0
        self._stop = False
        self._monitoring = True
        self._demand_until = 0.0
        self._wake = threading.Event()
        self._wake.set()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @property
    def standby(self) -> bool:
        """Whether capture is sleeping until inference or a viewer needs it."""
        return not self._demanded()

    def _demanded(self) -> bool:
        return self._monitoring or time.monotonic() < self._demand_until

    def set_monitoring(self, active: bool) -> None:
        """Keeps capture running while inference needs frames."""
        if self._monitoring and not active:
            self._demand_until = max(self._demand_until, time.monotonic() + DEMAND_IDLE_S)
        self._monitoring = active
        self._wake.set()

    def view(self) -> bool:
        """Keeps direct-source publishing alive for a recent HLS viewer."""
        if self._publish_url is None:
            return False
        self._demand_until = time.monotonic() + DEMAND_IDLE_S
        self._wake.set()
        return True

    def _open(self) -> tuple[Any, Any]:
        """Opens the container, returning it and any pipe to close afterwards.

        Callable sources are live MJPEG pipes; MJPEG_LIVE_OPTIONS caps the probe
        so av.open identifies the stream from its first frame instead of draining
        the pipe to fill PyAV's multi-megabyte default and never returning.
        """
        if not isinstance(self._source, str):
            pipe = self._source()
            return av.open(pipe, format="mjpeg", options=MJPEG_LIVE_OPTIONS), pipe
        if self._container_format is not None:
            last: Exception | None = None
            for options in self._open_options:
                try:
                    return av.open(self._source, format=self._container_format, options=options, timeout=5.0), None
                except OSError as exc:
                    last = exc
            raise last if last else RuntimeError(f"could not open {self._source!r}")
        options = {}
        if self._source.startswith("rtsp://"):
            options["rtsp_transport"] = "tcp"
        elif self._source.startswith(("http://", "https://")):
            options["timeout"] = "5000000"
        return av.open(self._source, options=options, timeout=5.0), None

    def _run(self) -> None:
        while not self._stop:
            if not self._demanded():
                self.online = False
                self._wake.wait()
                self._wake.clear()
                continue
            container: Any = None
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
                self._decode(container, stream, push)
            except Exception as exc:
                self.last_error = str(exc)
                logger.debug("camera source %r read failed: %s", self._source, exc)
            finally:
                if container is not None:
                    container.close()
                if push is not None:
                    push.close()
                if pipe is not None:
                    pipe.close()
            self.online = False
            if not self._stop and self._demanded():
                time.sleep(RECONNECT_DELAY_S)

    def _decode(self, container: Any, stream: Any, push: H264Push | None) -> None:
        """Keeps the freshest frame until the source ends, transcoding if asked.

        A capture device announces its stream before a frame is buffered, so the
        first reads - and any gap between frames - surface as EAGAIN. That is not
        a disconnect: the open session is kept and the read retried, rather than
        torn down and reconnected as a network drop would be.
        """
        warmup_until = time.monotonic() + MEASURE_WARMUP_S
        samples: list[float] = []
        while not self._stop:
            try:
                for frame in container.decode(stream):
                    if self._stop or not self._demanded():
                        return
                    self._seq += 1
                    self._latest = (frame, float(self._seq), time.time())
                    self.online = True
                    if push is not None:
                        push.send(frame)
                    if not self.fps and time.monotonic() >= warmup_until:
                        samples.append(time.monotonic())
                        if len(samples) == FPS_SAMPLE_FRAMES and samples[-1] > samples[0]:
                            self.fps = max(1.0, min(60.0, (len(samples) - 1) / (samples[-1] - samples[0])))
                return
            except av.error.BlockingIOError:
                time.sleep(0.02)

    async def grab(self) -> Frame | None:
        """Converts and returns the freshest decoded frame."""
        latest = self._latest
        if latest is None:
            return None
        frame, seq, ts = latest
        if self._latest_rgb is not None and self._latest_rgb.seq == seq:
            return self._latest_rgb
        rgb = await asyncio.to_thread(frame.to_ndarray, format="rgb24")
        result = Frame(rgb=rgb, seq=seq, ts=ts)
        if self._latest is latest:
            self._latest_rgb = result
        return result

    def close(self) -> None:
        """Stops the reader thread."""
        self._stop = True
        self.online = False
        self._wake.set()


class ServerPlatform:
    """Hub mode platform: hardware inference and frames via MediaMTX."""

    mode = "hub"
    update_repo = "oliverbravery/PrintGuard"

    def __init__(
        self, model_dir: Path, data_dir: Path, mediamtx_api: str, mediamtx_rtsp: str, update_asset: str | None = None
    ) -> None:
        self.version = metadata.version("printguard")
        self.update_asset = update_asset
        data_dir.mkdir(parents=True, exist_ok=True)
        self._inference = Inference(model_dir / "encoder_float32.onnx", data_dir / "model-cache")
        self.workers = self._inference.workers
        self.inference_device = self._inference.device
        logger.info("inference ready: %s (%d workers)", self.inference_device, self.workers)
        meta = json.loads((model_dir / "metadata.json").read_text())
        protos = json.loads((model_dir / "prototypes.json").read_text())["prototypes"]
        self.assets = vision.assets_from_dicts(meta, protos)
        self._state_path = data_dir / "state.json"
        self._client = httpx.AsyncClient(follow_redirects=True)
        self.mediamtx = MediaMTX(mediamtx_api, mediamtx_rtsp, self._client)
        self._sources: dict[str, AVSource] = {}

    async def close(self) -> None:
        """Releases the HTTP client and inference workers."""
        await self._client.aclose()
        self._inference.close()

    async def infer(self, rgb: np.ndarray) -> dict[str, Any]:
        """Runs the model through the selected hardware provider."""
        tensor = await asyncio.to_thread(vision.preprocess, rgb, self.assets)
        return vision.classify(await self._inference.run(tensor), self.assets)

    async def discover_cameras(self) -> list[dict[str, Any]]:
        """Lists the host's video devices and active MediaMTX paths as attachable sources."""
        devices = await asyncio.to_thread(_video_devices)
        sources: list[dict[str, Any]] = [{"kind": "device", "device_id": device_id, "label": label} for device_id, label in devices]
        try:
            paths = await self.mediamtx.list_paths()
        except Exception:
            return sources
        return sources + [{"kind": "path", "path": name, "label": name} for name in paths]

    async def open_camera(self, camera_id: str, source: dict[str, Any]) -> AVSource:
        """Attaches to a stream, getting URL sources into MediaMTX for viewers.

        RTSP/RTMP URLs and WebRTC WHEP endpoints are pulled by MediaMTX;
        HTTP/MJPEG ones are read directly and transcoded back into MediaMTX so
        both inference and viewers see them. Device sources are the host's own
        cameras, captured through libavdevice in this process - not a browser
        page - so on the desktop app they keep watching with every window closed;
        they are republished the same way.

        The wait must outlast a freshly published path's cold start: the remux
        announcing the track, a not-found retry, the demuxer probe, a mid-GOP
        join and - when the container declares no rate - measuring the fps.
        Together those approach twenty seconds; sources that are truly dead
        just take this long to report.
        """
        publish_url: str | None = None
        container_format: str | None = None
        open_options: tuple[dict[str, str], ...] | None = None
        target: str | Callable[[], Any]
        if source["kind"] == "device":
            await asyncio.to_thread(_authorize_macos_camera)
            container_format, target = _device_input(source["device_id"])
            open_options = await asyncio.to_thread(_device_open_options, source["device_id"])
            publish_url = self.mediamtx.rtsp_url(camera_id)
        elif source["kind"] == "url":
            pulled = pull_source(source["url"])
            if pulled is None:
                target = source["url"]
                publish_url = self.mediamtx.rtsp_url(camera_id)
            else:
                await self.mediamtx.ensure_path(camera_id, pulled, source.get("fingerprint"))
                target = self.mediamtx.rtsp_url(camera_id)
        elif source["kind"] == "path":
            target = self.mediamtx.rtsp_url(source["path"])
        elif source["kind"] == "bambu":
            target = partial(open_bambu_jpeg_stream, source["host"], source["access_code"])
            publish_url = self.mediamtx.rtsp_url(camera_id)
        else:
            raise ValueError(f"hub mode cannot open source kind {source['kind']!r}")
        av_source = AVSource(target, publish_url, container_format, open_options)
        self._sources[camera_id] = av_source
        try:
            deadline = time.monotonic() + OPEN_WAIT_S
            while time.monotonic() < deadline and not (av_source.online and av_source.fps > 0):
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            if self._sources.get(camera_id) is av_source:
                await self.release_camera(camera_id, source)
            else:
                av_source.close()
            raise
        if not av_source.online:
            await self.release_camera(camera_id, source)
            detail = f": {av_source.last_error}" if av_source.last_error else ""
            raise RuntimeError(f"no frames from camera {camera_id}{detail}")
        return av_source

    async def view_camera(self, camera_id: str) -> None:
        """Wakes a direct camera source for an HLS request."""
        source = self._sources.get(camera_id)
        if not source or not source.view():
            return
        deadline = time.monotonic() + OPEN_WAIT_S
        while time.monotonic() < deadline and not source.online:
            await asyncio.sleep(0.1)
        source.view()

    async def release_camera(self, camera_id: str, source: dict[str, Any]) -> None:
        """Closes the source and removes any MediaMTX pull path."""
        av_source = self._sources.pop(camera_id, None)
        if av_source:
            av_source.close()
        if source["kind"] == "url" and pull_source(source["url"]) is not None:
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
            return await asyncio.to_thread(encode)
        except Exception:
            return None

    async def decode_jpeg(self, data: bytes) -> np.ndarray | None:
        """Decodes supplied image bytes to an RGB frame with PyAV."""
        def decode() -> np.ndarray:
            with av.open(io.BytesIO(data)) as container:
                return next(container.decode(video=0)).to_ndarray(format="rgb24")

        try:
            return await asyncio.to_thread(decode)
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
