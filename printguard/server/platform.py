"""The hub's implementation of the platform contract."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
import stat
import struct
import subprocess
import sys
import threading
import time
import zlib
from fractions import Fraction
from functools import partial
from importlib import metadata
from pathlib import Path
from typing import Any, AsyncIterable, Callable

import av
import httpx
import numpy as np
import websockets
from av.video.reformatter import VideoReformatter
from ..engine import vision
from ..engine.platform import Frame, Notice
from ..engine.reports import scrub_url
from .bambu_camera import open_bambu_jpeg_stream
from .inference import Inference
from .mediamtx import MediaMTX, pull_source
from .plugins import WasmPluginRuntime
from .publish import H264Push

FPS_SAMPLE_FRAMES = 25
FPS_SAMPLE_S = 5.0
READER_STOP_WAIT_S = 6.0
"""How long a closed source's reader is given to end before its camera is
opened again: a read that times out and the pause before a reconnect."""

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

V4L2_OPEN_OPTIONS = ({"input_format": "mjpeg", "framerate": "30"}, {"input_format": "mjpeg"}, *DEVICE_OPEN_OPTIONS)
"""Capture options tried on Linux, MJPEG first. ffmpeg otherwise settles on a
webcam's first listed format, routinely uncompressed YUYV, which saturates the
USB bus and drops a 720p camera to a few frames a second, and several cameras
on one controller to none at all."""

V4L2_MAJOR = 81
VIDIOC_QUERYCAP = 0x80685600
V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_DEVICE_CAPS = 0x80000000
V4L2_CAPABILITY = "16x32s32xIII12x"
"""struct v4l2_capability in full, since the kernel writes all of it, unpacking
only card, version, capabilities and device_caps."""

SOCKET_TIMEOUT_S = 10.0
SOCKET_MAX_BYTES = 256 * 1024
DEVICE_SIZE_CAP = 1280 * 720
DEVICE_PIXEL_FORMATS = {"420v": "nv12", "420f": "nv12", "yuvs": "yuyv422", "2vuy": "uyvy422"}
"""AVFoundation format subtypes mapped to ffmpeg pixel formats. avfoundation
defaults to yuv420p, which it silently downgrades to the packed uyvy422 formats
(often capped to a few fps) so the biplanar nv12 formats that carry a device's
full frame rate are requested by name instead."""

logger = logging.getLogger(__name__)


def deployment(packaged: bool) -> str:
    """Names the deployment a plugin's declared platforms are matched against.

    Args:
        packaged: Whether this is the desktop app, which is the only build
            carrying its own installer to update with.

    Returns:
        A ``PLATFORMS`` id. The image build arg carries the variant, so the
        Intel and NVIDIA images name themselves and the plain one does not.
    """
    if packaged:
        return "macos" if sys.platform == "darwin" else "windows"
    return f"docker{os.environ.get('PRINTGUARD_VARIANT', '')}"


def _v4l2_card(node: Path) -> str | None:
    """The card name of a V4L2 node that captures video, or None if it does not.

    A USB camera registers a metadata node beside its video one, and only
    ``device_caps`` tells the two apart: the device-wide ``capabilities`` field
    advertises capture on both. Asking opens the node read-only and starts no
    stream, so a camera already in use answers too.
    """
    import fcntl

    try:
        descriptor = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        buffer = bytearray(struct.calcsize(V4L2_CAPABILITY))
        fcntl.ioctl(descriptor, VIDIOC_QUERYCAP, buffer)
    except OSError:
        return None
    finally:
        os.close(descriptor)
    card, _version, capabilities, device_caps = struct.unpack(V4L2_CAPABILITY, buffer)
    node_caps = device_caps if capabilities & V4L2_CAP_DEVICE_CAPS else capabilities
    if not node_caps & V4L2_CAP_VIDEO_CAPTURE:
        return None
    return card.split(b"\0")[0].decode(errors="replace").strip()


def _v4l2_devices() -> list[tuple[str, str]]:
    """Names the V4L2 capture nodes this process can see as (device_id, label).

    Nodes are found by their character device major rather than by a ``video*``
    glob, so a camera passed into a container under a name of its own, such as
    ``/dev/nozzle-cam``, is found as readily. A node reached under both a
    ``by-id`` name and a ``videoN`` one is listed under the ``by-id`` name,
    which still points at the same camera after a reboot renumbers the devices.
    """
    found: dict[int, tuple[str, str]] = {}
    for directory in (Path("/dev/v4l/by-id"), Path("/dev")):
        for node in sorted(directory.glob("*")):
            try:
                described = node.stat()
            except OSError:
                continue
            if not stat.S_ISCHR(described.st_mode) or os.major(described.st_rdev) != V4L2_MAJOR:
                continue
            if described.st_rdev in found:
                continue
            card = _v4l2_card(node)
            if card:
                found[described.st_rdev] = (str(node), card)
    return list(found.values())


def _video_devices() -> list[tuple[str, str]]:
    """Names the host's attachable video capture devices as (device_id, label).

    Screens are excluded - a capture of the host's own display is never a
    printer camera. Listing needs no camera permission; only opening a device
    does. DirectShow gives every device a path of its own beside the name it
    shows, and opens it by either, so on Windows the path is the id and two
    cameras of one model stay two cameras. AVFoundation's only other name is a
    position in the list, which moves whenever a camera is plugged in, so on
    macOS a device is still opened by the name it shows.
    """
    if sys.platform.startswith("linux"):
        return _v4l2_devices()
    backend = "avfoundation" if sys.platform == "darwin" else "dshow"
    try:
        devices = av.device.enumerate_input_devices(backend)
    except av.error.FFmpegError as exc:
        logger.debug("%s could not list its devices: %s", backend, exc)
        return []
    logger.debug("%s lists %s", backend, [(device.name, device.description, device.media_types) for device in devices])
    cameras = [
        device
        for device in devices
        if "video" in device.media_types and not device.description.startswith("Capture screen")
    ]
    shown = [device.description for device in cameras]
    return [
        (
            device.description if backend == "avfoundation" else device.name,
            f"{device.description} ({shown[:position].count(device.description) + 1})"
            if shown.count(device.description) > 1
            else device.description,
        )
        for position, device in enumerate(cameras)
    ]


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
    size within a sane cap that offers a usable rate is pinned explicitly; Linux
    asks for MJPEG and other platforms negotiate over common frame rates.
    """
    if sys.platform.startswith("linux"):
        return V4L2_OPEN_OPTIONS
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
    build signed by another identity - an ad hoc local build, or a release before
    2.5.0 - still reads as authorised while capture is refused, so an authorised state
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
        "macOS camera access is not granted. Allow PrintGuard under Privacy & Security, then Camera, in System Settings"
    )


class AVSource:
    """Continuously decodes a stream, keeping only the freshest frame.

    The source is either a URL string MediaMTX or ffmpeg can open, or a factory
    returning a fresh readable MJPEG byte stream (used for sources that speak a
    bespoke protocol, e.g. Bambu's chamber camera). When publish_url is set,
    each decoded frame is also transcoded to H.264 and pushed there, so sources
    MediaMTX cannot pull itself reach viewers as HLS. A push that fails costs
    the live view alone: capture carries on feeding detection, the failure is
    reported once through ``report``, and the push is tried again every
    RECONNECT_DELAY_S.

    A container's declared rate is taken for a network stream or a device and
    measured for a byte stream, whose raw MJPEG demuxer answers 25 whatever the
    camera sends. Measuring ends after FPS_SAMPLE_FRAMES frames or FPS_SAMPLE_S
    seconds, whichever comes first, so a camera sending one frame a second is
    not waited on for half a minute.

    Frames are converted to RGB through one reused single-threaded scaler,
    for the reason H264Push documents, and one conversion at a time: a scaler
    is a single FFmpeg context, and the scheduler and a snapshot request can
    both ask for the freshest frame at once.
    """

    def __init__(
        self,
        source: str | Callable[[], Any],
        publish_url: str | None = None,
        container_format: str | None = None,
        open_options: tuple[dict[str, str], ...] | None = None,
        report: Callable[[str, bool], None] = lambda message, recovered: None,
    ) -> None:
        self._source = source
        self._report = report
        self._publish_url = publish_url
        self._container_format = container_format
        self._open_options = open_options or DEVICE_OPEN_OPTIONS
        self.fps = 0.0
        self.online = False
        self.last_error: str | None = None
        self._latest: tuple[av.VideoFrame, float, float] | None = None
        self._latest_rgb: Frame | None = None
        self._reformatter = VideoReformatter()
        self._converting = asyncio.Lock()
        self._seq = 0
        self._stop = False
        self._monitoring = True
        self._demand_until = 0.0
        self._publish_failed = False
        self._publish_retry_at = 0.0
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
                except av.error.FFmpegError as exc:
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
                if isinstance(self._source, str) and not self.fps and 0 < declared <= 240:
                    self.fps = min(60.0, declared)
                if self._publish_url:
                    rate = stream.guessed_rate or stream.average_rate
                    push = H264Push(self._publish_url, int(rate) if rate and 0 < rate <= 60 else 15)
                self._decode(container, stream, push)
            except Exception as exc:
                self.last_error = self._without_credentials(str(exc))
                logger.debug("camera source read failed: %s", self.last_error)
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

    def _without_credentials(self, message: str) -> str:
        """Scrubs the source address out of an error PyAV raised, which quotes it in full."""
        if not isinstance(self._source, str):
            return message
        return message.replace(self._source, scrub_url(self._source))

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
                        self._publish(push, frame)
                    if not self.fps and time.monotonic() >= warmup_until:
                        samples.append(time.monotonic())
                        measured_for = samples[-1] - samples[0]
                        if measured_for > 0 and (len(samples) == FPS_SAMPLE_FRAMES or measured_for >= FPS_SAMPLE_S):
                            self.fps = max(1.0, min(60.0, (len(samples) - 1) / (samples[-1] - samples[0])))
                return
            except av.error.BlockingIOError:
                time.sleep(0.02)

    def _publish(self, push: H264Push, frame: av.VideoFrame) -> None:
        """Pushes a frame to the live view, leaving capture running when that fails."""
        if time.monotonic() < self._publish_retry_at:
            return
        try:
            push.send(frame)
        except av.error.FFmpegError as exc:
            push.close()
            self._publish_retry_at = time.monotonic() + RECONNECT_DELAY_S
            if not self._publish_failed:
                self._publish_failed = True
                self.last_error = f"live view unavailable: {exc}"
                self._report(f"{self.last_error}. Detection carries on without it", False)
            return
        if self._publish_failed:
            self._publish_failed = False
            self._report("live view restored", True)

    async def grab(self) -> Frame | None:
        """Converts and returns the freshest decoded frame.

        Returns:
            The frame, or None while capture is on standby or reconnecting: the
            last frame it decoded before then is no longer what the camera sees.
        """
        latest = self._latest
        if latest is None or not self.online:
            return None
        frame, seq, ts = latest
        async with self._converting:
            if self._latest_rgb is not None and self._latest_rgb.seq == seq:
                return self._latest_rgb
            rgb = await asyncio.to_thread(self._to_rgb, frame)
            result = Frame(rgb=rgb, seq=seq, ts=ts)
            if self._latest is latest:
                self._latest_rgb = result
            return result

    def _to_rgb(self, frame: av.VideoFrame) -> np.ndarray:
        return self._reformatter.reformat(frame, format="rgb24", threads=1).to_ndarray()

    def close(self) -> None:
        """Asks the reader thread to stop."""
        self._stop = True
        self.online = False
        self._wake.set()

    def stopped(self, timeout: float) -> bool:
        """Waits for the reader thread to end, reporting whether it has.

        A read inside libavdevice cannot be interrupted, so a device that
        opens and never delivers a frame holds its thread and its capture
        session for good.
        """
        self._thread.join(timeout)
        return not self._thread.is_alive()


class ConnectWithoutRedirects(websockets.connect):
    """A WebSocket handshake that ends at the address it was given."""

    def process_redirect(self, exc: Exception) -> Exception:
        """Hands a redirect back as the refusal it arrived as, never the address to try next."""
        return exc


async def _read_within(resp: httpx.Response, max_bytes: int) -> bytes:
    """Reads a response body, giving up once it passes a size.

    Args:
        resp: A response whose body has not been read.
        max_bytes: The most the body may come to once inflated.

    Returns:
        The body, inflated if it came as gzip.

    Raises:
        RuntimeError: If the body is larger, raised while it is still arriving,
            or came in an encoding the request did not ask for.
    """
    encoding = resp.headers.get("Content-Encoding", "identity").lower()
    if encoding not in ("gzip", "identity"):
        raise RuntimeError(f"{resp.url.host} answered in {encoding}, which was not asked for")
    inflate = zlib.decompressobj(zlib.MAX_WBITS | 16) if encoding == "gzip" else None
    body = bytearray()
    async for chunk in resp.aiter_raw():
        body += inflate.decompress(chunk, max_bytes + 1 - len(body)) if inflate else chunk
        if len(body) > max_bytes:
            raise RuntimeError(f"{resp.url.host} answered with more than {max_bytes // 1024} KB")
    return bytes(body)


def _parsed(content: bytes, encoding: str | None, binary: bool) -> Any:
    """Turns a response body into what ``Platform.http`` hands back.

    Args:
        content: The body as bytes.
        encoding: The charset the response declared.
        binary: Whether the caller asked for the bytes themselves.

    Returns:
        Base64 for a binary reply, parsed JSON where the body is JSON, and the
        text otherwise.
    """
    if binary:
        return base64.b64encode(content).decode()
    try:
        return json.loads(content)
    except ValueError:
        return content.decode(encoding or "utf-8", "replace")


class WebSocket:
    """One connection the hub holds open for a plugin."""

    def __init__(self, connection: websockets.ClientConnection) -> None:
        self._connection = connection
        self._reader: asyncio.Task[None] | None = None

    def read(self, arrived: Callable[[str, str], None]) -> None:
        """Starts reporting frames, and reports the close whatever ends it."""

        async def pump() -> None:
            arrived("open", "")
            try:
                async for frame in self._connection:
                    arrived("message", frame if isinstance(frame, str) else frame.decode("utf-8", "replace"))
            except Exception as exc:
                logger.info("plugin socket ended: %s", exc)
            finally:
                arrived("closed", "")

        self._reader = asyncio.ensure_future(pump())

    async def send(self, text: str) -> None:
        """Writes one text frame."""
        await self._connection.send(text)

    async def close(self) -> None:
        """Closes the connection and stops its reader."""
        if self._reader is not None:
            self._reader.cancel()
        await self._connection.close()


class DiskFileStore:
    """Print files and their previews on disk, under the data directory.

    A file is written beside its final name and renamed into place once it is
    complete, so a read never sees a partial upload and an upload that fails
    part way leaves nothing behind.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        """Where a key's bytes live, for serving straight from disk."""
        return self.root / key

    async def store(self, key: str, chunks: AsyncIterable[bytes]) -> int:
        """Writes a file from its chunks, replacing any under that key.

        Each write runs on a worker thread: an upload can be hundreds of
        megabytes onto an SD card, and the event loop also carries detection.
        """
        partial = self.path(f"{key}.part")
        size = 0
        try:
            with await asyncio.to_thread(partial.open, "wb") as handle:
                async for chunk in chunks:
                    await asyncio.to_thread(handle.write, chunk)
                    size += len(chunk)
            partial.replace(self.path(key))
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        return size

    async def read(self, key: str) -> bytes:
        """Returns a stored file's bytes."""
        return await asyncio.to_thread(self.path(key).read_bytes)

    async def remove(self, key: str) -> None:
        """Deletes a stored file, if there is one."""
        await asyncio.to_thread(self.path(key).unlink, True)


class ServerPlatform:
    """The hub's platform, with hardware inference and frames via MediaMTX."""

    update_repo = "oliverbravery/PrintGuard"

    def __init__(
        self,
        model_dir: Path,
        data_dir: Path,
        mediamtx_api: str,
        mediamtx_rtsp: str,
        update_asset: str | None = None,
        mediamtx_login: tuple[str, str] | None = None,
    ) -> None:
        self.version = metadata.version("printguard")
        self.update_asset = update_asset
        self.host = deployment(update_asset is not None)
        data_dir.mkdir(parents=True, exist_ok=True)
        self._model_dir = model_dir
        self._inference: Inference | None = None
        self.workers = 1
        self.inference_device = "Initialising"
        meta = json.loads((model_dir / "metadata.json").read_text())
        protos = json.loads((model_dir / "prototypes.json").read_text())["prototypes"]
        self.assets = vision.assets_from_dicts(meta, protos)
        self._state_path = data_dir / "state.json"
        self._client = httpx.AsyncClient(follow_redirects=True)
        self.mediamtx = MediaMTX(mediamtx_api, mediamtx_rtsp, self._client, mediamtx_login)
        self._sources: dict[str, AVSource] = {}
        self._closing: dict[str, AVSource] = {}
        self._notices: list[Notice] = []
        self._declares_devices = os.environ.get("PRINTGUARD_CAMERAS") == "auto"
        self.plugin_runtime = None if os.environ.get("PRINTGUARD_PLUGINS") == "off" else WasmPluginRuntime()
        self.files = DiskFileStore(data_dir / "prints")
        if self.plugin_runtime is None:
            logger.warning("plugins are disabled by PRINTGUARD_PLUGINS=off")

    async def configure(self, settings: dict[str, Any]) -> None:
        """Selects the requested inference runtime."""
        runtime = settings["inference_runtime"]
        inference = await asyncio.to_thread(Inference, self._model_dir, runtime)
        previous = self._inference
        self._inference = inference
        self.workers = inference.workers
        self.inference_device = inference.device
        if previous is not None:
            previous.close()
        self._notices += [Notice(message) for message in inference.skipped]
        logger.info(
            "inference ready: %s via %s (%d workers, %.0f fps)",
            self.inference_device,
            inference.runtime if runtime == "auto" else runtime,
            self.workers,
            inference.capacity_fps,
        )

    async def close(self) -> None:
        """Releases the HTTP client, and the inference workers once a runtime is up."""
        await self._client.aclose()
        if self._inference is not None:
            self._inference.close()

    def take_notices(self) -> list[Notice]:
        """Hands over what the hub has had to work around since the last call."""
        notices, self._notices = self._notices, []
        return notices

    async def infer(self, rgb: np.ndarray) -> dict[str, Any]:
        """Runs the model through the selected hardware provider."""
        tensor = await asyncio.to_thread(vision.preprocess, rgb, self.assets)
        return vision.classify(await self._inference.run(tensor), self.assets)

    async def discover_cameras(self) -> list[dict[str, Any]]:
        """Lists the host's video devices and active MediaMTX paths as attachable sources.

        A device is declared when the deployment chose it rather than merely
        having it attached, which ``PRINTGUARD_CAMERAS=auto`` says of this one.
        The image sets it, since a container sees only the cameras its compose
        file passes in and passing one in is already the decision to use it.
        """
        devices = await asyncio.to_thread(_video_devices)
        sources: list[dict[str, Any]] = [
            {"kind": "device", "device_id": device_id, "label": label, "declared": self._declares_devices}
            for device_id, label in devices
        ]
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

        Raises:
            RuntimeError: If no frame arrives in time, or if the reader this
                source was last opened with is still inside a read it cannot
                be called back from. Opening another beside it would add a
                thread and a capture session on every retry.
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
            raise ValueError(f"cannot open source kind {source['kind']!r}")
        reader = source.get("device_id", camera_id)
        closing = self._closing.pop(reader, None)
        if closing is not None and not await asyncio.to_thread(closing.stopped, READER_STOP_WAIT_S):
            self._closing[reader] = closing
            raise RuntimeError(
                "this camera's last capture stopped answering and cannot be closed, so it is not opened again. "
                "Restart PrintGuard to free it"
            )
        av_source = AVSource(
            target,
            publish_url,
            container_format,
            open_options,
            lambda message, recovered: self._notices.append(Notice(message, recovered, camera_id)),
        )
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
        """Closes the source and removes any MediaMTX pull path.

        The path is removed for every URL camera without asking how its address
        would be opened today: a printer can change its webcam to one that can
        no longer be pulled, and the path was added for the address before.
        """
        av_source = self._sources.pop(camera_id, None)
        if av_source:
            av_source.close()
            self._closing[source.get("device_id", camera_id)] = av_source
        if source["kind"] == "url":
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
        binary: bool = False,
        timeout: float = 10.0,
        follow_redirects: bool = True,
        max_bytes: int | None = None,
    ) -> tuple[int, Any]:
        """Performs an HTTP request with httpx, base64 encoding a binary reply.

        A capped request asks for gzip or nothing and is inflated here as it
        arrives, since httpx inflates a whole chunk before anyone can count it.

        Raises:
            RuntimeError: If a redirect made httpx replay the request under
                another method, as it does a POST answered with 301 or 302,
                so the request itself was never delivered, or if the body
                passes ``max_bytes`` or is neither gzip nor plain.
        """
        if max_bytes is not None:
            headers = httpx.Headers(headers)
            headers["Accept-Encoding"] = "gzip"
        async with self._client.stream(
            method, url, headers=headers, json=json, content=data, timeout=timeout, follow_redirects=follow_redirects
        ) as resp:
            hops = [*resp.history, resp]
            for hop, landed in zip(hops, hops[1:]):
                if hop.status_code != 303 and landed.request.method != hop.request.method:
                    source, target = (f"{at.url.scheme}://{at.url.netloc.decode()}" for at in (hop, landed))
                    raise RuntimeError(f"{source} redirects to {target}, which drops the {method}. Use the address it redirects to")
            content = await resp.aread() if max_bytes is None else await _read_within(resp, max_bytes)
        return resp.status_code, _parsed(content, resp.encoding, binary)

    async def open_socket(self, url: str, arrived: Callable[[str, str], None]) -> WebSocket:
        """Connects a WebSocket and reads it on a task of its own.

        Raises:
            websockets.InvalidStatus: If the server answers with anything but
                the upgrade, a redirect included.
        """
        connection = await ConnectWithoutRedirects(url, open_timeout=SOCKET_TIMEOUT_S, max_size=SOCKET_MAX_BYTES)
        socket = WebSocket(connection)
        socket.read(arrived)
        return socket

    async def encode_jpeg(self, rgb: np.ndarray) -> bytes | None:
        """Encodes a frame as JPEG using PyAV's mjpeg encoder."""
        def encode() -> bytes:
            even = rgb[: rgb.shape[0] // 2 * 2, : rgb.shape[1] // 2 * 2]
            frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(even), format="rgb24")
            codec = av.CodecContext.create("mjpeg", "w")
            codec.width, codec.height = frame.width, frame.height
            codec.pix_fmt = "yuvj420p"
            codec.time_base = Fraction(1, 30)
            codec.thread_count = 1
            packets = codec.encode(frame.reformat(format="yuvj420p", threads=1)) + codec.encode(None)
            return b"".join(bytes(p) for p in packets)

        try:
            return await asyncio.to_thread(encode)
        except Exception:
            return None

    async def decode_jpeg(self, data: bytes) -> np.ndarray | None:
        """Decodes supplied image bytes to an RGB frame with PyAV."""
        def decode() -> np.ndarray:
            with av.open(io.BytesIO(data)) as container:
                return next(container.decode(video=0)).reformat(format="rgb24", threads=1).to_ndarray()

        try:
            return await asyncio.to_thread(decode)
        except Exception:
            return None

    def load_state(self) -> dict[str, Any]:
        """Reads persisted engine state from the data directory.

        Returns:
            The saved state, or nothing on a first boot. A file that will not
            parse is moved aside before the hub starts empty, so the next save
            cannot overwrite what is left of it.

        Raises:
            RuntimeError: If the file is there and the hub may not read it,
                saying whose it has to be.
        """
        try:
            return json.loads(self._state_path.read_text())
        except FileNotFoundError:
            return {}
        except PermissionError as exc:
            raise RuntimeError(
                f"{self._state_path} could not be read ({exc}), so the hub cannot start. "
                "The data directory and the files in it have to belong to the user the hub runs as"
            ) from None
        except ValueError as exc:
            kept = self._state_path.with_suffix(".json.corrupt")
            self._state_path.replace(kept)
            logger.error("%s is damaged (%s), so the hub is starting empty. The file is kept as %s", self._state_path, exc, kept)
            return {}

    def save_state(self, state: dict[str, Any]) -> None:
        """Atomically writes engine state to the data directory, owner-readable only.

        It holds printer passwords, notifier keys, API token hashes and whatever
        credentials plugins have been given, so the temporary file is created
        with that mode and held to it before anything is written: anything else
        leaves a window where it is readable by everybody on the host. One left
        behind by a hub that was killed mid-write keeps the mode it had, which
        is why creating it that way is not enough. It is synced to disk before
        the rename too, or a power cut can leave the new name pointing at a
        file with nothing in it.
        """
        tmp = self._state_path.with_suffix(".tmp")
        with open(tmp, "w", opener=partial(os.open, mode=0o600)) as handle:
            tmp.chmod(0o600)
            handle.write(json.dumps(state, indent=2))
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(self._state_path)
