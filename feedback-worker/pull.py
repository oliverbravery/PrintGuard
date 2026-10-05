# /// script
# requires-python = ">=3.12"
# dependencies = ["boto3", "pillow"]
# ///
"""Empties the training inbox into a local dataset.

Every object is downloaded, decoded with Pillow and written back out as a fresh
JPEG, so nothing a stranger uploaded is ever opened by anything else. The clean
copy lands in ``<out>/<hub>/<print>/<frame>.jpg`` beside a row in
``<out>/frames.jsonl`` carrying its labels, and the object is then deleted from
the bucket. Grouping by hub and print is what lets a train and test split keep
a whole print on one side.

Run it with ``uv run feedback-worker/pull.py <out>``. It reads an R2 API token
that can read and delete in this one bucket from ``R2_ACCOUNT_ID``,
``R2_ACCESS_KEY_ID`` and ``R2_SECRET_ACCESS_KEY``.
"""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
from typing import Any, Iterator

import boto3
from PIL import Image

BUCKET = "printguard-feedback"
JURISDICTION = "eu"
PIXELS_MAX = 4096 * 4096
JPEG_QUALITY = 92


def sanitised(raw: bytes) -> bytes | None:
    """Re-encodes an uploaded file as a clean JPEG.

    Args:
        raw: The bytes exactly as they were uploaded.

    Returns:
        A JPEG holding only the decoded pixels, or None if the upload is not an
        image Pillow can decode.
    """
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception:
        return None
    clean = io.BytesIO()
    image.convert("RGB").save(clean, "JPEG", quality=JPEG_QUALITY)
    return clean.getvalue()


def inbox(client: Any) -> Iterator[str]:
    """Yields the key of every object waiting in the bucket."""
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET):
        for entry in page.get("Contents", []):
            yield entry["Key"]


def pull(client: Any, out: Path) -> tuple[int, int]:
    """Moves every waiting frame into the dataset directory.

    Args:
        client: An S3 client for the bucket's jurisdiction.
        out: The dataset directory.

    Returns:
        How many frames were kept and how many were discarded as undecodable.
    """
    kept = discarded = 0
    out.mkdir(parents=True, exist_ok=True)
    with (out / "frames.jsonl").open("a") as rows:
        for key in list(inbox(client)):
            stored = client.get_object(Bucket=BUCKET, Key=key)
            clean = sanitised(stored["Body"].read())
            hub, print_id, name = key.split("/")
            if clean is None:
                discarded += 1
            else:
                target = out / hub / print_id / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(clean)
                row = {"hub": hub, "print": print_id, "file": str(target.relative_to(out)), "uploaded": stored["LastModified"].isoformat(), **stored["Metadata"]}
                rows.write(json.dumps(row) + "\n")
                rows.flush()
                kept += 1
            client.delete_object(Bucket=BUCKET, Key=key)
    return kept, discarded


def main() -> None:
    """Pulls the inbox into the directory named on the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path, help="the dataset directory")
    Image.MAX_IMAGE_PIXELS = PIXELS_MAX
    client = boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.{JURISDICTION}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )
    kept, discarded = pull(client, parser.parse_args().out)
    print(f"kept {kept} frames, discarded {discarded}")


if __name__ == "__main__":
    main()
