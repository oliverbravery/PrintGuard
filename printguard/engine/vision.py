"""Pure-numpy preprocessing, prototype classification and defect scoring.

Every function here runs identically on CPython and Pyodide; the model
invocation itself is the platform's responsibility.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

INPUT_SIZE = 224
RESIZE_SHORTEST = 256
GREYSCALE_WEIGHTS = np.asarray([0.2989, 0.5870, 0.1140], dtype=np.float32)
MARGIN_HALF_SPAN = 4.0


@dataclass(frozen=True)
class Assets:
    """Model companion data: normalisation constants and class prototypes."""

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


def _resize(arr: np.ndarray, nw: int, nh: int) -> np.ndarray:
    h, w = arr.shape[:2]
    y_idx = np.linspace(0, h - 1, nh).astype(np.int64)
    x_idx = np.linspace(0, w - 1, nw).astype(np.int64)
    return arr[y_idx[:, None], x_idx[None, :]]


def preprocess(rgb: np.ndarray, assets: Assets) -> np.ndarray:
    """Converts an RGB frame into the model's normalised NCHW input tensor.

    Resizes the shortest edge to 256, centre-crops to 224, collapses to
    luminance and replicates across three normalised channels.

    Args:
        rgb: HxWx3 uint8 or float frame in RGB channel order.
        assets: Normalisation constants to apply.

    Returns:
        Float32 tensor of shape (1, 3, 224, 224).
    """
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError(f"expected HxWx3 RGB frame, got {rgb.shape}")
    arr = rgb.astype(np.float32) / 255.0
    h, w = arr.shape[:2]
    scale = RESIZE_SHORTEST / min(w, h)
    arr = _resize(arr, max(INPUT_SIZE, round(w * scale)), max(INPUT_SIZE, round(h * scale)))
    h, w = arr.shape[:2]
    top, left = (h - INPUT_SIZE) // 2, (w - INPUT_SIZE) // 2
    grey = arr[top : top + INPUT_SIZE, left : left + INPUT_SIZE] @ GREYSCALE_WEIGHTS
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


def defect_score(result: dict[str, Any], sensitivity: float = 1.0) -> float:
    """Maps a classification result onto a 0–1 defect score.

    A score of 0.5 sits on the decision boundary; higher means the frame
    looks more like a failing print. Sensitivity scales how aggressively
    the prototype distance margin moves the score away from 0.5.

    Args:
        result: Output of classify().
        sensitivity: Multiplier applied to the distance margin.

    Returns:
        Defect score clamped to [0, 1].
    """
    distances = result.get("distances") or {}
    if "success" not in distances or "failure" not in distances:
        return 0.5
    signed_margin = distances["success"] - distances["failure"]
    return max(0.0, min(1.0, 0.5 + (sensitivity * signed_margin) / (2 * MARGIN_HALF_SPAN)))
