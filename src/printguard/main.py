"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .model import download_model, load_model
from .routes import router
from .webrtc import cleanup


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Download model on startup if needed, then load it."""
    download_model()
    load_model()
    yield
    await cleanup()


app = FastAPI(
    title="PrintGuard API",
    description="Print defect detection API",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(router, prefix="/api")
