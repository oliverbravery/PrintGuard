import logging
from typing import Optional
from .inference_engine import UniversalInferenceEngine, InferenceBackend
import sys

_inference_engine: Optional[UniversalInferenceEngine] = None

try:
    import printguard.protonets as _pn
    sys.modules['protonets'] = _pn
except ImportError:
    pass


def _detect_backend() -> InferenceBackend:
    """Detect the best available backend based on installed packages.""" 
    # Check for ExecuTorch first (primary backend)
    try:
        import executorch
        logging.info("ExecuTorch detected, using ExecuTorch backend")
        return InferenceBackend.EXECUTORCH
    except ImportError:
        pass
    # Check for ONNX Runtime (optimized backend)
    try:
        import onnxruntime
        logging.info("ONNX Runtime detected, using ONNX Runtime backend")
        return InferenceBackend.ONNXRUNTIME
    except ImportError:
        pass
    # Check for PyTorch (fallback backend)
    try:
        import torch
        logging.info("PyTorch detected, using PyTorch backend")
        return InferenceBackend.PYTORCH
    except ImportError:
        pass
    logging.warning("No specific backend detected, defaulting to PyTorch")
    return InferenceBackend.PYTORCH


def get_inference_engine() -> UniversalInferenceEngine:
    """Get or create the global inference engine instance."""
    global _inference_engine
    if _inference_engine is None:
        backend = _detect_backend()
        _inference_engine = UniversalInferenceEngine(backend)
        logging.info(f"Created inference engine with {backend.value} backend")
    return _inference_engine
