import hashlib
import logging
import os
import shutil
from abc import ABC, abstractmethod
from typing import Any, List, Optional, Tuple

from PIL import Image
from torchvision import transforms

from ..inference_engine import InferenceEngine


class BaseInferenceEngine(InferenceEngine, ABC):
    """Base class for inference engines with common functionality."""

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

    def _process_support_images(self,
                                support_dir: str,
                                transform: Any) -> Tuple[List[str], List[List[Any]]]:
        """Process support images from directory structure.
        
        Args:
            support_dir: Directory containing class subdirectories with support images
            transform: Image preprocessing transform
            
        Returns:
            Tuple of (class_names, processed_images_per_class)
        """
        class_names = sorted([d for d in os.listdir(support_dir)
                             if os.path.isdir(os.path.join(support_dir, d)) 
                             and not d.startswith('.') and d != 'cache'])
        if not class_names:
            raise ValueError(f"No class subdirectories found in support directory: {support_dir}")
        processed_images = []
        loaded_class_names = []
        for cls in class_names:
            cls_dir = os.path.join(support_dir, cls)
            imgs = [os.path.join(cls_dir, f) for f in os.listdir(cls_dir)
                   if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
            if not imgs:
                logging.warning("No images found for class '%s' in %s", cls, cls_dir)
                continue
            processed_tensors = []
            for img_path in imgs:
                try:
                    img = Image.open(img_path).convert('RGB')
                    processed_tensors.append(transform(img))
                except Exception as e:
                    logging.error("Error processing support image %s: %s", img_path, e)
            if not processed_tensors:
                logging.warning(
                    "Could not load any valid images for class '%s'. Skipping this class.",
                    cls)
                continue
            processed_images.append(processed_tensors)
            loaded_class_names.append(cls)
        if not processed_images:
            raise ValueError("Failed to process any support images from the support set.")
        return loaded_class_names, processed_images

    def _determine_defect_idx(self, class_names: List[str], success_label: str = "success") -> int:
        """Determine the defect class index based on class names.
        
        Args:
            class_names: List of class names
            success_label: Label for the non-defective class
            
        Returns:
            Index of the defect class, or -1 if not found/ambiguous
        """
        defect_idx = -1
        if success_label in class_names:
            try:
                defect_candidates = [i for i, name in enumerate(class_names)
                                   if name != success_label]
                if len(defect_candidates) == 1:
                    defect_idx = defect_candidates[0]
                    logging.debug("Identified '%s' as the defect class (index %d).",
                                 class_names[defect_idx], defect_idx)
                elif len(defect_candidates) > 1:
                    logging.warning(
                        "Multiple non-'%s' classes found: %s. Sensitivity adjustment requires exactly one defect class. Adjustment disabled.",
                        success_label,
                        [class_names[i] for i in defect_candidates])
                else:
                    logging.warning(
                        "Only found the '%s' class. Cannot apply sensitivity adjustment.",
                        success_label)
            except IndexError:
                logging.warning(
                    "Could not identify a distinct defect class, though '%s' was present. Sensitivity adjustment disabled.",
                    success_label)
        else:
            logging.warning(
                "'%s' class not found in loaded support set %s. Cannot apply sensitivity adjustment.",
                success_label, class_names)
        return defect_idx

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
        if use_cache:
            prototypes, class_names, defect_idx = self._load_prototypes_from_cache(
                support_dir,
                device)
            if prototypes is not None:
                return prototypes, class_names, defect_idx
        logging.debug("Computing prototypes from scratch for support directory: %s", support_dir)
        support_dir_hash = self._get_support_dir_hash(support_dir)
        cache_file = os.path.join(support_dir, 'cache', f"prototypes_{support_dir_hash}.pkl")
        class_names, processed_images = self._process_support_images(support_dir, transform)
        prototypes = []
        for class_tensors in processed_images:
            embeddings = self._compute_embeddings(model, class_tensors, device)
            prototype = self._compute_prototype_from_embeddings(embeddings)
            prototypes.append(prototype)
        prototypes = self._stack_prototypes(prototypes)
        logging.debug("Prototypes built for classes: %s", class_names)
        defect_idx = self._determine_defect_idx(class_names, success_label)
        if use_cache:
            self._save_prototypes(prototypes, class_names, defect_idx, cache_file)
        return prototypes, class_names, defect_idx

    @abstractmethod
    def _compute_prototype_from_embeddings(self, embeddings: Any) -> Any:
        """Compute a single prototype from a set of embeddings.
        
        Args:
            embeddings: Embeddings for a single class
            
        Returns:
            Prototype representation for the class
        """

    @abstractmethod
    def _stack_prototypes(self, prototypes: List[Any]) -> Any:
        """Stack individual prototypes into a single structure.
        
        Args:
            prototypes: List of individual prototype representations
            
        Returns:
            Stacked prototype structure
        """

    def _apply_sensitivity_adjustment(self, initial_preds: Any, distances: Any,
                                    defect_idx: int, sensitivity: float) -> Any:
        """Apply sensitivity adjustment to predictions.
        
        Args:
            initial_preds: Initial predictions (class indices)
            distances: Distance matrix between embeddings and prototypes
            defect_idx: Index of the defect class
            sensitivity: Sensitivity multiplier for defect detection
            
        Returns:
            Adjusted predictions
        """
        if defect_idx < 0:
            return initial_preds
        final_preds = self._copy_predictions(initial_preds)
        for i in range(len(initial_preds)):
            if self._get_prediction_at_index(initial_preds, i) != defect_idx:
                min_dist = self._get_min_distance_at_index(distances, i)
                dist_to_defect = self._get_distance_to_class(distances, i, defect_idx)
                if dist_to_defect <= min_dist * sensitivity:
                    self._set_prediction_at_index(final_preds, i, defect_idx)
        return final_preds

    @abstractmethod
    def _copy_predictions(self, predictions: Any) -> Any:
        """Create a copy of predictions array."""

    @abstractmethod
    def _get_prediction_at_index(self, predictions: Any, index: int) -> int:
        """Get prediction at a specific index."""

    @abstractmethod
    def _get_min_distance_at_index(self, distances: Any, index: int) -> float:
        """Get minimum distance for a specific sample."""

    @abstractmethod
    def _get_distance_to_class(self, distances: Any, sample_idx: int, class_idx: int) -> float:
        """Get distance from sample to specific class."""

    @abstractmethod
    def _set_prediction_at_index(self, predictions: Any, index: int, value: int) -> None:
        """Set prediction at a specific index."""

    def _validate_batch_input(self, batch_tensors: Any) -> bool:
        """Validate batch input for prediction.
        
        Args:
            batch_tensors: Batch input to validate
            
        Returns:
            True if valid, False otherwise
        """
        if batch_tensors is None:
            logging.warning("Received None batch for prediction.")
            return False
        if self._is_empty_batch(batch_tensors):
            logging.warning("Received empty batch for prediction.")
            return False
        return True

    @abstractmethod
    def _is_empty_batch(self, batch_tensors: Any) -> bool:
        """Check if batch is empty (backend-specific)."""

    @abstractmethod
    def _compute_embeddings(self, model: Any, processed_images: List[Any], device: str) -> Any:
        """Compute embeddings for processed images (backend-specific).
        
        Args:
            model: The loaded model
            processed_images: List of processed image tensors
            device: Device to run computations on
            
        Returns:
            Computed embeddings
        """

    @abstractmethod
    def _save_prototypes(self, prototypes: Any, class_names: List[str],
                        defect_idx: int, cache_file: str) -> None:
        """Save computed prototypes to a cache file (backend-specific).
        
        Args:
            prototypes: The computed prototypes
            class_names: List of class names
            defect_idx: Index of the defect class
            cache_file: Path to save the cache file
        """

    @abstractmethod
    def _load_prototypes(self,
                         cache_file: str,
                         device: Optional[str] = None) -> Tuple[Any, List[str], int]:
        """Load prototypes from a cache file (backend-specific).
        
        Args:
            cache_file: Path to the cache file
            device: Device to load tensors onto (if applicable)
            
        Returns:
            Tuple of (prototypes, class_names, defect_idx) or (None, None, -1) if loading fails
        """

    def _load_prototypes_from_cache(self,
                                    support_dir: str,
                                    device: Optional[str] = None) -> Tuple[Any, List[str], int]:
        """Try to load prototypes from cache.
        
        Args:
            support_dir: Support directory path
            device: Device to load tensors onto (if applicable)
            
        Returns:
            Tuple of (prototypes, class_names, defect_idx) or (None, None, -1) if not found
        """
        cache_dir = os.path.join(support_dir, 'cache')
        if not os.path.exists(cache_dir):
            return None, None, -1
        downloaded_prototypes_file = os.path.join(cache_dir, "prototypes.pkl")
        if os.path.exists(downloaded_prototypes_file):
            logging.debug(
                "Attempting to load prototypes from downloaded file: %s",
                downloaded_prototypes_file)
            prototypes, class_names, defect_idx = self._load_prototypes(
                downloaded_prototypes_file,
                device)
            if prototypes is not None:
                logging.debug(
                    "Successfully loaded prototypes from downloaded file: %s",
                    downloaded_prototypes_file)
                return prototypes, class_names, defect_idx
        for filename in os.listdir(cache_dir):
            if filename.startswith("prototypes_") and filename.endswith(".pkl"):
                cache_file = os.path.join(cache_dir, filename)
                logging.debug("Attempting to load prototypes from cache: %s", cache_file)
                prototypes, class_names, defect_idx = self._load_prototypes(cache_file, device)
                if prototypes is not None:
                    logging.debug("Successfully loaded prototypes from cache: %s", cache_file)
                    return prototypes, class_names, defect_idx
        return None, None, -1
