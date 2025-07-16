import json
import logging
import os
import pickle
from typing import Any, List, Tuple

import torch
import numpy as np

from .base_engine import BaseInferenceEngine

try:
    from executorch.runtime import Runtime, Verification
except ImportError:
    Runtime = None
    Verification = None
    logging.warning("ExecutorTorch runtime not available. Install with: pip install executorch")

class ExecutorTorchInferenceEngine(BaseInferenceEngine):
    """ExecutorTorch-based inference engine implementation for optimized edge inference."""
    def __init__(self):
        """Initialize the ExecutorTorch engine."""
        if Runtime is None:
            raise ImportError(
                "ExecutorTorch runtime is not available. Install with: pip install executorch")
        self._runtime = Runtime.get()
        self._program = None
        self._method = None
        self._input_shape = None

    def load_model(self, model_path: str, options_path: str, device: str) -> Tuple[Any, List[int]]:
        """Load an ExecutorTorch model (.pte file) and its configuration options.

        Args:
            model_path: Path to the ExecutorTorch model file (.pte)
            options_path: Path to the JSON options file
            device: Device to run inference on (note: ExecutorTorch handles device internally)

        Returns:
            Tuple of (program_method, input_dimensions)
        """
        try:
            with open(options_path, 'r', encoding='utf-8') as f:
                model_opt = json.load(f)
            x_dim = list(map(int, model_opt['model.x_dim'].split(',')))
            self._program = self._runtime.load_program(
                model_path,
                verification=Verification.Minimal
            )
            self._method = self._program.load_method("forward")
            self._input_shape = x_dim
            logging.info("ExecutorTorch model loaded successfully. Available methods: %s",
                        self._program.method_names)
            logging.debug("Model input dimensions: %s", x_dim)
            return self._method, x_dim
        except Exception as e:
            logging.error("Failed to load ExecutorTorch model from %s: %s", model_path, e)
            raise

    def _compute_prototype_from_embeddings(self, embeddings: Any) -> Any:
        """Compute a single prototype from a set of embeddings.
        
        Args:
            embeddings: Embeddings tensor for a single class
            
        Returns:
            Prototype tensor for the class
        """
        if isinstance(embeddings, torch.Tensor):
            return embeddings.mean(0)
        else:
            embeddings_tensor = torch.tensor(embeddings) if (
                not isinstance(embeddings, torch.Tensor)) else embeddings
            return embeddings_tensor.mean(0)

    def _stack_prototypes(self, prototypes: List[Any]) -> Any:
        """Stack individual prototypes into a single structure.
        
        Args:
            prototypes: List of individual prototype tensors
            
        Returns:
            Stacked prototype tensor
        """
        return torch.stack(prototypes)

    def _copy_predictions(self, predictions: Any) -> Any:
        """Create a copy of predictions tensor."""
        if isinstance(predictions, torch.Tensor):
            return predictions.clone()
        else:
            return torch.tensor(predictions).clone()

    def _get_prediction_at_index(self, predictions: Any, index: int) -> int:
        """Get prediction at a specific index."""
        if isinstance(predictions, torch.Tensor):
            return int(predictions[index])
        else:
            return int(predictions[index])

    def _get_min_distance_at_index(self, distances: Any, index: int) -> float:
        """Get minimum distance for a specific sample."""
        if isinstance(distances, torch.Tensor):
            return float(torch.min(distances[index]))
        else:
            return float(np.min(distances[index]))

    def _get_distance_to_class(self, distances: Any, sample_idx: int, class_idx: int) -> float:
        """Get distance from sample to specific class."""
        if isinstance(distances, torch.Tensor):
            return float(distances[sample_idx, class_idx])
        else:
            return float(distances[sample_idx, class_idx])

    def _set_prediction_at_index(self, predictions: Any, index: int, value: int) -> None:
        """Set prediction at a specific index."""
        if isinstance(predictions, torch.Tensor):
            predictions[index] = value
        else:
            predictions[index] = value

    def _is_empty_batch(self, batch_tensors: Any) -> bool:
        """Check if batch is empty (ExecutorTorch-specific)."""
        if isinstance(batch_tensors, torch.Tensor):
            return batch_tensors.shape[0] == 0
        elif isinstance(batch_tensors, (list, tuple)):
            return len(batch_tensors) == 0
        else:
            return batch_tensors is None

    def _compute_embeddings(self, model: Any, processed_images: List[Any], device: str) -> Any:
        """Compute embeddings for processed images using ExecutorTorch.
        
        Args:
            model: The ExecutorTorch method
            processed_images: List of processed image tensors
            device: Device to run computations on (handled internally by ExecutorTorch)
            
        Returns:
            Computed embeddings tensor
        """
        batch_tensor = torch.stack(processed_images)
        inputs = (batch_tensor,)
        outputs = model.execute(inputs)
        embeddings = outputs[0]
        if not isinstance(embeddings, torch.Tensor):
            embeddings = torch.tensor(embeddings)
        return embeddings

    def predict_batch(self, model: Any, batch_tensors: Any, prototypes: Any, 
                     defect_idx: int, sensitivity: float, device: str) -> List[int]:
        """Predict classes for a batch of image tensors using prototype matching.

        Args:
            model: The ExecutorTorch method
            batch_tensors: Batch of preprocessed image tensors
            prototypes: Class prototype tensors
            defect_idx: Index of the defect class for sensitivity adjustment
            sensitivity: Sensitivity multiplier for defect detection
            device: Device to run computations on (handled internally by ExecutorTorch)

        Returns:
            List of predicted class indices for each input
        """
        if not self._validate_batch_input(batch_tensors):
            return []
        try:
            if not isinstance(batch_tensors, torch.Tensor):
                batch_tensors = torch.tensor(batch_tensors)
            inputs = (batch_tensors,)
            outputs = model.execute(inputs)
            batch_emb = outputs[0]
            if not isinstance(batch_emb, torch.Tensor):
                batch_emb = torch.tensor(batch_emb)
            if not isinstance(prototypes, torch.Tensor):
                prototypes = torch.tensor(prototypes)
            distances = torch.cdist(batch_emb, prototypes)
            _, initial_preds = torch.min(distances, dim=1)
            final_preds = self._apply_sensitivity_adjustment(initial_preds,
                                                             distances,
                                                             defect_idx,
                                                             sensitivity)
            if isinstance(final_preds, torch.Tensor):
                return final_preds.tolist()
            else:
                return final_preds
        except Exception as e:
            logging.error("Error during ExecutorTorch batch prediction: %s", e)
            return []

    def setup_device(self, requested_device: str) -> str:
        """Set up the compute device for ExecutorTorch.
        
        Note: ExecutorTorch handles device selection internally based on the model compilation.
        This method provides compatibility with the interface but doesn't actively change devices.

        Args:
            requested_device: Requested device ('cuda', 'mps', or 'cpu')

        Returns:
            The device string (ExecutorTorch handles this internally)
        """
        logging.info("ExecutorTorch handles device selection internally. Requested: %s",
                     requested_device)
        return requested_device

    def _save_prototypes(self, prototypes: torch.Tensor, class_names: List[str],
                        defect_idx: int, cache_file: str) -> None:
        """Save computed prototypes to a cache file.

        Args:
            prototypes: The computed prototype tensors
            class_names: List of class names
            defect_idx: Index of the defect class
            cache_file: Path to save the cache file
        """
        try:
            cache_dir = os.path.dirname(cache_file)
            os.makedirs(cache_dir, exist_ok=True)
            prototypes_cpu = prototypes.cpu() if isinstance(prototypes,
                                                            torch.Tensor) else prototypes
            cache_data = {
                'prototypes': prototypes_cpu,
                'class_names': class_names,
                'defect_idx': defect_idx,
                'backend': 'executorch'
            }
            with open(cache_file, 'wb') as f:
                pickle.dump(cache_data, f)
            logging.debug("ExecutorTorch prototypes saved to cache: %s", cache_file)
        except (OSError, pickle.PickleError) as e:
            logging.warning("Failed to save ExecutorTorch prototypes to cache: %s", e)

    def _load_prototypes(self, cache_file: str, device: str = None) -> Tuple[Any, List[str], int]:
        """Load prototypes from a cache file.

        Args:
            cache_file: Path to the cache file
            device: Device to load tensors onto (optional for ExecutorTorch)

        Returns:
            Tuple of (prototypes, class_names, defect_idx) or (None, None, -1) if loading fails
        """
        try:
            if not os.path.exists(cache_file):
                return None, None, -1
            with open(cache_file, 'rb') as f:
                cache_data = pickle.load(f)
            if cache_data.get('backend') != 'executorch':
                logging.debug("Cache file %s is not from ExecutorTorch backend, skipping",
                              cache_file)
                return None, None, -1
            prototypes = cache_data['prototypes']
            class_names = cache_data['class_names']
            defect_idx = cache_data['defect_idx']
            if not isinstance(prototypes, torch.Tensor):
                prototypes = torch.tensor(prototypes)
            logging.debug("ExecutorTorch prototypes loaded from cache: %s", cache_file)
            return prototypes, class_names, defect_idx
        except (OSError, pickle.PickleError, KeyError) as e:
            logging.warning("Failed to load ExecutorTorch prototypes from cache: %s", e)
            return None, None, -1
