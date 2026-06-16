"""Model Context Protocol server for agents (hub mode only).

The tool set is derived from the REST API with FastMCP.from_fastapi, so agents
and developers share one definition that always tracks the engine protocol. The
only hand-written tool is the camera frame, because a JPEG response is returned
as native MCP image content rather than a binary body. Scope tags carried over
from the REST routes are enforced by an authorization middleware that hides and
blocks any tool the caller's token does not cover.
"""

from __future__ import annotations

import hmac
from importlib.metadata import version as package_version
from typing import Callable

from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, TokenVerifier, restrict_tag
from fastmcp.server.middleware import AuthMiddleware
from fastmcp.server.providers.openapi import MCPType, RouteMap
from fastmcp.utilities.types import Image
from starlette.applications import Starlette

from ..engine.engine import Engine
from .api import expand_scope

INSTRUCTIONS = (
    "Monitor and control 3D printers through PrintGuard. Read printer and camera "
    "status, fetch the current camera frame as an image to judge a print, and "
    "pause, resume or cancel a print through its linked service."
)


class ScopedTokenVerifier(TokenVerifier):
    """Validates static bearer tokens and returns the scopes they grant."""

    def __init__(self, tokens: dict[str, set[str]]) -> None:
        super().__init__()
        self._tokens = tokens

    async def verify_token(self, token: str) -> AccessToken | None:
        for known, scopes in self._tokens.items():
            if hmac.compare_digest(known, token):
                return AccessToken(token=token, client_id="printguard", scopes=sorted(scopes))
        return None


def build_mcp(
    api_app: FastAPI,
    get_engine: Callable[[], Engine],
    tokens: dict[str, str],
    internal_token: str,
) -> FastMCP:
    """Derives the MCP server from the REST app and adds the frame tool.

    Tokens, when configured, gate every tool; with none configured the server is
    open to whatever fronts it but exposes only read tools. The internal token
    authenticates the in-process loopback the derived tools use to reach the REST
    layer and is always granted full scope.
    """
    verifier: TokenVerifier | None = None
    if tokens:
        granted = {token: expand_scope(scope) for token, scope in tokens.items()}
        granted[internal_token] = expand_scope("manage")
        verifier = ScopedTokenVerifier(granted)

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
        auth=verifier,
        middleware=[
            AuthMiddleware(
                auth=[
                    restrict_tag("control", scopes=["control"]),
                    restrict_tag("manage", scopes=["manage"]),
                ]
            )
        ],
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
    tokens: dict[str, str],
    internal_token: str,
) -> Starlette:
    """Builds the mountable Streamable HTTP app exposing the MCP server."""
    mcp = build_mcp(api_app, get_engine, tokens, internal_token)
    return mcp.http_app(path="/")
