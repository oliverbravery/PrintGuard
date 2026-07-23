"""Server platform model execution tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest

from printguard.server.platform import ServerPlatform


@pytest.mark.parametrize("runtime", ["auto", "litert", "onnx"])
async def test_model_inference(tmp_path: Path, runtime: str) -> None:
    """Every selectable production model runtime loads and classifies."""
    platform = ServerPlatform(Path("models"), tmp_path, "http://localhost:9997", "rtsp://localhost:8554")
    await platform.configure({"inference_runtime": runtime})
    image = np.arange(240 * 320 * 3, dtype=np.uint8).reshape(240, 320, 3)

    results = await asyncio.gather(platform.infer(image), platform.infer(image))
    await platform.close()

    assert all(result["prediction"] == "success" for result in results)
    assert platform.inference_device
    assert platform.workers > 0
