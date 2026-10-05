"""Preprocessing, prototype classification and defect scoring.

The model invocation itself is the platform's responsibility.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

INPUT_SIZE = 224
RESIZE_SHORTEST = 256


@dataclass(frozen=True)
class Assets:
    """Model companion data, the normalisation constants and class prototypes."""

    mean: tuple[float, ...]
    std: tuple[float, ...]
    prototypes: dict[str, np.ndarray]


def assets_from_dicts(meta: dict[str, Any], protos: dict[str, list[float]]) -> Assets:
    """Builds Assets from parsed metadata.json and prototypes.json contents.

    Args:
        meta: Parsed model metadata document.
        protos: Mapping of class name to prototype embedding.

    Returns:
        Immutable Assets ready for preprocessing and classification.
    """
    pre = meta["preprocessing"]
    return Assets(
        mean=tuple(float(x) for x in pre["normalise_mean"]),
        std=tuple(float(x) for x in pre["normalise_std"]),
        prototypes={k: np.asarray(v, dtype=np.float32) for k, v in protos.items()},
    )


def preprocess(rgb: np.ndarray, assets: Assets) -> np.ndarray:
    """Converts an RGB frame into the model's normalised NCHW input tensor.

    Follows the torchvision transforms the model was trained with, resizing the
    shortest edge to 256 through Pillow's bilinear filter, collapsing to luminance
    and centre-cropping to 224. Sampling single pixels instead hands each frame's
    sensor noise to the model, so a still scene's score jitters.

    Args:
        rgb: HxWx3 uint8 frame in RGB channel order.
        assets: Normalisation constants to apply.

    Returns:
        Float32 tensor of shape (1, 3, 224, 224).
    """
    image = Image.fromarray(rgb)
    scale = RESIZE_SHORTEST / min(image.size)
    image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.BILINEAR)
    left, top = (image.width - INPUT_SIZE) // 2, (image.height - INPUT_SIZE) // 2
    image = image.convert("L").crop((left, top, left + INPUT_SIZE, top + INPUT_SIZE))
    grey = np.asarray(image, dtype=np.float32) / 255.0
    chans = np.stack([(grey - m) / s for m, s in zip(assets.mean, assets.std)], axis=0)
    return chans[np.newaxis, ...].astype(np.float32)


def classify(embedding: np.ndarray, assets: Assets) -> dict[str, Any]:
    """Classifies an embedding by nearest prototype in Euclidean distance.

    Args:
        embedding: Flat embedding vector from the encoder.
        assets: Prototypes to compare against.

    Returns:
        Dict with prediction, per-class distances and the distance margin.
    """
    if not np.isfinite(embedding).all():
        return {"prediction": "unknown", "distances": {}, "margin": 0.0}
    distances = {cls: float(np.linalg.norm(embedding - proto)) for cls, proto in assets.prototypes.items()}
    if any(math.isnan(d) or math.isinf(d) for d in distances.values()):
        return {"prediction": "unknown", "distances": {}, "margin": 0.0}
    ordered = sorted(distances.items(), key=lambda kv: kv[1])
    margin = ordered[1][1] - ordered[0][1] if len(ordered) > 1 else 0.0
    return {"prediction": ordered[0][0], "distances": distances, "margin": margin}


def shrink(rgb: np.ndarray, shortest: int) -> np.ndarray:
    """Scales a frame down so its shorter side is ``shortest`` pixels.

    Args:
        rgb: HxWx3 uint8 frame.
        shortest: The shorter side's length after scaling.

    Returns:
        The scaled frame, or the original if it is already that small.
    """
    height, width = rgb.shape[:2]
    scale = shortest / min(height, width)
    if scale >= 1:
        return rgb
    return np.asarray(Image.fromarray(rgb).resize((round(width * scale), round(height * scale)), Image.Resampling.BILINEAR))


def rotate_frame(rgb: np.ndarray, rotation: int) -> np.ndarray:
    """Rotates an RGB frame clockwise by a multiple of 90 degrees.

    Args:
        rgb: HxWx3 uint8 frame.
        rotation: Clockwise rotation in degrees; one of 0, 90, 180, 270.

    Returns:
        The rotated frame, or the original when rotation is 0.
    """
    k = (4 - rotation // 90) % 4
    return rgb if k == 0 else np.rot90(rgb, k)


def crop_frame(rgb: np.ndarray, crop: dict[str, float] | None) -> np.ndarray:
    """Crops an RGB frame to the given normalised region.

    Args:
        rgb: HxWx3 uint8 frame.
        crop: Normalised crop {x, y, w, h} in 0-1 range, or None for no crop.

    Returns:
        Cropped uint8 frame, or the original if crop is None.
    """
    if crop is None:
        return rgb
    h, w = rgb.shape[:2]
    x0 = int(crop["x"] * w)
    y0 = int(crop["y"] * h)
    x1 = int((crop["x"] + crop["w"]) * w)
    y1 = int((crop["y"] + crop["h"]) * h)
    x0 = max(0, min(w - 1, x0))
    y0 = max(0, min(h - 1, y0))
    x1 = max(x0 + 1, min(w, x1))
    y1 = max(y0 + 1, min(h, y1))
    return rgb[y0:y1, x0:x1]


def adjust(rgb: np.ndarray, brightness: float = 1.0, contrast: float = 1.0, sharpness: float = 0.0) -> np.ndarray:
    """Applies brightness, contrast and sharpness to an RGB frame.

    Args:
        rgb: HxWx3 uint8 frame in RGB channel order.
        brightness: Linear multiplier on pixel values (1.0 = unchanged).
        contrast: Scale around mid-grey (1.0 = unchanged).
        sharpness: Unsharp-mask strength (0.0 = unchanged).

    Returns:
        Adjusted uint8 frame of the same shape.
    """
    if brightness == 1.0 and contrast == 1.0 and sharpness <= 0.0:
        return rgb
    arr = rgb.astype(np.float32)
    if brightness != 1.0:
        arr *= brightness
    if contrast != 1.0:
        arr = (arr - 128.0) * contrast + 128.0
    if sharpness > 0.0:
        padded = np.pad(arr, ((1, 1), (1, 1), (0, 0)), mode="edge")
        blur = (
            padded[:-2, :-2]
            + padded[:-2, 1:-1]
            + padded[:-2, 2:]
            + padded[1:-1, :-2]
            + padded[1:-1, 1:-1]
            + padded[1:-1, 2:]
            + padded[2:, :-2]
            + padded[2:, 1:-1]
            + padded[2:, 2:]
        ) / 9.0
        arr = arr + sharpness * (arr - blur)
    return np.clip(arr, 0, 255).astype(np.uint8)


def transform(
    rgb: np.ndarray,
    *,
    rotation: int = 0,
    crop: dict[str, float] | None = None,
    brightness: float = 1.0,
    contrast: float = 1.0,
    sharpness: float = 0.0,
) -> np.ndarray:
    """Applies a camera's full image pipeline, rotating, then cropping, then adjusting.

    The crop is interpreted in the rotated frame's coordinates, so the result
    matches exactly what the live view shows and what the model infers on.

    Args:
        rgb: HxWx3 uint8 frame in RGB channel order.
        rotation: Clockwise rotation in degrees (0, 90, 180, 270).
        crop: Normalised crop region on the rotated frame, or None.
        brightness: Linear brightness multiplier.
        contrast: Contrast scale around mid-grey.
        sharpness: Unsharp-mask strength.

    Returns:
        The transformed uint8 frame.
    """
    rgb = rotate_frame(rgb, rotation)
    rgb = crop_frame(rgb, crop)
    return adjust(rgb, brightness, contrast, sharpness)


def defect_score(result: dict[str, Any]) -> float:
    """Returns the model's probability that a frame shows a failing print.

    This is the softmax over negative squared prototype distances the
    Prototypical Network was trained with, so 0.5 sits on the decision
    boundary and the score reads as the model's own confidence.

    Args:
        result: Output of classify().

    Returns:
        Failure probability in [0, 1], or 0.5 when the frame could not be classified.
    """
    distances = result.get("distances") or {}
    if "success" not in distances or "failure" not in distances:
        return 0.5
    return 0.5 * (1.0 + math.tanh((distances["success"] ** 2 - distances["failure"] ** 2) / 2))
