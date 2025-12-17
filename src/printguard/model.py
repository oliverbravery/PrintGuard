"""Model loading and state management."""

import json
import pickle

import onnxruntime as ort
from huggingface_hub import hf_hub_download

from .config import MODEL_DIR

REPO_ID = "oliverbravery/printguard"
FILES = ["model.onnx", "opt.json", "prototypes.pkl"]

_model_info: dict | None = None


def download_model(force: bool = False) -> None:
    """Download model files from HuggingFace if not present."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for filename in FILES:
        filepath = MODEL_DIR / filename
        if force or not filepath.exists():
            hf_hub_download(
                repo_id=REPO_ID,
                filename=filename,
                local_dir=MODEL_DIR,
                local_dir_use_symlinks=False
            )


def load_model() -> dict:
    """Load and return model info dict."""
    global _model_info
    if _model_info is not None:
        return _model_info
    session_options = ort.SessionOptions()
    session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    session = ort.InferenceSession(
        str(MODEL_DIR / "model.onnx"),
        sess_options=session_options,
        providers=['CPUExecutionProvider']
    )
    with open(MODEL_DIR / "opt.json") as f:
        options = json.load(f)
    with open(MODEL_DIR / "prototypes.pkl", "rb") as f:
        prototype_data = pickle.load(f)
    _model_info = {
        "session": session,
        "input_name": session.get_inputs()[0].name,
        "output_name": session.get_outputs()[0].name,
        "prototypes": prototype_data["prototypes"],
        "class_names": prototype_data["class_names"],
        "defect_idx": prototype_data["defect_idx"],
        "options": options,
    }
    return _model_info


def get_model() -> dict:
    """Get loaded model info."""
    if _model_info is None:
        raise RuntimeError("Model not loaded")
    return _model_info
