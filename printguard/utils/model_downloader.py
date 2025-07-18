import os
import logging
from typing import Optional, Dict, Any
from pathlib import Path

from huggingface_hub import hf_hub_download

from .inference_lib import _detect_backend, InferenceBackend

class ModelDownloader:
    """Downloads models from Hugging Face Hub based on detected backend."""
    def __init__(self, model_repo: str = "oliverbravery/printguard"):
        """Initialize the model downloader.
        
        Args:
            model_repo: Hugging Face repository containing models
        """
        self.model_repo = model_repo
        self.base_dir = Path(__file__).parent.parent / "model"
        self.base_dir.mkdir(exist_ok=True)
        self.backend_files = {
            InferenceBackend.PYTORCH: {
                "model": "model.pt",
                "options": "opt.json",
                "prototypes": "prototypes.pkl"
            },
            InferenceBackend.ONNXRUNTIME: {
                "model": "model.onnx", 
                "options": "opt.json",
                "prototypes": "prototypes.pkl"
            }
        }

    def get_model_path(self, backend: Optional[InferenceBackend] = None) -> str:
        """Get the local path to the model file for the given backend.
        
        Args:
            backend: Backend to get model path for (auto-detected if None)
            
        Returns:
            Path to the model file
        """
        if backend is None:
            backend = _detect_backend()
        model_file = self.backend_files[backend]["model"]
        return str(self.base_dir / model_file)

    def get_options_path(self) -> str:
        """Get the local path to the model options file.
        
        Returns:
            Path to the options JSON file
        """
        return str(self.base_dir / "opt.json")

    def get_prototypes_path(self) -> str:
        """Get the local path to the prototypes cache directory.
        
        Returns:
            Path to the prototypes directory
        """
        return str(self.base_dir / "prototypes")

    def get_prototypes_cache_file(self) -> str:
        """Get the local path to the downloaded prototypes cache file.
        
        Returns:
            Path to the prototypes.pkl file
        """
        return str(self.base_dir / "prototypes" / "cache" / "prototypes.pkl")

    def _is_file_cached(self, file_path: str) -> bool:
        """Check if a file is already cached locally.
        
        Args:
            file_path: Path to the file to check
            
        Returns:
            True if file exists and is non-empty
        """
        return os.path.exists(file_path) and os.path.getsize(file_path) > 0

    def _download_file(self, filename: str, local_path: str) -> bool:
        """Download a file from Hugging Face Hub.
        
        Args:
            filename: Name of file in the repository
            local_path: Local path to save the file
            
        Returns:
            True if download was successful
        """
        try:
            logging.info("Downloading %s from %s", filename, self.model_repo)
            downloaded_path = hf_hub_download(
                repo_id=self.model_repo,
                filename=filename,
                local_dir=self.base_dir,
                local_dir_use_symlinks=False
            )
            if downloaded_path != local_path:
                os.rename(downloaded_path, local_path)
            logging.info("Successfully downloaded %s to %s", filename, local_path)
            return True
        except (OSError, ValueError, RuntimeError) as e:
            logging.error("Failed to download %s: %s", filename, e)
            return False

    def download_model(self,
                       backend: Optional[InferenceBackend] = None,
                       force: bool = False) -> bool:
        """Download the model file for the specified backend.
        
        Args:
            backend: Backend to download model for (auto-detected if None)
            force: Force download even if file exists
            
        Returns:
            True if model is available (cached or downloaded)
        """
        if backend is None:
            backend = _detect_backend()
        model_file = self.backend_files[backend]["model"]
        local_path = self.get_model_path(backend)
        if not force and self._is_file_cached(local_path):
            logging.info("Model %s already cached at %s", model_file, local_path)
            return True
        return self._download_file(model_file, local_path)

    def download_options(self, force: bool = False) -> bool:
        """Download the model options file.
        
        Args:
            force: Force download even if file exists
            
        Returns:
            True if options file is available (cached or downloaded)
        """
        local_path = self.get_options_path()
        if not force and self._is_file_cached(local_path):
            logging.info("Options file already cached at %s", local_path)
            return True
        return self._download_file("opt.json", local_path)

    def download_prototypes(self, force: bool = False) -> bool:
        """Download the cached prototypes file.
        
        Args:
            force: Force download even if file exists
            
        Returns:
            True if prototypes are available (cached or downloaded)
        """
        prototypes_dir = Path(self.get_prototypes_path())
        prototypes_dir.mkdir(parents=True, exist_ok=True)
        cache_dir = prototypes_dir / "cache"
        cache_dir.mkdir(exist_ok=True)
        local_path = self.get_prototypes_cache_file()
        if not force and self._is_file_cached(local_path):
            logging.info("Prototypes already cached at %s", local_path)
            return True
        return self._download_file("prototypes.pkl", local_path)

    def download_all(self,
                     backend: Optional[InferenceBackend] = None,
                     force: bool = False) -> bool:
        """Download all required files for the specified backend.
        
        Args:
            backend: Backend to download files for (auto-detected if None)
            force: Force download even if files exist
            
        Returns:
            True if all files are available
        """
        if backend is None:
            backend = _detect_backend()
        logging.info("Downloading all model files for %s backend", backend.value)
        success = True
        success &= self.download_model(backend, force)
        success &= self.download_options(force)
        success &= self.download_prototypes(force)
        if success:
            logging.info(
                "All model files successfully downloaded/cached for %s backend",
                backend.value)
        else:
            logging.error(
                "Failed to download some model files for %s backend",
                backend.value)
        return success

    def get_backend_info(self) -> Dict[str, Any]:
        """Get information about the detected backend and file availability.
        
        Returns:
            Dictionary with backend info and file status
        """
        backend = _detect_backend()
        info = {
            "detected_backend": backend.value,
            "model_repo": self.model_repo,
            "files": {}
        }
        model_path = self.get_model_path(backend)
        info["files"]["model"] = {
            "path": model_path,
            "exists": self._is_file_cached(model_path),
            "filename": self.backend_files[backend]["model"]
        }
        options_path = self.get_options_path()
        info["files"]["options"] = {
            "path": options_path,
            "exists": self._is_file_cached(options_path),
            "filename": "opt.json"
        }
        prototypes_file = self.get_prototypes_cache_file()
        info["files"]["prototypes"] = {
            "path": prototypes_file,
            "exists": self._is_file_cached(prototypes_file),
            "filename": "prototypes.pkl"
        }
        return info

_model_downloader: Optional[ModelDownloader] = None

def get_model_downloader() -> ModelDownloader:
    """Get the global model downloader instance."""
    # pylint: disable=global-statement
    global _model_downloader
    if _model_downloader is None:
        _model_downloader = ModelDownloader()
    return _model_downloader

def ensure_model_files(backend: Optional[InferenceBackend] = None) -> bool:
    """Ensure all required model files are available for the specified backend.
    
    Args:
        backend: Backend to ensure files for (auto-detected if None)
        
    Returns:
        True if all files are available
    """
    downloader = get_model_downloader()
    return downloader.download_all(backend)
