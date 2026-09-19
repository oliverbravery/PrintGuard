"""The hub's side of the print library: taking uploads in and serving files out.

The engine owns the records and the checks, and the platform's store owns the
bytes. This is the HTTP plumbing between them, shared by the dashboard's own
routes and the versioned REST API so an upload is handled one way.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, AsyncIterator

from fastapi import HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from ..engine import gcode
from ..engine.engine import Engine
from ..engine.prints import extension
from ..engine.registry import PrintFile
from .platform import DiskFileStore

MAX_PRINT_BYTES = 512 * 1024 * 1024
MAX_SAMPLE_BYTES = gcode.HEAD_BYTES + gcode.TAIL_BYTES + 1
ADD_TIMEOUT_S = 120.0
THUMBNAIL_CACHE_CONTROL = "private, max-age=31536000, immutable"


class PrintUpload(BaseModel):
    """How an uploaded file enters the library, given as query parameters beside its raw body."""

    filename: str = Field(description="The file's name, whose extension decides its format.")
    name: str = Field("", description="Display name, the filename's stem when empty.")
    printer_ids: str = Field("", description="Comma-separated printers to tag it for.")
    nozzle: float | None = Field(None, description="First-layer nozzle temperature to rewrite the file to, in °C.")
    bed: float | None = Field(None, description="First-layer bed temperature to rewrite the file to, in °C.")


def store_of(engine: Engine) -> DiskFileStore:
    """The hub's file store, as the disk store it is rather than the protocol."""
    files = engine.platform.files
    assert isinstance(files, DiskFileStore)
    return files


def record_of(engine: Engine, print_id: str) -> PrintFile:
    """The library record for an id.

    Raises:
        HTTPException: 404 when there is none.
    """
    record = engine.prints.get(print_id)
    if record is None:
        raise HTTPException(404, f"no print {print_id!r}")
    return record


async def receive_print(engine: Engine, upload: PrintUpload, body: AsyncIterator[bytes]) -> PrintFile:
    """Streams an upload into the store and registers it with the engine.

    Args:
        engine: The hub's engine.
        upload: What the file is called, who it is for and what it heats to.
        body: The bytes as they arrive.

    Returns:
        The registered record.

    Raises:
        HTTPException: 400 for a file the library does not take or the engine
            refuses, 413 for one over the size limit.
    """
    filename = upload.filename.rsplit("/", 1)[-1]
    try:
        ext = extension(filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    print_id = uuid.uuid4().hex[:8]
    await store_of(engine).store(f"{print_id}.{ext}", _capped(body, MAX_PRINT_BYTES))
    try:
        await engine.request(
            {
                "cmd": "print.add",
                "id": print_id,
                "filename": filename,
                "name": upload.name,
                "printer_ids": [printer_id for printer_id in upload.printer_ids.split(",") if printer_id],
                "nozzle": upload.nozzle,
                "bed": upload.bed,
            },
            timeout=ADD_TIMEOUT_S,
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    return record_of(engine, print_id)


async def inspect_sample(ext: str, body: AsyncIterator[bytes]) -> dict[str, Any]:
    """Reads what a file says about itself from the head and tail the library reads.

    The dashboard sends only those before a file is uploaded, so the upload
    panel can show the slicer's estimates and temperatures while the file is
    still on the user's device.

    Args:
        ext: The file's format, or ``gcode`` for a 3mf's plate.
        body: The file's first ``gcode.HEAD_BYTES``, a newline and its last
            ``gcode.TAIL_BYTES``, or the whole file when it is smaller.

    Returns:
        The file's ``meta`` and whether it carries a ``thumbnail``.

    Raises:
        HTTPException: 400 for a format the library does not take or a sample
            it cannot read, 413 for one larger than the library reads.
    """
    try:
        extension(f"sample.{ext}")
        sliced = await asyncio.to_thread(gcode.inspect, b"".join([chunk async for chunk in _capped(body, MAX_SAMPLE_BYTES)]), ext)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"meta": sliced.meta, "thumbnail": sliced.thumbnail is not None}


async def _capped(body: AsyncIterator[bytes], limit: int) -> AsyncIterator[bytes]:
    size = 0
    async for chunk in body:
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, f"that upload is over the {limit // 1024 // 1024} MB limit")
        yield chunk


def file_response(engine: Engine, print_id: str) -> Response:
    """The stored file, for downloading."""
    record = record_of(engine, print_id)
    return FileResponse(store_of(engine).path(record.file_key), media_type="application/octet-stream", filename=record.filename)


async def gcode_response(engine: Engine, print_id: str) -> Response:
    """The file's text gcode for the viewer, unpacked from a 3mf.

    Raises:
        HTTPException: 404 for binary gcode, which has no text to draw from.
    """
    record = record_of(engine, print_id)
    path = store_of(engine).path(record.file_key)
    if record.ext == "3mf":
        _, plate = gcode.plate_gcode(path.read_bytes())
        return Response(plate, media_type="text/plain")
    if record.ext == "bgcode":
        raise HTTPException(404, "binary gcode carries nothing the viewer can draw")
    return FileResponse(path, media_type="text/plain")


def thumbnail_response(engine: Engine, print_id: str) -> Response:
    """The preview image the file carried.

    Raises:
        HTTPException: 404 when it carried none.
    """
    record = record_of(engine, print_id)
    if record.thumbnail is None:
        raise HTTPException(404, f"print {print_id!r} has no preview")
    return FileResponse(
        store_of(engine).path(record.thumbnail_key),
        media_type=record.thumbnail,
        headers={"Cache-Control": THUMBNAIL_CACHE_CONTROL},
    )
