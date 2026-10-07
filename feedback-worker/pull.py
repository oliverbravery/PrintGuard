# /// script
# requires-python = ">=3.12"
# dependencies = ["boto3==1.43.108", "pillow==12.3.0"]
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
import re
import unicodedata
from email.errors import HeaderParseError
from email.header import decode_header, make_header
from pathlib import Path
from typing import Any, Iterator

import boto3
from PIL import Image

BUCKET = "printguard-feedback"
JURISDICTION = "eu"
PIXELS_MAX = 4096 * 4096
JPEG_QUALITY = 92
FRAME_KEY = re.compile(r"[0-9a-f]{32}/[0-9a-f]{12}/[0-9a-f]{12}\.jpg")


def sanitised(raw: bytes) -> bytes | None:
    """Re-encodes an uploaded file as a clean JPEG.

    Args:
        raw: The bytes exactly as they were uploaded.

    Returns:
        A JPEG holding only the decoded pixels, or None if the upload is not an
        image Pillow can decode or one over ``PIXELS_MAX`` pixels.
    """
    try:
        image = Image.open(io.BytesIO(raw))
        if image.width * image.height > PIXELS_MAX:
            return None
        image.load()
    except Exception:
        return None
    clean = io.BytesIO()
    pixels = image.convert("RGB")
    pixels.info.clear()
    pixels.save(clean, "JPEG", quality=JPEG_QUALITY)
    return clean.getvalue()


def labels(metadata: dict[str, str]) -> dict[str, str]:
    """Decodes an object's labels, which R2 hands back RFC 2047 encoded when they are not ASCII, and drops control characters."""
    return {name: _decoded(value) for name, value in metadata.items()}


def _decoded(value: str) -> str:
    """Decodes one label, keeping it as sent when it only looks encoded, such as one naming a charset there isn't or holding broken base64."""
    try:
        decoded = str(make_header(decode_header(value)))
    except (HeaderParseError, LookupError, ValueError):
        decoded = value
    return "".join(char for char in decoded if unicodedata.category(char) != "Cc")


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
        How many frames were kept and how many were discarded as undecodable. An
        object that expired between the listing and the download is skipped with
        a note and counted as neither.
    """
    kept = discarded = 0
    out.mkdir(parents=True, exist_ok=True)
    with (out / "frames.jsonl").open("a") as rows:
        for key in list(inbox(client)):
            try:
                stored = client.get_object(Bucket=BUCKET, Key=key)
            except client.exceptions.NoSuchKey:
                print(f"{key} expired before it could be pulled, skipped")
                continue
            clean = sanitised(stored["Body"].read()) if FRAME_KEY.fullmatch(key) else None
            if clean is None:
                discarded += 1
            else:
                hub, print_id, name = key.split("/")
                target = out / hub / print_id / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(clean)
                row = {**labels(stored["Metadata"]), "hub": hub, "print": print_id, "file": str(target.relative_to(out)), "uploaded": stored["LastModified"].isoformat()}
                rows.write(json.dumps(row) + "\n")
                rows.flush()
                kept += 1
            client.delete_object(Bucket=BUCKET, Key=key)
    _keep_latest_rows(out / "frames.jsonl")
    return kept, discarded


def _keep_latest_rows(path: Path) -> None:
    """Leaves one row for each file, the newest, since a frame sent again after a pull replaces its JPEG."""
    latest = {json.loads(row)["file"]: row for row in path.read_text().splitlines()}
    path.write_text("".join(f"{row}\n" for row in latest.values()))


def main() -> None:
    """Pulls the inbox into the directory named on the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path, help="the dataset directory")
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
