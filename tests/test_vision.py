"""Row-blocked adjustments against the original full-frame formula at seams, edges and cropped views."""

from __future__ import annotations

import numpy as np
import pytest

from printguard.engine import vision
from vision_reference import adjust_full_frame


def assert_within_one_level(actual: np.ndarray, expected: np.ndarray) -> None:
    """Fused float maths may round a pixel one level away from the unfused formula."""
    assert actual.shape == expected.shape
    np.testing.assert_array_less(np.abs(actual.astype(np.int16) - expected), 2)


@pytest.fixture
def small_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shrinks the block budget so small frames still cross several seams."""
    monkeypatch.setattr(vision, "ADJUST_BLOCK_PIXELS", 1024)


@pytest.mark.usefixtures("small_blocks")
@pytest.mark.parametrize("shape", [(1, 1, 3), (31, 37, 3), (32, 33, 3), (33, 35, 3), (65, 63, 3), (97, 104, 3), (5, 2000, 3)])
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
    assert actual.dtype == np.uint8
    assert_within_one_level(actual, adjust_full_frame(image, *settings))
    np.testing.assert_array_equal(image, original)


@pytest.mark.usefixtures("small_blocks")
def test_sharpening_reads_across_block_boundaries() -> None:
    """Features on both sides of a seam contribute to the same 3x3 kernel."""
    width = 81
    seam = vision.ADJUST_BLOCK_PIXELS // width
    image = np.full((98, width, 3), 128, dtype=np.uint8)
    image[seam - 1 : seam + 1, 20:61] = (32, 224, 64)
    image[2 * seam - 1 : 2 * seam + 1, 21:60] = (224, 32, 192)
    image[[0, -1]] = (0, 255, 127)
    assert_within_one_level(vision.adjust(image, 1.1, 1.05, 2), adjust_full_frame(image, 1.1, 1.05, 2))


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("crop", [None, {"x": .1, "y": .2, "w": .7, "h": .6}])
def test_transform_retains_rotation_and_crop_order(rotation: int, crop: dict[str, float] | None) -> None:
    """Only the adjustment's working set changes after rotation and cropping."""
    image = np.random.default_rng(733).integers(0, 256, (131, 173, 3), dtype=np.uint8)
    prepared = vision.crop_frame(vision.rotate_frame(image, rotation), crop)
    expected = adjust_full_frame(prepared, 1.1, 1.05, .5)
    actual = vision.transform(image, rotation=rotation, crop=crop, brightness=1.1, contrast=1.05, sharpness=.5)
    assert_within_one_level(actual, expected)


@pytest.mark.parametrize("shape", [(720, 1280, 3), (1296, 2304, 3)])
def test_hd_adjustments_preserve_pixels(shape: tuple[int, int, int]) -> None:
    """The high-resolution path keeps the full-frame result without resizing."""
    image = np.random.default_rng(734).integers(0, 256, shape, dtype=np.uint8)
    assert_within_one_level(vision.adjust(image, 1.1, 1.05, .5), adjust_full_frame(image, 1.1, 1.05, .5))


def test_neutral_adjustments_keep_original_frame() -> None:
    """Neutral settings still avoid allocation and processing."""
    image = np.zeros((65, 83, 3), dtype=np.uint8)
    assert vision.adjust(image) is image
