"""Print library records: the sliced files a hub keeps and where they may go.

A print file is a registered resource like a camera or a printer. It can be
tagged with the printers it was sliced for, and a tag is checked both when it
is set and when the file is sent, so a file never starts on a printer it was
not meant for.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from .integrations import INTEGRATIONS, IntegrationAdapter

if TYPE_CHECKING:
    from .registry import Printer, PrinterRegistry

FORMATS = ("gcode", "gco", "g", "bgcode", "3mf")
NAME_MAX = 80
FILENAME_MAX = 60

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def extension(filename: str) -> str:
    """The format a filename carries.

    Raises:
        ValueError: If it is not one the library takes.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in FORMATS:
        raise ValueError(f"{filename!r} is not a sliced file, PrintGuard takes {', '.join('.' + f for f in FORMATS)}")
    return ext


def sanitise_name(name: Any, fallback: str) -> str:
    """Collapses whitespace and bounds a display name, falling back when empty."""
    return " ".join(str(name or "").split())[:NAME_MAX] or fallback


def accepts(printer: "Printer", ext: str) -> IntegrationAdapter:
    """The printer's adapter, if its service prints the format.

    Raises:
        ValueError: If the service takes no such file.
    """
    adapter = INTEGRATIONS[printer.provider]
    if ext not in adapter.formats:
        raise ValueError(f"{printer.name} ({adapter.label}) cannot print .{ext} files")
    return adapter


def sanitise_printers(printer_ids: Any, ext: str, printers: "PrinterRegistry") -> list[str]:
    """The printers a file is tagged for, each registered and able to print it.

    Raises:
        KeyError: If a printer does not exist.
        ValueError: If one cannot print the format.
    """
    chosen: list[str] = []
    for printer_id in printer_ids or []:
        printer = printers.get(str(printer_id))
        if printer is None:
            raise KeyError(f"no printer {printer_id}")
        accepts(printer, ext)
        if printer.id not in chosen:
            chosen.append(printer.id)
    return chosen


def printer_filename(name: str, ext: str) -> str:
    """A name safe on any print service's filesystem, ASCII with no spaces."""
    stem = _UNSAFE.sub("_", name).strip("._")[:FILENAME_MAX].strip("._") or "print"
    return f"{stem}.{ext}"
