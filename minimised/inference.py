"""Simple inference functions using ONNX Runtime."""

import json
import pickle
from pathlib import Path
from typing import Tuple, List, Union

import numpy as np
import onnxruntime as ort
from PIL import Image
from torchvision import transforms

from .download import download_all, DEFAULT_MODEL_DIR


def get_transform():
    """Get the image preprocessing transform.
    
    Returns:
        torchvision transform pipeline
    """
    return transforms.Compose([
        transforms.Resize(256),
        transforms.Grayscale(num_output_channels=3),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    ])


def preprocess_image(image: Union[str, Image.Image, np.ndarray]) -> np.ndarray:
    """Preprocess an image for inference.
    
    Args:
        image: Path to image, PIL Image, or numpy array
        
    Returns:
        Preprocessed image as numpy array ready for inference
    """
    transform = get_transform()
    
    if isinstance(image, str):
        image = Image.open(image).convert('RGB')
    elif isinstance(image, np.ndarray):
        image = Image.fromarray(image).convert('RGB')
    elif isinstance(image, Image.Image):
        image = image.convert('RGB')
    
    tensor = transform(image)
    return tensor.unsqueeze(0).numpy()


def load_model(model_dir: str = None, auto_download: bool = True) -> Tuple[ort.InferenceSession, dict]:
    """Load the ONNX model.
    
    Args:
        model_dir: Directory containing model files
        auto_download: Automatically download model if not found
        
    Returns:
        Tuple of (ONNX session, model info dict)
    """
    model_dir = Path(model_dir) if model_dir else DEFAULT_MODEL_DIR
    
    model_path = model_dir / "model.onnx"
    options_path = model_dir / "opt.json"
    prototypes_path = model_dir / "prototypes.pkl"
    
    # Download if needed
    if auto_download and not model_path.exists():
        download_all(str(model_dir))
    
    # Load ONNX model
    session_options = ort.SessionOptions()
    session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    
    session = ort.InferenceSession(
        str(model_path),
        sess_options=session_options,
        providers=['CPUExecutionProvider']
    )
    
    # Load options
    with open(options_path, 'r') as f:
        options = json.load(f)
    
    # Load prototypes
    with open(prototypes_path, 'rb') as f:
        prototype_data = pickle.load(f)
    
    model_info = {
        "session": session,
        "input_name": session.get_inputs()[0].name,
        "output_name": session.get_outputs()[0].name,
        "prototypes": prototype_data["prototypes"],
        "class_names": prototype_data["class_names"],
        "defect_idx": prototype_data["defect_idx"],
        "options": options,
    }
    
    return session, model_info


def get_embedding(session: ort.InferenceSession, image_array: np.ndarray, 
                  input_name: str, output_name: str) -> np.ndarray:
    """Get embedding for a preprocessed image.
    
    Args:
        session: ONNX inference session
        image_array: Preprocessed image array
        input_name: Model input name
        output_name: Model output name
        
    Returns:
        Embedding vector
    """
    outputs = session.run([output_name], {input_name: image_array})
    return outputs[0].flatten()


def predict(image: Union[str, Image.Image, np.ndarray], 
            model_info: dict = None,
            sensitivity: float = 1.0) -> dict:
    """Predict the class of an image.
    
    Args:
        image: Path to image, PIL Image, or numpy array
        model_info: Model info dict from load_model (auto-loads if None)
        sensitivity: Sensitivity for defect detection (1.0 = normal)
        
    Returns:
        Dictionary with prediction results:
        - class_name: Predicted class name
        - class_idx: Predicted class index
        - confidence: Confidence score (inverse of distance)
        - distances: Distances to all class prototypes
    """
    # Auto-load model if needed
    if model_info is None:
        _, model_info = load_model()
    
    # Preprocess image
    image_array = preprocess_image(image)
    
    # Get embedding
    embedding = get_embedding(
        model_info["session"],
        image_array,
        model_info["input_name"],
        model_info["output_name"]
    )
    
    # Compute distances to prototypes
    prototypes = model_info["prototypes"]
    distances = np.linalg.norm(prototypes - embedding, axis=1)
    
    # Apply sensitivity adjustment for defect class
    adjusted_distances = distances.copy()
    defect_idx = model_info["defect_idx"]
    if defect_idx >= 0 and sensitivity != 1.0:
        adjusted_distances[defect_idx] *= (1.0 / sensitivity)
    
    # Get prediction
    predicted_idx = int(np.argmin(adjusted_distances))
    class_names = model_info["class_names"]
    
    # Calculate confidence (inverse normalized distance)
    min_dist = adjusted_distances[predicted_idx]
    confidence = 1.0 / (1.0 + min_dist)
    
    return {
        "class_name": class_names[predicted_idx],
        "class_idx": predicted_idx,
        "confidence": float(confidence),
        "distances": {name: float(d) for name, d in zip(class_names, distances)},
    }


def predict_batch(images: List[Union[str, Image.Image, np.ndarray]],
                  model_info: dict = None,
                  sensitivity: float = 1.0) -> List[dict]:
    """Predict classes for multiple images.
    
    Args:
        images: List of images (paths, PIL Images, or numpy arrays)
        model_info: Model info dict from load_model (auto-loads if None)
        sensitivity: Sensitivity for defect detection
        
    Returns:
        List of prediction dictionaries
    """
    if model_info is None:
        _, model_info = load_model()
    
    return [predict(img, model_info, sensitivity) for img in images]
