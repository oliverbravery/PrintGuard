"""Selectable LiteRT and ONNX inference for the hub platform."""

from __future__ import annotations

import asyncio
import ctypes
import importlib
import importlib.util
import logging
import os
import sys
import sysconfig
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from functools import partial
from pathlib import Path
from typing import Callable, Literal

import numpy as np
import onnxruntime as ort
from ai_edge_litert.interpreter import Interpreter

InferenceRuntime = Literal["auto", "litert", "onnx"]
Model = Callable[[np.ndarray], np.ndarray]

BENCHMARK_RUNS = 10
BENCHMARK_TENSOR = np.zeros((1, 3, 224, 224), dtype=np.float32)
SCALING_GAIN = 1.1
PLUGIN_MODULES = ("onnxruntime_ep_nv_tensorrt_rtx", "onnxruntime_ep_openvino")
CUDA_RUNTIME_LIBRARY = "nvidia/cuda_runtime/lib/libcudart.so.12"
WINDOWS_PROVIDERS = {
    "MIGraphXExecutionProvider",
    "NvTensorRtRtxExecutionProvider",
    "OpenVINOExecutionProvider",
    "QNNExecutionProvider",
    "VitisAIExecutionProvider",
}
DEFAULT_CPU_PROVIDER = "CPUExecutionProvider"
CORE_ML_PROVIDERS = [
    ("CoreMLExecutionProvider", {"ModelFormat": "MLProgram", "MLComputeUnits": "ALL", "RequireStaticInputShapes": "1"}),
    DEFAULT_CPU_PROVIDER,
]
DEVICE_PRIORITY = ("GPU", "NPU", "CPU")
SOFTWARE_ADAPTER = (0x1414, 0x8C)
REGISTERED_LIBRARIES: set[str] = set()
logger = logging.getLogger(__name__)


def _preload_cuda_runtime() -> None:
    """Loads the CUDA runtime that the TensorRT RTX provider library links against.

    The NVIDIA Container Toolkit injects the driver, not the runtime, and the wheel
    carrying `libcudart.so.12` installs it under site-packages where the dynamic linker
    does not look, so the provider library cannot open without it being loaded first.
    """
    library = Path(sysconfig.get_paths()["purelib"], CUDA_RUNTIME_LIBRARY)
    if library.exists():
        ctypes.CDLL(str(library), mode=ctypes.RTLD_GLOBAL)


def _register_library(name: str, path: str) -> bool:
    """Registers a provider library with ONNX Runtime, reporting whether it is usable.

    A provider whose libraries the host cannot supply, such as a GPU image started
    without the drivers passed through, leaves inference on the CPU rather than
    stopping PrintGuard from starting.
    """
    if name in REGISTERED_LIBRARIES:
        return True
    try:
        ort.register_execution_provider_library(name, path)
    except Exception as exc:
        logger.warning("execution provider %s is unavailable: %s", name, exc)
        return False
    REGISTERED_LIBRARIES.add(name)
    return True


def _device_rank(device: ort.OrtEpDevice) -> tuple[int, bool]:
    """Orders one provider device by the throughput its hardware can be expected to reach."""
    return DEVICE_PRIORITY.index(device.device.type.name), device.device.metadata.get("Discrete") != "1"


def _execution_devices(devices: list[ort.OrtEpDevice]) -> list[ort.OrtEpDevice]:
    """Returns the hardware the registered providers offer, fastest first.

    A provider registers one device per piece of hardware it can reach, so a GPU
    missing from this list is one the host's driver never handed to the provider,
    which is the difference between a GPU that is unusable and one that is merely
    slower. ONNX Runtime's own selection policies pick a device without saying which,
    and OpenVINO's meta devices choose again at inference time, so neither can name
    the hardware actually in use: the choice is made here instead, where it is named
    in the `compute` readout and in the log. Microsoft's Basic Render Driver is left
    out, since it is the software adapter Windows falls back to without a GPU driver
    and DirectML ends the process when a session is created on it.
    """
    return sorted(
        (
            device
            for device in devices
            if device.ep_name != DEFAULT_CPU_PROVIDER
            and "ov_meta_device" not in device.ep_metadata
            and (device.device.vendor_id, device.device.device_id) != SOFTWARE_ADAPTER
        ),
        key=_device_rank,
    )


def _device_label(device: ort.OrtEpDevice) -> str:
    """Names the hardware behind a provider device, for example `Intel GPU`."""
    return f"{device.ep_vendor} {device.device.type.name}"


def _throughput(model: Model, workers: int) -> float:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        if not all(np.isfinite(embedding).all() for embedding in pool.map(lambda _: model(BENCHMARK_TENSOR), range(workers))):
            raise ValueError("it returned a non-finite embedding")
        started = time.perf_counter()
        list(pool.map(lambda _: [model(BENCHMARK_TENSOR) for _ in range(BENCHMARK_RUNS)], range(workers)))
        elapsed = time.perf_counter() - started
    return workers * BENCHMARK_RUNS / elapsed


def _measure_concurrency(model: Model) -> tuple[int, float]:
    """Returns the worker count where throughput stops growing, and that throughput.

    Concurrency is measured rather than derived from the core count because how far
    a runtime scales depends on the execution provider, on whether its Python
    binding releases the GIL, and on any CPU quota the container is under. Doubling
    from one worker and stopping at the first step that fails to pay for itself
    lands on the host's real ceiling in a handful of measurements.
    """
    ceiling = os.cpu_count() or 2
    best, best_fps, workers = 1, 0.0, 1
    while True:
        fps = _throughput(model, workers)
        if fps < best_fps * SCALING_GAIN:
            return best, best_fps
        best, best_fps = workers, fps
        if workers >= ceiling:
            return best, best_fps
        workers = min(workers * 2, ceiling)


class OnnxInference:
    """Runs the ONNX model through the fastest execution provider that can run it.

    Every device the providers offer is tried, fastest first, and one that cannot
    build a session or get through the benchmark is skipped with a warning, ending
    on ONNX Runtime's own CPU provider. ONNX Runtime's own fallback is switched off
    while that is decided: it retries on the CPU in silence, which would leave the
    `compute` readout naming hardware the model never ran on.

    Core ML compiles the model on every session rather than into a cache directory.
    Its cache lookup builds the model URL with `NSURL URLWithString`, which yields
    nil for any path holding a space, so a cache under `~/Library/Application
    Support` fails every session it is meant to speed up - and the desktop app,
    which is where that path is used, could not start at all. Compiling costs
    about 0.2s per session.

    Attributes:
        device: Name of the hardware the model runs on.
        measured: Worker count the device sustains, and its throughput there.
        skipped: One message for each device that was offered and passed over.
    """

    runtime = "onnx"

    def __init__(self, model_path: Path) -> None:
        self.skipped: list[str] = []
        self._resources = ExitStack()
        self._model_path = str(model_path)
        self._register_plugins()
        if sys.platform == "win32":
            self._register_windows_providers()

        devices = _execution_devices(ort.get_ep_devices())
        accelerated = [(_device_label(device), partial(self._session_on, [device])) for device in devices]
        if devices:
            logger.info("execution providers offer: %s", ", ".join(label for label, _ in accelerated))
        elif "CoreMLExecutionProvider" in ort.get_available_providers():
            accelerated = [("Apple Core ML", partial(self._session_on, [], CORE_ML_PROVIDERS))]
        for label, build in accelerated:
            self.device = label
            try:
                self._benchmark(build())
                return
            except Exception as exc:
                self.skipped.append(f"{label} cannot run the model, so detection is not using it: {exc}")
        self.device = "ONNX CPU"
        self._benchmark(self._session_on([], [DEFAULT_CPU_PROVIDER]))

    def _session_on(
        self, devices: list[ort.OrtEpDevice], providers: list[str | tuple[str, dict[str, str]]] | None = None
    ) -> ort.InferenceSession:
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        if devices:
            options.add_provider_for_devices(devices, {})
        return ort.InferenceSession(self._model_path, sess_options=options, providers=providers, enable_fallback=0)

    def _benchmark(self, session: ort.InferenceSession) -> None:
        self._session = session
        self._input_name = session.get_inputs()[0].name
        self.measured = _measure_concurrency(self.run)
        session.enable_fallback()

    def _register_plugins(self) -> None:
        _preload_cuda_runtime()
        for module_name in PLUGIN_MODULES:
            if importlib.util.find_spec(module_name) is None:
                continue
            module = importlib.import_module(module_name)
            _register_library(module_name, module.get_library_path())

    def _register_windows_providers(self) -> None:
        if sys.getwindowsversion().build < 26100:
            return
        from winui3.microsoft.windows.applicationmodel.dynamicdependency.bootstrap import initialize
        import winui3.microsoft.windows.ai.machinelearning as winml

        try:
            self._resources.enter_context(initialize())
        except OSError as error:
            logger.warning("Windows ML is unavailable without the Windows App Runtime 2.x: %s", error)
            return
        try:
            providers = [
                provider
                for provider in winml.ExecutionProviderCatalog.get_default().find_all_providers()
                if provider.name in WINDOWS_PROVIDERS
            ]
        except Exception as error:
            logger.warning("Windows ML could not list its providers: %s", error)
            return
        for provider in providers:
            try:
                if provider.ready_state != winml.ExecutionProviderReadyState.READY:
                    result = provider.ensure_ready_async().get()
                    if result.status != winml.ExecutionProviderReadyResultState.SUCCESS:
                        continue
                library = provider.library_path
            except Exception as error:
                logger.warning("execution provider %s could not be installed: %s", provider.name, error)
                continue
            _register_library(provider.name, library)

    def run(self, tensor: np.ndarray) -> np.ndarray:
        """Returns the model embedding for one preprocessed frame."""
        return self._session.run(None, {self._input_name: tensor})[0][0].copy()

    def close(self) -> None:
        """Releases provider runtimes held for the session lifetime."""
        self._session = None
        self._resources.close()


class LiteRtInference:
    """Runs the LiteRT model on one single-threaded CPU interpreter per worker thread.

    `Interpreter.invoke` releases the GIL, so interpreters held per thread run
    genuinely in parallel; the `CompiledModel` API does not, and serialises every
    caller onto one core no matter how many workers are given to it.

    The model is handed over as bytes: given a path, LiteRT opens it through
    the ANSI code page on Windows and can fail under a user folder whose name
    is outside it.

    Attributes:
        measured: Worker count the processor sustains, and its throughput there.
    """

    runtime = "litert"
    device = "LiteRT CPU"
    skipped: list[str] = []

    def __init__(self, model_path: Path) -> None:
        self._model = model_path.read_bytes()
        self._interpreters = threading.local()
        probe = Interpreter(model_content=self._model, num_threads=1)
        self._input_index = probe.get_input_details()[0]["index"]
        self._output_index = probe.get_output_details()[0]["index"]
        self.measured = _measure_concurrency(self.run)

    def run(self, tensor: np.ndarray) -> np.ndarray:
        """Returns the model embedding for one preprocessed frame."""
        interpreter = getattr(self._interpreters, "interpreter", None)
        if interpreter is None:
            interpreter = Interpreter(model_content=self._model, num_threads=1)
            interpreter.allocate_tensors()
            self._interpreters.interpreter = interpreter
        interpreter.set_tensor(self._input_index, tensor)
        interpreter.invoke()
        return interpreter.get_tensor(self._output_index)[0].copy()

    def close(self) -> None:
        """Drops the per-thread interpreters."""
        self._interpreters = threading.local()


class Inference:
    """Runs the requested model runtime at the concurrency it measurably sustains.

    Attributes:
        skipped: One message for each accelerator that was offered and passed
            over, whichever runtime was chosen in the end.
    """

    def __init__(self, model_dir: Path, runtime: InferenceRuntime) -> None:
        candidates: list[OnnxInference | LiteRtInference] = []
        if runtime in ("auto", "onnx"):
            candidates.append(OnnxInference(model_dir / "encoder_float32.onnx"))
        if runtime in ("auto", "litert"):
            candidates.append(LiteRtInference(model_dir / "encoder_float32.tflite"))
        logger.info(
            "inference benchmark: %s",
            ", ".join(
                f"{candidate.device} {candidate.measured[1]:.1f} fps across {candidate.measured[0]} workers"
                for candidate in candidates
            ),
        )
        self.skipped = [message for candidate in candidates for message in candidate.skipped]
        selected = max(candidates, key=lambda candidate: candidate.measured[1])
        self.workers, self.capacity_fps = selected.measured
        for candidate in candidates:
            if candidate is not selected:
                candidate.close()
        self._selected = selected
        self.runtime = selected.runtime
        self.device = selected.device
        self._pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="inference")
        self._running = 0
        self._idle = asyncio.Event()
        self._idle.set()

    async def run(self, tensor: np.ndarray) -> np.ndarray:
        """Returns the model embedding for one preprocessed frame."""
        self._running += 1
        self._idle.clear()
        try:
            return await asyncio.get_running_loop().run_in_executor(self._pool, self._selected.run, tensor)
        finally:
            self._running -= 1
            if not self._running:
                self._idle.set()

    async def drained(self) -> None:
        """Waits until every frame sent to ``run`` has come back, so closing cannot cut one short."""
        await self._idle.wait()

    def close(self) -> None:
        """Releases the selected model runtime and its worker threads."""
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._selected.close()
