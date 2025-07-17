import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple
from enum import Enum

import cv2

class InferenceBackend(Enum):
    """Supported inference backends."""
    PYTORCH = "pytorch"
    ONNXRUNTIME = "onnxruntime"


class InferenceEngine(ABC):
    """Abstract base class for inference engines."""

    @abstractmethod
    def load_model(self, model_path: str, options_path: str, device: str) -> Tuple[Any, List[int]]:
        """Load a model and its configuration.
        
        Args:
            model_path: Path to the model file
            options_path: Path to the model options/config file
            device: Device to load the model on
            
        Returns:
            Tuple of (model, input_dimensions)
        """

    @abstractmethod
    def get_transform(self) -> Any:
        """Get the image preprocessing transform pipeline.
        
        Returns:
            Transform pipeline for preprocessing images
        """

    @abstractmethod
    def compute_prototypes(self, model: Any, support_dir: str, transform: Any,
                          device: str, success_label: str = "success",
                          use_cache: bool = True) -> Tuple[Any, List[str], int]:
        """Compute class prototypes from support images.
        
        Args:
            model: The loaded model
            support_dir: Directory containing class subdirectories with support images
            transform: Image preprocessing transform
            device: Device to run computations on
            success_label: Label for the non-defective class
            use_cache: Whether to use cached prototypes if available
            
        Returns:
            Tuple of (prototypes, class_names, defect_idx)
        """

    @abstractmethod
    def predict_batch(self, model: Any, batch_tensors: Any, prototypes: Any,
                     defect_idx: int, sensitivity: float, device: str) -> List[int]:
        """Predict classes for a batch of image tensors.
        
        Args:
            model: The loaded model
            batch_tensors: Batch of preprocessed image tensors
            prototypes: Class prototype tensors
            defect_idx: Index of the defect class for sensitivity adjustment
            sensitivity: Sensitivity multiplier for defect detection
            device: Device to run computations on
            
        Returns:
            List of predicted class indices
        """

    @abstractmethod
    def setup_device(self, requested_device: str) -> str:
        """Set up the compute device based on availability and request.
        
        Args:
            requested_device: Requested device ('cuda', 'mps', or 'cpu')
            
        Returns:
            The actual device string to use
        """

    @abstractmethod
    def clear_prototype_cache(self, support_dir: str) -> None:
        """Clear the prototype cache for a support directory.
        
        Args:
            support_dir: Path to the support directory whose cache should be cleared
        """

class UniversalInferenceEngine:
    """Universal inference engine that delegates to backend-specific engines."""
    def __init__(self, backend: InferenceBackend = InferenceBackend.PYTORCH):
        """Initialize the universal inference engine.
        
        Args:
            backend: The inference backend to use
        """
        self.backend = backend
        self._engine = self._create_engine(backend)

    def _create_engine(self, backend: InferenceBackend) -> InferenceEngine:
        """Create the appropriate backend engine.
        
        Args:
            backend: The inference backend to create
            
        Returns:
            The backend-specific inference engine
        """
        # pylint: disable=import-outside-toplevel
        if backend == InferenceBackend.PYTORCH:
            from .backends.pytorch_engine import PyTorchInferenceEngine
            return PyTorchInferenceEngine()
        elif backend == InferenceBackend.ONNXRUNTIME:
            from .backends.onnxruntime_engine import ONNXRuntimeInferenceEngine
            return ONNXRuntimeInferenceEngine()
        else:
            raise ValueError(f"Unsupported backend: {backend}")

    def load_model(self, model_path: str, options_path: str, device: str) -> Tuple[Any, List[int]]:
        """Load a model and its configuration."""
        return self._engine.load_model(model_path, options_path, device)

    def get_transform(self) -> Any:
        """Get the image preprocessing transform pipeline."""
        return self._engine.get_transform()

    def compute_prototypes(self, model: Any, support_dir: str, transform: Any,
                          device: str, success_label: str = "success",
                          use_cache: bool = True) -> Tuple[Any, List[str], int]:
        """Compute class prototypes from support images."""
        return self._engine.compute_prototypes(
            model, support_dir, transform, device, success_label, use_cache
        )

    def predict_batch(self, model: Any, batch_tensors: Any, prototypes: Any,
                     defect_idx: int, sensitivity: float, device: str) -> List[int]:
        """Predict classes for a batch of image tensors."""
        return self._engine.predict_batch(
            model, batch_tensors, prototypes, defect_idx, sensitivity, device
        )

    def setup_device(self, requested_device: str) -> str:
        """Set up the compute device based on availability and request."""
        return self._engine.setup_device(requested_device)

    def clear_prototype_cache(self, support_dir: str) -> None:
        """Clear the prototype cache for a support directory."""
        self._engine.clear_prototype_cache(support_dir)

    def draw_label(self, frame: Any, label: str, color: Tuple[int, int, int],
                   success_label: str = "success") -> Any:
        """Draw a detection label on an image frame.
        
        This is a common utility function that doesn't depend on the backend.
        
        Args:
            frame: The image frame to draw on
            label: The prediction label to display
            color: RGB color tuple for the label background
            success_label: Label considered as "success" (non-defective)
            
        Returns:
            The frame with the label drawn on it
        """
        # pylint: disable=E1101
        text = "non-defective" if label == success_label else "defect"
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 2
        thickness = 3
        try:
            text_size, _ = cv2.getTextSize(text, font, font_scale, thickness)
            text_w, text_h = text_size
            h, w, _ = frame.shape
            rect_start = (w - text_w - 40, h - text_h - 40)
            rect_end = (w - 20, h - 20)
            text_pos = (w - text_w - 30, h - 30)
            cv2.rectangle(frame, rect_start, rect_end, color, -1)
            cv2.putText(frame, text, text_pos, font, font_scale,
                        (255, 255, 255), thickness, cv2.LINE_AA)
        except Exception as e:
            logging.error("Error drawing label: %s. Frame shape: %s, Label: %s",
                         e, frame.shape, label)
        return frame

    def get_backend_info(self) -> Dict[str, Any]:
        """Get information about the current backend.
        
        Returns:
            Dictionary containing backend information
        """
        return {
            "backend": self.backend.value,
            "engine_class": self._engine.__class__.__name__,
            "available_devices": self._get_available_devices()
        }

    def _get_available_devices(self) -> List[str]:
        """Get list of available devices for the current backend."""
        devices = ["cpu"]
        if self.backend == InferenceBackend.PYTORCH:
            # pylint: disable=import-outside-toplevel
            import torch
            if torch.cuda.is_available():
                devices.append("cuda")
            if torch.backends.mps.is_available():
                devices.append("mps")
        elif self.backend == InferenceBackend.ONNXRUNTIME:
            # pylint: disable=import-outside-toplevel
            try:
                import onnxruntime as ort
                available_providers = ort.get_available_providers()
                if 'CUDAExecutionProvider' in available_providers:
                    devices.append("cuda")
                if 'CoreMLExecutionProvider' in available_providers:
                    devices.append("mps")
            except ImportError:
                pass
        return devices
