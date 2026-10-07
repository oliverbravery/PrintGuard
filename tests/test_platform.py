"""Server platform tests, from model execution to camera discovery."""

from __future__ import annotations

import asyncio
import errno
import fcntl
import gc
import io
import json
import logging
import socket
import struct
import subprocess
import sys
import threading
import time
import weakref
from contextlib import ExitStack
from fractions import Fraction
from pathlib import Path
from types import ModuleType, SimpleNamespace

import av
import httpx
import numpy as np
import onnxruntime as ort
import pytest
import websockets
from fakes import redirected_socket
from test_state_file import needs_an_unprivileged_user

from printguard.engine import reports, vision
from printguard.server.inference import (
    Inference,
    OnnxInference,
    _device_label,
    _execution_devices,
    _measure_concurrency,
    _register_library,
)
from printguard.server.public_network import PublicOnlyTransport, connect_to_public
from printguard.server.platform import (
    V4L2_CAP_DEVICE_CAPS,
    V4L2_CAP_VIDEO_CAPTURE,
    V4L2_OPEN_OPTIONS,
    AVSource,
    DiskFileStore,
    ServerPlatform,
    _v4l2_card,
    _video_devices,
)

V4L2_CAP_META_CAPTURE = 0x00800000
V4L2_CAPABILITY_FILLED = "16s32s32sIII12x"


@pytest.mark.parametrize("runtime", ["auto", "litert", "onnx"])
async def test_model_inference(tmp_path: Path, runtime: str) -> None:
    """Every selectable production model runtime loads and classifies."""
    platform = ServerPlatform(Path("models"), tmp_path, "http://localhost:9997", "rtsp://localhost:8554")
    await platform.configure({"inference_runtime": runtime})
    image = np.arange(240 * 320 * 3, dtype=np.uint8).reshape(240, 320, 3)

    results = await asyncio.gather(platform.infer(image), platform.infer(image))
    await platform.close()

    assert all(result["prediction"] == "success" for result in results)
    assert platform.inference_device
    assert platform.workers > 0


async def test_a_frame_in_flight_finishes_on_the_runtime_it_started_on_when_the_runtime_is_switched(tmp_path: Path) -> None:
    """A classify call is outside the scheduler's drain, and closing the ONNX session under it ended in an AttributeError."""
    platform = ServerPlatform(Path("models"), tmp_path, "http://localhost:9997", "rtsp://localhost:8554")
    await platform.configure({"inference_runtime": "onnx"})
    selected = platform._inference._selected
    run = selected.run
    entered, release = threading.Event(), threading.Event()

    def held(tensor: np.ndarray) -> np.ndarray:
        entered.set()
        release.wait(10)
        return run(tensor)

    selected.run = held
    image = np.arange(240 * 320 * 3, dtype=np.uint8).reshape(240, 320, 3)
    classifying = asyncio.ensure_future(platform.infer(image))
    await asyncio.to_thread(entered.wait, 10)
    switching = asyncio.ensure_future(platform.configure({"inference_runtime": "litert"}))
    await asyncio.sleep(0.5)
    assert not switching.done(), "the runtime was closed with a frame still on it"
    release.set()
    result = await classifying
    await switching
    await platform.close()

    assert result["prediction"] == "success" and platform.inference_device == "LiteRT CPU"


async def test_a_login_in_the_video_servers_addresses_is_one_the_engine_scrubs(tmp_path: Path) -> None:
    platform = ServerPlatform(
        Path("models"),
        tmp_path,
        "http://pg:API-PASS-31@mediamtx:9997",
        "rtsp://hub:RTSP-PASS-77@mediamtx:8554",
        mediamtx_hls="http://viewer:HLS-PASS-52@mediamtx:8888",
    )
    await platform.close()

    assert {"pg", "API-PASS-31", "hub", "RTSP-PASS-77", "viewer", "HLS-PASS-52"} <= platform.secrets


async def test_the_login_the_bundled_server_is_given_is_one_the_engine_scrubs(tmp_path: Path) -> None:
    """Frames are read from an RTSP address that carries it, and an error from the reader can quote that."""
    platform = ServerPlatform(Path("models"), tmp_path, "http://mediamtx:9997", "rtsp://mediamtx:8554", None, ("printguard", "per-launch-pass"))
    await platform.close()

    assert "per-launch-pass" in platform.secrets
    assert platform.mediamtx.rtsp_url("cam") == "rtsp://printguard:per-launch-pass@mediamtx:8554/cam"


async def test_the_bundled_servers_user_name_is_not_scrubbed_from_a_log_line_naming_a_printguard_logger(tmp_path: Path) -> None:
    platform = ServerPlatform(Path("models"), tmp_path, "http://mediamtx:9997", "rtsp://mediamtx:8554", None, ("printguard", "per-launch-pass"))
    await platform.close()
    line = "INFO printguard.server.platform: rtsp://printguard:per-launch-pass@mediamtx:8554/cam"

    scrubbed = reports.scrub(line, set(platform.secrets), standalone_below=reports.MESSAGE_STANDALONE_BELOW)

    assert scrubbed == f"INFO printguard.server.platform: rtsp://printguard:{reports.REDACTED}@mediamtx:8554/cam"


async def test_runtimes_agree_on_classification() -> None:
    """Both runtimes carry the same model, so they must classify a frame the same way.

    Execution providers pick kernels for the hardware they land on, so the embeddings
    are held to the only agreement the detector depends on rather than to an
    elementwise tolerance. Every prototype distance moves by at most the distance
    between the two embeddings, so drift under half the margin cannot reach the
    nearest prototype of the other.
    """
    model_dir = Path("models")
    assets = vision.assets_from_dicts(
        json.loads((model_dir / "metadata.json").read_text()),
        json.loads((model_dir / "prototypes.json").read_text())["prototypes"],
    )
    tensor = np.random.default_rng(0).random((1, 3, 224, 224), dtype=np.float32)
    embeddings = []
    for runtime in ("litert", "onnx"):
        inference = Inference(model_dir, runtime)
        embeddings.append(await inference.run(tensor))
        inference.close()

    classifications = [vision.classify(embedding, assets) for embedding in embeddings]
    drift = float(np.linalg.norm(embeddings[0] - embeddings[1]))

    assert embeddings[0].shape == embeddings[1].shape == (1024,)
    assert classifications[0]["prediction"] == classifications[1]["prediction"]
    assert drift < min(result["margin"] for result in classifications) / 2


def _ep_device(
    ep_name: str, vendor: str, device_type: str, ep_metadata: dict[str, str], vendor_id: int = 0, device_id: int = 0
) -> SimpleNamespace:
    """Builds a stand-in for one device an ONNX Runtime provider offers."""
    return SimpleNamespace(
        ep_name=ep_name,
        ep_vendor=vendor,
        ep_metadata=ep_metadata,
        device=SimpleNamespace(
            type=SimpleNamespace(name=device_type), metadata={}, vendor_id=vendor_id, device_id=device_id
        ),
    )


def test_the_accelerator_a_provider_offers_wins_and_is_the_one_named() -> None:
    """An Intel image with a working GPU must run on it, and say so.

    OpenVINO offers a CPU path under the same provider name as its GPU, so a GPU
    that the host's driver never handed over is indistinguishable from one in use
    unless the hardware behind the provider is what gets ranked and named. Its meta
    devices pick again at inference time, so neither can stand in for the GPU.
    """
    devices = [
        _ep_device("CPUExecutionProvider", "Microsoft", "CPU", {}),
        _ep_device("OpenVINOExecutionProvider", "Intel", "CPU", {"ov_device": "CPU"}),
        _ep_device("OpenVINOExecutionProvider.AUTO", "Intel", "GPU", {"ov_device": "GPU", "ov_meta_device": "AUTO"}),
        _ep_device("OpenVINOExecutionProvider", "Intel", "GPU", {"ov_device": "GPU"}),
    ]

    assert [_device_label(device) for device in _execution_devices(devices)] == ["Intel GPU", "Intel CPU"]


def test_windows_software_adapter_is_never_handed_to_directml() -> None:
    """A Windows PC without a GPU driver must start on the CPU.

    Windows offers its Basic Render Driver as a GPU when no driver is installed, and
    DirectML ends the process when a session is created on it.
    """
    devices = [
        _ep_device("CPUExecutionProvider", "Microsoft", "CPU", {}),
        _ep_device("DmlExecutionProvider", "Microsoft", "GPU", {}, vendor_id=0x1414, device_id=0x8C),
    ]

    assert _execution_devices(devices) == []


def test_windows_device_listing_ends_without_failing_the_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hub on Windows must start whether or not a camera is plugged in.

    DirectShow can end a device listing with FFmpeg's immediate exit, which PyAV
    raises as an error of its own rather than an ``OSError``.
    """

    def list_devices(_format: str) -> list[object]:
        raise av.error.ExitError(1414092869, "Immediate exit requested")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(av.device, "enumerate_input_devices", list_devices)

    assert _video_devices() == []


def test_windows_lists_its_cameras_by_device_path_and_leaves_out_microphones(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """DirectShow reports cameras and microphones together, each under a name and a device path.

    What it reported is logged at debug, so one run on a PC shows whether the
    listing matches what this expects of it.
    """
    devices = [
        SimpleNamespace(name="@device_pnp_usb#vid_046d", description="HD Pro Webcam C920", media_types=["video"]),
        SimpleNamespace(name="@device_cm_wave", description="Microphone (HD Pro Webcam C920)", media_types=["audio"]),
    ]
    asked: list[str] = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(av.device, "enumerate_input_devices", lambda name: asked.append(name) or devices)

    with caplog.at_level(logging.DEBUG, logger="printguard.server.platform"):
        assert _video_devices() == [("@device_pnp_usb#vid_046d", "HD Pro Webcam C920")]
    assert asked == ["dshow"]
    assert "@device_cm_wave" in caplog.text and "HD Pro Webcam C920" in caplog.text


def test_two_windows_cameras_of_one_model_are_two_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    """Listed by the name they share, the second vanished and would have opened the first anyway."""
    devices = [
        SimpleNamespace(name="@device_pnp_usb#vid_046d&mi_00#6", description="HD Pro Webcam C920", media_types=["video"]),
        SimpleNamespace(name="@device_pnp_usb#vid_046d&mi_00#7", description="HD Pro Webcam C920", media_types=["video"]),
    ]
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(av.device, "enumerate_input_devices", lambda name: devices)

    assert _video_devices() == [
        ("@device_pnp_usb#vid_046d&mi_00#6", "HD Pro Webcam C920 (1)"),
        ("@device_pnp_usb#vid_046d&mi_00#7", "HD Pro Webcam C920 (2)"),
    ]


def test_macos_opens_a_camera_by_the_name_it_shows(monkeypatch: pytest.MonkeyPatch) -> None:
    """AVFoundation's other name is a position in the list, which moves when a camera is plugged in."""
    devices = [
        SimpleNamespace(name="0", description="FaceTime HD Camera", media_types=["video"]),
        SimpleNamespace(name="1", description="Capture screen 0", media_types=["video"]),
    ]
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(av.device, "enumerate_input_devices", lambda name: devices)

    assert _video_devices() == [("FaceTime HD Camera", "FaceTime HD Camera")]


def test_the_macos_camera_bridge_is_installed_with_the_hub_and_not_only_the_desktop_extra() -> None:
    """`uv sync && uv run printguard` on a Mac failed to add a USB camera with no module named objc."""
    from importlib import metadata

    from packaging.requirements import Requirement

    bridge = next(Requirement(line) for line in metadata.requires("printguard") if line.startswith("pyobjc-framework-cocoa"))

    assert bridge.marker is not None and "extra" not in str(bridge.marker)
    assert bridge.marker.evaluate({"sys_platform": "darwin"}) and not bridge.marker.evaluate({"sys_platform": "linux"})


def test_provider_library_that_cannot_load_leaves_the_cpu(tmp_path: Path) -> None:
    """A GPU image whose provider libraries the host cannot supply must still start.

    The accelerated images carry a provider that needs libraries only the host can hand
    over, so any host without them, or any container started without GPU access, would
    otherwise take PrintGuard down at startup rather than watching printers on the CPU.
    """
    assert _register_library("printguard_test_provider", str(tmp_path / "libmissing.so")) is False


@pytest.mark.parametrize(("runtime", "fault"), [("auto", "build"), ("onnx", "build"), ("onnx", "run")])
async def test_an_accelerator_that_cannot_run_the_model_loses_to_the_cpu(
    monkeypatch: pytest.MonkeyPatch, runtime: str, fault: str
) -> None:
    """A GPU that is offered but cannot compile or run the model must not stop the hub starting.

    What was passed over is kept for the dashboard, whichever runtime wins.

    The setting that picked the runtime is only reachable from a running hub, so a
    start that fails here leaves editing the state file as the way back.
    """
    real_session = ort.InferenceSession

    def refuse(*_: object) -> None:
        raise RuntimeError("the GPU ran out of memory")

    def session(path: str, sess_options: object = None, providers: object = None, **kwargs: object) -> object:
        if providers is not None:
            return real_session(path, sess_options=sess_options, providers=providers, **kwargs)
        if fault == "build":
            raise RuntimeError("the GPU could not compile the model")
        return SimpleNamespace(get_inputs=lambda: [SimpleNamespace(name="input")], run=refuse)

    monkeypatch.setattr(ort, "get_ep_devices", lambda: [_ep_device("OpenVINOExecutionProvider", "Intel", "GPU", {})])
    monkeypatch.setattr(ort.SessionOptions, "add_provider_for_devices", lambda *_: None)
    monkeypatch.setattr(ort, "InferenceSession", session)

    inference = Inference(Path("models"), runtime)
    embedding = await inference.run(np.zeros((1, 3, 224, 224), dtype=np.float32))
    inference.close()

    reason = "could not compile the model" if fault == "build" else "ran out of memory"
    assert inference.device in ("ONNX CPU", "LiteRT CPU" if runtime == "auto" else "ONNX CPU")
    assert embedding.shape == (1024,)
    assert inference.skipped == [f"Intel GPU cannot run the model, so detection is not using it: the GPU {reason}"]


def test_a_windows_provider_that_cannot_be_installed_is_left_out(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Windows ML downloads its providers on first launch, and a failed download must not stop the app."""

    def unreachable() -> None:
        raise OSError("the Store could not be reached")

    provider = SimpleNamespace(
        name="OpenVINOExecutionProvider",
        ready_state="absent",
        ensure_ready_async=lambda: SimpleNamespace(get=unreachable),
    )
    catalogue = SimpleNamespace(find_all_providers=lambda: [provider])
    modules = {
        "winui3.microsoft.windows.applicationmodel.dynamicdependency.bootstrap": {"initialize": ExitStack},
        "winui3.microsoft.windows.ai.machinelearning": {
            "ExecutionProviderCatalog": SimpleNamespace(get_default=lambda: catalogue),
            "ExecutionProviderReadyState": SimpleNamespace(READY="ready"),
        },
    }
    for name, members in modules.items():
        parts = name.split(".")
        for depth in range(1, len(parts) + 1):
            package = sys.modules.get(".".join(parts[:depth])) or ModuleType(".".join(parts[:depth]))
            monkeypatch.setitem(sys.modules, package.__name__, package)
            if depth > 1:
                monkeypatch.setattr(sys.modules[".".join(parts[: depth - 1])], parts[depth - 1], package, raising=False)
        for member, value in members.items():
            monkeypatch.setattr(sys.modules[name], member, value, raising=False)
    monkeypatch.setattr(sys, "getwindowsversion", lambda: SimpleNamespace(build=26100), raising=False)

    with caplog.at_level(logging.WARNING, logger="printguard.server.inference"):
        OnnxInference._register_windows_providers(SimpleNamespace(_resources=ExitStack()))

    assert [record.getMessage() for record in caplog.records] == [
        "execution provider OpenVINOExecutionProvider could not be installed: the Store could not be reached"
    ]


def test_measured_concurrency_tracks_scaling() -> None:
    """Workers follow throughput a runtime actually adds, not the host's core count.

    A runtime whose binding holds the GIL gains nothing from a second worker and
    must be given one, however many cores the host has.
    """
    serialising = threading.Lock()

    def scales(tensor: np.ndarray) -> np.ndarray:
        time.sleep(0.002)
        return tensor

    def serialises(tensor: np.ndarray) -> np.ndarray:
        with serialising:
            time.sleep(0.002)
        return tensor

    assert _measure_concurrency(scales)[0] > 1
    assert _measure_concurrency(serialises)[0] == 1


def test_a_provider_that_returns_non_finite_output_fails_the_benchmark() -> None:
    def broken(tensor: np.ndarray) -> np.ndarray:
        return np.full(8, np.nan, dtype=np.float32)

    with pytest.raises(ValueError, match="non-finite"):
        _measure_concurrency(broken)


@pytest.mark.parametrize(
    ("answer", "reached", "outcome"),
    [
        ("301 Moved Permanently", ["GET"], "drops the POST"),
        ("302 Found", ["GET"], "drops the POST"),
        ("307 Temporary Redirect", ["POST"], 204),
        ("308 Permanent Redirect", ["POST"], 204),
    ],
)
async def test_a_redirect_never_turns_a_command_into_a_read(answer: str, reached: list[str], outcome: str | int) -> None:
    """httpx replays a POST answered with 301 or 302 as a GET, which OctoPrint answers 200 while the print carries on."""
    arrived: list[str] = []

    async def printer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        arrived.append((await reader.readuntil(b"\r\n\r\n")).split()[0].decode())
        writer.write(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
        await writer.drain()
        writer.close()

    async def proxy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(f"HTTP/1.1 {answer}\r\nLocation: {moved}/api/job\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())
        await writer.drain()
        writer.close()

    async with await asyncio.start_server(printer, "127.0.0.1", 0) as behind, await asyncio.start_server(proxy, "127.0.0.1", 0) as front:
        moved = f"http://127.0.0.1:{behind.sockets[0].getsockname()[1]}"
        registered = f"http://127.0.0.1:{front.sockets[0].getsockname()[1]}"
        async with httpx.AsyncClient(follow_redirects=True) as client:
            holder = SimpleNamespace(_client=client)
            if isinstance(outcome, int):
                assert (await ServerPlatform.http(holder, "POST", f"{registered}/api/job", json={"command": "pause"}))[0] == outcome
            else:
                with pytest.raises(RuntimeError, match=f"{registered} redirects to {moved}, which {outcome}"):
                    await ServerPlatform.http(holder, "POST", f"{registered}/api/job", json={"command": "pause"})
            assert (await ServerPlatform.http(holder, "GET", f"{registered}/api/job"))[0] == 204
            assert (await ServerPlatform.http(holder, "POST", f"{registered}/api/job", redirects="answer"))[0] == int(answer[:3])
    assert arrived == [*reached, "GET"]


@pytest.mark.parametrize("answer", ["301 Moved Permanently", "302 Found", "307 Temporary Redirect", "308 Permanent Redirect"])
@pytest.mark.parametrize("method", ["GET", "POST", "PUT"])
async def test_a_redirect_an_adapter_meets_is_refused_and_takes_its_key_nowhere(answer: str, method: str) -> None:
    """A command to a service that redirects fails when it is registered, and an API key never follows it to another host."""
    arrived: list[bytes] = []

    async def elsewhere(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        arrived.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
        await writer.drain()
        writer.close()

    async def proxy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(f"HTTP/1.1 {answer}\r\nLocation: {moved}/api/job\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())
        await writer.drain()
        writer.close()

    async with await asyncio.start_server(elsewhere, "127.0.0.1", 0) as behind, await asyncio.start_server(proxy, "127.0.0.1", 0) as front:
        moved = f"http://127.0.0.1:{behind.sockets[0].getsockname()[1]}"
        registered = f"http://127.0.0.1:{front.sockets[0].getsockname()[1]}"
        async with httpx.AsyncClient(follow_redirects=True) as client:
            with pytest.raises(RuntimeError, match=f"^{registered} redirects to {moved}. Register the address the service answers on$"):
                await ServerPlatform.http(SimpleNamespace(_client=client), method, f"{registered}/api/job", headers={"X-Api-Key": "secret"}, redirects="refuse")
    assert arrived == []


def test_a_camera_that_will_not_open_keeps_its_password_out_of_the_error() -> None:
    """PyAV quotes the address it failed on, and that text becomes an error event."""
    source = AVSource("http://admin:CAMPASS@127.0.0.1:9/video?user=admin&pwd=QUERYPASS", None)
    try:
        deadline = time.monotonic() + 15
        while source.last_error is None and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        source.close()

    assert source.last_error and "127.0.0.1:9/video" in source.last_error
    assert "CAMPASS" not in source.last_error and "QUERYPASS" not in source.last_error


class _MjpegPipe:
    """A healthy MJPEG camera read as a byte stream, as a Bambu A1's is."""

    opened = 0
    frame_every_s = 0.03

    def __init__(self) -> None:
        type(self).opened += 1
        codec = av.CodecContext.create("mjpeg", "w")
        codec.width, codec.height, codec.pix_fmt, codec.time_base = 320, 240, "yuvj420p", Fraction(1, 30)
        picture = av.VideoFrame.from_ndarray(np.zeros((240, 320, 3), dtype=np.uint8), format="rgb24")
        encoded = codec.encode(picture.reformat(format="yuvj420p", threads=1)) + codec.encode(None)
        self._jpeg = b"".join(bytes(packet) for packet in encoded)
        self._unread = b""
        self._closed = False

    def read(self, size: int = -1) -> bytes:
        if self._closed:
            return b""
        if not self._unread:
            time.sleep(self.frame_every_s)
            self._unread = self._jpeg
        out, self._unread = self._unread[:size], self._unread[size:]
        return out

    def close(self) -> None:
        self._closed = True


async def test_a_live_view_that_cannot_publish_leaves_detection_running(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """MediaMTX being down, or another program holding its port, costs the live view and nothing else."""
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        refusing = f"rtsp://127.0.0.1:{unused.getsockname()[1]}/cam1"
    publishes: list[str] = []
    real_open = av.open

    def spy(file: object, *args: object, **kwargs: object) -> object:
        if file == refusing:
            publishes.append(file)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(av, "open", spy)
    monkeypatch.setattr("printguard.server.platform.RECONNECT_DELAY_S", 0.3)
    monkeypatch.setattr(_MjpegPipe, "opened", 0)
    reported: list[tuple[str, bool]] = []

    source = AVSource(_MjpegPipe, refusing, report=lambda message, recovered: reported.append((message, recovered)))
    try:
        deadline = time.monotonic() + 15
        while len(publishes) < 3 and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        online = source.online
        frame = await source.grab()
    finally:
        source.close()

    assert len(publishes) >= 3, "the publish was not tried again"
    assert _MjpegPipe.opened == 1, "retrying the publish restarted capture"
    assert online and frame is not None and frame.seq > 10
    assert source.last_error and source.last_error.startswith("live view unavailable: ")
    assert reported == [(f"{source.last_error}. Detection carries on without it", False)], "the dashboard is told once"


async def test_a_camera_on_standby_hands_over_no_frame_from_before_it_stood_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("printguard.server.platform.DEMAND_IDLE_S", 0.1)
    source = AVSource(_MjpegPipe)
    try:
        deadline = time.monotonic() + 15
        while not source.online and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        watching = await source.grab()
        source.set_monitoring(False)
        while source.online and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        stood_down = await source.grab()
    finally:
        source.close()

    assert watching is not None and source.standby
    assert stood_down is None, "a frame from before the camera stood down was handed over as its current one"


async def test_a_slow_byte_stream_camera_has_its_rate_measured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Bambu A1 sends about a frame a second, and the raw MJPEG demuxer calls every stream 25."""
    monkeypatch.setattr("printguard.server.platform.MEASURE_WARMUP_S", 0.2)
    monkeypatch.setattr("printguard.server.platform.FPS_SAMPLE_S", 1.0)
    monkeypatch.setattr(_MjpegPipe, "frame_every_s", 0.2)

    source = AVSource(_MjpegPipe)
    try:
        deadline = time.monotonic() + 15
        while not source.online and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        unmeasured = source.fps
        while not source.fps and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
    finally:
        source.close()

    assert unmeasured == 0, "the demuxer's default was taken for the camera's rate"
    assert 3 <= source.fps <= 6


async def test_a_reader_that_cannot_be_stopped_is_not_joined_by_another(monkeypatch: pytest.MonkeyPatch) -> None:
    """A device that opens and never delivers a frame holds its thread inside a read nothing can interrupt.

    Every re-attach used to start another beside it, each with a capture
    session of its own.
    """
    release = threading.Event()
    opened: list[int] = []

    def stuck_stream(host: str, access_code: str) -> object:
        opened.append(1)
        release.wait()
        raise OSError("gone")

    monkeypatch.setattr("printguard.server.platform.open_bambu_jpeg_stream", stuck_stream)
    monkeypatch.setattr("printguard.server.platform.OPEN_WAIT_S", 0.2)
    monkeypatch.setattr("printguard.server.platform.READER_STOP_WAIT_S", 0.2)
    platform = object.__new__(ServerPlatform)
    platform.mediamtx = SimpleNamespace(rtsp_url=lambda path: f"rtsp://127.0.0.1:9/{path}")
    platform._sources, platform._closing, platform._notices = {}, {}, []
    camera = {"kind": "bambu", "host": "printer", "access_code": "code"}

    try:
        with pytest.raises(RuntimeError, match="no frames from camera cam1"):
            await platform.open_camera("cam1", camera)
        for _ in range(2):
            with pytest.raises(RuntimeError, match="stopped answering and cannot be closed"):
                await platform.open_camera("cam1", camera)
        assert opened == [1]
    finally:
        stuck = platform._closing["cam1"]
    release.set()
    assert stuck.stopped(5.0)
    release.clear()
    with pytest.raises(RuntimeError, match="no frames from camera cam1"):
        await platform.open_camera("cam1", camera)
    release.set()
    assert opened == [1, 1], "a reader that ended still kept its camera from opening"


async def test_a_camera_whose_address_can_no_longer_be_pulled_is_still_released() -> None:
    """A printer can change its webcam to a WebRTC page with no WHEP, and removing that printer must not stop half way."""
    removed: list[str] = []

    async def remove_path(name: str) -> None:
        removed.append(name)

    platform = object.__new__(ServerPlatform)
    platform.mediamtx = SimpleNamespace(remove_path=remove_path)
    platform._sources, platform._closing = {}, {}

    await platform.release_camera("cam1", {"kind": "url", "url": "http://pi/webcam/webrtc"})

    assert removed == ["cam1"]


async def test_an_upload_is_written_off_the_event_loop(tmp_path: Path) -> None:
    """A sliced file can be hundreds of megabytes onto an SD card, and the loop also carries detection."""
    loop_thread = threading.get_ident()
    written_on: list[int] = []

    class Recording(type(tmp_path)):
        def open(self, *args: object, **kwargs: object) -> object:
            handle = super().open(*args, **kwargs)
            real_write = handle.write
            handle.write = lambda chunk: written_on.append(threading.get_ident()) or real_write(chunk)
            return handle

    async def chunks() -> object:
        yield b"G28\n"
        yield b"G1 X10\n"

    store = DiskFileStore(tmp_path)
    plain_path = store.path
    store.path = lambda key: Recording(plain_path(key))

    assert await store.store("benchy.gcode", chunks()) == 11
    assert (tmp_path / "benchy.gcode").read_bytes() == b"G28\nG1 X10\n"
    assert written_on and loop_thread not in written_on


def test_a_camera_without_mjpeg_is_opened_with_the_next_capture_options(monkeypatch: pytest.MonkeyPatch) -> None:
    """FFmpeg refuses a format a YUYV-only webcam lacks with EINVAL, which PyAV does not raise as an ``OSError``."""
    tried: list[dict[str, str]] = []

    def open_device(file: str, format: str, options: dict[str, str], timeout: float) -> str:
        tried.append(options)
        if options.get("input_format") == "mjpeg":
            raise av.error.ArgumentError(errno.EINVAL, "Invalid argument", file)
        return "opened"

    monkeypatch.setattr(av, "open", open_device)
    camera = SimpleNamespace(_source="/dev/video0", _container_format="v4l2", _open_options=V4L2_OPEN_OPTIONS)

    assert AVSource._open(camera) == ("opened", None)
    assert tried == list(V4L2_OPEN_OPTIONS[:3])


async def test_a_plugin_socket_refuses_a_redirect_instead_of_following_it() -> None:
    """Only the address a plugin declared was checked against its grant."""
    async with redirected_socket() as (declared, reached):
        with pytest.raises(websockets.InvalidStatus, match="HTTP 302"):
            await ServerPlatform.open_socket(None, f"{declared}/feed", lambda state, text: None)

    assert reached == [], "the handshake went on to an address nobody checked"


def answering_with(monkeypatch: pytest.MonkeyPatch, **names: list[str]) -> list[str]:
    """Makes the resolver answer the names given, and records every name it was asked."""
    asked: list[str] = []
    real = socket.getaddrinfo

    def getaddrinfo(host: str | bytes, port: int, *args: object, **kwargs: object):
        host = host.decode() if isinstance(host, bytes) else host
        asked.append(host)
        if host in names:
            return [(socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port)) for address in names[host]]
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return asked


async def local_server() -> tuple[asyncio.Server, list[bytes]]:
    """A loopback HTTP server that answers every request and keeps what it was sent."""
    received: list[bytes] = []

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        received.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nhi")
        await writer.drain()
        writer.close()

    return await asyncio.start_server(serve, "127.0.0.1", 0), received


@pytest.mark.parametrize("answers", [["127.0.0.1"], ["93.184.216.34", "127.0.0.1"], ["127.0.0.1", "93.184.216.34"], ["10.0.0.5"], ["::1"], ["64:ff9b::c0a8:101"]])
async def test_a_name_that_resolves_anywhere_on_this_network_is_refused_at_the_connection(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> None:
    """A resolver the attacker runs answers a public address to the first lookup and loopback to the second."""
    server, received = await local_server()
    answering_with(monkeypatch, **{"rebind.example": answers})
    port = server.sockets[0].getsockname()[1]
    hub = SimpleNamespace(_public_client=httpx.AsyncClient(transport=PublicOnlyTransport()))
    async with server:
        with pytest.raises(PermissionError, match="on this network"):
            await ServerPlatform.http(hub, "GET", f"http://rebind.example:{port}/admin", public_only=True)

    assert received == [], "a request reached this machine through a name that resolves to it"


async def test_a_literal_address_on_this_network_is_refused_at_the_connection() -> None:
    server, received = await local_server()
    port = server.sockets[0].getsockname()[1]
    hub = SimpleNamespace(_public_client=httpx.AsyncClient(transport=PublicOnlyTransport()))
    async with server:
        with pytest.raises(PermissionError):
            await ServerPlatform.http(hub, "GET", f"http://127.0.0.1:{port}/", public_only=True)

    assert received == []


async def test_a_name_is_resolved_once_and_the_connection_goes_to_what_was_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    """A second lookup is what a rebinding resolver answers differently, so there is none."""
    lookups: list[str] = []

    def getaddrinfo(host: str, *args: object, **kwargs: object):
        lookups.append(host)
        address = "93.184.216.34" if len(lookups) == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    connected: list[str] = []

    async def connect(address: str) -> str:
        connected.append(address)
        return address

    assert await connect_to_public("rebind.example", 443, connect) == "93.184.216.34"
    assert connected == ["93.184.216.34"] and lookups == ["rebind.example"]


async def test_a_name_that_will_not_connect_on_its_first_address_is_tried_on_the_next(monkeypatch: pytest.MonkeyPatch) -> None:
    answering_with(monkeypatch, **{"dual.example": ["93.184.216.34", "93.184.216.35"]})

    async def connect(address: str) -> str:
        if address.endswith(".34"):
            raise ConnectionRefusedError
        return address

    assert await connect_to_public("dual.example", 80, connect) == "93.184.216.35"


async def test_a_request_without_the_public_only_limit_connects_to_the_resolved_address_and_names_the_host(monkeypatch: pytest.MonkeyPatch) -> None:
    server, received = await local_server()
    answering_with(monkeypatch, **{"printer.example": ["127.0.0.1"]})
    port = server.sockets[0].getsockname()[1]
    async with server, httpx.AsyncClient() as client:
        status, body = await ServerPlatform.http(SimpleNamespace(_client=client), "GET", f"http://printer.example:{port}/api")

    assert (status, body) == (200, "hi")
    assert f"Host: printer.example:{port}".encode() in received[0]


async def test_a_plugin_socket_to_a_name_on_this_network_is_refused_at_the_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    reached: list[str] = []

    async def hold(connection: websockets.ServerConnection) -> None:
        reached.append(connection.request.headers["Host"])

    answering_with(monkeypatch, **{"rebind.example": ["93.184.216.34", "127.0.0.1"], "printer.example": ["127.0.0.1"]})
    async with websockets.serve(hold, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        with pytest.raises(PermissionError, match="on this network"):
            await ServerPlatform.open_socket(None, f"ws://rebind.example:{port}/feed", lambda state, text: None, public_only=True)
        assert reached == []

        opened = await ServerPlatform.open_socket(None, f"ws://printer.example:{port}/feed", lambda state, text: None)
        await opened.close()
        assert reached == [f"printer.example:{port}"]


def _capability(card: bytes, device_caps: int) -> bytes:
    """A struct v4l2_capability as the kernel fills it for one node of a USB camera.

    Args:
        card: Name the driver reports for the camera.
        device_caps: What this node itself can do, as against the whole device.

    Returns:
        The packed reply to a QUERYCAP on that node.
    """
    whole_device = V4L2_CAP_VIDEO_CAPTURE | V4L2_CAP_META_CAPTURE | V4L2_CAP_DEVICE_CAPS
    return struct.pack(V4L2_CAPABILITY_FILLED, b"uvcvideo", card, b"usb-0000:01:00.0-1.2", 0, whole_device, device_caps)


def _answering(monkeypatch, reply: bytes) -> None:
    """Answers every QUERYCAP with one filled capability struct."""

    def ioctl(descriptor: int, request: int, buffer: bytearray) -> int:
        buffer[:] = reply
        return 0

    monkeypatch.setattr(fcntl, "ioctl", ioctl)


def test_a_capture_node_is_offered_under_its_card_name(tmp_path: Path, monkeypatch) -> None:
    """The name a camera is registered with is the one its driver reports."""
    node = tmp_path / "video0"
    node.touch()
    _answering(monkeypatch, _capability(b"HD Pro Webcam C920", V4L2_CAP_VIDEO_CAPTURE))

    assert _v4l2_card(node) == "HD Pro Webcam C920"


def test_the_metadata_node_beside_a_camera_is_not_offered(tmp_path: Path, monkeypatch) -> None:
    """A USB camera registers two nodes and only one of them has any picture.

    Both advertise capture in the device-wide capabilities, so anything reading
    that field offers a second camera that opens and never delivers a frame.
    """
    node = tmp_path / "video1"
    node.touch()
    _answering(monkeypatch, _capability(b"HD Pro Webcam C920", V4L2_CAP_META_CAPTURE))

    assert _v4l2_card(node) is None


def test_a_sliver_of_a_frame_is_not_scaled_up_whole_before_it_is_cropped(monkeypatch) -> None:
    """A 4000x2 image posted for classifying was resized to 512000x256 first."""
    from PIL import Image

    resized: list[tuple[int, int]] = []
    resize = Image.Image.resize

    def measured(image, size, *args, **kwargs):
        resized.append(size)
        return resize(image, size, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "resize", measured)
    assets = vision.Assets(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225), prototypes={})

    assert vision.preprocess(np.zeros((2, 4000, 3), dtype=np.uint8), assets).shape == (1, 3, 224, 224)
    assert vision.preprocess(np.zeros((720, 1280, 3), dtype=np.uint8), assets).shape == (1, 3, 224, 224)
    assert resized == [(1024, 256), (455, 256)]


SVG_STREAM = b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="blue"/></svg>'


def _run_in_child(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)


def test_an_image_ffmpeg_can_demux_but_not_decode_does_not_end_the_hub() -> None:
    """A 110-byte SVG has a demuxer and no decoder, and decoding it ended the process with SIGBUS."""
    child = _run_in_child(
        "import asyncio\n"
        "from types import SimpleNamespace\n"
        "from printguard.server.platform import ServerPlatform\n"
        f"print(asyncio.run(ServerPlatform.decode_jpeg(SimpleNamespace(), {SVG_STREAM!r})))\n"
    )

    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == "None"


def test_a_camera_whose_stream_has_no_decoder_goes_offline_with_the_reason(tmp_path: Path) -> None:
    """A saved camera whose address starts serving an SVG ended the hub at every start."""
    stream = tmp_path / "webcam.svg"
    stream.write_bytes(SVG_STREAM)
    child = _run_in_child(
        "import time\n"
        "from printguard.server.platform import AVSource\n"
        f"source = AVSource({str(stream)!r})\n"
        "deadline = time.monotonic() + 15\n"
        "while source.last_error is None and time.monotonic() < deadline:\n"
        "    time.sleep(0.05)\n"
        "source.close()\n"
        "print(source.online, source.last_error)\n"
    )

    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == "False no decoder for this stream"


SDP_STREAM = b"v=0\no=- 0 0 IN IP4 127.0.0.1\ns=x\nc=IN IP4 127.0.0.1\nt=0 0\nm=video 41000 RTP/AVP 96\na=rtpmap:96 H264/90000"


async def test_a_stream_description_posted_as_an_image_is_refused_without_listening_for_its_stream() -> None:
    """FFmpeg read an SDP body as a stream to receive, bound its UDP port and held a worker thread about 20 seconds."""
    started = time.monotonic()

    assert await ServerPlatform.decode_jpeg(SimpleNamespace(), SDP_STREAM) is None
    assert time.monotonic() - started < 2


@pytest.mark.parametrize("image_format", ["JPEG", "PNG"])
async def test_a_jpeg_and_a_png_are_decoded(image_format: str) -> None:
    from PIL import Image

    encoded = io.BytesIO()
    Image.new("RGB", (64, 48), (0, 0, 255)).save(encoded, image_format)

    frame = await ServerPlatform.decode_jpeg(SimpleNamespace(), encoded.getvalue())

    assert frame.shape == (48, 64, 3) and frame[0, 0, 2] > 200


async def test_an_image_with_more_pixels_than_the_cap_is_refused_before_it_is_decoded(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 2 MB JPEG of 12000x12000 pixels grew the hub from 386 MB to 1.6 GB."""
    from PIL import Image

    def jpeg(side: int) -> bytes:
        encoded = io.BytesIO()
        Image.new("RGB", (side, side)).save(encoded, "JPEG")
        return encoded.getvalue()

    decoded: list[int] = []
    real_reformat = av.VideoFrame.reformat
    monkeypatch.setattr(av.VideoFrame, "reformat", lambda frame, *a, **k: decoded.append(frame.width) or real_reformat(frame, *a, **k))
    monkeypatch.setattr("printguard.server.platform.CLASSIFY_MAX_PIXELS", 100 * 100)
    holder = SimpleNamespace()

    assert await ServerPlatform.decode_jpeg(holder, jpeg(101)) is None
    assert decoded == []
    assert (await ServerPlatform.decode_jpeg(holder, jpeg(100))).shape == (100, 100, 3)


async def test_a_quiet_device_is_released_when_its_camera_stands_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """A USB camera answering every read with EAGAIN never reached the standby check, which only ran when a frame arrived."""
    closed = threading.Event()

    class QuietDevice:
        streams = SimpleNamespace(video=[SimpleNamespace(average_rate=30, guessed_rate=30, codec_context=object())])

        def decode(self, stream: object) -> object:
            raise av.error.BlockingIOError(errno.EAGAIN, "Resource temporarily unavailable")

        def close(self) -> None:
            closed.set()

    monkeypatch.setattr(av, "open", lambda *args, **kwargs: QuietDevice())
    monkeypatch.setattr("printguard.server.platform.DEMAND_IDLE_S", 0.1)
    source = AVSource("/dev/video0", None, "v4l2", ({},))
    try:
        await asyncio.sleep(0.3)
        source.set_monitoring(False)
        released = await asyncio.to_thread(closed.wait, 3.0)
    finally:
        source.close()

    assert released, "a device that delivers nothing was held open after nothing needed it"


async def test_a_reader_that_cannot_be_stopped_is_remembered_when_the_wait_for_it_is_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    """The entry was taken out before the wait, so cancelling the wait forgot it and the next open started a second capture thread."""
    release = threading.Event()
    opened: list[int] = []

    def stuck_stream(host: str, access_code: str) -> object:
        opened.append(1)
        release.wait()
        raise OSError("gone")

    monkeypatch.setattr("printguard.server.platform.open_bambu_jpeg_stream", stuck_stream)
    monkeypatch.setattr("printguard.server.platform.OPEN_WAIT_S", 0.2)
    monkeypatch.setattr("printguard.server.platform.READER_STOP_WAIT_S", 1.0)
    platform = object.__new__(ServerPlatform)
    platform.mediamtx = SimpleNamespace(rtsp_url=lambda path: f"rtsp://127.0.0.1:9/{path}")
    platform._sources, platform._closing, platform._notices = {}, {}, []
    camera = {"kind": "bambu", "host": "printer", "access_code": "code"}

    try:
        with pytest.raises(RuntimeError, match="no frames from camera cam1"):
            await platform.open_camera("cam1", camera)
        waiting = asyncio.ensure_future(platform.open_camera("cam1", camera))
        await asyncio.sleep(0.1)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        with pytest.raises(RuntimeError, match="stopped answering and cannot be closed"):
            await platform.open_camera("cam1", camera)
        assert opened == [1]
    finally:
        release.set()


async def test_a_released_camera_is_forgotten_once_its_reader_has_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every released camera's source, with its last frames, was kept for the life of the process."""
    monkeypatch.setattr("printguard.server.platform.open_bambu_jpeg_stream", lambda host, access_code: _MjpegPipe())
    monkeypatch.setattr("printguard.server.platform.MEASURE_WARMUP_S", 0.1)
    monkeypatch.setattr("printguard.server.platform.FPS_SAMPLE_S", 0.3)
    platform = object.__new__(ServerPlatform)
    platform.mediamtx = SimpleNamespace(rtsp_url=lambda path: f"rtsp://127.0.0.1:9/{path}")
    platform._sources, platform._closing, platform._notices = {}, {}, []
    camera = {"kind": "bambu", "host": "printer", "access_code": "code"}

    opened = await platform.open_camera("cam1", camera)
    assert await opened.grab() is not None
    reader = weakref.ref(opened)
    await platform.release_camera("cam1", camera)
    del opened
    deadline = time.monotonic() + 5
    while platform._closing and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    gc.collect()

    assert platform._closing == {}
    assert reader() is None


def test_a_closed_device_leaves_no_frame_pointing_into_its_buffers(monkeypatch: pytest.MonkeyPatch) -> None:
    """V4L2's raw formats decode into buffers the close unmaps, so the kept frame is copied out, then dropped at the close."""
    writable: list[int] = []
    online_at_close: list[bool] = []
    ended, constructed = threading.Event(), threading.Event()

    class Frame:
        def make_writable(self) -> None:
            writable.append(1)

    class Device:
        streams = SimpleNamespace(video=[SimpleNamespace(average_rate=30, guessed_rate=30, codec_context=object())])

        def decode(self, stream: object) -> object:
            yield Frame()
            constructed.wait()
            raise RuntimeError("device unplugged")

        def close(self) -> None:
            online_at_close.append(source.online)
            ended.set()

    monkeypatch.setattr(av, "open", lambda *args, **kwargs: Device())
    monkeypatch.setattr("printguard.server.platform.RECONNECT_DELAY_S", 5.0)
    source = AVSource("/dev/video0", None, "v4l2", ({},))
    constructed.set()
    try:
        assert ended.wait(5.0)
        deadline = time.monotonic() + 5
        while source._latest is not None and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        source.close()

    assert writable == [1]
    assert online_at_close == [False]
    assert source._latest is None and source._latest_rgb is None


def test_a_live_view_listener_that_never_answers_fails_the_push_instead_of_stalling_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    """MediaMTX accepting on 8554 and never replying held the capture thread inside the first mux for good."""
    from printguard.server.publish import H264Push

    monkeypatch.setattr("printguard.server.publish.PUSH_TIMEOUT_US", 500_000)
    outcomes: list[Exception | None] = []
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        push = H264Push(f"rtsp://127.0.0.1:{listener.getsockname()[1]}/cam", 15, 60.0, outcomes.append)
        frame = av.VideoFrame.from_ndarray(np.zeros((240, 320, 3), dtype=np.uint8), format="rgb24")
        push.send(frame)
        deadline = time.monotonic() + 15
        while not outcomes and time.monotonic() < deadline:
            time.sleep(0.05)
        push.close()

    assert isinstance(outcomes[0], av.error.FFmpegError), "the push never gave up on a listener that does not answer"


def test_a_browser_camera_recording_slower_than_a_frame_a_second_is_still_pushed() -> None:
    """Its rate rounded down to 0 and the divide by it closed the publish socket with 1011."""
    from printguard.server.publish import ChunkStream, remux

    recording = io.BytesIO()
    with av.open(recording, "w", format="matroska") as container:
        stream = container.add_stream("mjpeg", rate=Fraction(1, 2))
        stream.width, stream.height, stream.pix_fmt = 64, 48, "yuvj420p"
        frame = av.VideoFrame.from_ndarray(np.zeros((48, 64, 3), dtype=np.uint8), format="rgb24")
        for pts in range(3):
            frame.pts = pts
            for packet in stream.encode(frame):
                container.mux(packet)
    chunks = ChunkStream()
    chunks.feed(recording.getvalue())
    chunks.feed(None)
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        nobody_listening = f"rtsp://127.0.0.1:{unused.getsockname()[1]}/cam"

        with pytest.raises(av.error.FFmpegError):
            remux(chunks, nobody_listening)


def test_a_recording_that_ends_drops_what_was_still_queued() -> None:
    """One sent faster than it plays went on publishing after its socket closed, and held a stopping hub for 15 s."""
    from printguard.server.publish import ChunkStream

    chunks = ChunkStream()
    chunks.feed(b"\x1a\x45")
    assert chunks.read(1) == b"\x1a"
    for _ in range(3):
        chunks.feed(b"\xdf\xa3")
    chunks.end()

    assert chunks.read(64) == b"\x45" and chunks.read(64) == b""


@needs_an_unprivileged_user
def test_a_print_store_the_hub_may_not_write_stops_the_hub_with_the_owner_named(tmp_path, monkeypatch) -> None:
    """It started and then failed the first upload, where the data directory itself is checked at the start."""
    monkeypatch.setenv("PRINTGUARD_PLUGINS", "off")
    store = tmp_path / "prints"
    store.mkdir(mode=0o500)
    try:
        with pytest.raises(RuntimeError, match=f"could not be created .*{store} belongs to .*belong to the user the hub runs as"):
            ServerPlatform(Path("models"), tmp_path, "http://localhost:9997", "rtsp://localhost:8554")
    finally:
        store.chmod(0o700)


def test_a_print_store_that_is_a_file_stops_the_hub_with_a_reason(tmp_path, monkeypatch) -> None:
    """A bare FileExistsError said nothing of what the hub wanted there."""
    monkeypatch.setenv("PRINTGUARD_PLUGINS", "off")
    (tmp_path / "prints").write_text("")

    with pytest.raises(RuntimeError, match="prints could not be created .*so the hub cannot start"):
        ServerPlatform(Path("models"), tmp_path, "http://localhost:9997", "rtsp://localhost:8554")


def test_a_browser_camera_push_to_a_listener_that_never_answers_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """The remux had no timeout, so a MediaMTX that accepted and never replied held its thread for good."""
    from printguard.server.publish import ChunkStream, remux

    recording = io.BytesIO()
    with av.open(recording, "w", format="matroska") as container:
        stream = container.add_stream("mjpeg", rate=15)
        stream.width, stream.height, stream.pix_fmt = 64, 48, "yuvj420p"
        frame = av.VideoFrame.from_ndarray(np.zeros((48, 64, 3), dtype=np.uint8), format="rgb24")
        for pts in range(5):
            frame.pts = pts
            for packet in stream.encode(frame):
                container.mux(packet)
    chunks = ChunkStream()
    chunks.feed(recording.getvalue())
    chunks.feed(None)
    monkeypatch.setattr("printguard.server.publish.PUSH_TIMEOUT_US", 500_000)
    outcome: list[BaseException] = []

    def push(url: str) -> None:
        try:
            remux(chunks, url)
        except BaseException as exc:
            outcome.append(exc)

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        thread = threading.Thread(target=push, args=(f"rtsp://127.0.0.1:{listener.getsockname()[1]}/cam",), daemon=True)
        thread.start()
        thread.join(15)

    assert not thread.is_alive(), "the remux never gave up on a listener that does not answer"
    assert isinstance(outcome[0], av.error.FFmpegError)


async def test_a_live_view_that_stops_answering_never_delays_the_frames_detection_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each retry blocked the capture thread for the push's whole timeout, so a camera gave a frame half the time."""

    def stalls(self: object, frame: object) -> None:
        time.sleep(1.0)
        raise av.error.TimeoutError(errno.ETIMEDOUT, "Operation timed out")

    monkeypatch.setattr("printguard.server.publish.H264Push._encode", stalls)
    monkeypatch.setattr("printguard.server.platform.RECONNECT_DELAY_S", 0.1)
    monkeypatch.setattr(_MjpegPipe, "opened", 0)
    reported: list[tuple[str, bool]] = []
    source = AVSource(_MjpegPipe, "rtsp://127.0.0.1:9/cam1", report=lambda message, recovered: reported.append((message, recovered)))
    try:
        deadline = time.monotonic() + 15
        while not source.online and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        started = source._seq
        await asyncio.sleep(2.5)
        gained = source._seq - started
    finally:
        source.close()

    assert gained > 40, f"capture delivered {gained} frames in 2.5 s while the live view stalled"
    assert len(reported) == 1, "the dashboard is told once per outage"


async def test_a_stored_file_is_readable_only_by_whoever_runs_the_hub(tmp_path: Path) -> None:
    """Review frames and sliced files sat at 0644 beside a state file at 0600."""

    async def chunks() -> object:
        yield b"G28\n"

    store = DiskFileStore(tmp_path)
    leftover = tmp_path / "benchy.gcode.part"
    leftover.write_bytes(b"from a hub that was killed")
    leftover.chmod(0o644)

    await store.store("benchy.gcode", chunks())
    await store.store("frame.jpg", chunks())

    assert oct((tmp_path / "benchy.gcode").stat().st_mode)[-3:] == "600"
    assert oct((tmp_path / "frame.jpg").stat().st_mode)[-3:] == "600"


@pytest.mark.parametrize(
    ("camera", "named"),
    [
        ({"kind": "url", "url": "whep://admin:CAMPASS@camera.invalid/stream"}, "whep://camera.invalid/stream"),
        ({"kind": "path", "path": "garage"}, "garage"),
    ],
)
async def test_a_camera_pulled_through_the_hub_names_the_address_it_was_given(
    monkeypatch: pytest.MonkeyPatch, camera: dict[str, str], named: str
) -> None:
    """The error named rtsp://localhost:8554/<camera id>, an address the hub made up, and never the user's."""

    async def ensure_path(name: str, pulled: str, fingerprint: object) -> None:
        return None

    async def remove_path(name: str) -> None:
        return None

    monkeypatch.setattr("printguard.server.platform.OPEN_WAIT_S", 5.0)
    platform = object.__new__(ServerPlatform)
    platform.mediamtx = SimpleNamespace(
        rtsp_url=lambda path: f"rtsp://127.0.0.1:9/{path}", ensure_path=ensure_path, remove_path=remove_path
    )
    platform._sources, platform._closing, platform._notices = {}, {}, []

    with pytest.raises(RuntimeError, match="no frames from camera cam1") as raised:
        await platform.open_camera("cam1", camera)

    assert named in str(raised.value)
    assert "127.0.0.1" not in str(raised.value) and "CAMPASS" not in str(raised.value)


async def test_a_frame_that_cannot_be_encoded_is_logged_not_swallowed(caplog: pytest.LogCaptureFixture) -> None:
    """The alert went out with no picture and no word of why."""
    holder = SimpleNamespace()
    with caplog.at_level(logging.WARNING, logger="printguard.server.platform"):
        assert await ServerPlatform.encode_jpeg(holder, np.zeros((240, 320, 4), dtype=np.uint8)) is None

    assert [record.levelname for record in caplog.records] == ["WARNING"]
    assert "JPEG" in caplog.text
