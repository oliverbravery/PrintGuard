"""MCP surface: tools derived from the REST routes, scope filtering and the
hand-written camera frame tool returning native image content."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock

import httpx
import mcp.types as mt
import pytest
from fastmcp import Client

from fakes import FakePlatform
from printguard.engine.engine import Engine
from printguard.server.api import ApiAuth, build_api_app
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


async def test_a_tool_call_carrying_nan_is_refused_and_registers_nothing() -> None:
    engine = Engine(FakePlatform())
    await engine.start()
    auth = ApiAuth(internal_token="INT")
    api_app = build_api_app(auth)
    api_app.state.engine = engine
    app = build_mcp_app(api_app, lambda: engine, auth, "INT")
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    handshake = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
    }
    call = b'{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "add_printer", "arguments": {"name": "P", "provider": "octoprint", "config": {"note": NaN}}}}'
    try:
        async with app.lifespan(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            session = (await client.post("/", json=handshake, headers=headers)).headers["mcp-session-id"]
            headers["mcp-session-id"] = session
            await client.post("/", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers)
            answer = await client.post("/", content=call, headers=headers)
        assert "isError" in answer.text and "true" in answer.text.split("isError")[1][:8], answer.text
        assert not list(engine.printers.items)
    finally:
        await engine.stop()
