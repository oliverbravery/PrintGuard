"""Preprocessing, scoring and the image pipeline shared by every model.

The model invocation itself is the platform's responsibility.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

LONGEST_RATIO = 4
SQUARE_OVERLAP = 0.2
DECISION_BOUNDARY = 0.5
# About 400 KB per float32 temporary, inside a Raspberry Pi 5 core's 512 KB L2 cache.
ADJUST_BLOCK_PIXELS = 32768


@dataclass(frozen=True)
class Assets:
    """How one model's frames are prepared and its output read.

    Attributes:
        name: The model's name as people see it, such as ``Standard``.
        size: Side of the square the model takes, in pixels.
        resize_shortest: Length the shorter side is resized to before the centre crop.
        grey: Whether frames are collapsed to luminance, as the model was trained on.
        mean: Per-channel normalisation mean.
        std: Per-channel normalisation spread.
        prototypes: Class prototypes the model's embedding is compared against,
            or None for a model that gives its own probability.
    """

    name: str
    size: int
    resize_shortest: int
    grey: bool
    mean: np.ndarray
    std: np.ndarray
    prototypes: dict[str, np.ndarray] | None


def assets_from_dicts(meta: dict[str, Any], protos: dict[str, list[float]] | None) -> Assets:
    """Builds Assets from a model's parsed metadata.json and, for an embedding model, its prototypes.

    Args:
        meta: Parsed model metadata document.
        protos: Mapping of class name to prototype embedding, or None for a
            model whose output is a probability.

    Returns:
        Immutable Assets ready for preprocessing and classification.
    """
    pre = meta["preprocessing"]
    return Assets(
        name=meta["name"],
        size=int(pre["center_crop_px"]),
        resize_shortest=int(pre["resize_shortest_edge_px"]),
        grey=pre["color"] == "grey",
        mean=np.asarray(pre["normalise_mean"], dtype=np.float32),
        std=np.asarray(pre["normalise_std"], dtype=np.float32),
        prototypes=None if protos is None else {k: np.asarray(v, dtype=np.float32) for k, v in protos.items()},
    )


def preprocess(rgb: np.ndarray, assets: Assets) -> np.ndarray:
    """Converts an RGB frame into the model's normalised NCHW input tensor.

    Follows the torchvision eval transforms each model was trained with:
    ``Resize`` of the shortest edge through Pillow's bilinear filter, sized
    and rounded as torchvision sizes it, then ``CenterCrop``, with the frame
    collapsed to luminance first for a model trained on grey frames. Sampling
    single pixels instead hands each frame's sensor noise to the model, so a
    still scene's score jitters. Only the middle of the long side survives the
    crop, so no more than ``LONGEST_RATIO`` times the short side is resized,
    or a frame a few pixels tall and thousands wide would be scaled up to
    hundreds of megabytes first.

    Args:
        rgb: HxWx3 uint8 frame in RGB channel order.
        assets: The model's input size and normalisation constants.

    Returns:
        Float32 tensor of shape (1, 3, size, size).
    """
    image = Image.fromarray(rgb)
    short = min(image.size)
    width, height = (min(side, short * LONGEST_RATIO) for side in image.size)
    left, top = (image.width - width) // 2, (image.height - height) // 2
    resized = tuple(assets.resize_shortest if side == short else int(assets.resize_shortest * side / short) for side in (width, height))
    image = image.resize(resized, Image.Resampling.BILINEAR, box=(left, top, left + width, top + height))
    if assets.grey:
        image = image.convert("L")
    left, top = (int(round((side - assets.size) / 2.0)) for side in image.size)
    pixels = np.atleast_3d(np.asarray(image.crop((left, top, left + assets.size, top + assets.size)), dtype=np.float32) / 255.0)
    return ((pixels - assets.mean) / assets.std).transpose(2, 0, 1)[np.newaxis].astype(np.float32)


def square_starts(long: int, short: int) -> list[int]:
    """Where each square the model scores begins along a frame's long side.

    The model is trained on squares, so a wide frame is scored as squares the
    height of the frame that overlap by at least ``SQUARE_OVERLAP``, the
    sliding-window overlap common to tiled inference, so a defect on the seam
    is whole in one of them. A frame no more than that overlap wider than it
    is tall is one centred square. Beyond ``LONGEST_RATIO`` times the short
    side only the middle is covered, as ``preprocess`` does.

    Args:
        long: The frame's longer side in pixels.
        short: The frame's shorter side in pixels.

    Returns:
        The offset of each square along the long side, in order.
    """
    span = min(long, short * LONGEST_RATIO)
    ratio = span / short
    if ratio <= 1 + SQUARE_OVERLAP:
        return [(long - short) // 2]
    count = math.ceil((ratio - SQUARE_OVERLAP) / (1 - SQUARE_OVERLAP))
    margin, step = (long - span) // 2, (span - short) / (count - 1)
    return [margin + round(index * step) for index in range(count)]


def squares(rgb: np.ndarray) -> list[np.ndarray]:
    """Splits a frame into the overlapping squares the model scores, laid along its long side.

    Args:
        rgb: HxWx3 frame.

    Returns:
        The squares, each a view into ``rgb``.
    """
    height, width = rgb.shape[:2]
    if width >= height:
        return [rgb[:, start : start + height] for start in square_starts(width, height)]
    return [rgb[start : start + width] for start in square_starts(height, width)]


def classify(output: np.ndarray, assets: Assets) -> dict[str, Any]:
    """Reads a model's output as its probability that the frame shows a failing print.

    A model with prototypes gives an embedding, scored with the softmax over
    negative squared prototype distances the Prototypical Network was trained
    with. Every other model gives its own calibrated probability. Either way
    0.5 is the decision boundary, so the score reads as the model's own
    confidence.

    Args:
        output: The model's first output for one frame.
        assets: Prototypes to compare an embedding against.

    Returns:
        Dict with the verdict at the decision boundary and the defect score in [0, 1].

    Raises:
        ValueError: If the output is not finite, which means the runtime
            failed rather than that the frame is unclear.
    """
    if not np.isfinite(output).all():
        raise ValueError("the model returned a non-finite output")
    if assets.prototypes is None:
        score = float(output)
    else:
        success, failure = (float(np.linalg.norm(output.astype(np.float64) - assets.prototypes[name])) for name in ("success", "failure"))
        score = 0.5 * (1.0 + math.tanh((success - failure) * (success + failure) / 2))
    return {"prediction": "failure" if score >= DECISION_BOUNDARY else "success", "defect_score": score}


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

    Works through blocks of about ``ADJUST_BLOCK_PIXELS`` pixels, each with one
    neighbouring row on either side so sharpening is unbroken at the seams.

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
    height, width = rgb.shape[:2]
    block_rows = max(1, ADJUST_BLOCK_PIXELS // width)
    halo = 1 if sharpness > 0.0 else 0
    result = np.empty_like(rgb)
    for top in range(0, height, block_rows):
        bottom = min(height, top + block_rows)
        lo, hi = max(0, top - halo), min(height, bottom + halo)
        result[top:bottom] = _adjust_block(rgb[lo:hi], brightness, contrast, sharpness)[top - lo : bottom - lo]
    return result


def _adjust_block(rgb: np.ndarray, brightness: float, contrast: float, sharpness: float) -> np.ndarray:
    """Applies the adjustment formula to a block and its neighbouring rows.

    Brightness and contrast fold into one multiply and add, and the 3x3 box blur
    is summed rows then columns, in place where possible. The reordered float
    maths can leave a pixel one level from the unfused formula.

    Args:
        rgb: RGB rows, including neighbours when sharpening is enabled.
        brightness: Linear multiplier on pixel values.
        contrast: Scale around mid-grey.
        sharpness: Unsharp-mask strength.

    Returns:
        Adjusted uint8 pixels, including the neighbouring rows.
    """
    arr = rgb.astype(np.float32)
    arr *= np.float32(brightness * contrast)
    arr += np.float32(128.0 * (1.0 - contrast))
    if sharpness > 0.0:
        padded = np.pad(arr, ((1, 1), (1, 1), (0, 0)), mode="edge")
        rows = padded[:-2] + padded[1:-1] + padded[2:]
        blur = rows[:, :-2] + rows[:, 1:-1] + rows[:, 2:]
        blur *= np.float32(-sharpness / 9.0)
        arr *= np.float32(1.0 + sharpness)
        arr += blur
    np.clip(arr, 0, 255, out=arr)
    return arr.astype(np.uint8)


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

    The crop is interpreted in the rotated frame's coordinates, so the framing
    matches the live view. The dashboard redraws the adjustments itself at the
    size the feed is shown, so its sharpness looks stronger than the full-size
    frame the model infers on.

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
