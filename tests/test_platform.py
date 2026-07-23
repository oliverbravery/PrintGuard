"""Server platform model execution tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np

from printguard.server.platform import ServerPlatform


async def test_onnx_model_inference(tmp_path: Path) -> None:
    """The production model loads and classifies through ONNX Runtime."""
    platform = ServerPlatform(Path("models"), tmp_path, "http://localhost:9997", "rtsp://localhost:8554")
    image = np.arange(240 * 320 * 3, dtype=np.uint8).reshape(240, 320, 3)

    results = await asyncio.gather(platform.infer(image), platform.infer(image))
    await platform.close()

    assert all(result["prediction"] == "success" for result in results)
    assert platform.inference_device
    assert platform.workers > 0
