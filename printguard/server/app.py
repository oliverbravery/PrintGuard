"""FastAPI application: serves the UI, model assets and the engine socket.

The same image serves both modes — hub mode runs the engine here, while
local mode only needs the static UI, the model files and the Python
source archive that Pyodide unpacks in the browser.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

import printguard

from ..engine.engine import Engine
from .platform import ServerPlatform

PACKAGE_ROOT = Path(printguard.__file__).parent
REPO_ROOT = PACKAGE_ROOT.parent


def _build_pysrc() -> bytes:
    """Zips the shared and browser package source for Pyodide."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(PACKAGE_ROOT / "__init__.py", "printguard/__init__.py")
        for module_dir in ("engine", "browser"):
            for path in sorted((PACKAGE_ROOT / module_dir).rglob("*.py")):
                archive.write(path, f"printguard/{path.relative_to(PACKAGE_ROOT)}")
    return buffer.getvalue()


def create_app() -> FastAPI:
    """Builds the application with the engine attached to its lifespan."""
    model_dir = Path(os.environ.get("MODEL_DIR", REPO_ROOT / "models"))
    data_dir = Path(os.environ.get("DATA_DIR", REPO_ROOT / "data"))
    static_dir = Path(os.environ.get("STATIC_DIR", REPO_ROOT / "web" / "dist"))
    mediamtx_api = os.environ.get("MEDIAMTX_API", "http://localhost:9997")
    mediamtx_rtsp = os.environ.get("MEDIAMTX_RTSP", "rtsp://localhost:8554")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        platform = ServerPlatform(model_dir, data_dir, mediamtx_api, mediamtx_rtsp)
        engine = Engine(platform)
        await engine.start()
        app.state.engine = engine
        yield
        await engine.stop()
        await platform.close()

    app = FastAPI(title="PrintGuard", lifespan=lifespan)
    pysrc = _build_pysrc()

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

    app.mount("/models", StaticFiles(directory=model_dir), name="models")
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="ui")
    return app


def main() -> None:
    """Console entry point."""
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
