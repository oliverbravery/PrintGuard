"""Browser implementation of the platform contract for local mode.

Capture, model execution, JPEG encoding and storage are delegated to a
small JavaScript bridge (window.__pg); everything above this module is
shared with the server.
"""

from __future__ import annotations

import json as jsonlib
import time
from typing import Any

import numpy as np

from ..engine import vision
from ..engine.platform import Frame


def _imagedata_to_rgb(image_data: Any) -> np.ndarray:
    rgba = np.frombuffer(image_data.data.to_py(), dtype=np.uint8)
    return rgba.reshape((int(image_data.height), int(image_data.width), 4))[..., :3]


class BrowserSource:
    """Frame source backed by a getUserMedia stream held by the bridge."""

    def __init__(self, bridge: Any, camera_id: str, fps: float) -> None:
        self._bridge = bridge
        self._camera_id = camera_id
        self.fps = fps

    @property
    def online(self) -> bool:
        """Whether the underlying media track is still live."""
        return bool(self._bridge.isLive(self._camera_id))

    async def grab(self) -> Frame | None:
        """Draws the current video frame and converts it to RGB."""
        image_data = self._bridge.grab(self._camera_id)
        if image_data is None:
            return None
        return Frame(rgb=_imagedata_to_rgb(image_data), seq=float(image_data.seq), ts=time.time())

    def close(self) -> None:
        """Stops the media track."""
        self._bridge.closeCamera(self._camera_id)


class BrowserPlatform:
    """Local mode platform: LiteRT.js in WASM, cameras via getUserMedia."""

    mode = "local"
    workers = 1

    def __init__(self, bridge: Any, assets: vision.Assets) -> None:
        self._bridge = bridge
        self.assets = assets

    @classmethod
    async def create(cls, bridge: Any) -> "BrowserPlatform":
        """Fetches model companion data and builds the platform.

        Args:
            bridge: The window.__pg JavaScript bridge object.

        Returns:
            A ready BrowserPlatform.
        """
        from pyodide.http import pyfetch

        meta = jsonlib.loads(await (await pyfetch("models/metadata.json")).string())
        protos = jsonlib.loads(await (await pyfetch("models/prototypes.json")).string())["prototypes"]
        return cls(bridge, vision.assets_from_dicts(meta, protos))

    async def infer(self, rgb: np.ndarray) -> dict[str, Any]:
        """Preprocesses in numpy and runs the model through LiteRT.js."""
        from pyodide.ffi import to_js

        tensor = vision.preprocess(rgb, self.assets)
        output = await self._bridge.infer(to_js(tensor.tobytes()))
        embedding = np.frombuffer(output.to_py(), dtype=np.float32)
        return vision.classify(embedding, self.assets)

    async def discover_cameras(self) -> list[dict[str, Any]]:
        """Enumerates attachable video input devices."""
        sources = await self._bridge.discover()
        return [dict(s) for s in sources.to_py()]

    async def open_camera(self, camera_id: str, source: dict[str, Any]) -> BrowserSource:
        """Opens a getUserMedia stream and reads its native frame rate."""
        if source["kind"] != "device":
            raise ValueError(f"local mode cannot open source kind {source['kind']!r}")
        fps = float(await self._bridge.openCamera(camera_id, source["device_id"]))
        return BrowserSource(self._bridge, camera_id, max(1.0, min(60.0, fps or 15.0)))

    async def release_camera(self, camera_id: str, source: dict[str, Any]) -> None:
        """No external resources exist for browser cameras."""

    async def http(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        data: bytes | None = None,
        timeout: float = 10.0,
    ) -> tuple[int, Any]:
        """Performs an HTTP request with the browser's fetch."""
        import asyncio

        from pyodide.ffi import JsException
        from pyodide.http import pyfetch

        kwargs: dict[str, Any] = {"method": method, "headers": headers or {}}
        if json is not None:
            kwargs["headers"] = {**kwargs["headers"], "Content-Type": "application/json"}
            kwargs["body"] = jsonlib.dumps(json)
        elif data is not None:
            kwargs["body"] = data
        try:
            resp = await asyncio.wait_for(pyfetch(url, **kwargs), timeout)
        except (JsException, asyncio.TimeoutError) as exc:
            raise ConnectionError(f"could not reach {url} — unreachable, or CORS is not enabled on the target service") from exc
        text = await resp.string()
        try:
            return resp.status, jsonlib.loads(text)
        except ValueError:
            return resp.status, text

    async def encode_jpeg(self, rgb: np.ndarray) -> bytes | None:
        """Encodes a frame as JPEG through a canvas in the bridge."""
        from pyodide.ffi import to_js

        rgba = np.dstack([rgb, np.full(rgb.shape[:2], 255, dtype=np.uint8)])
        result = await self._bridge.jpegFromRgba(to_js(rgba.tobytes()), rgb.shape[1], rgb.shape[0])
        if result is None:
            return None
        return bytes(result.to_py())

    def load_state(self) -> dict[str, Any]:
        """Reads persisted engine state from localStorage."""
        raw = self._bridge.storageLoad()
        try:
            return jsonlib.loads(raw) if raw else {}
        except ValueError:
            return {}

    def save_state(self, state: dict[str, Any]) -> None:
        """Writes engine state to localStorage."""
        self._bridge.storageSave(jsonlib.dumps(state))
