from __future__ import annotations

import asyncio
import json
from typing import Any

import numpy as np

import core

MODEL_BASE = "/models"
INPUT_SIZE = core.INPUT_SIZE

ASSETS: core.Assets | None = None
_MODEL: Any = None
_MODEL_URL: str | None = None


def _imagedata_to_rgb(data: Any) -> np.ndarray:
    buf = data.data.to_py()
    width = int(data.width)
    height = int(data.height)
    rgba = np.asarray(buf, dtype=np.uint8).reshape((height, width, 4))
    return rgba[..., :3]


async def _local_infer(frame_rgb: np.ndarray) -> dict[str, Any]:
    from js import Float32Array, Reflect, __litert, document
    from pyodide.ffi import to_js

    global _MODEL, _MODEL_URL
    pre = core.preprocess(frame_rgb)
    model_url = f"{document.location.origin}{MODEL_BASE}/encoder_float32.tflite"
    if _MODEL is None or _MODEL_URL != model_url:
        _MODEL = await __litert.loadAndCompile(model_url, {"accelerator": "wasm"})
        _MODEL_URL = model_url
    pre_list = to_js(pre.ravel().tolist())
    pre_arr = Float32Array.new(pre_list)
    shape = to_js([1, 3, INPUT_SIZE, INPUT_SIZE])
    tensor = Reflect.construct(__litert.Tensor, [pre_arr, shape])
    inputs = to_js([tensor])
    outputs = await _MODEL.run(inputs)
    emb = await outputs[0].data()
    tensor.delete()
    for o in outputs:
        o.delete()
    emb_arr = np.asarray(emb, dtype=np.float32)
    if not np.isfinite(emb_arr).all():
        return {"prediction": "unknown", "distances": [], "margin": 0.0}
    return core.classify(emb_arr, ASSETS.prototypes)


async def _hub_infer() -> dict[str, Any]:
    from js import document, window
    from pyodide.http import pyfetch

    blob = await window.__frameGrabber()
    buf = await blob.arrayBuffer()
    body = bytes(buf) if not hasattr(buf, "to_py") else bytes(buf.to_py())
    url = f"{document.location.origin}/infer"
    resp = await pyfetch(url, method="POST", headers={"Content-Type": "image/png"}, body=body)
    return json.loads(await resp.string())


def _get_mode() -> str:
    from js import document

    return document.getElementById("mode").value


def _set_mode(value: str) -> None:
    from js import localStorage

    localStorage.setItem("pg.mode", value)


def _restore_mode() -> None:
    from js import document, localStorage

    saved = localStorage.getItem("pg.mode")
    if saved in ("local", "hub"):
        document.getElementById("mode").value = saved


async def _grab_frame_rgb() -> np.ndarray:
    from js import window

    data = await window.__frameGrabberImageData()
    return _imagedata_to_rgb(data)


async def detect(event: Any) -> None:
    from js import console, document

    result_el = document.getElementById("result")
    result_el.innerText = "running…"
    try:
        mode = _get_mode()
        _set_mode(mode)
        console.log(f"[pg] detect mode={mode}")
        if mode == "local":
            rgb = await _grab_frame_rgb()
            out = await _local_infer(rgb)
        else:
            out = await _hub_infer()
        result_el.innerText = json.dumps(out, indent=2)
    except Exception as e:
        console.error(f"[pg] detect failed: {e}")
        result_el.innerText = f"error: {e}"


async def start_camera(event: Any) -> None:
    from js import document, navigator
    from pyodide.ffi import to_js

    stream = await navigator.mediaDevices.getUserMedia(to_js({"video": True, "audio": False}))
    video = document.getElementById("camera")
    video.srcObject = stream
    await video.play()


def _wire() -> None:
    from js import document
    from pyodide.ffi import create_proxy

    document.getElementById("detect-btn").addEventListener("click", create_proxy(detect))
    document.getElementById("start-btn").addEventListener("click", create_proxy(start_camera))


async def _init_assets() -> None:
    global ASSETS
    from js import document
    from pyodide.http import pyfetch

    base = f"{document.location.origin}{MODEL_BASE}"
    meta_resp = await pyfetch(f"{base}/metadata.json")
    proto_resp = await pyfetch(f"{base}/prototypes.json")
    meta = json.loads(await meta_resp.string())
    protos = json.loads(await proto_resp.string())["prototypes"]
    ASSETS = core.assets_from_dicts(meta, protos)
    core.initialise(ASSETS)


async def main() -> None:
    await _init_assets()
    _restore_mode()
    _wire()
    from js import document
    document.getElementById("result").innerText = "ready — start camera"


asyncio.ensure_future(main())
