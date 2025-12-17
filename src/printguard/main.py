"""FastAPI application entry point."""

import asyncio

from contextlib import asynccontextmanager
from fastapi import FastAPI

from .core.config import get_settings
from .core.model import download_model, load_model
from .api.routes import router
from .services.webrtc import cleanup
from .services.tunnels import setup_active_tunnel


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Download model on startup if needed, then load it, sets up tunnel based on configuration and cleans up on shutdown."""
    settings = get_settings()
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
