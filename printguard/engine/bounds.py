"""Bounds for the numbers a command or a saved setting carries."""

from __future__ import annotations

import math
from typing import Any

HEATER_MAX = {"nozzle": 350.0, "bed": 150.0}
"""The hottest target in degrees Celsius a heater is ever sent or a sliced file is rewritten to."""


def clamp(field: str, value: Any, low: float, high: float) -> float:
    """Holds a number inside a range, refusing one that is not a number at all.

    NaN compares false with everything, so ``max`` and ``min`` alone hand back
    whichever bound they were given first.

    Args:
        field: What the number sets, named in the refusal.
        value: The number as it arrived.
        low: The least it may be.
        high: The most it may be.

    Returns:
        The number, moved to the nearer bound when it lies outside them.

    Raises:
        ValueError: If the value is NaN or infinite, or does not read as a number.
    """
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number, not {number}")
    return max(low, min(high, number))
