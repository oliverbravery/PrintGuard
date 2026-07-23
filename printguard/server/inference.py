"""Hardware-accelerated ONNX inference for the hub platform."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import os
import sys
from contextlib import ExitStack
from pathlib import Path

import numpy as np
import onnxruntime as ort

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


def _register_library(name: str, path: str) -> None:
    if name not in REGISTERED_LIBRARIES:
        ort.register_execution_provider_library(name, path)
        REGISTERED_LIBRARIES.add(name)


class Inference:
    """Runs one ONNX model through the fastest available execution provider."""

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
        self.device = PROVIDER_LABELS.get(provider, "CPU")
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

    async def run(self, tensor: np.ndarray) -> np.ndarray:
        """Returns the model embedding for one preprocessed frame."""
        outputs = await asyncio.to_thread(self._session.run, None, {self._input_name: tensor})
        return outputs[0][0].copy()

    def close(self) -> None:
        """Releases provider runtimes held for the session lifetime."""
        self._session = None
        self._resources.close()
