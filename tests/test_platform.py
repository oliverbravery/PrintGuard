"""Server platform model execution tests."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from printguard.engine import vision
from printguard.server.inference import (
    Inference,
    _device_label,
    _execution_devices,
    _measure_concurrency,
    _register_library,
)
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


async def test_runtimes_agree_on_classification() -> None:
    """Both runtimes carry the same model, so they must classify a frame the same way.

    Execution providers pick kernels for the hardware they land on, so the embeddings
    are held to the only agreement the detector depends on rather than to an
    elementwise tolerance. Every prototype distance moves by at most the distance
    between the two embeddings, so drift under half the margin cannot reach the
    nearest prototype of the other.
    """
    model_dir = Path("models")
    assets = vision.assets_from_dicts(
        json.loads((model_dir / "metadata.json").read_text()),
        json.loads((model_dir / "prototypes.json").read_text())["prototypes"],
    )
    tensor = np.random.default_rng(0).random((1, 3, 224, 224), dtype=np.float32)
    embeddings = []
    for runtime in ("litert", "onnx"):
        inference = Inference(model_dir, runtime)
        embeddings.append(await inference.run(tensor))
        inference.close()

    classifications = [vision.classify(embedding, assets) for embedding in embeddings]
    drift = float(np.linalg.norm(embeddings[0] - embeddings[1]))

    assert embeddings[0].shape == embeddings[1].shape == (1024,)
    assert classifications[0]["prediction"] == classifications[1]["prediction"]
    assert drift < min(result["margin"] for result in classifications) / 2


def _ep_device(ep_name: str, vendor: str, device_type: str, ep_metadata: dict[str, str]) -> SimpleNamespace:
    """Builds a stand-in for one device an ONNX Runtime provider offers."""
    return SimpleNamespace(
        ep_name=ep_name,
        ep_vendor=vendor,
        ep_metadata=ep_metadata,
        device=SimpleNamespace(type=SimpleNamespace(name=device_type), metadata={}),
    )


def test_the_accelerator_a_provider_offers_wins_and_is_the_one_named() -> None:
    """An Intel image with a working GPU must run on it, and say so.

    OpenVINO offers a CPU path under the same provider name as its GPU, so a GPU
    that the host's driver never handed over is indistinguishable from one in use
    unless the hardware behind the provider is what gets ranked and named. Its meta
    devices pick again at inference time, so neither can stand in for the GPU.
    """
    devices = [
        _ep_device("CPUExecutionProvider", "Microsoft", "CPU", {}),
        _ep_device("OpenVINOExecutionProvider", "Intel", "CPU", {"ov_device": "CPU"}),
        _ep_device("OpenVINOExecutionProvider.AUTO", "Intel", "GPU", {"ov_device": "GPU", "ov_meta_device": "AUTO"}),
        _ep_device("OpenVINOExecutionProvider", "Intel", "GPU", {"ov_device": "GPU"}),
    ]

    assert [_device_label(device) for device in _execution_devices(devices)] == ["Intel GPU", "Intel CPU"]


def test_provider_library_that_cannot_load_leaves_the_cpu(tmp_path: Path) -> None:
    """A GPU image whose provider libraries the host cannot supply must still start.

    The accelerated images carry a provider that needs libraries only the host can hand
    over, so any host without them, or any container started without GPU access, would
    otherwise take PrintGuard down at startup rather than watching printers on the CPU.
    """
    assert _register_library("printguard_test_provider", str(tmp_path / "libmissing.so")) is False


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


def test_the_state_file_is_readable_only_by_whoever_runs_the_hub(tmp_path) -> None:
    """It holds printer passwords, API token hashes and plugin credentials."""
    from printguard.server.platform import ServerPlatform

    holder = SimpleNamespace(_state_path=tmp_path / "state.json")
    ServerPlatform.save_state(holder, {"printers": [{"config": {"password": "hunter2"}}]})

    assert oct((tmp_path / "state.json").stat().st_mode)[-3:] == "600"
    assert not (tmp_path / "state.tmp").exists(), "the temporary file was left behind"
