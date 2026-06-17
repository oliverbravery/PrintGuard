"""REST surface: the engine request/snapshot bridge and bearer-scope gating."""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
import pytest

from fakes import FakePlatform
from printguard.engine.engine import Engine
from printguard.server.api import ApiAuth, build_api_app

OCTOPRINT = {"provider": "octoprint", "config": {"base_url": "http://op", "api_key": "k"}}


@asynccontextmanager
async def api(tokens: dict[str, str] | None = None):
    """Yields an HTTP client, the engine, a printer and a monitor on one camera."""
    platform = FakePlatform()
    engine = Engine(platform)
    await engine.start()
    await engine.handle({"cmd": "camera.add", "name": "cam", "source": {"kind": "fake", "fps": 10.0}})
    camera_id = next(iter(engine.cameras.items))
    await engine.handle({"cmd": "printer.add", "printer": {"name": "P", **OCTOPRINT}})
    printer_id = next(iter(engine.printers.items))
    await engine.handle({"cmd": "monitor.add", "monitor": {"name": "M", "camera_id": camera_id, "printer_id": printer_id}})
    monitor_id = next(iter(engine.monitors))
    app = build_api_app(ApiAuth(tokens or {}, internal_token="INT"))
    app.state.engine = engine
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    try:
        yield client, engine, platform, monitor_id, printer_id, camera_id
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
    async with api() as (client, _engine, _platform, _monitor_id, printer_id, camera_id):
        assert (await client.get("/state")).status_code == 200
        frame = await client.get(f"/cameras/{camera_id}/frame")
        assert frame.status_code == 200 and frame.headers["content-type"] == "image/jpeg"
        assert frame.content == b"\xff\xd8fake"
        assert (await client.post(f"/printers/{printer_id}/action", json={"action": "pause"})).status_code == 403
        assert (await client.post("/printers", json={"name": "x"})).status_code == 403
        assert (await client.post("/monitors", json={"name": "x"})).status_code == 403


async def test_scoped_tokens_gate_control_and_management() -> None:
    async with api({"M": "manage", "R": "read"}) as (client, _engine, platform, _monitor_id, printer_id, camera_id):
        assert (await client.get("/state")).status_code == 401
        assert (await client.get("/state", headers={"Authorization": "Bearer bad"})).status_code == 401

        read = {"Authorization": "Bearer R"}
        assert (await client.get("/state", headers=read)).status_code == 200
        assert (await client.post(f"/printers/{printer_id}/action", json={"action": "pause"}, headers=read)).status_code == 403

        manage = {"Authorization": "Bearer M"}
        acted = await client.post(f"/printers/{printer_id}/action", json={"action": "pause"}, headers=manage)
        assert acted.status_code == 200
        assert any("/api/job" in url for _, url in platform.http_calls)
        added = await client.post("/printers", json={"name": "x", "provider": "octoprint", "config": {}}, headers=manage)
        assert added.status_code == 200
        made = await client.post("/monitors", json={"name": "m2", "camera_id": camera_id}, headers=manage)
        assert made.status_code == 200


async def test_unknown_ids_and_events() -> None:
    async with api() as (client, _engine, _platform, _monitor_id, _printer_id, _camera_id):
        assert (await client.get("/printers/nope")).status_code == 404
        assert (await client.get("/monitors/nope")).status_code == 404
        assert (await client.get("/cameras/nope/frame")).status_code == 404
        assert isinstance((await client.get("/events")).json(), list)


async def test_rejected_command_is_400() -> None:
    async with api({"M": "manage"}) as (client, _engine, platform, _monitor_id, printer_id, _camera_id):
        platform.reject_actions = True
        rejected = await client.post(f"/printers/{printer_id}/action", json={"action": "pause"}, headers={"Authorization": "Bearer M"})
        assert rejected.status_code == 400
