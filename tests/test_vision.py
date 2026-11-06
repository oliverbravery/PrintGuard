"""Pixel equivalence of row-blocked adjustments at seams, edges and cropped views."""

from __future__ import annotations

import numpy as np
import pytest

from printguard.engine import vision
from vision_reference import adjust_full_frame


@pytest.mark.parametrize("shape", [(1, 1, 3), (31, 37, 3), (32, 33, 3), (33, 35, 3), (65, 63, 3), (97, 104, 3)])
@pytest.mark.parametrize("settings", [(1, 1, 0), (1.1, 1.05, .5), (.25, 2, 2), (2, .25, .01), (2, 2, 0), (1, 1, 2)])
@pytest.mark.parametrize("layout", ["contiguous", "reversed", "rotated"])
def test_adjustments_match_full_frame_pixels(shape: tuple[int, int, int], settings: tuple[float, float, float], layout: str) -> None:
    """Block seams preserve every channel, including clipped values and strided views."""
    image = np.random.default_rng(732).integers(0, 256, shape, dtype=np.uint8)
    if layout == "reversed":
        image = image[::-1, ::-1]
    elif layout == "rotated":
        image = np.rot90(image)
    original = image.copy()
    actual = vision.adjust(image, *settings)
    np.testing.assert_array_equal(actual, adjust_full_frame(image, *settings))
    np.testing.assert_array_equal(image, original)
    assert actual.dtype == np.uint8 and actual.shape == image.shape


def test_sharpening_reads_across_block_boundaries() -> None:
    """Features on both sides of a seam contribute to the same 3x3 kernel."""
    image = np.full((98, 81, 3), 128, dtype=np.uint8)
    image[31:33, 20:61] = (32, 224, 64)
    image[63:65, 21:60] = (224, 32, 192)
    image[[0, -1]] = (0, 255, 127)
    np.testing.assert_array_equal(vision.adjust(image, 1.1, 1.05, 2), adjust_full_frame(image, 1.1, 1.05, 2))


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("crop", [None, {"x": .1, "y": .2, "w": .7, "h": .6}])
def test_transform_retains_rotation_and_crop_order(rotation: int, crop: dict[str, float] | None) -> None:
    """Only the adjustment's working set changes after rotation and cropping."""
    image = np.random.default_rng(733).integers(0, 256, (131, 173, 3), dtype=np.uint8)
    prepared = vision.crop_frame(vision.rotate_frame(image, rotation), crop)
    expected = adjust_full_frame(prepared, 1.1, 1.05, .5)
    actual = vision.transform(image, rotation=rotation, crop=crop, brightness=1.1, contrast=1.05, sharpness=.5)
    np.testing.assert_array_equal(actual, expected)


@pytest.mark.parametrize("shape", [(720, 1280, 3), (1296, 2304, 3)])
def test_hd_adjustments_preserve_pixels(shape: tuple[int, int, int]) -> None:
    """The high-resolution path preserves output without resizing."""
    image = np.random.default_rng(734).integers(0, 256, shape, dtype=np.uint8)
    np.testing.assert_array_equal(vision.adjust(image, 1.1, 1.05, .5), adjust_full_frame(image, 1.1, 1.05, .5))


def test_neutral_adjustments_keep_original_frame() -> None:
    """Neutral settings still avoid allocation and processing."""
    image = np.zeros((65, 83, 3), dtype=np.uint8)
    assert vision.adjust(image) is image
