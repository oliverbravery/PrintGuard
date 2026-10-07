"""The state file in the hub's data directory."""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any, Callable

STATE_SECTIONS: dict[str, type | tuple[type, ...]] = {
    "cameras": list,
    "printers": list,
    "prints": list,
    "monitors": list,
    "reviews": list,
    "tokens": list,
    "plugins": list,
    "settings": dict,
    "feedback_token": (str, type(None)),
}
"""What the engine saves under each top-level key of the state file, so one
holding anything else is treated as damaged."""

KEPT_DAMAGED_COPIES = 5
"""How many damaged state files are kept, the first of them for good: a hub
that starts empty and is damaged in turn must not replace the one holding the
configuration the user wants back."""

logger = logging.getLogger(__name__)


def data_directory_refused(directory: Path, problem: str, cause: OSError) -> RuntimeError:
    """Explains a data directory the hub's user may not use, which stops the hub.

    Args:
        directory: The data directory.
        problem: What the hub could not do there.
        cause: The error the operating system gave.

    Returns:
        The error to raise, saying whose the directory is and whose it has to be.
    """
    existing = next(parent for parent in (directory, *directory.parents) if parent.exists())
    try:
        owner = existing.owner()
    except (KeyError, NotImplementedError):
        owner = f"uid {existing.stat().st_uid}"
    whose = f"{directory} belongs to {owner}" if existing == directory else f"{directory} does not exist and {existing} belongs to {owner}"
    return RuntimeError(
        f"{problem} ({cause}), so the hub cannot start. "
        f"{whose}, and the data directory and the files in it have to belong to the user the hub runs as"
    )


def prepare_data_directory(directory: Path) -> None:
    """Creates the data directory and checks the hub can write to it.

    A directory the hub can read but not write would otherwise only show at
    the first save, with the settings already lost.

    Args:
        directory: The data directory.

    Raises:
        RuntimeError: If it cannot be created or written to, saying whose it has to be.
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
        tempfile.TemporaryFile(dir=directory).close()
    except OSError as exc:
        raise data_directory_refused(directory, f"{exc.filename} could not be created", exc) from None


def drop_non_finite(value: Any, path: str, dropped: list[str]) -> None:
    """Removes every NaN and infinity from parsed JSON, in place.

    A dashboard cannot be sent one, so a hub that kept it would break every
    socket it opened. A key holding one is deleted and a list item becomes null.

    Args:
        value: Parsed JSON of any shape.
        path: Where ``value`` sits in the document, for the report.
        dropped: Receives the path of each number that was removed.
    """
    if isinstance(value, dict):
        entries = list(value.items())
    elif isinstance(value, list):
        entries = list(enumerate(value))
    else:
        return
    for key, item in entries:
        here = f"{path}.{key}" if isinstance(value, dict) else f"{path}[{key}]"
        if isinstance(item, float) and not math.isfinite(item):
            dropped.append(here)
            if isinstance(value, dict):
                del value[key]
            else:
                value[key] = None
        else:
            drop_non_finite(item, here, dropped)


class StateFile:
    """Engine state persisted as JSON, saved without holding up the caller.

    A save is serialised on the caller's thread, since the engine goes on
    changing what it passed, and written on a thread of its own: syncing a
    megabyte to an SD card takes long enough to stall inference on the event
    loop. A save made while another is waiting replaces it, so a burst of
    commands costs one write. A write that fails is logged and reported once
    through ``report``, which is called from the writer's thread with a message
    and whether it says the failure is over.
    """

    def __init__(self, path: Path, report: Callable[[str, bool], None]) -> None:
        self._path = path
        self._report = report
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="state-file")
        self._lock = threading.Lock()
        self._pending: str | None = None
        self._failed = False

    def load(self) -> dict[str, Any]:
        """Reads persisted engine state.

        Returns:
            The saved state, or nothing on a first boot. A file that will not
            parse, or parses to something the engine never saves, is moved
            aside before the hub starts empty, so the next save cannot
            overwrite what is left of it.

        Raises:
            RuntimeError: If the hub may not read the file or move a damaged
                one aside, saying whose the data directory has to be.
        """
        try:
            state = json.loads(self._path.read_text(encoding="utf-8-sig"))
            if not isinstance(state, dict):
                raise ValueError(f"it holds {type(state).__name__}, not an object")
            for section, expected in STATE_SECTIONS.items():
                if section in state and not isinstance(state[section], expected):
                    raise ValueError(f"its {section} are {type(state[section]).__name__}")
            dropped: list[str] = []
            drop_non_finite(state, "state", dropped)
            if dropped:
                logger.warning("%s held numbers that are not finite, so the hub dropped them: %s", self._path, ", ".join(dropped))
            return state
        except FileNotFoundError:
            return {}
        except PermissionError as exc:
            raise data_directory_refused(self._path.parent, f"{self._path} could not be read", exc) from None
        except ValueError as exc:
            kept = self._free_name_for_damaged_copy()
            try:
                self._path.replace(kept)
            except PermissionError as denied:
                raise data_directory_refused(
                    self._path.parent, f"{self._path} is damaged ({exc}) and could not be moved aside", denied
                ) from None
            logger.error("%s is damaged (%s), so the hub is starting empty. The file is kept as %s", self._path, exc, kept)
            return {}

    def _free_name_for_damaged_copy(self) -> Path:
        """Names where a damaged file goes, the last of the slots once they are all taken."""
        names = [self._path.with_suffix(".json.corrupt"), *(self._path.with_suffix(f".json.corrupt.{n}") for n in range(1, KEPT_DAMAGED_COPIES))]
        return next((name for name in names if not name.exists()), names[-1])

    def save(self, state: dict[str, Any]) -> None:
        """Queues state to be written, readable only by the account running the hub."""
        text = json.dumps(state, indent=2)
        with self._lock:
            already_queued = self._pending is not None
            self._pending = text
        if not already_queued:
            self._writer.submit(self._write_pending)

    def flush(self) -> None:
        """Waits until everything saved so far is on disk."""
        self._writer.submit(lambda: None).result()

    def _write_pending(self) -> None:
        with self._lock:
            text, self._pending = self._pending, None
        try:
            self._write(text)
        except OSError as exc:
            logger.error("state could not be saved to %s: %s", self._path, exc)
            if not self._failed:
                self._failed = True
                self._report(f"settings could not be saved ({exc}). Changes made now are lost if the hub stops", False)
        else:
            if self._failed:
                self._failed = False
                self._report("settings are being saved again", True)

    def _write(self, text: str) -> None:
        """Atomically replaces the file.

        It holds printer passwords, notifier keys, API token hashes and whatever
        credentials plugins have been given, so the temporary file is created
        with that mode and held to it before anything is written: anything else
        leaves a window where it is readable by everybody on the host. One left
        behind by a hub that was killed mid-write keeps the mode it had, which
        is why creating it that way is not enough. It is synced to disk before
        the rename too, or a power cut can leave the new name pointing at a
        file with nothing in it.
        """
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w", opener=partial(os.open, mode=0o600)) as handle:
            tmp.chmod(0o600)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(self._path)
