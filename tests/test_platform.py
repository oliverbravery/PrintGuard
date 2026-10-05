"""Server platform tests, from model execution to camera discovery."""

from __future__ import annotations

import asyncio
import fcntl
import json
import struct
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import av
import httpx
import numpy as np
import pytest
import websockets
from fakes import redirected_socket

from printguard.engine import vision
from printguard.server.inference import (
    Inference,
    _device_label,
    _execution_devices,
    _measure_concurrency,
    _register_library,
)
from printguard.server.platform import (
    V4L2_CAP_DEVICE_CAPS,
    V4L2_CAP_VIDEO_CAPTURE,
    AVSource,
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


def test_windows_lists_its_cameras_by_name_and_leaves_out_microphones(monkeypatch: pytest.MonkeyPatch) -> None:
    """DirectShow reports cameras and microphones together, each under a name and a device path."""
    devices = [
        SimpleNamespace(name="@device_pnp_usb#vid_046d", description="HD Pro Webcam C920", media_types=["video"]),
        SimpleNamespace(name="@device_cm_wave", description="Microphone (HD Pro Webcam C920)", media_types=["audio"]),
    ]
    asked: list[str] = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(av.device, "enumerate_input_devices", lambda name: asked.append(name) or devices)

    assert _video_devices() == [("HD Pro Webcam C920", "HD Pro Webcam C920")]
    assert asked == ["dshow"]


def test_provider_library_that_cannot_load_leaves_the_cpu(tmp_path: Path) -> None:
    """A GPU image whose provider libraries the host cannot supply must still start.

    The accelerated images carry a provider that needs libraries only the host can hand
    over, so any host without them, or any container started without GPU access, would
    otherwise take PrintGuard down at startup rather than watching printers on the CPU.
    """
    assert _register_library("printguard_test_provider", str(tmp_path / "libmissing.so")) is False


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


def test_the_state_file_is_readable_only_by_whoever_runs_the_hub(tmp_path) -> None:
    """It holds printer passwords, API token hashes and plugin credentials."""
    holder = SimpleNamespace(_state_path=tmp_path / "state.json")
    ServerPlatform.save_state(holder, {"printers": [{"config": {"password": "hunter2"}}]})

    assert oct((tmp_path / "state.json").stat().st_mode)[-3:] == "600"
    assert not (tmp_path / "state.tmp").exists(), "the temporary file was left behind"


def test_the_state_file_reaches_the_disk_before_it_takes_the_name(tmp_path, monkeypatch) -> None:
    """A rename without a sync can survive a power cut pointing at an empty file."""
    synced: list[int] = []
    monkeypatch.setattr("printguard.server.platform.os.fsync", lambda descriptor: synced.append((tmp_path / "state.tmp").stat().st_size))
    holder = SimpleNamespace(_state_path=tmp_path / "state.json")
    ServerPlatform.save_state(holder, {"printers": []})

    assert synced == [(tmp_path / "state.json").stat().st_size]


def test_a_damaged_state_file_is_kept_rather_than_overwritten(tmp_path, caplog) -> None:
    """Starting empty in silence loses every printer and reopens anonymous reads of the API."""
    holder = SimpleNamespace(_state_path=tmp_path / "state.json")
    assert ServerPlatform.load_state(holder) == {}
    assert not caplog.records, "a first boot has no state file and nothing to say about it"

    (tmp_path / "state.json").write_text('{"printers": [{"id": "p1"')
    assert ServerPlatform.load_state(holder) == {}
    ServerPlatform.save_state(holder, {})

    assert (tmp_path / "state.json.corrupt").read_text() == '{"printers": [{"id": "p1"'
    assert [record.levelname for record in caplog.records] == ["ERROR"]
    assert "state.json.corrupt" in caplog.text


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
            assert (await ServerPlatform.http(holder, "POST", f"{registered}/api/job", follow_redirects=False))[0] == int(answer[:3])
    assert arrived == [*reached, "GET"]


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


async def test_a_plugin_socket_refuses_a_redirect_instead_of_following_it() -> None:
    """Only the address a plugin declared was checked against its grant."""
    async with redirected_socket() as (declared, reached):
        with pytest.raises(websockets.InvalidStatus, match="HTTP 302"):
            await ServerPlatform.open_socket(None, f"{declared}/feed", lambda state, text: None)

    assert reached == [], "the handshake went on to an address nobody checked"


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
