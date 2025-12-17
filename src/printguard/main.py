"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .model import download_model, load_model
from .routes import router
from .webrtc import cleanup
from .tunnels import setup_active_tunnel


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Download model on startup if needed, then load it."""
    settings = get_settings()
    download_model()
    load_model()

    # Setup tunnel (only one will be activated)
    await setup_active_tunnel(app, settings)

    yield
    await cleanup()
    await cleanup()


app = FastAPI(
    title="PrintGuard API",
    description="Print defect detection API",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(router, prefix="/api")
