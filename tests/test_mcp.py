"""MCP surface: tools derived from the REST routes, scope filtering and the
hand-written camera frame tool returning native image content."""

from __future__ import annotations

import asyncio
import base64
import logging
from unittest.mock import AsyncMock

import httpx
import mcp.types as mt
import pytest
from fastmcp import Client

from fakes import FakePlatform
from printguard.engine.engine import Engine
from printguard.server import mcp as mcp_module
from printguard.server.api import CLASSIFY_IN_FLIGHT, ApiAuth, build_api_app
from printguard.server.mcp import build_mcp, build_mcp_app

READ_TOOLS = {
    "get_state",
    "list_monitors",
    "get_monitor",
    "list_printers",
    "get_printer",
    "list_cameras",
    "get_camera",
    "get_camera_frame",
    "classify_frame",
    "get_monitor_history",
    "get_monitor_snapshot",
    "list_prints",
    "get_print",
    "recent_events",
}


async def _server():
    engine = Engine(FakePlatform())
    await engine.start()
    await engine.handle({"cmd": "camera.add", "name": "cam", "source": {"kind": "fake", "fps": 10.0}})
    camera_id = next(iter(engine.cameras.items))
    auth = ApiAuth(internal_token="INT")
    app = build_api_app(auth)
    app.state.engine = engine
    mcp = build_mcp(app, lambda: engine, auth, "INT")
    return engine, mcp, camera_id


async def test_full_tool_set_is_derived_with_scope_tags() -> None:
    engine, mcp, _ = await _server()
    try:
        assert (await mcp.get_tool("control_printer")).tags == {"control"}
        assert (await mcp.get_tool("heat_printer")).tags == {"control"}
        assert (await mcp.get_tool("add_printer")).tags == {"manage"}
        assert (await mcp.get_tool("add_monitor")).tags == {"manage"}
        assert (await mcp.get_tool("get_camera_frame")).tags == {"read"}
        assert (await mcp.get_tool("start_print")).tags == {"control"}
        assert (await mcp.get_tool("update_print")).tags == {"manage"}
        names = {tool.name for tool in await mcp.list_tools()}
        assert {"add_print", "get_print_file"}.isdisjoint(names), "binary upload and download are not tools"
    finally:
        await engine.stop()


async def test_unauthorised_caller_sees_only_read_tools() -> None:
    engine, mcp, _ = await _server()
    try:
        async with Client(mcp) as client:
            names = {tool.name for tool in await client.list_tools()}
        assert names == READ_TOOLS
        assert "control_printer" not in names and "add_printer" not in names
    finally:
        await engine.stop()


async def test_frame_tool_returns_image_content() -> None:
    engine, mcp, camera_id = await _server()
    try:
        async with Client(mcp) as client:
            result = await client.call_tool("get_camera_frame", {"camera_id": camera_id})
        images = [block for block in result.content if isinstance(block, mt.ImageContent)]
        assert images and images[0].mimeType == "image/jpeg"
    finally:
        await engine.stop()


async def test_snapshot_tool_returns_image_content(monkeypatch) -> None:
    """Derived from the REST route it would hand an agent a JPEG as text."""
    engine, mcp, _ = await _server()
    monkeypatch.setattr(engine, "monitor_snapshot", AsyncMock(side_effect=lambda monitor_id, snap_id: b"\xff\xd8jpeg" if snap_id == "s1" else None))
    try:
        async with Client(mcp) as client:
            result = await client.call_tool("get_monitor_snapshot", {"monitor_id": "m1", "snap_id": "s1"})
            with pytest.raises(Exception):
                await client.call_tool("get_monitor_snapshot", {"monitor_id": "m1", "snap_id": "gone"})
        assert [block.mimeType for block in result.content] == ["image/jpeg"]
        assert isinstance(result.content[0], mt.ImageContent)
    finally:
        await engine.stop()


async def test_classify_tool_scores_a_supplied_image() -> None:
    engine, mcp, _ = await _server()
    try:
        image_base64 = base64.b64encode(b"\xff\xd8jpeg").decode()
        async with Client(mcp) as client:
            result = await client.call_tool("classify_frame", {"image_base64": image_base64})
            with pytest.raises(Exception):
                await client.call_tool("classify_frame", {"image_base64": base64.b64encode(b"nope").decode()})
            with pytest.raises(Exception, match="over 32 MB"):
                await client.call_tool("classify_frame", {"image_base64": "A" * (33 * 1024 * 1024 * 4 // 3)})
        assert result.data["prediction"] in ("success", "failure", "unknown")
        assert "defect_score" in result.data
    finally:
        await engine.stop()


async def test_the_classify_tool_waits_its_turn_with_the_rest_route(monkeypatch) -> None:
    """The tool and the route share the slots, so neither is a way round the other's bound."""
    engine, mcp, _ = await _server()
    running = most = 0

    async def classify(data: bytes) -> dict:
        nonlocal running, most
        running += 1
        most = max(most, running)
        await asyncio.sleep(0.02)
        running -= 1
        return {"prediction": "success"}

    monkeypatch.setattr(engine, "classify", classify)
    try:
        async with Client(mcp) as client:
            await asyncio.gather(*(client.call_tool("classify_frame", {"image_base64": "/9g="}) for _ in range(6)))
    finally:
        await engine.stop()

    assert most == CLASSIFY_IN_FLIGHT


@pytest.mark.parametrize("chunked", [False, True])
async def test_a_request_body_over_the_cap_is_refused_before_it_is_held(monkeypatch, chunked: bool) -> None:
    """The transport read a body of any size before anything looked at it, and 400 MB cost a token-less hub 1.5 GB."""
    monkeypatch.setattr(mcp_module, "MAX_BODY_BYTES", 1024)
    engine = Engine(FakePlatform())
    await engine.start()
    auth = ApiAuth(internal_token="INT")
    api_app = build_api_app(auth)
    api_app.state.engine = engine
    app = build_mcp_app(api_app, lambda: engine, auth, "INT")
    read = 0

    async def endless():
        nonlocal read
        while True:
            read += 256
            yield b"x" * 256

    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    handshake = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
    }
    try:
        async with app.lifespan(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            async with asyncio.timeout(2):
                refused = await client.post("/", content=endless() if chunked else b"x" * 2048, headers=headers)
            held = await client.post("/", json=handshake, headers=headers)
    finally:
        await engine.stop()

    assert refused.status_code == 413 and read <= 2048
    assert held.status_code == 200 and "PrintGuard" in held.text


async def test_unauthorised_control_call_is_denied() -> None:
    engine, mcp, _ = await _server()
    try:
        async with Client(mcp) as client:
            with pytest.raises(Exception):
                await client.call_tool("control_printer", {"printer_id": "x", "action": "pause"})
    finally:
        await engine.stop()


async def test_a_session_is_not_opened_without_a_bearer_once_tokens_exist() -> None:
    """The tool filter alone answered the handshake with the server's name and version."""
    engine = Engine(FakePlatform())
    await engine.start()
    auth = ApiAuth(internal_token="INT")
    api_app = build_api_app(auth)
    api_app.state.engine = engine
    app = build_mcp_app(api_app, lambda: engine, auth, "INT")
    handshake = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
    }
    accept = {"Accept": "application/json, text/event-stream"}
    try:
        async with app.lifespan(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            open_hub = await client.post("/", json=handshake, headers=accept)
            assert open_hub.status_code == 200 and "PrintGuard" in open_hub.text

            events = await engine.request({"cmd": "token.create", "name": "agent", "scope": "read"})
            token = next(e["token"] for e in events if e.get("event") == "token_created")
            for headers in (accept, {**accept, "Authorization": "Bearer pg_wrong"}):
                refused = await client.post("/", json=handshake, headers=headers)
                assert refused.status_code == 401 and refused.headers["www-authenticate"] == "Bearer"
                assert "PrintGuard" not in refused.text
            held = await client.post("/", json=handshake, headers={**accept, "Authorization": f"Bearer {token}"})
            assert held.status_code == 200 and "PrintGuard" in held.text
    finally:
        await engine.stop()


HANDSHAKE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
}


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("add_printer", '{"name": "P", "provider": "octoprint", "config": {"base_url": "http://printer", "api_key": "k", "note": NaN}}'),
        ("update_settings", '{"preheat": [{"name": "PLA", "nozzle": NaN, "bed": 60}]}'),
        ("update_settings", '{"mqtt": {"enabled": false, "host": "broker", "port": Infinity}}'),
        ("update_settings", '{"fault_grace_s": NaN}'),
        ("update_settings", '{"fault_grace_s": 1e999}'),
    ],
)
async def test_a_tool_call_carrying_a_number_that_is_not_finite_is_refused_and_changes_nothing(tool: str, arguments: str) -> None:
    """Nested ones reached the REST layer as null and were accepted, and the old test was only ever refused for having no token."""
    engine = Engine(FakePlatform())
    await engine.start()
    auth = ApiAuth(internal_token="INT")
    api_app = build_api_app(auth)
    api_app.state.engine = engine
    app = build_mcp_app(api_app, lambda: engine, auth, "INT")
    created = await engine.request({"cmd": "token.create", "name": "agent", "scope": "manage"})
    token = next(event["token"] for event in created if event.get("event") == "token_created")
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    before = {key: engine.settings.get(key) for key in ("preheat", "mqtt", "fault_grace_s")}
    call = f'{{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {{"name": "{tool}", "arguments": {arguments}}}}}'
    try:
        async with app.lifespan(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            session = (await client.post("/", json=HANDSHAKE, headers=headers)).headers["mcp-session-id"]
            headers["mcp-session-id"] = session
            await client.post("/", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers)
            answer = await client.post("/", content=call.encode(), headers=headers)
        assert '"isError":true' in answer.text.replace(" ", ""), answer.text
        assert "finite number" in answer.text, answer.text
        assert not list(engine.printers.items)
        assert {key: engine.settings.get(key) for key in before} == before
    finally:
        await engine.stop()


async def test_a_call_the_rest_layer_refuses_is_a_tool_error_logged_in_one_line(caplog: pytest.LogCaptureFixture, capfd: pytest.CaptureFixture[str]) -> None:
    """FastMCP printed a rich traceback to stderr for each one, past the hub's log format."""
    engine, mcp, _ = await _server()
    try:
        with caplog.at_level(logging.INFO, logger="printguard.server.mcp"):
            async with Client(mcp) as client:
                with pytest.raises(Exception, match="HTTP error 404.*no monitor"):
                    await client.call_tool("get_monitor", {"monitor_id": "missing"})
    finally:
        await engine.stop()

    said = [record.getMessage() for record in caplog.records if record.name == "printguard.server.mcp"]
    assert said == ["MCP tool call refused: GET /monitors/missing answered 404"]
    assert not [record for record in caplog.records if record.exc_info or "Error calling tool" in record.getMessage()]
    assert "Traceback" not in capfd.readouterr().err


async def test_an_image_sent_while_too_many_wait_is_turned_away_before_it_is_read(monkeypatch) -> None:
    """Every caller's body was read and decoded before the two turns were asked for, so the ones waiting held an image each."""
    monkeypatch.setattr(mcp_module, "CALL_BYTES", 64)
    monkeypatch.setattr(mcp_module, "CLASSIFY_WAITING", 1)
    engine = Engine(FakePlatform())
    await engine.start()
    auth = ApiAuth(internal_token="INT")
    api_app = build_api_app(auth)
    api_app.state.engine = engine
    release = asyncio.Event()
    read: list[int] = []

    async def held(scope, receive, send) -> None:
        read.append(len((await receive())["body"]))
        await release.wait()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    gate = mcp_module.BearerGate(held, auth, lambda: engine)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gate), base_url="http://127.0.0.1") as client:
            images = [asyncio.ensure_future(client.post("/", content=b"x" * 128)) for _ in range(CLASSIFY_IN_FLIGHT + 1)]
            await asyncio.sleep(0.05)
            turned_away = await client.post("/", content=b"x" * 128)
            small = asyncio.ensure_future(client.post("/", content=b"{}"))
            await asyncio.sleep(0.05)
            assert read == [128] * CLASSIFY_IN_FLIGHT + [2], "a waiting image is not read, and a plain call does not wait"
            release.set()
            answers = await asyncio.gather(*images, small)
    finally:
        await engine.stop()

    assert turned_away.status_code == 503 and turned_away.headers["retry-after"] == "1"
    assert [answer.status_code for answer in answers] == [200] * (CLASSIFY_IN_FLIGHT + 2)


async def test_a_snapshot_whose_file_is_gone_is_a_tool_error_that_names_no_path(tmp_path) -> None:
    from fastmcp.exceptions import ToolError

    from printguard.server.platform import DiskFileStore

    engine, mcp, camera_id = await _server()
    try:
        engine.platform.files = DiskFileStore(tmp_path)
        await engine.handle({"cmd": "monitor.add", "monitor": {"name": "M", "camera_id": camera_id}})
        monitor_id = next(iter(engine.monitors))
        engine.reviews.restore(
            [{"id": "r1", "monitor_id": monitor_id, "started": 0.0, "spacing_s": 60.0, "frames": [{"id": "f1", "ts": 1.0, "score": 0.9, "kind": "alert", "action": "none", "size": 3}]}]
        )
        async with Client(mcp) as client:
            with pytest.raises(ToolError) as refused:
                await client.call_tool("get_monitor_snapshot", {"monitor_id": monitor_id, "snap_id": "f1"})
        assert str(tmp_path) not in str(refused.value)
    finally:
        await engine.stop()


async def test_the_settings_tool_takes_the_same_typed_keys_as_the_rest_route() -> None:
    engine, mcp, _ = await _server()
    try:
        schema = (await mcp.get_tool("update_settings")).parameters["properties"]
        assert {"notifiers", "mqtt", "inference_runtime", "preheat", "fault_grace_s", "update_check", "feedback"} <= set(schema)
        assert schema["fault_grace_s"]["anyOf"][0]["type"] == "number" and schema["feedback"]["anyOf"][0]["enum"] == ["ask", "off"]
    finally:
        await engine.stop()
