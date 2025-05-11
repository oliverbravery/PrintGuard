import os
import json
import torch
from PIL import Image
from torchvision import transforms
import cv2

def load_model(model_path, options_path, device):
    model = torch.load(model_path, weights_only=False)
    model.eval()
    model.to(device)
    with open(options_path, 'r', encoding='utf-8') as f:
        model_opt = json.load(f)
    x_dim = list(map(int, model_opt['model.x_dim'].split(',')))
    return model, x_dim

def make_transform():
    return transforms.Compose([
        transforms.Resize(256),
        transforms.Grayscale(num_output_channels=3),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    ])

def draw_label(frame, label, color, success_label="success"):
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
        cv2.putText(frame, text, text_pos, font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
    except Exception as e:
        print(f"Error drawing label: {e}. Frame shape: {frame.shape}, Label: {label}")
    return frame


def compute_prototypes(model, support_dir, transform, device, success_label="success"):
    class_names = sorted([d for d in os.listdir(support_dir)
                          if os.path.isdir(os.path.join(support_dir, d))])
    if not class_names:
         raise ValueError(f"No class subdirectories found in support directory: {support_dir}")

    prototypes = []
    loaded_class_names = []
    for cls in class_names:
        cls_dir = os.path.join(support_dir, cls)
        imgs = [os.path.join(cls_dir,f) for f in os.listdir(cls_dir) if f.lower().endswith(('.png','.jpg','.jpeg'))]
        if not imgs:
             print(f"Warning: No images found for class '{cls}' in {cls_dir}")
             continue
        tensors = []
        for img_path in imgs:
            try:
                img = Image.open(img_path).convert('RGB')
                tensors.append(transform(img))
            except Exception as e:
                print(f"Error loading support image {img_path}: {e}")
        if not tensors:
             print(f"Warning: Could not load any valid images for class '{cls}'. Skipping this class.")
             continue
        ts = torch.stack(tensors).to(device)
        with torch.no_grad():
            emb = model.encoder(ts)
        prototype = emb.mean(0)
        prototypes.append(prototype)
        loaded_class_names.append(cls)
    if not prototypes:
         raise ValueError("Failed to build any prototypes from the support set.")
    prototypes = torch.stack(prototypes)
    print(f"Prototypes built for classes: {loaded_class_names}")

    defect_idx = -1
    if success_label in loaded_class_names:
        try:
            defect_candidates = [i for i, name in enumerate(loaded_class_names) if name != success_label]
            if len(defect_candidates) == 1:
                defect_idx = defect_candidates[0]
                print(f"Identified '{loaded_class_names[defect_idx]}' as the defect class (index {defect_idx}).")
            elif len(defect_candidates) > 1:
                 print(f"Warning: Multiple non-'{success_label}' classes found: {[loaded_class_names[i] for i in defect_candidates]}. Sensitivity adjustment requires exactly one defect class. Adjustment disabled.")
            else:
                 print(f"Warning: Only found the '{success_label}' class. Cannot apply sensitivity adjustment.")
        except IndexError:
            print(f"Warning: Could not identify a distinct defect class, though '{success_label}' was present. Sensitivity adjustment disabled.")
    else:
        print(f"Warning: '{success_label}' class not found in loaded support set {loaded_class_names}. Cannot apply sensitivity adjustment.")

    return prototypes, loaded_class_names, defect_idx


def predict_batch(model, batch_tensors, prototypes, defect_idx, sensitivity, device):
    if batch_tensors is None or batch_tensors.shape[0] == 0:
        print("Warning: Received empty or invalid batch for prediction.")
        return []

    model.eval()
    with torch.no_grad():
        batch_x = batch_tensors.to(device)
        batch_emb = model.encoder(batch_x)

        distances = torch.cdist(batch_emb, prototypes)

        min_dists, initial_preds = torch.min(distances, dim=1) # (B,), (B,)
        final_preds = initial_preds.clone()
        for i in range(batch_emb.size(0)):
            if initial_preds[i] != defect_idx:
                dist_to_defect = distances[i, defect_idx]
                if dist_to_defect <= min_dists[i] * sensitivity:
                    final_preds[i] = defect_idx

        return final_preds.cpu().tolist()


def setup_device(requested_device):
    if requested_device == 'cuda' and torch.cuda.is_available():
        device = torch.device('cuda')
    elif requested_device == 'mps' and torch.backends.mps.is_available():
        device = torch.device('mps')
    else:
        device = torch.device('cpu')
        if requested_device != 'cpu':
            print(f"Warning: {requested_device} requested but not available. Falling back to CPU.")
    print(f"Using device: {device}")
    return device

DEFAULT_MODEL_PATH = os.path.join(os.path.dirname(__file__), "model/best_model.pt")
DEFAULT_MODEL_OPTIONS_PATH = os.path.join(os.path.dirname(__file__), "model/opt.json")
DEFAULT_SUPPORT_DIR = os.path.join(os.path.dirname(__file__), "model/prototypes")
