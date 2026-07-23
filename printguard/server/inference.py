"""Selectable LiteRT and ONNX inference for the hub platform."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from typing import Literal

import numpy as np
import onnxruntime as ort
from ai_edge_litert.compiled_model import CompiledModel
from ai_edge_litert.hardware_accelerator import HardwareAccelerator
from ai_edge_litert.options import CpuOptions, Options

InferenceRuntime = Literal["auto", "litert", "onnx"]

BENCHMARK_RUNS = 10
PLUGIN_MODULES = ("onnxruntime_ep_nv_tensorrt_rtx", "onnxruntime_ep_openvino")
WINDOWS_PROVIDERS = {
    "MIGraphXExecutionProvider",
    "NvTensorRtRtxExecutionProvider",
    "OpenVINOExecutionProvider",
    "QNNExecutionProvider",
    "VitisAIExecutionProvider",
}
PROVIDER_LABELS = {
    "CoreMLExecutionProvider": "Apple Core ML",
    "MIGraphXExecutionProvider": "AMD GPU",
    "NvTensorRtRtxExecutionProvider": "NVIDIA GPU",
    "nv_tensorrt_rtx": "NVIDIA GPU",
    "OpenVINOExecutionProvider": "Intel OpenVINO",
    "QNNExecutionProvider": "Qualcomm NPU",
    "VitisAIExecutionProvider": "AMD NPU",
}
REGISTERED_LIBRARIES: set[str] = set()
logger = logging.getLogger(__name__)


def _register_library(name: str, path: str) -> None:
    if name not in REGISTERED_LIBRARIES:
        ort.register_execution_provider_library(name, path)
        REGISTERED_LIBRARIES.add(name)


class OnnxInference:
    """Runs the ONNX model through the fastest available execution provider."""

    runtime = "onnx"

    def __init__(self, model_path: Path, cache_dir: Path) -> None:
        self._resources = ExitStack()
        registered = self._register_plugins()
        if sys.platform == "win32":
            registered += self._register_windows_providers()

        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        if registered:
            options.set_provider_selection_policy(ort.OrtExecutionProviderDevicePolicy.MAX_PERFORMANCE)
            self._session = ort.InferenceSession(str(model_path), sess_options=options)
        elif "CoreMLExecutionProvider" in ort.get_available_providers():
            cache_dir.mkdir(parents=True, exist_ok=True)
            providers = [
                (
                    "CoreMLExecutionProvider",
                    {
                        "ModelFormat": "MLProgram",
                        "MLComputeUnits": "ALL",
                        "RequireStaticInputShapes": "1",
                        "ModelCacheDirectory": str(cache_dir),
                    },
                ),
                "CPUExecutionProvider",
            ]
            self._session = ort.InferenceSession(str(model_path), sess_options=options, providers=providers)
        else:
            self._session = ort.InferenceSession(
                str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
            )

        provider = next((name for name in self._session.get_providers() if name in PROVIDER_LABELS), None)
        self.device = PROVIDER_LABELS.get(provider, "ONNX CPU")
        self.workers = 2 if provider else max(1, (os.cpu_count() or 2) - 1)
        self._input_name = self._session.get_inputs()[0].name

    def _register_plugins(self) -> int:
        registered = 0
        for module_name in PLUGIN_MODULES:
            if importlib.util.find_spec(module_name) is None:
                continue
            module = importlib.import_module(module_name)
            _register_library(module_name, module.get_library_path())
            registered += 1
        return registered

    def _register_windows_providers(self) -> int:
        if sys.getwindowsversion().build < 26100:
            return 0
        from winui3.microsoft.windows.applicationmodel.dynamicdependency.bootstrap import InitializeOptions, initialize
        import winui3.microsoft.windows.ai.machinelearning as winml

        self._resources.enter_context(initialize(options=InitializeOptions.ON_NO_MATCH_SHOW_UI))
        providers = [
            provider
            for provider in winml.ExecutionProviderCatalog.get_default().find_all_providers()
            if provider.name in WINDOWS_PROVIDERS
        ]
        registered = 0
        for provider in providers:
            if provider.ready_state != winml.ExecutionProviderReadyState.READY:
                result = provider.ensure_ready_async().get()
                if result.status != winml.ExecutionProviderReadyResultState.SUCCESS:
                    continue
            _register_library(provider.name, provider.library_path)
            registered += 1
        return registered

    def _run(self, tensor: np.ndarray) -> np.ndarray:
        return self._session.run(None, {self._input_name: tensor})[0][0].copy()

    async def run(self, tensor: np.ndarray) -> np.ndarray:
        """Returns the model embedding for one preprocessed frame."""
        return await asyncio.to_thread(self._run, tensor)

    def benchmark(self) -> float:
        """Measures concurrent model throughput in inferences per second."""
        tensor = np.zeros((1, 3, 224, 224), dtype=np.float32)
        self._run(tensor)
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            list(pool.map(lambda _: [self._run(tensor) for _ in range(BENCHMARK_RUNS)], range(self.workers)))
        return self.workers * BENCHMARK_RUNS / (time.perf_counter() - started)

    def close(self) -> None:
        """Releases provider runtimes held for the session lifetime."""
        self._session = None
        self._resources.close()


class _LiteRtWorker:
    def __init__(self, model_path: Path, threads: int) -> None:
        options = Options(
            hardware_accelerators=HardwareAccelerator.CPU,
            cpu_options=CpuOptions(num_threads=threads),
        )
        self._model = CompiledModel.from_file(str(model_path), options=options)
        self._inputs = self._model.create_input_buffers(0)
        self._outputs = self._model.create_output_buffers(0)

    def run(self, tensor: np.ndarray) -> np.ndarray:
        self._inputs[0].write(tensor)
        self._model.run_by_index(0, self._inputs, self._outputs)
        return self._outputs[0].read(1024, np.float32)

    def close(self) -> None:
        for buffer in self._inputs + self._outputs:
            buffer.destroy()


class LiteRtInference:
    """Runs the LiteRT model through an optimised CPU worker pool."""

    runtime = "litert"
    device = "LiteRT CPU"

    def __init__(self, model_path: Path) -> None:
        cores = os.cpu_count() or 2
        self.workers = min(2, cores)
        threads = min(4, max(1, cores // self.workers))
        self._workers = [_LiteRtWorker(model_path, threads) for _ in range(self.workers)]
        self._available: asyncio.Queue[_LiteRtWorker] = asyncio.Queue()
        for worker in self._workers:
            self._available.put_nowait(worker)

    async def run(self, tensor: np.ndarray) -> np.ndarray:
        """Returns the model embedding for one preprocessed frame."""
        worker = await self._available.get()
        try:
            return await asyncio.to_thread(worker.run, tensor)
        finally:
            self._available.put_nowait(worker)

    def benchmark(self) -> float:
        """Measures concurrent model throughput in inferences per second."""
        tensor = np.zeros((1, 3, 224, 224), dtype=np.float32)
        for worker in self._workers:
            worker.run(tensor)
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            list(pool.map(lambda worker: [worker.run(tensor) for _ in range(BENCHMARK_RUNS)], self._workers))
        return self.workers * BENCHMARK_RUNS / (time.perf_counter() - started)

    def close(self) -> None:
        """Releases LiteRT models and tensor buffers."""
        for worker in self._workers:
            worker.close()


class Inference:
    """Selects and runs the requested model runtime."""

    def __init__(self, model_dir: Path, cache_dir: Path, runtime: InferenceRuntime) -> None:
        if runtime == "onnx":
            selected: OnnxInference | LiteRtInference = OnnxInference(model_dir / "encoder_float32.onnx", cache_dir)
        elif runtime == "litert":
            selected = LiteRtInference(model_dir / "encoder_float32.tflite")
        else:
            candidates: list[OnnxInference | LiteRtInference] = [
                OnnxInference(model_dir / "encoder_float32.onnx", cache_dir),
                LiteRtInference(model_dir / "encoder_float32.tflite"),
            ]
            scores = [candidate.benchmark() for candidate in candidates]
            logger.info(
                "automatic inference benchmark: %s",
                ", ".join(f"{candidate.device} {score:.1f} fps" for candidate, score in zip(candidates, scores)),
            )
            selected = candidates[scores.index(max(scores))]
            for candidate in candidates:
                if candidate is not selected:
                    candidate.close()
        self._selected = selected
        self.runtime = selected.runtime
        self.device = selected.device
        self.workers = selected.workers

    async def run(self, tensor: np.ndarray) -> np.ndarray:
        """Returns the model embedding for one preprocessed frame."""
        return await self._selected.run(tensor)

    def close(self) -> None:
        """Releases the selected model runtime."""
        self._selected.close()
