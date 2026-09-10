"""Model Context Protocol server for agents (hub mode only).

The tool set is derived from the REST API with FastMCP.from_fastapi, so agents
and developers share one definition that always tracks the engine protocol. The
two image tools are hand-written because a binary body cannot be derived: the
camera frame returns a JPEG as native MCP image content, and classify takes an
image the caller supplies (base64) and returns the model's verdict. A single
authorization check resolves the caller's bearer token against the live,
UI-managed token set through the same ApiAuth the REST layer uses, hiding and
blocking any tool the caller's scope does not cover.
"""

from __future__ import annotations

import base64
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
    "camera status, fetch the current camera frame as an image to judge a print, "
    "classify a print image you supply for defects, pause, resume or cancel a "
    "print through its printer service, and start a sliced file from the print "
    "library on an idle printer it is tagged for."
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
            RouteMap(methods="*", pattern=r".*/classify$", mcp_type=MCPType.EXCLUDE),
            RouteMap(methods="*", pattern=r".*/file$", mcp_type=MCPType.EXCLUDE),
            RouteMap(methods=["POST"], pattern=r".*/prints$", mcp_type=MCPType.EXCLUDE),
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

    @mcp.tool(name="classify_frame", tags={"read"})
    async def classify_frame(image_base64: str, sensitivity: float = 1.0) -> dict:
        """Classifies a supplied print image for defects - no registered camera needed.

        Pass a base64-encoded JPEG or PNG frame (one shared in the conversation or
        downloaded) and get back {prediction, distances, margin, defect_score}: the
        same per-frame verdict the scheduler produces for a camera PrintGuard pulls
        itself. Use it to judge a still the model never captured directly.
        """
        try:
            return await get_engine().classify(base64.b64decode(image_base64), sensitivity)
        except (ValueError, RuntimeError) as exc:
            raise ToolError(f"could not classify image: {exc}")

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
