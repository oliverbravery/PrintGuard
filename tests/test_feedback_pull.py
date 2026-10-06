"""The script that empties the training inbox into a local dataset."""

from __future__ import annotations

import datetime
import importlib.util
import io
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

HUB = "a" * 32
PRINT = "b" * 12
UPLOADED = datetime.datetime(2026, 10, 6, tzinfo=datetime.timezone.utc)


@pytest.fixture(scope="module")
def pull() -> types.ModuleType:
    sys.modules.setdefault("boto3", types.ModuleType("boto3"))
    spec = importlib.util.spec_from_file_location("pull", Path(__file__).parent.parent / "feedback-worker" / "pull.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def jpeg(size: tuple[int, int] = (64, 48), **save: Any) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, "JPEG", **save)
    return out.getvalue()


def labels(**changes: str) -> dict[str, str]:
    return {"label": "good", "kind": "spaced", "score": "0.12", "version": "2.6.0", "provider": "klipper", "printer": "Voron 2.4", **changes}


class Bucket:
    def __init__(self, objects: dict[str, tuple[bytes, dict[str, str]]]) -> None:
        self.objects = dict(objects)

    def get_paginator(self, _name: str) -> Any:
        keys = sorted(self.objects)

        class Pages:
            def paginate(self, Bucket: str) -> Any:
                for start in range(0, len(keys), 2):
                    yield {"Contents": [{"Key": key} for key in keys[start : start + 2]]}

        return Pages()

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        body, metadata = self.objects[Key]
        return {"Body": io.BytesIO(body), "Metadata": metadata, "LastModified": UPLOADED}

    def delete_object(self, Bucket: str, Key: str) -> None:
        del self.objects[Key]


def key(frame: int) -> str:
    return f"{HUB}/{PRINT}/{frame:012x}.jpg"


def test_a_label_that_only_looks_encoded_is_kept_as_sent(pull: types.ModuleType, tmp_path: Path) -> None:
    bucket = Bucket({key(frame): (jpeg(), labels(printer="=?utf-8?b?A?=" if frame == 2 else "Voron 2.4")) for frame in (1, 2, 3)})

    assert pull.pull(bucket, tmp_path) == (3, 0)

    assert bucket.objects == {}
    rows = [json.loads(row) for row in (tmp_path / "frames.jsonl").read_text().splitlines()]
    assert sorted(row["printer"] for row in rows) == ["=?utf-8?b?A?=", "Voron 2.4", "Voron 2.4"]


def test_a_label_in_rfc_2047_is_decoded(pull: types.ModuleType) -> None:
    assert pull.labels({"printer": "=?utf-8?b?UHJ1c2EgTUs0?="}) == {"printer": "Prusa MK4"}


def test_a_frame_sent_again_after_a_pull_leaves_one_row(pull: types.ModuleType, tmp_path: Path) -> None:
    pull.pull(Bucket({key(1): (jpeg(), labels(label="good"))}), tmp_path)
    pull.pull(Bucket({key(1): (jpeg(), labels(label="failure"))}), tmp_path)

    assert [json.loads(row)["label"] for row in (tmp_path / "frames.jsonl").read_text().splitlines()] == ["failure"]

def test_a_frame_over_the_pixel_cap_is_discarded_before_it_is_decoded(pull: types.ModuleType) -> None:
    assert pull.sanitised(jpeg((5780, 5780), quality=10)) is None
    assert pull.sanitised(jpeg((4096, 4096), quality=10)) is not None

