from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backends import ServerBackend

ROOT = Path(__file__).resolve().parent
MODELS_DIR = ROOT / "models"

app = FastAPI(title="PrintGuard POC")
backend = ServerBackend(MODELS_DIR)


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/infer")
async def infer(request: Request) -> dict:
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="empty body")
    arr = np.frombuffer(data, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise HTTPException(status_code=400, detail="could not decode image")
    return backend.infer(bgr)


app.mount("/models", StaticFiles(directory=MODELS_DIR), name="models")
app.mount("/static", StaticFiles(directory=ROOT), name="static")


@app.get("/app.py")
def app_py() -> FileResponse:
    return FileResponse(ROOT / "app.py", media_type="text/x-python", headers={"Cache-Control": "no-store"})


@app.get("/core.py")
def core_py() -> FileResponse:
    return FileResponse(ROOT / "core.py", media_type="text/x-python", headers={"Cache-Control": "no-store"})


@app.get("/pyscript.toml")
def pyscript_toml() -> FileResponse:
    return FileResponse(ROOT / "pyscript.toml", media_type="text/x-toml", headers={"Cache-Control": "no-store"})


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "main.html", headers={"Cache-Control": "no-store"})
