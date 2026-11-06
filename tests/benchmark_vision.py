"""Compare full-frame adjustment with 16, 32, 64 and 128-row blocks offline.

Run with ``uv run python tests/benchmark_vision.py``. This reports timings but
sets no CI speed threshold. Inputs are synthetic; no camera or printer is used.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import statistics
import time
from collections.abc import Callable

import numpy as np

from printguard.engine import vision
from vision_reference import adjust_full_frame


def benchmark(width: int, height: int, repeats: int, warmup: int, seed: int) -> dict[str, object]:
    """Measures the old formula and the production path at each block size.

    Args:
        width: Synthetic frame width.
        height: Synthetic frame height.
        repeats: Timed calls per implementation.
        warmup: Untimed calls per implementation.
        seed: Seed for pixels and the interleaved execution order.

    Returns:
        Timings and pixel equality for each path on this environment.
    """
    image = np.random.default_rng(seed).integers(0, 256, (height, width, 3), dtype=np.uint8)
    settings = (1.1, 1.05, .5)
    expected = adjust_full_frame(image, *settings)
    cases = [0, 16, 32, 64, 128]
    samples: dict[int, list[float]] = {rows: [] for rows in cases}
    order = random.Random(seed)
    original_rows = vision.ADJUST_BLOCK_ROWS
    try:
        for iteration in range(warmup + repeats):
            order.shuffle(cases)
            for rows in cases:
                operation: Callable[..., np.ndarray] = adjust_full_frame
                if rows:
                    vision.ADJUST_BLOCK_ROWS = rows
                    operation = vision.adjust
                started = time.perf_counter()
                actual = operation(image, *settings)
                elapsed_ms = (time.perf_counter() - started) * 1000
                np.testing.assert_array_equal(actual, expected)
                del actual
                if iteration >= warmup:
                    samples[rows].append(elapsed_ms)
    finally:
        vision.ADJUST_BLOCK_ROWS = original_rows
    return {"width": width, "height": height, "settings": dict(zip(("brightness", "contrast", "sharpness"), settings)),
            "paths": {str(rows) if rows else "full_frame": {"median_ms": statistics.median(times),
                       "min_ms": min(times), "max_ms": max(times), "samples_ms": times,
                       "identical_pixels": True} for rows, times in sorted(samples.items())}}


def main() -> None:
    """Prints a reproducible JSON comparison, without writing application state."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", default=["320x240", "640x480", "1280x720", "1920x1080", "2304x1296", "3840x2160"])
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--seed", type=int, default=732)
    args = parser.parse_args()
    if args.repeats < 1 or args.warmup < 0:
        parser.error("repeats must be positive and warmup non-negative")
    sizes = []
    for size in args.sizes:
        try:
            width, height = (int(value) for value in size.lower().split("x"))
            if width < 1 or height < 1:
                raise ValueError
        except ValueError:
            parser.error("sizes must be positive WIDTHxHEIGHT pairs")
        sizes.append((width, height))
    result = {"environment": {"python": platform.python_version(), "numpy": np.__version__,
                              "system": platform.system(), "machine": platform.machine(), "logical_cpus": os.cpu_count()},
              "method": "Synthetic RGB; shuffled interleaved order; warmups and equality checks excluded from timings; shared host load not controlled",
              "warmup_calls_per_path": args.warmup, "timed_calls_per_path": args.repeats, "seed": args.seed,
              "results": [benchmark(width, height, args.repeats, args.warmup, args.seed) for width, height in sizes]}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
