"""Model Context Protocol server for agents (hub mode only).

The tool set is derived from the REST API with FastMCP.from_fastapi, so agents
and developers share one definition that always tracks the engine protocol. The
only hand-written tool is the camera frame, because a JPEG response is returned
as native MCP image content rather than a binary body. A single authorization
check resolves the caller's bearer token against the live, UI-managed token set
through the same ApiAuth the REST layer uses, hiding and blocking any tool the
caller's scope does not cover.
"""

from __future__ import annotations

from importlib.metadata import version as package_version
from typing import Callable

from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AuthContext
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import AuthMiddleware
from fastmcp.server.providers.openapi import MCPType, RouteMap
from fastmcp.utilities.types import Image
from starlette.applications import Starlette

from ..engine.engine import Engine
from .api import ApiAuth, route_scope

INSTRUCTIONS = (
    "Monitor and control 3D printers through PrintGuard. Read monitor, printer and "
    "camera status, fetch the current camera frame as an image to judge a print, and "
    "pause, resume or cancel a print through its printer service."
)


def build_mcp(
    api_app: FastAPI,
    get_engine: Callable[[], Engine],
    auth: ApiAuth,
    internal_token: str,
) -> FastMCP:
    """Derives the MCP server from the REST app and adds the frame tool.

    Each call resolves the caller's bearer token against the engine's current
    token set. With none issued the server is open to whatever fronts it but
    exposes only read tools; once tokens exist a valid bearer is required and the
    tool list is filtered to the scope it grants. The internal token authenticates
    the in-process loopback the derived tools use to reach the REST layer.
    """

    def scope_check(context: AuthContext) -> bool:
        header = get_http_headers(include={"Authorization"}).get("authorization")
        granted = auth.resolve(header, get_engine().token_scopes())
        if granted is None:
            return False
        return route_scope(list(context.component.tags)) in granted

    mcp = FastMCP.from_fastapi(
        api_app,
        name="PrintGuard",
        version=package_version("printguard"),
        instructions=INSTRUCTIONS,
        route_maps=[
            RouteMap(methods="*", pattern=r".*/frame$", mcp_type=MCPType.EXCLUDE),
            RouteMap(methods="*", pattern=r".*", mcp_type=MCPType.TOOL),
        ],
        httpx_client_kwargs={"headers": {"Authorization": f"Bearer {internal_token}"}},
        middleware=[AuthMiddleware(auth=scope_check)],
    )

    @mcp.tool(name="get_camera_frame", tags={"read"})
    async def get_camera_frame(camera_id: str) -> Image:
        """Returns the freshest frame from a camera as an image of the print."""
        jpeg = await get_engine().snapshot(camera_id)
        if jpeg is None:
            raise ToolError(f"no frame available for camera {camera_id!r}")
        return Image(data=jpeg, format="jpeg")

    return mcp


def build_mcp_app(
    api_app: FastAPI,
    get_engine: Callable[[], Engine],
    auth: ApiAuth,
    internal_token: str,
) -> Starlette:
    """Builds the mountable Streamable HTTP app exposing the MCP server."""
    mcp = build_mcp(api_app, get_engine, auth, internal_token)
    return mcp.http_app(path="/")
