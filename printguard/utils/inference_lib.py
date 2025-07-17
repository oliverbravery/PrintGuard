import logging
from typing import Optional
from .inference_engine import UniversalInferenceEngine, InferenceBackend

_inference_engine: Optional[UniversalInferenceEngine] = None

def _detect_backend() -> InferenceBackend:
    """Detect the best available backend based on installed packages.""" 
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
    # pylint: disable=import-outside-toplevel
    from .model_downloader import ensure_model_files
    # pylint: disable=global-statement
    global _inference_engine
    if _inference_engine is None:
        backend = _detect_backend()
        try:
            if not ensure_model_files(backend):
                logging.warning("Failed to download model files for %s backend", backend.value)
        except ImportError:
            logging.warning("Model downloader not available, assuming models are present")
        _inference_engine = UniversalInferenceEngine(backend)
        logging.info("Created inference engine with %s backend", backend.value)
    return _inference_engine
