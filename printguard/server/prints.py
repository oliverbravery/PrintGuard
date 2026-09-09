"""The hub's side of the print library: taking uploads in and serving files out.

The engine owns the records and the checks, and the platform's store owns the
bytes. This is the HTTP plumbing between them, shared by the dashboard's own
routes and the versioned REST API so an upload is handled one way.
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator

from fastapi import HTTPException
from fastapi.responses import FileResponse, Response

from ..engine import gcode
from ..engine.engine import Engine
from ..engine.prints import extension
from ..engine.registry import PrintFile
from .platform import DiskFileStore

MAX_PRINT_BYTES = 512 * 1024 * 1024
MAX_PREVIEW_BYTES = 2 * 1024 * 1024
ADD_TIMEOUT_S = 120.0
THUMBNAIL_CACHE_CONTROL = "private, max-age=31536000, immutable"


def store_of(engine: Engine) -> DiskFileStore:
    """The hub's file store, which every hub has."""
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


async def receive_print(engine: Engine, filename: str, name: str, printer_ids: list[str], body: AsyncIterator[bytes]) -> PrintFile:
    """Streams an upload into the store and registers it with the engine.

    Args:
        engine: The hub's engine.
        filename: The name the file was uploaded as, whose extension decides
            its format.
        name: Display name, or empty for the filename's stem.
        printer_ids: Printers to tag it for.
        body: The bytes as they arrive.

    Returns:
        The registered record.

    Raises:
        HTTPException: 400 for a file the library does not take or the engine
            refuses, 413 for one over the size limit.
    """
    filename = filename.rsplit("/", 1)[-1]
    try:
        ext = extension(filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    print_id = uuid.uuid4().hex[:8]
    await store_of(engine).store(f"{print_id}.{ext}", _capped(body, MAX_PRINT_BYTES))
    try:
        await engine.request(
            {"cmd": "print.add", "id": print_id, "filename": filename, "name": name, "printer_ids": printer_ids},
            timeout=ADD_TIMEOUT_S,
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    return record_of(engine, print_id)


async def receive_preview(engine: Engine, print_id: str, body: AsyncIterator[bytes]) -> None:
    """Keeps a preview drawn from a file's toolpath, for one the slicer wrote none into.

    Args:
        engine: The hub's engine.
        print_id: The library file the preview belongs to.
        body: The PNG as it arrives.

    Raises:
        HTTPException: 404 for a file the library does not hold, 413 for a
            preview over the size limit.
    """
    record = record_of(engine, print_id)
    await store_of(engine).store(record.thumbnail_key, _capped(body, MAX_PREVIEW_BYTES))
    await engine.request({"cmd": "print.preview", "id": print_id})


async def _capped(body: AsyncIterator[bytes], limit: int) -> AsyncIterator[bytes]:
    size = 0
    async for chunk in body:
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, f"that upload is over the {limit // 1024 // 1024} MB limit")
        yield chunk


def file_response(engine: Engine, print_id: str) -> Response:
    """The stored file as it was uploaded, for downloading."""
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
