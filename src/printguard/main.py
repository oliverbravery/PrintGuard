"""FastAPI application entry point."""

import asyncio

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import os

from .core.config import get_settings
from .core.model import download_model, load_model
from .core.database import init_db
from .api.routes import router
from .services.webrtc import cleanup
from .services.tunnels import setup_active_tunnel


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Download model on startup if needed, then load it, sets up tunnel based on configuration and cleans up on shutdown."""
    settings = get_settings()
    # Initialize database
    await init_db()
    # Download PrintGuard model
    download_model()
    load_model()
    # Setup tunnel (only one will be activated)
    await setup_active_tunnel(app, settings)

    yield
    
    # Cleanup tunnel process if it exists
    if hasattr(app.state, "tunnel_process"):
        process = app.state.tunnel_process
        if process:
            print(f"Stopping tunnel process (PID: {process.pid})...")
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                process.kill()
    # Cleanup WebRTC resources
    await cleanup()


app = FastAPI(
    title="PrintGuard API",
    description="Print defect detection API",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(router, prefix="/api")

webui_dist = os.path.join(os.getcwd(), "webui", "dist")
if os.path.exists(webui_dist):
    app.mount("/", StaticFiles(directory=webui_dist, html=True), name="webui")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    """Handle validation errors gracefully, especially with binary/encrypted data."""
    details = []
    for error in exc.errors():
        if "input" in error and isinstance(error["input"], bytes):
            error["input"] = "<binary data>"
        details.append(error)
    return JSONResponse(
        status_code=422,
        content={"detail": details},
    )
