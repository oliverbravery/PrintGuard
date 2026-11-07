"""The full-frame adjustment formula before row blocking, kept as a test oracle."""

from __future__ import annotations

import numpy as np


def adjust_full_frame(rgb: np.ndarray, brightness: float = 1.0, contrast: float = 1.0, sharpness: float = 0.0) -> np.ndarray:
    """Applies the original full-frame formula without sharing production helpers.

    Args:
        rgb: HxWx3 uint8 frame in RGB channel order.
        brightness: Linear multiplier on pixel values.
        contrast: Scale around mid-grey.
        sharpness: Unsharp-mask strength.

    Returns:
        Adjusted uint8 pixels, or the original frame when settings are neutral.
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
