"""Model Context Protocol server for agents.

The tool set is derived from the REST API with FastMCP.from_fastapi, so agents
and developers share one definition that always tracks the engine protocol. The
three image tools are hand-written because a binary body cannot be derived: the
camera frame and a monitor's alert snapshot return a JPEG as native MCP image
content, and classify takes an image the caller supplies (base64) and returns
the model's verdict. A single
authorization check resolves the caller's bearer token against the live,
UI-managed token set through the same ApiAuth the REST layer uses, hiding and
blocking any tool the caller's scope does not cover. The HTTP transport asks
the same question before a session opens, so once tokens exist a caller without
one is not told the server's name and version either.

A call the REST layer refuses is the caller's mistake and an ordinary tool
error, so it is logged here in one line and FastMCP is not left to print it a
traceback.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from contextlib import AsyncExitStack
from importlib.metadata import version as package_version
from typing import Any, Callable

import httpx
from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AuthContext
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import AuthMiddleware
from fastmcp.server.providers.openapi import MCPType, RouteMap
from fastmcp.utilities.types import Image
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..engine.engine import Engine
from .api import CLASSIFY_IN_FLIGHT, CLASSIFY_WAITING, MAX_FRAME_BYTES, ApiAuth, Busy, Turns, route_scope
from .events import require_finite

logger = logging.getLogger(__name__)

INSTRUCTIONS = (
    "Monitor and control 3D printers through PrintGuard. Read monitor, printer and "
    "camera status, fetch the current camera frame as an image to judge a print, "
    "classify a print image you supply for defects, pause, resume or cancel a "
    "print through its printer service, and start a sliced file from the print "
    "library on an idle printer it is tagged for."
)


async def refusal_as_tool_error(response: httpx.Response) -> None:
    """Turns an answer the REST layer refused a derived tool's call with into a tool error.

    Args:
        response: The loopback's answer.

    Raises:
        ToolError: If the status is an error, carrying the status and the
            reason the REST layer gave.
    """
    if not response.is_error:
        return
    await response.aread()
    logger.info("MCP tool call refused: %s %s answered %d", response.request.method, response.request.url.path, response.status_code)
    raise ToolError(f"HTTP error {response.status_code}: {response.text}", log_level=logging.DEBUG)


def build_mcp(
    api_app: FastAPI,
    get_engine: Callable[[], Engine],
    auth: ApiAuth,
    internal_token: str,
) -> FastMCP:
    """Derives the MCP server from the REST app and adds the image tools.

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
            RouteMap(methods="*", pattern=r".*/snapshots/[^/]+$", mcp_type=MCPType.EXCLUDE),
            RouteMap(methods="*", pattern=r".*/classify$", mcp_type=MCPType.EXCLUDE),
            RouteMap(methods="*", pattern=r".*/file$", mcp_type=MCPType.EXCLUDE),
            RouteMap(methods=["POST"], pattern=r".*/prints$", mcp_type=MCPType.EXCLUDE),
            RouteMap(methods="*", pattern=r".*", mcp_type=MCPType.TOOL),
        ],
        httpx_client_kwargs={
            "headers": {"Authorization": f"Bearer {internal_token}"},
            "event_hooks": {"response": [refusal_as_tool_error]},
        },
        middleware=[AuthMiddleware(auth=scope_check)],
    )

    @mcp.tool(name="get_camera_frame", tags={"read"})
    async def get_camera_frame(camera_id: str) -> Image:
        """Returns the freshest frame from a camera as an image of the print."""
        jpeg = await get_engine().snapshot(camera_id)
        if jpeg is None:
            raise ToolError(f"no frame available for camera {camera_id!r}")
        return Image(data=jpeg, format="jpeg")

    @mcp.tool(name="get_monitor_snapshot", tags={"read"})
    async def get_monitor_snapshot(monitor_id: str, snap_id: str) -> Image:
        """Returns a snapshot from a monitor's history as an image, by the id the history lists it under."""
        jpeg = await get_engine().monitor_snapshot(monitor_id, snap_id)
        if jpeg is None:
            raise ToolError(f"no snapshot {snap_id!r} for monitor {monitor_id!r}")
        return Image(data=jpeg, format="jpeg")

    @mcp.tool(name="classify_frame", tags={"read"})
    async def classify_frame(image_base64: str) -> dict:
        """Classifies a supplied print image for defects - no registered camera needed.

        Pass a base64-encoded JPEG or PNG frame (one shared in the conversation or
        downloaded) and get back {prediction, distances, margin, defect_score}: the
        same per-frame verdict the scheduler produces for a camera PrintGuard pulls
        itself. Use it to judge a still the model never captured directly.
        """
        if len(image_base64) * 3 // 4 > MAX_FRAME_BYTES:
            raise ToolError(f"could not classify image: it is over {MAX_FRAME_BYTES // 1024 // 1024} MB")
        try:
            async with api_app.state.classifying.turn():
                return await get_engine().classify(base64.b64decode(image_base64))
        except (ValueError, RuntimeError, Busy) as exc:
            raise ToolError(f"could not classify image: {exc}")

    return mcp


CALL_BYTES = 64 * 1024
"""Room for a tool call itself. A request larger than this can only be carrying an image to classify."""
MAX_BODY_BYTES = MAX_FRAME_BYTES * 4 // 3 + CALL_BYTES
"""The largest request the server reads: an image of ``MAX_FRAME_BYTES`` in base64, and the call around it."""


def non_finite_refusal(body: bytes) -> dict[str, Any] | None:
    """Writes the tool error that answers a tool call carrying NaN or Infinity.

    The transport reads either as a number and writes it on as null, which the
    REST layer takes for a field left out, so the call has to be refused from
    the body as it arrived.

    Args:
        body: A request body.

    Returns:
        The JSON-RPC answer, or None for a body that is not a tool call or
        holds only finite numbers.
    """
    try:
        call = json.loads(body)
    except (ValueError, RecursionError):
        return None
    if not isinstance(call, dict) or call.get("method") != "tools/call":
        return None
    try:
        require_finite(call)
    except ValueError as refused:
        return {"jsonrpc": "2.0", "id": call.get("id"), "result": {"content": [{"type": "text", "text": str(refused)}], "isError": True}}
    return None


class BearerGate:
    """Answers 401 to a request with no valid bearer once tokens exist, and 413 to a body over ``MAX_BODY_BYTES``.

    The tool filter alone lets such a caller open a session and read the
    server's name, version and instructions, with an empty tool list. The
    transport reads a whole body before it looks at it, so the size is held
    here, from the length a request declares and again as it arrives, since a
    chunked one declares none.

    A request over ``CALL_BYTES`` waits for a turn before the rest of it is
    read and keeps the turn until it is answered, so the images held at once
    are bounded as the REST route bounds them, and one that finds too many
    waiting is answered 503. A tool call carrying NaN or Infinity is answered
    here with a tool error.
    """

    def __init__(self, app: ASGIApp, auth: ApiAuth, get_engine: Callable[[], Engine]) -> None:
        self._app = app
        self._auth = auth
        self._get_engine = get_engine
        self._images = Turns(CLASSIFY_IN_FLIGHT, CLASSIFY_WAITING)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Passes a request on, or refuses one whose token resolves to nothing or whose body is too large."""
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if self._auth.resolve(headers.get("authorization"), self._get_engine().token_scopes()) is None:
            await JSONResponse({"detail": "missing or invalid token"}, 401, {"WWW-Authenticate": "Bearer"})(scope, receive, send)
            return
        too_large = JSONResponse({"detail": f"a request is at most {MAX_BODY_BYTES // 1024 // 1024} MB"}, 413)
        declared = headers.get("content-length", "")
        if declared.isdecimal() and int(declared) > MAX_BODY_BYTES:
            await too_large(scope, receive, send)
            return
        async with AsyncExitStack() as turn:
            body = bytearray()
            image = declared.isdecimal() and int(declared) > CALL_BYTES
            try:
                if image:
                    await turn.enter_async_context(self._images.turn())
                message = await receive()
                while message["type"] == "http.request":
                    body += message.get("body", b"")
                    if len(body) > MAX_BODY_BYTES:
                        await too_large(scope, receive, send)
                        return
                    if len(body) > CALL_BYTES and not image:
                        image = True
                        await turn.enter_async_context(self._images.turn())
                    if not message.get("more_body"):
                        message = {"type": "http.request", "body": bytes(body)}
                        break
                    message = await receive()
            except Busy as busy:
                await JSONResponse({"detail": str(busy)}, 503, {"Retry-After": "1"})(scope, receive, send)
                return
            if refusal := await asyncio.to_thread(non_finite_refusal, message.get("body", b"")):
                await JSONResponse(refusal)(scope, receive, send)
                return
            first: list[Message] = [message]

            async def replay() -> Message:
                return first.pop() if first else await receive()

            await self._app(scope, replay, send)


def build_mcp_app(
    api_app: FastAPI,
    get_engine: Callable[[], Engine],
    auth: ApiAuth,
    internal_token: str,
) -> Starlette:
    """Builds the mountable Streamable HTTP app exposing the MCP server."""
    mcp = build_mcp(api_app, get_engine, auth, internal_token)
    return mcp.http_app(path="/", middleware=[Middleware(BearerGate, auth=auth, get_engine=get_engine)])
