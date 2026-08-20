"""FastAPI application serving the UI, model assets and the engine socket.

The same image serves both modes - hub mode runs the engine here, while
local mode only needs the static UI, the model files and the Python
source archive that Pyodide unpacks in the browser.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import secrets
import time
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from string import Template
from typing import Any
from urllib.parse import urlsplit

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from starlette.requests import HTTPConnection
from starlette.types import Scope

import printguard

from ..engine import logs, oauth
from ..engine.engine import Engine
from ..pysrc import build_pysrc
from .api import ApiAuth, build_api_app
from .events import ConflatedEventQueue
from .mcp import build_mcp_app
from .mediamtx import EmbeddedMediaMTX
from .mqtt import MqttBridge
from .platform import ServerPlatform
from .publish import ChunkStream, remux

logger = logging.getLogger(__name__)

PACKAGE_ROOT = Path(printguard.__file__).parent
REPO_ROOT = PACKAGE_ROOT.parent
HLS_WARN_THROTTLE_S = 30.0
REVALIDATE_CACHE_CONTROL = "no-cache"
ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"


class WebStaticFiles(StaticFiles):
    """Serves the Vite shell with update-safe caching."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = ASSET_CACHE_CONTROL if path.startswith("assets/") else REVALIDATE_CACHE_CONTROL
        return response


def origin_allowed(websocket: WebSocket, allowed: set[str]) -> bool:
    """Rejects cross-site WebSocket handshakes the auth proxy cannot screen.

    Proxies in front of the hub authenticate the session cookie, which the
    browser attaches to any socket a page opens, so a logged-in user's other
    tabs could otherwise drive the engine and read its secrets. The browser
    sets Origin and the forwarded host itself and forbids pages from forging
    them, so a same-origin (or explicitly allow-listed) Origin is the gate.
    """
    origin = websocket.headers.get("origin")
    if not origin:
        return True
    if origin.rstrip("/") in allowed:
        return True
    host = websocket.headers.get("x-forwarded-host") or websocket.headers.get("host")
    return bool(host) and urlsplit(origin).netloc == host.split(",")[0].strip()


GATE_EXEMPT_PREFIXES = ("/api/health",)
GATE_CACHE_TTL_S = 10.0
PLUGIN_REQUEST_HEADERS = ("cookie", "authorization", "accept", "content-type", "x-forwarded-for", "user-agent")
PLUGIN_RESPONSE_HEADERS = ("set-cookie", "location", "cache-control")
PLUGIN_BODY_LIMIT = 64 * 1024
PLUGIN_PAGE_CSP = "sandbox allow-forms allow-scripts; frame-ancestors 'none'"
SIGN_IN_PAGE = Template("""<!doctype html>
<meta charset="utf-8">
<title>PrintGuard</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 15px/1.6 -apple-system, "Segoe UI", system-ui, sans-serif; margin: 0; display: grid; place-items: center; height: 100vh; }
</style>
<p>$message</p>
""")
"""A plugin's own pages are served into a sandboxed, opaque origin. They may
render and script themselves, but they are not the dashboard's origin, so they
cannot read its storage, and the engine socket's origin check turns them away."""


def plugin_request(connection: HTTPConnection, method: str, body: str | None = None) -> dict[str, Any]:
    """Describes a request for a plugin's route or gate handler.

    Args:
        connection: The request or the WebSocket handshake being described.
        method: Its HTTP method, which a handshake does not carry itself.
        body: The request body, for a route that is given one.
    """
    return {
        "method": method,
        "path": connection.url.path,
        "query": dict(connection.query_params),
        "headers": {k: v for k, v in connection.headers.items() if k.lower() in PLUGIN_REQUEST_HEADERS},
        "body": body,
    }


def create_app() -> FastAPI:
    """Builds the application with the engine attached to its lifespan."""
    logs.setup_from_env()
    model_dir = Path(os.environ.get("MODEL_DIR", REPO_ROOT / "models"))
    data_dir = Path(os.environ.get("DATA_DIR", REPO_ROOT / "data"))
    static_dir = Path(os.environ.get("STATIC_DIR", REPO_ROOT / "web" / "dist"))
    mediamtx_api = os.environ.get("MEDIAMTX_API", "http://localhost:9997")
    mediamtx_rtsp = os.environ.get("MEDIAMTX_RTSP", "rtsp://localhost:8554").rstrip("/")
    mediamtx_hls = os.environ.get("MEDIAMTX_HLS", "http://localhost:8888")
    mediamtx_binary = os.environ.get("MEDIAMTX_BINARY")
    mediamtx_config = os.environ.get("MEDIAMTX_CONFIG", str(REPO_ROOT / "mediamtx.yml"))
    update_asset = os.environ.get("UPDATE_ASSET") or None
    allowed_origins = {o.strip().rstrip("/") for o in os.environ.get("PRINTGUARD_ORIGINS", "").split(",") if o.strip()}
    internal_token = secrets.token_urlsafe(32)
    api_auth = ApiAuth(internal_token)
    api_app = build_api_app(api_auth)
    mcp_app = build_mcp_app(api_app, lambda: api_app.state.engine, api_auth, internal_token)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Brings the hub up, and unwinds whatever it got up however it ends.

        Startup can fail part way - a port already held, a model runtime that will
        not load - and the pieces already running have to come back down with it,
        or the streaming server outlives the hub and keeps its ports from the next
        one. A stack releases them in reverse, on that path as on a clean stop.
        """
        logger.info("hub starting (data=%s, models=%s, static=%s)", data_dir, model_dir, static_dir)
        async with AsyncExitStack() as resources:
            if mediamtx_binary and Path(mediamtx_binary).exists():
                streamer = EmbeddedMediaMTX(mediamtx_binary, mediamtx_config, mediamtx_api)
                await streamer.start()
                resources.push_async_callback(streamer.stop)
            else:
                logger.warning("no bundled MediaMTX binary (%r), expecting an external MediaMTX at %s", mediamtx_binary, mediamtx_api)
            platform = ServerPlatform(model_dir, data_dir, mediamtx_api, mediamtx_rtsp, update_asset)
            resources.push_async_callback(platform.close)
            engine = Engine(platform)
            await engine.start()
            resources.push_async_callback(engine.stop)
            app.state.engine = engine
            api_app.state.engine = engine
            app.state.hls = httpx.AsyncClient(base_url=mediamtx_hls, timeout=httpx.Timeout(10.0, read=60.0))
            resources.push_async_callback(app.state.hls.aclose)
            bridge = MqttBridge(engine, lambda: engine.settings.get("mqtt", {}))
            bridge.start()
            resources.push_async_callback(bridge.stop)
            await resources.enter_async_context(mcp_app.lifespan(app))
            yield
            logger.info("hub shutting down")

    app = FastAPI(title="PrintGuard", lifespan=lifespan)
    pysrc = build_pysrc()
    gate_cache: dict[tuple[str, ...], float] = {}

    async def gate_allows(request: Request) -> bool:
        """Asks a gating plugin whether a request may proceed.

        Answers are cached per credential and path for a few seconds so a
        dashboard polling HLS does not wake the sandbox on every segment.
        Refusals are never cached, so signing in takes effect at once.
        """
        runtime = app.state.engine.platform.plugin_runtime
        if runtime is None or request.url.path.startswith(GATE_EXEMPT_PREFIXES + runtime.gate_paths()):
            return True
        key = (request.headers.get("cookie", ""), request.headers.get("authorization", ""), request.method, request.url.path)
        if gate_cache.get(key, 0.0) > time.monotonic():
            return True
        verdict = await runtime.authorise(plugin_request(request, request.method))
        if verdict is None or verdict:
            gate_cache[key] = time.monotonic() + GATE_CACHE_TTL_S
            return True
        return False

    async def socket_allowed(websocket: WebSocket) -> bool:
        """Runs a gating plugin over a WebSocket handshake.

        HTTP middleware never sees these, so the sockets ask for themselves, the
        way they already check the request's origin.
        """
        runtime = app.state.engine.platform.plugin_runtime
        if runtime is None:
            return True
        return await runtime.authorise(plugin_request(websocket, "GET")) is not False

    @app.middleware("http")
    async def plugin_gate(request: Request, call_next):
        """Lets a plugin holding the gate permission refuse requests."""
        if await gate_allows(request):
            return await call_next(request)
        return Response("refused by a plugin", status_code=403)

    @app.api_route("/plugins/{plugin_id}/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def plugin_route(plugin_id: str, path: str, request: Request) -> Response:
        """Serves a plugin's own pages and endpoints from its sandbox."""
        runtime = app.state.engine.platform.plugin_runtime
        if runtime is None:
            raise HTTPException(404, "plugins are not running")
        body = (await request.body())[:PLUGIN_BODY_LIMIT].decode("utf-8", "replace")
        answer = await runtime.serve(plugin_id, plugin_request(request, request.method, body))
        if answer is None:
            raise HTTPException(404, f"plugin {plugin_id!r} serves no routes")
        headers = {k: str(v) for k, v in (answer.get("headers") or {}).items() if k.lower() in PLUGIN_RESPONSE_HEADERS}
        return Response(
            str(answer.get("body", "")),
            status_code=int(answer.get("status", 200)),
            media_type=str(answer.get("type", "text/plain")),
            headers={**headers, "Content-Security-Policy": PLUGIN_PAGE_CSP, "X-Content-Type-Options": "nosniff"},
        )

    @app.get(oauth.CALLBACK_PATH)
    async def oauth_callback(request: Request, code: str = "", state: str = "", error: str = "") -> Response:
        """Takes the user back from a provider a plugin sent them to."""
        if error or not code:
            return HTMLResponse(SIGN_IN_PAGE.substitute(message=html.escape(error or "no code came back")), status_code=400)
        try:
            name = await request.app.state.engine.finish_sign_in(state, code)
        except (PermissionError, RuntimeError) as exc:
            return HTMLResponse(SIGN_IN_PAGE.substitute(message=html.escape(str(exc))), status_code=403)
        if name is None:
            return HTMLResponse(SIGN_IN_PAGE.substitute(message="nothing was waiting for that sign-in"), status_code=404)
        return HTMLResponse(SIGN_IN_PAGE.substitute(message=f"{html.escape(name)} is connected. You can close this tab."))

    @app.get("/api/health")
    def health(response: Response) -> dict[str, bool | str]:
        """Reports hub readiness and the running version."""
        response.headers["Cache-Control"] = "no-store"
        return {"ok": True, "version": app.state.engine.platform.version}

    @app.get("/pysrc.zip")
    def pysrc_zip() -> Response:
        """Serves the engine source archive consumed by local mode."""
        return Response(pysrc, media_type="application/zip", headers={"Cache-Control": "no-store"})

    @app.websocket("/api/ws")
    async def engine_socket(websocket: WebSocket) -> None:
        """Bridges one UI connection onto the engine protocol."""
        if not origin_allowed(websocket, allowed_origins):
            logger.warning("rejected cross-origin engine socket (origin=%s)", websocket.headers.get("origin"))
            await websocket.close(code=1008, reason="origin not allowed")
            return
        if not await socket_allowed(websocket):
            await websocket.close(code=1008, reason="refused by a plugin")
            return
        await websocket.accept()
        logger.info("UI connected")
        engine: Engine = app.state.engine
        queue = ConflatedEventQueue()

        async def pump() -> None:
            while True:
                await websocket.send_text(json.dumps(await queue.get()))

        async def receive() -> None:
            while True:
                await engine.handle(json.loads(await websocket.receive_text()))

        engine.add_sink(queue.put)
        tasks = [asyncio.ensure_future(pump()), asyncio.ensure_future(receive())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except WebSocketDisconnect:
            pass
        finally:
            logger.info("UI disconnected")
            engine.remove_sink(queue.put)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    hls_warned_at = [0.0]

    @app.get("/hls/{path:path}")
    async def hls_proxy(path: str, request: Request) -> StreamingResponse:
        """Streams LL-HLS playlists and segments from MediaMTX through the hub's own port.

        An unreachable MediaMTX answers 502 with a throttled warning - the
        dashboard polls playlists every second, so letting the error escape
        would flood the log with one ASGI traceback per poll.

        A request from an opaque origin is refused. Plugin pages are served into
        one, and nothing else in a browser sends ``Origin: null``. Without this a
        plugin could serve itself a page that pulls the live feed.
        """
        if request.headers.get("origin") == "null":
            raise HTTPException(403, "camera streams are not served to sandboxed pages")
        await app.state.engine.platform.view_camera(path.split("/", 1)[0])
        client: httpx.AsyncClient = app.state.hls
        try:
            upstream = await client.send(
                client.build_request("GET", f"/{path}", params=request.query_params), stream=True
            )
        except httpx.TransportError as exc:
            if time.monotonic() - hls_warned_at[0] > HLS_WARN_THROTTLE_S:
                hls_warned_at[0] = time.monotonic()
                logger.warning("HLS upstream unreachable: %s", exc)
            raise HTTPException(502, "stream engine unreachable") from exc
        hop_by_hop = {"connection", "keep-alive", "transfer-encoding", "content-length"}
        headers = {k: v for k, v in upstream.headers.items() if k.lower() not in hop_by_hop}
        if headers.get("location", "").startswith("/"):
            headers["location"] = f"/hls{headers['location']}"
        return StreamingResponse(
            upstream.aiter_raw(), status_code=upstream.status_code, headers=headers,
            background=BackgroundTask(upstream.aclose),
        )

    @app.websocket("/api/publish/{path}")
    async def publish_socket(websocket: WebSocket, path: str) -> None:
        """Receives a browser camera recording and republishes it over RTSP."""
        if not re.fullmatch(r"[\w-]+", path) or not origin_allowed(websocket, allowed_origins) or not await socket_allowed(websocket):
            logger.warning("rejected publish socket (path=%r, origin=%s)", path, websocket.headers.get("origin"))
            await websocket.close(code=1008, reason="invalid request")
            return
        await websocket.accept()
        logger.info("camera publish started: %s", path)
        source = ChunkStream()
        pusher = asyncio.create_task(asyncio.to_thread(remux, source, f"{mediamtx_rtsp}/{path}"))
        connected = True
        try:
            while not pusher.done():
                source.feed(await websocket.receive_bytes())
        except WebSocketDisconnect:
            connected = False
        finally:
            source.feed(None)
        try:
            await pusher
        except Exception as err:
            logger.warning("camera publish %s failed: %s", path, err)
            if connected:
                await websocket.close(code=1011, reason=str(err)[:120])
        logger.info("camera publish ended: %s", path)

    app.mount("/api/v1", api_app)
    app.mount("/mcp", mcp_app)
    app.mount("/models", StaticFiles(directory=model_dir), name="models")
    if static_dir.is_dir():
        app.mount("/", WebStaticFiles(directory=static_dir, html=True), name="ui")
    return app


def main() -> None:
    """Console entry point.

    Uvicorn runs without its own logging config so its records propagate to
    the root handlers, and without access logs - per-request lines for the
    HLS polling would drown the tail that bug reports attach.
    """
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), log_config=None, access_log=False)


if __name__ == "__main__":
    main()
