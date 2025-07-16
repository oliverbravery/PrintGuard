import json
import logging
import os
import hashlib
import pickle
import shutil
from typing import Any, List, Tuple

import torch
from PIL import Image
from torchvision import transforms

from ..inference_engine import InferenceEngine

try:
    import printguard.protonets as _pn
    import sys
    sys.modules['protonets'] = _pn
except ImportError:
    pass


class PyTorchInferenceEngine(InferenceEngine):
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
    
    def get_transform(self) -> Any:
        """Create the standard image preprocessing transform pipeline.

        Returns:
            Transform pipeline for preprocessing images
        """
        return transforms.Compose([
            transforms.Resize(256),
            transforms.Grayscale(num_output_channels=3),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])
    
    def compute_prototypes(self, model: Any, support_dir: str, transform: Any, 
                          device: str, success_label: str = "success", 
                          use_cache: bool = True) -> Tuple[Any, List[str], int]:
        """Compute class prototypes from support images.

        Args:
            model: The encoder model to use
            support_dir: Directory containing class subdirectories with support images
            transform: Image preprocessing transform
            device: Device to run computations on
            success_label: Label for the non-defective class
            use_cache: Whether to use cached prototypes if available

        Returns:
            Tuple of (prototypes, class_names, defect_idx)
        """
        device_obj = torch.device(device)
        cache_dir = os.path.join(support_dir, 'cache')
        if use_cache and os.path.exists(cache_dir):
            for filename in os.listdir(cache_dir):
                if filename.startswith("prototypes_") and filename.endswith(".pkl"):
                    cache_file = os.path.join(cache_dir, filename)
                    logging.debug("Attempting to load prototypes from cache: %s", cache_file)
                    prototypes, class_names, defect_idx = self._load_prototypes(cache_file, device_obj)
                    if prototypes is not None:
                        logging.debug("Successfully loaded prototypes from cache: %s", cache_file)
                        return prototypes, class_names, defect_idx
        logging.debug("Computing prototypes from scratch for support directory: %s", support_dir)
        support_dir_hash = self._get_support_dir_hash(support_dir)
        cache_file = os.path.join(cache_dir, f"prototypes_{support_dir_hash}.pkl")
        class_names = sorted([d for d in os.listdir(support_dir)
                             if os.path.isdir(os.path.join(support_dir, d)) 
                             and not d.startswith('.') and d != 'cache'])
        if not class_names:
            raise ValueError(f"No class subdirectories found in support directory: {support_dir}")
        prototypes = []
        loaded_class_names = []
        for cls in class_names:
            cls_dir = os.path.join(support_dir, cls)
            imgs = [os.path.join(cls_dir, f) for f in os.listdir(cls_dir) 
                   if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
            if not imgs:
                logging.warning("No images found for class '%s' in %s", cls, cls_dir)
                continue
            tensors = []
            for img_path in imgs:
                try:
                    img = Image.open(img_path).convert('RGB')
                    tensors.append(transform(img))
                except Exception as e:
                    logging.error("Error loading support image %s: %s", img_path, e)
            if not tensors:
                logging.warning("Could not load any valid images for class '%s'. Skipping this class.", cls)
                continue
            ts = torch.stack(tensors).to(device_obj)
            with torch.no_grad():
                emb = model.encoder(ts)
            prototype = emb.mean(0)
            prototypes.append(prototype)
            loaded_class_names.append(cls)
        if not prototypes:
            raise ValueError("Failed to build any prototypes from the support set.")
        prototypes = torch.stack(prototypes)
        logging.debug("Prototypes built for classes: %s", loaded_class_names)
        defect_idx = -1
        if success_label in loaded_class_names:
            try:
                defect_candidates = [i for i, name in enumerate(loaded_class_names) 
                                   if name != success_label]
                if len(defect_candidates) == 1:
                    defect_idx = defect_candidates[0]
                    logging.debug("Identified '%s' as the defect class (index %d).",
                                 loaded_class_names[defect_idx], defect_idx)
                elif len(defect_candidates) > 1:
                    logging.warning("Multiple non-'%s' classes found: %s. Sensitivity adjustment requires exactly one defect class. Adjustment disabled.",
                                   success_label, [loaded_class_names[i] for i in defect_candidates])
                else:
                    logging.warning("Only found the '%s' class. Cannot apply sensitivity adjustment.",
                                   success_label)
            except IndexError:
                logging.warning("Could not identify a distinct defect class, though '%s' was present. Sensitivity adjustment disabled.",
                               success_label)
        else:
            logging.warning("'%s' class not found in loaded support set %s. Cannot apply sensitivity adjustment.",
                           success_label, loaded_class_names)
        if use_cache:
            self._save_prototypes(prototypes, loaded_class_names, defect_idx, cache_file)
        return prototypes, loaded_class_names, defect_idx
    
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
        if batch_tensors is None or batch_tensors.shape[0] == 0:
            logging.warning("Received empty or invalid batch for prediction.")
            return []
        device_obj = torch.device(device)
        model.eval()
        with torch.no_grad():
            batch_x = batch_tensors.to(device_obj)
            batch_emb = model.encoder(batch_x)
            distances = torch.cdist(batch_emb, prototypes)
            min_dists, initial_preds = torch.min(distances, dim=1)
            final_preds = initial_preds.clone()
            for i in range(batch_emb.size(0)):
                if initial_preds[i] != defect_idx:
                    dist_to_defect = distances[i, defect_idx]
                    if dist_to_defect <= min_dists[i] * sensitivity:
                        final_preds[i] = defect_idx
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
    
    def clear_prototype_cache(self, support_dir: str) -> None:
        """Clear the prototype cache for a support directory.

        Args:
            support_dir: Path to the support directory whose cache should be cleared
        """
        cache_dir = os.path.join(support_dir, 'cache')
        if os.path.exists(cache_dir):
            try:
                shutil.rmtree(cache_dir)
                logging.debug("Prototype cache cleared for support directory: %s", support_dir)
            except OSError as e:
                logging.error("Failed to clear prototype cache: %s", e)
        else:
            logging.debug("No cache directory found for support directory: %s", support_dir)
    
    def _get_support_dir_hash(self, support_dir: str) -> str:
        """Generate a hash of the support directory contents for caching.

        Args:
            support_dir: Path to the support directory

        Returns:
            MD5 hash of the directory structure and file metadata
        """
        file_paths = []
        for root, dirs, files in os.walk(support_dir):
            dirs.sort()
            for file in sorted(files):
                if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                    file_path = os.path.join(root, file)
                    stat = os.stat(file_path)
                    file_paths.append(f"{file_path}:{stat.st_size}:{stat.st_mtime}")
        content = '\n'.join(file_paths)
        return hashlib.md5(content.encode()).hexdigest()
    
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
    
    def _load_prototypes(self, cache_file: str, device: torch.device) -> Tuple[Any, List[str], int]:
        """Load prototypes from a cache file.

        Args:
            cache_file: Path to the cache file
            device: Device to load tensors onto

        Returns:
            Tuple of (prototypes, class_names, defect_idx) or (None, None, None) if loading fails
        """
        try:
            if not os.path.exists(cache_file):
                return None, None, None
            with open(cache_file, 'rb') as f:
                cache_data = pickle.load(f)
            prototypes = cache_data['prototypes'].to(device)
            class_names = cache_data['class_names']
            defect_idx = cache_data['defect_idx']
            logging.debug("Prototypes loaded from cache: %s", cache_file)
            return prototypes, class_names, defect_idx
        except (OSError, pickle.PickleError, KeyError) as e:
            logging.warning("Failed to load prototypes from cache: %s", e)
            return None, None, None
