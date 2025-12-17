"""Simple functions to download model files from HuggingFace."""

import os
from pathlib import Path
from huggingface_hub import hf_hub_download

REPO_ID = "oliverbravery/printguard"
DEFAULT_MODEL_DIR = Path(__file__).parent / "model"


def download_model(model_dir: str = None, force: bool = False) -> str:
    """Download the ONNX model from HuggingFace.
    
    Args:
        model_dir: Directory to save model (defaults to ./model)
        force: Force re-download even if file exists
        
    Returns:
        Path to the downloaded model file
    """
    model_dir = Path(model_dir) if model_dir else DEFAULT_MODEL_DIR
    model_dir.mkdir(parents=True, exist_ok=True)
    
    model_path = model_dir / "model.onnx"
    
    if not force and model_path.exists():
        return str(model_path)
    
    hf_hub_download(
        repo_id=REPO_ID,
        filename="model.onnx",
        local_dir=model_dir,
        local_dir_use_symlinks=False
    )
    
    return str(model_path)


def download_options(model_dir: str = None, force: bool = False) -> str:
    """Download the model options/config from HuggingFace.
    
    Args:
        model_dir: Directory to save options (defaults to ./model)
        force: Force re-download even if file exists
        
    Returns:
        Path to the downloaded options file
    """
    model_dir = Path(model_dir) if model_dir else DEFAULT_MODEL_DIR
    model_dir.mkdir(parents=True, exist_ok=True)
    
    options_path = model_dir / "opt.json"
    
    if not force and options_path.exists():
        return str(options_path)
    
    hf_hub_download(
        repo_id=REPO_ID,
        filename="opt.json",
        local_dir=model_dir,
        local_dir_use_symlinks=False
    )
    
    return str(options_path)


def download_prototypes(model_dir: str = None, force: bool = False) -> str:
    """Download pre-computed prototypes from HuggingFace.
    
    Args:
        model_dir: Directory to save prototypes (defaults to ./model)
        force: Force re-download even if file exists
        
    Returns:
        Path to the downloaded prototypes file
    """
    model_dir = Path(model_dir) if model_dir else DEFAULT_MODEL_DIR
    model_dir.mkdir(parents=True, exist_ok=True)
    
    prototypes_path = model_dir / "prototypes.pkl"
    
    if not force and prototypes_path.exists():
        return str(prototypes_path)
    
    hf_hub_download(
        repo_id=REPO_ID,
        filename="prototypes.pkl",
        local_dir=model_dir,
        local_dir_use_symlinks=False
    )
    
    return str(prototypes_path)


def download_all(model_dir: str = None, force: bool = False) -> dict:
    """Download all required model files from HuggingFace.
    
    Args:
        model_dir: Directory to save files (defaults to ./model)
        force: Force re-download even if files exist
        
    Returns:
        Dictionary with paths to all downloaded files
    """
    return {
        "model": download_model(model_dir, force),
        "options": download_options(model_dir, force),
        "prototypes": download_prototypes(model_dir, force),
    }
