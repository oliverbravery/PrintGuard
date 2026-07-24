"""REST surface: the engine request/snapshot bridge and bearer-scope gating."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import numpy as np
import pytest

from fakes import FakePlatform
from printguard.engine.engine import Engine
from printguard.engine.registry import Camera
from printguard.server.api import ApiAuth, build_api_app

OCTOPRINT = {"provider": "octoprint", "config": {"base_url": "http://op", "api_key": "k"}}


@asynccontextmanager
async def api(scopes: tuple[str, ...] = ()):
    """Yields an HTTP client, the engine, a printer, a monitor and minted token secrets."""
    platform = FakePlatform()
    engine = Engine(platform)
    await engine.start()
    await engine.handle({"cmd": "camera.add", "name": "cam", "source": {"kind": "fake", "fps": 10.0}})
    camera_id = next(iter(engine.cameras.items))
    await engine.handle({"cmd": "printer.add", "printer": {"name": "P", **OCTOPRINT}})
    printer_id = next(iter(engine.printers.items))
    await engine.handle({"cmd": "monitor.add", "monitor": {"name": "M", "camera_id": camera_id, "printer_id": printer_id}})
    monitor_id = next(iter(engine.monitors))
    tokens = {}
    for scope in scopes:
        events = await engine.request({"cmd": "token.create", "name": scope, "scope": scope})
        tokens[scope] = next(e["token"] for e in events if e.get("event") == "token_created")
    app = build_api_app(ApiAuth(internal_token="INT"))
    app.state.engine = engine
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    try:
        yield client, engine, platform, monitor_id, printer_id, camera_id, tokens
    finally:
        await client.aclose()
        await engine.stop()


async def test_request_returns_state_and_raises_on_error() -> None:
    engine = Engine(FakePlatform())
    await engine.start()
    try:
        events = await engine.request({"cmd": "camera.add", "name": "c", "source": {"kind": "fake", "fps": 5.0}})
        assert any(e.get("event") == "state" for e in events)
        with pytest.raises(RuntimeError):
            await engine.request({"cmd": "monitor.update", "id": "missing", "patch": {}})
    finally:
        await engine.stop()


async def test_snapshot_returns_jpeg_or_none() -> None:
    engine = Engine(FakePlatform())
    await engine.start()
    try:
        await engine.handle({"cmd": "camera.add", "name": "c", "source": {"kind": "fake", "fps": 5.0}})
        camera_id = next(iter(engine.cameras.items))
        assert await engine.snapshot(camera_id) == b"\xff\xd8fake"
        assert await engine.snapshot("nope") is None
    finally:
        await engine.stop()


async def test_classify_scores_a_supplied_frame() -> None:
    engine = Engine(FakePlatform())
    await engine.start()
    try:
        result = await engine.classify(b"\xff\xd8jpeg", sensitivity=1.0)
        assert result["prediction"] == "success"
        assert 0.0 <= result["defect_score"] <= 1.0
        with pytest.raises(RuntimeError):
            await engine.classify(b"not an image")
    finally:
        await engine.stop()


async def test_classify_endpoint_reads_a_supplied_frame() -> None:
    async with api() as (client, *_):
        ok = await client.post("/classify", content=b"\xff\xd8jpeg", headers={"Content-Type": "image/jpeg"})
        assert ok.status_code == 200
        assert ok.json()["prediction"] in ("success", "failure", "unknown")
        assert "defect_score" in ok.json()
        bad = await client.post("/classify", content=b"nope", headers={"Content-Type": "image/jpeg"})
        assert bad.status_code == 400


async def test_baseline_is_read_only_without_tokens() -> None:
    async with api() as (client, _engine, _platform, _monitor_id, printer_id, camera_id, _tokens):
        assert (await client.get("/state")).status_code == 200
        frame = await client.get(f"/cameras/{camera_id}/frame")
        assert frame.status_code == 200 and frame.headers["content-type"] == "image/jpeg"
        assert frame.content == b"\xff\xd8fake"
        assert (await client.post(f"/printers/{printer_id}/action", json={"action": "pause"})).status_code == 403
        assert (await client.post("/printers", json={"name": "x"})).status_code == 403
        assert (await client.post("/monitors", json={"name": "x"})).status_code == 403


async def test_scoped_tokens_gate_control_and_management() -> None:
    async with api(("read", "manage")) as (client, _engine, platform, _monitor_id, printer_id, camera_id, tokens):
        assert (await client.get("/state")).status_code == 401
        assert (await client.get("/state", headers={"Authorization": "Bearer bad"})).status_code == 401

        read = {"Authorization": f"Bearer {tokens['read']}"}
        assert (await client.get("/state", headers=read)).status_code == 200
        assert (await client.post(f"/printers/{printer_id}/action", json={"action": "pause"}, headers=read)).status_code == 403

        manage = {"Authorization": f"Bearer {tokens['manage']}"}
        acted = await client.post(f"/printers/{printer_id}/action", json={"action": "pause"}, headers=manage)
        assert acted.status_code == 200
        assert any("/api/job" in url for _, url in platform.http_calls)
        added = await client.post("/printers", json={"name": "x", "provider": "octoprint", "config": {}}, headers=manage)
        assert added.status_code == 200
        made = await client.post("/monitors", json={"name": "m2", "camera_id": camera_id}, headers=manage)
        assert made.status_code == 200


async def test_read_surface_strips_linked_service_secrets() -> None:
    async with api(("read",)) as (client, engine, _platform, _monitor_id, printer_id, _camera_id, tokens):
        await engine.handle({"cmd": "settings.update", "patch": {"notifiers": {"telegram": {"bot_token": "T", "chat_id": "9"}}}})
        read = {"Authorization": f"Bearer {tokens['read']}"}

        state = (await client.get("/state", headers=read)).json()
        printer = next(p for p in state["printers"] if p["id"] == printer_id)
        assert printer["config"] == {"base_url": "http://op"}
        assert state["settings"]["notifiers"]["telegram"] == {"chat_id": "9"}

        listed = (await client.get("/printers", headers=read)).json()
        one = (await client.get(f"/printers/{printer_id}", headers=read)).json()
        assert "api_key" not in listed[0]["config"]
        assert "api_key" not in one["config"]

        full = engine.state_event()
        assert full["printers"][0]["config"]["api_key"] == "k"
        assert full["settings"]["notifiers"]["telegram"]["bot_token"] == "T"


async def test_refresh_printer_cameras_registers_exposed_cameras(monkeypatch) -> None:
    from printguard.engine.integrations import INTEGRATIONS

    async with api(("read", "manage")) as (client, _engine, _platform, _monitor_id, printer_id, _camera_id, tokens):
        async def fake_cameras(http, config):
            return [{"key": "webcam", "name": "Shop cam", "source": {"kind": "fake", "fps": 10.0}}]

        monkeypatch.setattr(INTEGRATIONS["octoprint"], "cameras", fake_cameras)
        read = {"Authorization": f"Bearer {tokens['read']}"}
        manage = {"Authorization": f"Bearer {tokens['manage']}"}
        assert (await client.post("/cameras/refresh-printers", headers=read)).status_code == 403, "refresh needs a manage token"

        cameras = (await client.post("/cameras/refresh-printers", headers=manage)).json()
        registered = {c["id"]: c for c in cameras}
        assert f"{printer_id}-webcam" in registered
        assert registered[f"{printer_id}-webcam"]["printer_id"] == printer_id


async def test_read_surface_strips_camera_source_credentials() -> None:
    async with api(("read",)) as (client, engine, _platform, _monitor_id, _printer_id, _camera_id, tokens):
        engine.cameras.add(
            Camera(id="x1", name="X1 cam", source={"kind": "url", "url": "rtsps://bblp:SECRET@host:322/streaming/live/1", "fingerprint": "FP"}, max_fps=15.0)
        )
        engine.cameras.add(Camera(id="a1", name="A1 cam", source={"kind": "bambu", "host": "host", "access_code": "SECRET"}, max_fps=15.0))
        read = {"Authorization": f"Bearer {tokens['read']}"}

        cameras = {c["id"]: c for c in (await client.get("/cameras", headers=read)).json()}
        assert cameras["x1"]["source"]["url"] == "rtsps://host:322/streaming/live/1", "rtsps credentials are stripped"
        assert "access_code" not in cameras["a1"]["source"], "the port-6000 access code is dropped"
        assert cameras["a1"]["source"]["host"] == "host"

        full = {c.id: c for c in engine.cameras.values()}
        assert "SECRET" in full["x1"].source["url"], "the engine keeps the working URL for itself"
        assert full["a1"].source["access_code"] == "SECRET"


def test_bambu_jpeg_stream_strips_frame_headers() -> None:
    import struct

    from printguard.server.bambu_camera import BambuJpegStream

    jpegs = [b"\xff\xd8\xff\xe0AAA\xff\xd9", b"\xff\xd8\xff\xe0BBBB\xff\xd9"]
    wire = b"".join(struct.pack("<IIII", len(j), 0, 1, 0) + j for j in jpegs)

    class FakeSock:
        def __init__(self, data: bytes) -> None:
            self.data = data

        def recv(self, count: int) -> bytes:
            out, self.data = self.data[:count], self.data[count:]
            return out

        def close(self) -> None:
            pass

    stream = BambuJpegStream(FakeSock(wire))
    out = b""
    while chunk := stream.read(4096):
        out += chunk
    assert out == b"".join(jpegs), "the 16-byte frame headers are stripped, leaving concatenated JPEGs"


def test_callable_mjpeg_sources_cap_pyav_probe(monkeypatch) -> None:
    from printguard.server import platform

    pipe = object()
    captured = {}

    def fake_open(target, *, format, options):
        captured.update(target=target, format=format, options=options)
        return "container"

    monkeypatch.setattr(platform.av, "open", fake_open)
    source = object.__new__(platform.AVSource)
    source._source = lambda: pipe

    container, returned_pipe = source._open()

    assert (container, returned_pipe) == ("container", pipe)
    assert captured == {
        "target": pipe,
        "format": "mjpeg",
        "options": {"analyzeduration": "0", "probesize": "32"},
    }, "live MJPEG pipes cap PyAV probing so av.open returns instead of draining frames"


def test_direct_camera_source_wakes_for_viewers(monkeypatch) -> None:
    from printguard.server import platform

    monkeypatch.setattr(platform.AVSource, "_run", lambda self: None)
    now = [100.0]
    monkeypatch.setattr(platform.time, "monotonic", lambda: now[0])
    source = platform.AVSource("http://camera/stream", "rtsp://mediamtx/camera")
    source.set_monitoring(False)
    assert not source.standby
    now[0] += platform.DEMAND_IDLE_S
    assert source.standby
    source.view()
    assert not source.standby
    source.close()


def test_pullable_camera_source_leaves_viewing_to_mediamtx(monkeypatch) -> None:
    from printguard.server import platform

    monkeypatch.setattr(platform.AVSource, "_run", lambda self: None)
    now = [100.0]
    monkeypatch.setattr(platform.time, "monotonic", lambda: now[0])
    source = platform.AVSource("rtsp://mediamtx/camera")
    source.set_monitoring(False)
    now[0] += platform.DEMAND_IDLE_S
    source.view()
    assert source.standby
    source.close()


async def test_view_camera_renews_demand_after_cold_start() -> None:
    from printguard.server import platform

    source = SimpleNamespace(online=True, view=Mock(return_value=True))
    server = object.__new__(platform.ServerPlatform)
    server._sources = {"camera": source}

    await server.view_camera("camera")

    assert source.view.call_count == 2


async def test_cancelled_camera_open_closes_platform_source(monkeypatch) -> None:
    from printguard.server import platform

    source = SimpleNamespace(online=False, fps=0.0, last_error=None, close=Mock())
    monkeypatch.setattr(platform, "AVSource", lambda *args: source)
    server = object.__new__(platform.ServerPlatform)
    server.mediamtx = SimpleNamespace(rtsp_url=Mock(return_value="rtsp://mediamtx/camera"))
    server._sources = {}
    task = asyncio.create_task(server.open_camera("camera", {"kind": "url", "url": "http://camera/stream"}))
    await asyncio.sleep(0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    source.close.assert_called_once()
    assert server._sources == {}


async def test_releasing_pull_camera_removes_managed_path() -> None:
    from printguard.server import platform

    source = SimpleNamespace(close=Mock())
    server = object.__new__(platform.ServerPlatform)
    server.mediamtx = SimpleNamespace(remove_path=AsyncMock())
    server._sources = {"camera": source}

    await server.release_camera("camera", {"kind": "url", "url": "rtsp://camera/live"})

    source.close.assert_called_once()
    server.mediamtx.remove_path.assert_awaited_once_with("camera")


class Scaler:
    """Records the conversions a reused VideoReformatter is asked for."""

    created: list["Scaler"] = []

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        Scaler.created.append(self)

    def reformat(self, frame, *, format: str, threads: int):
        self.calls.append((format, threads))
        return SimpleNamespace(to_ndarray=lambda: np.zeros((48, 64, 3), dtype=np.uint8))


@pytest.fixture
def scalers(monkeypatch):
    """Replaces both scaler call sites, yielding every instance they create."""
    from printguard.server import platform, publish

    Scaler.created = []
    monkeypatch.setattr(platform, "VideoReformatter", Scaler)
    monkeypatch.setattr(publish, "VideoReformatter", Scaler)
    return Scaler.created


async def test_camera_source_converts_only_grabbed_frames(monkeypatch, scalers) -> None:
    from printguard.server import platform

    monkeypatch.setattr(platform.AVSource, "_run", lambda self: None)

    source = platform.AVSource("rtsp://mediamtx/camera")
    source._latest = (object(), 1.0, 2.0)
    first = await source.grab()
    second = await source.grab()
    source._latest = (object(), 2.0, 3.0)
    third = await source.grab()
    source.close()

    assert first is second and third is not first
    assert first is not None and first.seq == 1.0 and first.ts == 2.0
    assert [scaler.calls for scaler in scalers] == [[("rgb24", 1), ("rgb24", 1)]]


def test_published_frames_share_one_single_threaded_scaler(monkeypatch, scalers) -> None:
    """Per-frame conversion reuses one single-threaded scaler.

    PyAV builds a fresh scaler per reformat() call, and its default thread
    count gives each one a slice-thread pool, so converting every frame of a
    camera churns OS threads faster than the system reclaims them until the
    process can no longer start one.
    """
    from printguard.server import publish

    stream = SimpleNamespace(
        width=0, height=0, pix_fmt="", codec_context=SimpleNamespace(options={}, time_base=None), encode=Mock(return_value=[])
    )
    monkeypatch.setattr(
        publish.av, "open", Mock(return_value=SimpleNamespace(add_stream=Mock(return_value=stream), mux=Mock()))
    )
    push = publish.H264Push("rtsp://mediamtx/camera", 30)

    for _ in range(3):
        push.send(SimpleNamespace(width=64, height=48))

    assert [scaler.calls for scaler in scalers] == [[("yuv420p", 1)] * 3]


async def test_unknown_ids_and_events() -> None:
    async with api() as (client, _engine, _platform, _monitor_id, _printer_id, _camera_id, _tokens):
        assert (await client.get("/printers/nope")).status_code == 404
        assert (await client.get("/monitors/nope")).status_code == 404
        assert (await client.get("/cameras/nope/frame")).status_code == 404
        assert isinstance((await client.get("/events")).json(), list)


async def test_rejected_command_is_400() -> None:
    async with api(("manage",)) as (client, _engine, platform, _monitor_id, printer_id, _camera_id, tokens):
        platform.reject_actions = True
        rejected = await client.post(
            f"/printers/{printer_id}/action", json={"action": "pause"}, headers={"Authorization": f"Bearer {tokens['manage']}"}
        )
        assert rejected.status_code == 400
