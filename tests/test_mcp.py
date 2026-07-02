"""MCP surface: tools derived from the REST routes, scope filtering and the
hand-written camera frame tool returning native image content."""

from __future__ import annotations

import mcp.types as mt
import pytest
from fastmcp import Client

from fakes import FakePlatform
from printguard.engine.engine import Engine
from printguard.server.api import ApiAuth, build_api_app
from printguard.server.mcp import build_mcp

READ_TOOLS = {
    "get_state",
    "list_monitors",
    "get_monitor",
    "list_printers",
    "get_printer",
    "list_cameras",
    "get_camera",
    "get_camera_frame",
    "get_monitor_history",
    "get_monitor_snapshot",
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
        assert (await mcp.get_tool("add_printer")).tags == {"manage"}
        assert (await mcp.get_tool("add_monitor")).tags == {"manage"}
        assert (await mcp.get_tool("get_camera_frame")).tags == {"read"}
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


async def test_unauthorised_control_call_is_denied() -> None:
    engine, mcp, _ = await _server()
    try:
        async with Client(mcp) as client:
            with pytest.raises(Exception):
                await client.call_tool("control_printer", {"printer_id": "x", "action": "pause"})
    finally:
        await engine.stop()
