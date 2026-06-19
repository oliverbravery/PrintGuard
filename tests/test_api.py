"""REST surface: the engine request/snapshot bridge and bearer-scope gating."""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
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
