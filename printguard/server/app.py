"""FastAPI application: serves the UI, model assets and the engine socket.

The same image serves both modes — hub mode runs the engine here, while
local mode only needs the static UI, the model files and the Python
source archive that Pyodide unpacks in the browser.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

import printguard

from ..engine.engine import Engine
from ..pysrc import build_pysrc
from .api import ApiAuth, build_api_app, parse_tokens
from .mcp import build_mcp_app
from .platform import ServerPlatform
from .publish import ChunkStream, remux

PACKAGE_ROOT = Path(printguard.__file__).parent
REPO_ROOT = PACKAGE_ROOT.parent


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


def create_app() -> FastAPI:
    """Builds the application with the engine attached to its lifespan."""
    model_dir = Path(os.environ.get("MODEL_DIR", REPO_ROOT / "models"))
    data_dir = Path(os.environ.get("DATA_DIR", REPO_ROOT / "data"))
    static_dir = Path(os.environ.get("STATIC_DIR", REPO_ROOT / "web" / "dist"))
    mediamtx_api = os.environ.get("MEDIAMTX_API", "http://localhost:9997")
    mediamtx_rtsp = os.environ.get("MEDIAMTX_RTSP", "rtsp://localhost:8554").rstrip("/")
    mediamtx_hls = os.environ.get("MEDIAMTX_HLS", "http://localhost:8888")
    allowed_origins = {o.strip().rstrip("/") for o in os.environ.get("PRINTGUARD_ORIGINS", "").split(",") if o.strip()}
    api_tokens = parse_tokens(os.environ.get("PRINTGUARD_API_TOKENS", ""))
    internal_token = secrets.token_urlsafe(32)
    api_app = build_api_app(ApiAuth(api_tokens, internal_token))
    mcp_app = build_mcp_app(api_app, lambda: api_app.state.engine, api_tokens, internal_token)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        platform = ServerPlatform(model_dir, data_dir, mediamtx_api, mediamtx_rtsp)
        engine = Engine(platform)
        await engine.start()
        app.state.engine = engine
        api_app.state.engine = engine
        app.state.hls = httpx.AsyncClient(base_url=mediamtx_hls, timeout=httpx.Timeout(10.0, read=60.0))
        async with mcp_app.lifespan(app):
            yield
        await app.state.hls.aclose()
        await engine.stop()
        await platform.close()

    app = FastAPI(title="PrintGuard", lifespan=lifespan)
    pysrc = build_pysrc()

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        """Liveness probe."""
        return {"ok": True}

    @app.get("/pysrc.zip")
    def pysrc_zip() -> Response:
        """Serves the engine source archive consumed by local mode."""
        return Response(pysrc, media_type="application/zip", headers={"Cache-Control": "no-store"})

    @app.websocket("/api/ws")
    async def engine_socket(websocket: WebSocket) -> None:
        """Bridges one UI connection onto the engine protocol."""
        if not origin_allowed(websocket, allowed_origins):
            await websocket.close(code=1008, reason="origin not allowed")
            return
        await websocket.accept()
        engine: Engine = app.state.engine
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)

        def sink(event: dict) -> None:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

        async def pump() -> None:
            while True:
                await websocket.send_text(json.dumps(await queue.get()))

        engine.add_sink(sink)
        pump_task = asyncio.ensure_future(pump())
        try:
            while True:
                await engine.handle(json.loads(await websocket.receive_text()))
        except WebSocketDisconnect:
            pass
        finally:
            engine.remove_sink(sink)
            pump_task.cancel()

    @app.get("/hls/{path:path}")
    async def hls_proxy(path: str, request: Request) -> StreamingResponse:
        """Streams LL-HLS playlists and segments from MediaMTX through the hub's own port."""
        client: httpx.AsyncClient = app.state.hls
        upstream = await client.send(
            client.build_request("GET", f"/{path}", params=request.query_params), stream=True
        )
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
        if not re.fullmatch(r"[\w-]+", path) or not origin_allowed(websocket, allowed_origins):
            await websocket.close(code=1008, reason="invalid request")
            return
        await websocket.accept()
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
            if connected:
                await websocket.close(code=1011, reason=str(err)[:120])

    app.mount("/api/v1", api_app)
    app.mount("/mcp", mcp_app)
    app.mount("/models", StaticFiles(directory=model_dir), name="models")
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="ui")
    return app


def main() -> None:
    """Console entry point."""
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
