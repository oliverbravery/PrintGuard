import json
import logging
import os
import pickle
from typing import Any, List, Tuple, Dict, Optional

import numpy as np

from .base_engine import BaseInferenceEngine

try:
    import onnxruntime as ort
except ImportError:
    ort = None
    logging.warning("ONNX Runtime not available. Install with: pip install onnxruntime")


class ONNXRuntimeInferenceEngine(BaseInferenceEngine):
    """ONNX Runtime-based inference engine implementation."""
    def __init__(self):
        """Initialize the ONNX Runtime engine."""
        if ort is None:
            raise ImportError(
                "ONNX Runtime is not available. Install with: pip install onnxruntime")
        self._session = None
        self._input_name = None
        self._output_name = None
        self._input_shape = None
        
    def load_model(self, model_path: str, options_path: str, device: str) -> Tuple[Any, List[int]]:
        """Load an ONNX model and its configuration options.

        Args:
            model_path: Path to the ONNX model file (.onnx)
            options_path: Path to the JSON options file
            device: Device to run inference on ('cpu', 'cuda', etc.)

        Returns:
            Tuple of (inference_session, input_dimensions)
        """
        with open(options_path, 'r', encoding='utf-8') as f:
            model_opt = json.load(f)
        x_dim = list(map(int, model_opt['model.x_dim'].split(',')))
        providers = self._get_execution_providers(device)
        session_options = ort.SessionOptions()
        session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        session_options.execution_mode = ort.ExecutionMode.ORT_PARALLEL
        try:
            self._session = ort.InferenceSession(
                model_path,
                sess_options=session_options,
                providers=providers
            )
            self._input_name = self._session.get_inputs()[0].name
            self._output_name = self._session.get_outputs()[0].name
            self._input_shape = self._session.get_inputs()[0].shape
            logging.info("ONNX model loaded successfully. Input: %s, Output: %s, Shape: %s",
                        self._input_name, self._output_name, self._input_shape)
            return self._session, x_dim
        except Exception as e:
            logging.error("Failed to load ONNX model from %s: %s", model_path, e)
            raise

    def _compute_prototype_from_embeddings(self, embeddings: Any) -> Any:
        """Compute a single prototype from a set of embeddings.
        
        Args:
            embeddings: Embeddings array for a single class
            
        Returns:
            Prototype array for the class
        """
        return np.mean(embeddings, axis=0)

    def _stack_prototypes(self, prototypes: List[Any]) -> Any:
        """Stack individual prototypes into a single structure.
        
        Args:
            prototypes: List of individual prototype arrays
            
        Returns:
            Stacked prototype array
        """
        return np.array(prototypes)

    def _copy_predictions(self, predictions: Any) -> Any:
        """Create a copy of predictions array."""
        return predictions.copy()

    def _get_prediction_at_index(self, predictions: Any, index: int) -> int:
        """Get prediction at a specific index."""
        return int(predictions[index])

    def _get_min_distance_at_index(self, distances: Any, index: int) -> float:
        """Get minimum distance for a specific sample."""
        return float(np.min(distances[index]))

    def _get_distance_to_class(self, distances: Any, sample_idx: int, class_idx: int) -> float:
        """Get distance from sample to specific class."""
        return float(distances[sample_idx, class_idx])

    def _set_prediction_at_index(self, predictions: Any, index: int, value: int) -> None:
        """Set prediction at a specific index."""
        predictions[index] = value

    def _is_empty_batch(self, batch_tensors: Any) -> bool:
        """Check if batch is empty (ONNX Runtime-specific)."""
        return len(batch_tensors) == 0

    def _compute_embeddings(self, model: Any, processed_images: List[Any], device: str) -> Any:
        """Compute embeddings for processed images using ONNX Runtime.
        
        Args:
            model: The ONNX inference session
            processed_images: List of processed image tensors
            device: Device to run computations on (for compatibility, not used in ONNX)
            
        Returns:
            Computed embeddings array
        """
        embeddings = []
        for tensor in processed_images:
            input_array = tensor.unsqueeze(0).cpu().numpy()
            embedding = self._run_inference(model, input_array)
            embeddings.append(embedding)
        return np.array(embeddings)

    def predict_batch(self, model: Any, batch_tensors: Any, prototypes: Any, 
                     defect_idx: int, sensitivity: float, device: str) -> List[int]:
        """Predict classes for a batch of image tensors using prototype matching.

        Args:
            model: The ONNX inference session
            batch_tensors: Batch of preprocessed image tensors (torch.Tensor or numpy.ndarray)
            prototypes: Class prototype arrays
            defect_idx: Index of the defect class for sensitivity adjustment
            sensitivity: Sensitivity multiplier for defect detection
            device: Device to run computations on (for compatibility, not used in ONNX)

        Returns:
            List of predicted class indices for each input
        """
        if not self._validate_batch_input(batch_tensors):
            return []
        if hasattr(batch_tensors, 'cpu'):
            batch_tensors = batch_tensors.cpu()
        if hasattr(batch_tensors, 'numpy'):
            batch_array = batch_tensors.numpy()
        else:
            batch_array = np.array(batch_tensors)
        if len(batch_array.shape) == 3:
            batch_array = np.expand_dims(batch_array, axis=0)
        embeddings = []
        for i in range(batch_array.shape[0]):
            input_array = batch_array[i:i+1]
            embedding = self._run_inference(model, input_array)
            embeddings.append(embedding)
        embeddings = np.array(embeddings)
        distances = np.linalg.norm(
            prototypes[:, np.newaxis, :] - embeddings[np.newaxis, :, :], axis=2).T
        initial_preds = np.argmin(distances, axis=1)
        final_preds = self._apply_sensitivity_adjustment(initial_preds,
                                                         distances,
                                                         defect_idx,
                                                         sensitivity)
        return [int(pred) for pred in final_preds]

    def setup_device(self, requested_device: str) -> str:
        """Set up the compute device based on availability and request.

        Args:
            requested_device: Requested device ('cuda', 'cpu', 'mps', etc.)

        Returns:
            The actual device string to use
        """
        available_providers = ort.get_available_providers()
        if requested_device == 'cuda' and 'CUDAExecutionProvider' in available_providers:
            device = 'cuda'
        elif requested_device == 'mps' and 'CoreMLExecutionProvider' in available_providers:
            device = 'mps'
        elif requested_device == 'cpu' or 'CPUExecutionProvider' in available_providers:
            device = 'cpu'
        else:
            device = 'cpu'
            if requested_device != 'cpu':
                logging.warning(
                    "%s requested but not available. Available providers: %s. Falling back to CPU.",
                    requested_device,
                    available_providers)
        logging.debug("Using device: %s", device)
        return device

    def _get_execution_providers(self, device: str) -> List[str]:
        """Get the appropriate execution providers for the requested device.

        Args:
            device: The requested device ('cpu', 'cuda', 'mps', etc.)

        Returns:
            List of execution providers in priority order
        """
        available_providers = ort.get_available_providers()
        providers = []
        if device == 'cuda' and 'CUDAExecutionProvider' in available_providers:
            providers.append('CUDAExecutionProvider')
        elif device == 'mps' and 'CoreMLExecutionProvider' in available_providers:
            providers.append('CoreMLExecutionProvider')
        if 'CPUExecutionProvider' in available_providers:
            providers.append('CPUExecutionProvider')
        if not providers:
            raise RuntimeError("No compatible execution providers available")
        logging.debug("Using execution providers: %s", providers)
        return providers

    def _run_inference(self, session: Any, input_array: np.ndarray) -> np.ndarray:
        """Run inference on the ONNX model.

        Args:
            session: The ONNX inference session
            input_array: Input array for inference

        Returns:
            The output embedding/features
        """
        try:
            outputs = session.run([self._output_name], {self._input_name: input_array})
            return outputs[0].flatten()
        except Exception as e:
            logging.error("Error during ONNX inference: %s", e)
            raise

    def _save_prototypes(self, prototypes: np.ndarray, class_names: List[str], 
                        defect_idx: int, cache_file: str) -> None:
        """Save computed prototypes to a cache file.

        Args:
            prototypes: The computed prototype arrays
            class_names: List of class names
            defect_idx: Index of the defect class
            cache_file: Path to save the cache file
        """
        try:
            cache_dir = os.path.dirname(cache_file)
            os.makedirs(cache_dir, exist_ok=True)
            cache_data = {
                'prototypes': prototypes,
                'class_names': class_names,
                'defect_idx': defect_idx
            }
            with open(cache_file, 'wb') as f:
                pickle.dump(cache_data, f)
            logging.debug("Prototypes saved to cache: %s", cache_file)
        except (OSError, pickle.PickleError) as e:
            logging.warning("Failed to save prototypes to cache: %s", e)

    def _load_prototypes(self, cache_file: str,
                         device: Optional[str] = None) -> Tuple[Optional[np.ndarray],
                                                                Optional[List[str]],
                                                                int]:
        """Load prototypes from a cache file.

        Args:
            cache_file: Path to the cache file
            device: Device to load tensors onto (for compatibility, not used in ONNX)

        Returns:
            Tuple of (prototypes, class_names, defect_idx) or (None, None, -1) if loading fails
        """
        try:
            if not os.path.exists(cache_file):
                return None, None, -1
            with open(cache_file, 'rb') as f:
                cache_data = pickle.load(f)
            prototypes = cache_data['prototypes']
            class_names = cache_data['class_names']
            defect_idx = cache_data['defect_idx']
            logging.debug("Prototypes loaded from cache: %s", cache_file)
            return prototypes, class_names, defect_idx
        except (OSError, pickle.PickleError, KeyError) as e:
            logging.warning("Failed to load prototypes from cache: %s", e)
            return None, None, -1

    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the loaded ONNX model.

        Returns:
            Dictionary containing model metadata
        """
        if self._session is None:
            return {"status": "No model loaded"}
        try:
            model_metadata = self._session.get_modelmeta()
            inputs = self._session.get_inputs()
            outputs = self._session.get_outputs()
            providers = self._session.get_providers()
            return {
                "status": "Model loaded",
                "model_version": model_metadata.version,
                "producer_name": model_metadata.producer_name,
                "domain": model_metadata.domain,
                "inputs": [{"name": inp.name,
                            "shape": inp.shape,
                            "type": inp.type} for inp in inputs],
                "outputs": [{"name": out.name,
                             "shape": out.shape,
                             "type": out.type} for out in outputs],
                "providers": providers
            }
        except Exception as e:
            return {"status": "Error getting model info", "error": str(e)}
