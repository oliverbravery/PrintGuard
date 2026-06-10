from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

INPUT_SIZE = 224
RESIZE_SHORTEST = 256
GREYSCALE_WEIGHTS = np.asarray([0.2989, 0.5870, 0.1140], dtype=np.float32)


@dataclass(frozen=True)
class Assets:
    mean: np.ndarray
    std: np.ndarray
    prototypes: dict[str, np.ndarray]
    classes: tuple[str, ...]


def load_assets(model_dir: str | Path) -> Assets:
    d = Path(model_dir)
    meta = json.loads((d / "metadata.json").read_text())
    protos = json.loads((d / "prototypes.json").read_text())["prototypes"]
    return assets_from_dicts(meta, protos)


def assets_from_dicts(meta: dict[str, Any], protos: dict[str, list[float]]) -> Assets:
    mean = np.asarray(meta["preprocessing"]["normalise_mean"], dtype=np.float32)
    std = np.asarray(meta["preprocessing"]["normalise_std"], dtype=np.float32)
    classes = tuple(meta["classification"]["classes"])
    return Assets(
        mean=mean,
        std=std,
        prototypes={k: np.asarray(v, dtype=np.float32) for k, v in protos.items()},
        classes=classes,
    )


def _resize_shortest(arr: np.ndarray) -> np.ndarray:
    h, w = arr.shape[:2]
    scale = RESIZE_SHORTEST / min(w, h)
    nw = max(INPUT_SIZE, round(w * scale))
    nh = max(INPUT_SIZE, round(h * scale))
    return _resize(arr, nw, nh)


def _resize(arr: np.ndarray, nw: int, nh: int) -> np.ndarray:
    h, w = arr.shape[:2]
    y_idx = (np.linspace(0, h - 1, nh)).astype(np.int64)
    x_idx = (np.linspace(0, w - 1, nw)).astype(np.int64)
    return arr[y_idx[:, None], x_idx[None, :]]


def _center_crop(arr: np.ndarray) -> np.ndarray:
    h, w = arr.shape[:2]
    left = (w - INPUT_SIZE) // 2
    top = (h - INPUT_SIZE) // 2
    return arr[top : top + INPUT_SIZE, left : left + INPUT_SIZE]


def preprocess(arr_rgb_or_bgr: np.ndarray) -> np.ndarray:
    if arr_rgb_or_bgr.ndim != 3 or arr_rgb_or_bgr.shape[2] != 3:
        raise ValueError(f"expected HxWx3, got {arr_rgb_or_bgr.shape}")
    rgb = arr_rgb_or_bgr[..., ::-1] if arr_rgb_or_bgr.shape[2] == 3 else arr_rgb_or_bgr
    rgb = rgb.astype(np.float32) / 255.0
    resized = _resize_shortest(rgb)
    cropped = _center_crop(resized)
    grey = cropped @ GREYSCALE_WEIGHTS
    chans = np.stack([(grey - _m) / _s for _m, _s in zip(_MEAN, _STD)], axis=0)
    return chans[np.newaxis, ...].astype(np.float32)


_MEAN: tuple[float, ...] = ()
_STD: tuple[float, ...] = ()


def configure_norm(mean: np.ndarray, std: np.ndarray) -> None:
    global _MEAN, _STD
    _MEAN = tuple(float(x) for x in mean)
    _STD = tuple(float(x) for x in std)


def classify(emb: np.ndarray, prototypes: dict[str, np.ndarray]) -> dict[str, Any]:
    distances = sorted(
        ({"class": cls, "distance": float(np.linalg.norm(emb - proto))} for cls, proto in prototypes.items()),
        key=lambda d: d["distance"],
    )
    if any(math.isnan(d["distance"]) or math.isinf(d["distance"]) for d in distances):
        return {"prediction": "unknown", "distances": [], "margin": 0.0}
    margin = distances[1]["distance"] - distances[0]["distance"] if len(distances) > 1 else 0.0
    return {"prediction": distances[0]["class"], "distances": distances, "margin": margin}


def initialise(assets: Assets) -> None:
    configure_norm(assets.mean, assets.std)
