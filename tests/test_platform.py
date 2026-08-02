"""Server platform model execution tests."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from printguard.server.inference import Inference, _measure_concurrency
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


async def test_runtimes_agree_on_embedding(tmp_path: Path) -> None:
    """Both runtimes carry the same model, so they must embed a frame the same way."""
    tensor = np.random.default_rng(0).random((1, 3, 224, 224), dtype=np.float32)
    embeddings = []
    for runtime in ("litert", "onnx"):
        inference = Inference(Path("models"), tmp_path, runtime)
        embeddings.append(await inference.run(tensor))
        inference.close()

    assert embeddings[0].shape == embeddings[1].shape == (1024,)
    assert np.allclose(*embeddings, atol=1e-3)


def test_measured_concurrency_tracks_scaling() -> None:
    """Workers follow throughput a runtime actually adds, not the host's core count.

    A runtime whose binding holds the GIL gains nothing from a second worker and
    must be given one, however many cores the host has.
    """
    serialising = threading.Lock()

    def scales(tensor: np.ndarray) -> np.ndarray:
        time.sleep(0.002)
        return tensor

    def serialises(tensor: np.ndarray) -> np.ndarray:
        with serialising:
            time.sleep(0.002)
        return tensor

    assert _measure_concurrency(scales)[0] > 1
    assert _measure_concurrency(serialises)[0] == 1
