import json
import logging
import os
import pickle
from typing import Any, List, Tuple

import torch

from .base_engine import BaseInferenceEngine

try:
    from . import protonets as _pn
    import sys
    sys.modules['protonets'] = _pn
except ImportError:
    pass

class PyTorchInferenceEngine(BaseInferenceEngine):
    """PyTorch-based inference engine implementation."""

    def load_model(self, model_path: str, options_path: str, device: str) -> Tuple[Any, List[int]]:
        """Load a PyTorch model and its configuration options.

        Args:
            model_path: Path to the saved model file
            options_path: Path to the JSON options file
            device: Device to load the model onto

        Returns:
            Tuple of (model, input_dimensions)
        """
        device_obj = torch.device(device)
        model = torch.load(model_path, map_location=device_obj, weights_only=False)
        model.eval()
        with open(options_path, 'r', encoding='utf-8') as f:
            model_opt = json.load(f)
        x_dim = list(map(int, model_opt['model.x_dim'].split(',')))
        return model, x_dim

    def _compute_prototype_from_embeddings(self, embeddings: Any) -> Any:
        """Compute a single prototype from a set of embeddings.
        
        Args:
            embeddings: Embeddings tensor for a single class
            
        Returns:
            Prototype tensor for the class
        """
        return embeddings.mean(0)

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
        return predictions.clone()

    def _get_prediction_at_index(self, predictions: Any, index: int) -> int:
        """Get prediction at a specific index."""
        return int(predictions[index])

    def _get_min_distance_at_index(self, distances: Any, index: int) -> float:
        """Get minimum distance for a specific sample."""
        return float(torch.min(distances[index]))

    def _get_distance_to_class(self, distances: Any, sample_idx: int, class_idx: int) -> float:
        """Get distance from sample to specific class."""
        return float(distances[sample_idx, class_idx])

    def _set_prediction_at_index(self, predictions: Any, index: int, value: int) -> None:
        """Set prediction at a specific index."""
        predictions[index] = value

    def _is_empty_batch(self, batch_tensors: Any) -> bool:
        """Check if batch is empty (PyTorch-specific)."""
        return batch_tensors.shape[0] == 0
    
    def _compute_embeddings(self, model: Any, processed_images: List[Any], device: str) -> Any:
        """Compute embeddings for processed images using PyTorch.
        
        Args:
            model: The PyTorch model
            processed_images: List of processed image tensors
            device: Device to run computations on
            
        Returns:
            Computed embeddings tensor
        """
        device_obj = torch.device(device)
        ts = torch.stack(processed_images).to(device_obj)
        with torch.no_grad():
            emb = model.encoder(ts)
        return emb
    
    def predict_batch(self, model: Any, batch_tensors: Any, prototypes: Any, 
                     defect_idx: int, sensitivity: float, device: str) -> List[int]:
        """Predict classes for a batch of image tensors using prototype matching.

        Args:
            model: The encoder model
            batch_tensors: Batch of preprocessed image tensors
            prototypes: Class prototype tensors
            defect_idx: Index of the defect class for sensitivity adjustment
            sensitivity: Sensitivity multiplier for defect detection
            device: Device to run computations on

        Returns:
            List of predicted class indices for each input
        """
        if not self._validate_batch_input(batch_tensors):
            return []
        device_obj = torch.device(device)
        model.eval()
        with torch.no_grad():
            batch_x = batch_tensors.to(device_obj)
            batch_emb = model.encoder(batch_x)
            distances = torch.cdist(batch_emb, prototypes)
            _, initial_preds = torch.min(distances, dim=1)
            final_preds = self._apply_sensitivity_adjustment(initial_preds, distances, defect_idx, sensitivity)
            return final_preds.cpu().tolist()

    def setup_device(self, requested_device: str) -> str:
        """Set up the compute device based on availability and request.

        Args:
            requested_device: Requested device ('cuda', 'mps', or 'cpu')

        Returns:
            The actual device string to use
        """
        if requested_device == 'cuda' and torch.cuda.is_available():
            device = 'cuda'
        elif requested_device == 'mps' and torch.backends.mps.is_available():
            device = 'mps'
        else:
            device = 'cpu'
            if requested_device != 'cpu':
                logging.warning("%s requested but not available. Falling back to CPU.", 
                               requested_device)
        logging.debug("Using device: %s", device)
        return device
    
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
            cache_data = {
                'prototypes': prototypes.cpu(),
                'class_names': class_names,
                'defect_idx': defect_idx
            }
            with open(cache_file, 'wb') as f:
                pickle.dump(cache_data, f)
            logging.debug("Prototypes saved to cache: %s", cache_file)
        except (OSError, pickle.PickleError) as e:
            logging.warning("Failed to save prototypes to cache: %s", e)
    
    def _load_prototypes(self, cache_file: str, device: str = None) -> Tuple[Any, List[str], int]:
        """Load prototypes from a cache file.

        Args:
            cache_file: Path to the cache file
            device: Device to load tensors onto

        Returns:
            Tuple of (prototypes, class_names, defect_idx) or (None, None, -1) if loading fails
        """
        try:
            if not os.path.exists(cache_file):
                return None, None, -1
            with open(cache_file, 'rb') as f:
                cache_data = pickle.load(f)
            if device is not None:
                device_obj = torch.device(device) if isinstance(device, str) else device
                prototypes = cache_data['prototypes'].to(device_obj)
            else:
                prototypes = cache_data['prototypes']
            class_names = cache_data['class_names']
            defect_idx = cache_data['defect_idx']
            logging.debug("Prototypes loaded from cache: %s", cache_file)
            return prototypes, class_names, defect_idx
        except (OSError, pickle.PickleError, KeyError) as e:
            logging.warning("Failed to load prototypes from cache: %s", e)
            return None, None, -1
