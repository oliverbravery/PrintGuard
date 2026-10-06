"""The state file: how it is saved without stalling the hub, and what a damaged or unreachable one does."""

from __future__ import annotations

import errno
import json
import os
import threading
from pathlib import Path

import pytest

from printguard.server.platform import ServerPlatform
from printguard.server.state_file import StateFile

needs_an_unprivileged_user = pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="the directory's mode has to bind")


def state_file_in(directory: Path, reports: list[tuple[str, bool]] | None = None) -> StateFile:
    sink = reports if reports is not None else []
    return StateFile(directory / "state.json", lambda message, recovered: sink.append((message, recovered)))


def test_the_state_file_is_readable_only_by_whoever_runs_the_hub(tmp_path) -> None:
    """It holds printer passwords, API token hashes and plugin credentials."""
    state_file = state_file_in(tmp_path)
    state_file.save({"printers": [{"config": {"password": "hunter2"}}]})
    state_file.flush()

    assert oct((tmp_path / "state.json").stat().st_mode)[-3:] == "600"
    assert not (tmp_path / "state.tmp").exists(), "the temporary file was left behind"


def test_the_state_file_is_never_readable_by_anyone_else_while_it_is_written(tmp_path, monkeypatch) -> None:
    """The temporary file holds every secret from the first byte, not only once it is renamed.

    One a killed hub left behind keeps the mode it had, so it is held to the
    mode as well as created with it.
    """
    modes: list[str] = []
    monkeypatch.setattr("printguard.server.state_file.os.fsync", lambda descriptor: modes.append(oct((tmp_path / "state.tmp").stat().st_mode)[-3:]))
    state_file = state_file_in(tmp_path)
    state_file.save({"printers": [{"config": {"password": "hunter2"}}]})
    state_file.flush()
    (tmp_path / "state.tmp").write_text("left by a hub that was killed")
    (tmp_path / "state.tmp").chmod(0o644)
    state_file.save({"printers": []})
    state_file.flush()

    assert modes == ["600", "600"]


def test_the_state_file_reaches_the_disk_before_it_takes_the_name(tmp_path, monkeypatch) -> None:
    """A rename without a sync can survive a power cut pointing at an empty file."""
    synced: list[int] = []
    monkeypatch.setattr("printguard.server.state_file.os.fsync", lambda descriptor: synced.append((tmp_path / "state.tmp").stat().st_size))
    state_file = state_file_in(tmp_path)
    state_file.save({"printers": []})
    state_file.flush()

    assert synced == [(tmp_path / "state.json").stat().st_size]


def test_saving_state_does_not_write_on_the_calling_thread(tmp_path, monkeypatch) -> None:
    """The engine saves from the event loop, and a sync to an SD card stalls inference there."""
    written_on: list[threading.Thread] = []
    monkeypatch.setattr("printguard.server.state_file.os.fsync", lambda descriptor: written_on.append(threading.current_thread()))
    state_file = state_file_in(tmp_path)
    state_file.save({"printers": []})
    state_file.flush()

    assert written_on
    assert threading.current_thread() not in written_on


def test_saves_made_while_one_is_waiting_cost_one_write_of_the_last(tmp_path, monkeypatch) -> None:
    """A burst of commands, or a review's frames arriving one after another, must not queue a sync each."""
    release = threading.Event()
    written: list[dict] = []
    state_file = state_file_in(tmp_path)
    monkeypatch.setattr(state_file, "_write", lambda text: (release.wait(5), written.append(json.loads(text))))
    for count in range(50):
        state_file.save({"count": count})
    release.set()
    state_file.flush()

    assert written[-1] == {"count": 49}
    assert len(written) <= 2


def test_a_state_file_that_cannot_be_written_is_reported_once_and_again_when_it_recovers(tmp_path, monkeypatch, caplog) -> None:
    """The write is off the caller's thread, so a full disk reaches nobody unless it is reported."""
    reports: list[tuple[str, bool]] = []
    state_file = state_file_in(tmp_path, reports)
    real_write = state_file._write

    def full_disk(text: str) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(state_file, "_write", full_disk)
    for _ in range(3):
        state_file.save({})
        state_file.flush()
    monkeypatch.setattr(state_file, "_write", real_write)
    state_file.save({})
    state_file.flush()

    assert [recovered for _message, recovered in reports] == [False, True]
    assert "No space left on device" in reports[0][0]
    assert caplog.text.count("state could not be saved") == 3


def test_a_damaged_state_file_is_kept_rather_than_overwritten(tmp_path, caplog) -> None:
    """Starting empty in silence loses every printer and reopens anonymous reads of the API."""
    state_file = state_file_in(tmp_path)
    assert state_file.load() == {}
    assert not caplog.records, "a first boot has no state file and nothing to say about it"

    (tmp_path / "state.json").write_text('{"printers": [{"id": "p1"')
    assert state_file.load() == {}
    state_file.save({})
    state_file.flush()

    assert (tmp_path / "state.json.corrupt").read_text() == '{"printers": [{"id": "p1"'
    assert [record.levelname for record in caplog.records] == ["ERROR"]
    assert "state.json.corrupt" in caplog.text


def test_a_second_damaged_state_file_does_not_replace_the_first_one_kept(tmp_path) -> None:
    """The empty hub's own file can be damaged before its owner has recovered the real one."""
    state_file = state_file_in(tmp_path)
    for generation in range(8):
        (tmp_path / "state.json").write_text(f"damaged {generation}")
        assert state_file.load() == {}

    assert (tmp_path / "state.json.corrupt").read_text() == "damaged 0"
    assert (tmp_path / "state.json.corrupt.1").read_text() == "damaged 1"
    assert (tmp_path / "state.json.corrupt.4").read_text() == "damaged 7"
    assert sorted(path.name for path in tmp_path.glob("state.json*")) == [
        f"state.json.corrupt{suffix}" for suffix in ("", ".1", ".2", ".3", ".4")
    ]


@pytest.mark.parametrize(
    "saved",
    ["null", "[]", '"state"', '{"settings": "x"}', '{"cameras": {"cam1": {}}}', '{"feedback_token": 5}', '{"tokens": null}'],
)
def test_a_state_file_of_the_wrong_shape_is_kept_like_one_that_will_not_parse(tmp_path, caplog, saved: str) -> None:
    """Valid JSON that is not what the engine saves started an empty hub, or ended the start with an AttributeError."""
    state_file = state_file_in(tmp_path)
    (tmp_path / "state.json").write_text(saved)

    assert state_file.load() == {}
    state_file.save({})
    state_file.flush()

    assert (tmp_path / "state.json.corrupt").read_text() == saved
    assert [record.levelname for record in caplog.records] == ["ERROR"]
    assert "state.json.corrupt" in caplog.text


def test_a_state_file_of_the_shape_the_engine_saves_is_read(tmp_path) -> None:
    state = {
        "cameras": [], "printers": [], "prints": [], "monitors": [], "reviews": [], "tokens": [], "plugins": [],
        "settings": {}, "feedback_token": None,
    }
    (tmp_path / "state.json").write_text(json.dumps(state))

    assert state_file_in(tmp_path).load() == state


def test_a_state_file_saved_with_a_byte_order_mark_is_read(tmp_path) -> None:
    """Notepad adds one when it saves a file a user has edited by hand."""
    (tmp_path / "state.json").write_bytes(b"\xef\xbb\xbf" + json.dumps({"settings": {"theme": "dark"}}).encode())

    assert state_file_in(tmp_path).load() == {"settings": {"theme": "dark"}}
    assert not (tmp_path / "state.json.corrupt").exists()


def test_a_state_file_the_hub_may_not_read_says_whose_it_has_to_be(tmp_path, monkeypatch) -> None:
    """A bare PermissionError traceback does not tell anyone the data directory has the wrong owner."""

    def denied(path: Path, *args: object, **kwargs: object) -> str:
        raise PermissionError(errno.EACCES, "Permission denied", str(path))

    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(RuntimeError, match="state.json could not be read .*belongs to .*belong to the user the hub runs as"):
        state_file_in(tmp_path).load()


@needs_an_unprivileged_user
def test_a_damaged_state_file_in_a_directory_the_hub_may_not_write_stops_the_hub_with_the_owner_named(tmp_path) -> None:
    """A bare PermissionError from the rename does not tell anyone whose the directory has to be."""
    (tmp_path / "state.json").write_text("{not json")
    tmp_path.chmod(0o500)
    try:
        with pytest.raises(RuntimeError, match="is damaged .*could not be moved aside .*belongs to .*belong to the user the hub runs as") as raised:
            state_file_in(tmp_path).load()
    finally:
        tmp_path.chmod(0o700)

    assert str(tmp_path) in str(raised.value)


@needs_an_unprivileged_user
def test_a_data_directory_the_hub_may_not_write_stops_the_hub_with_the_owner_named(tmp_path, monkeypatch) -> None:
    """An install from before the print library has no prints/ yet, and creating it failed with a bare PermissionError."""
    monkeypatch.setenv("PRINTGUARD_PLUGINS", "off")
    tmp_path.chmod(0o500)
    try:
        with pytest.raises(RuntimeError, match="prints could not be created .*belongs to .*belong to the user the hub runs as"):
            ServerPlatform(Path("models"), tmp_path, "http://localhost:9997", "rtsp://localhost:8554")
    finally:
        tmp_path.chmod(0o700)


async def test_stopping_the_hub_writes_the_state_still_queued(tmp_path, monkeypatch) -> None:
    """A save is queued behind the one being written, and the process ending must not drop it."""
    monkeypatch.setenv("PRINTGUARD_PLUGINS", "off")
    platform = ServerPlatform(Path("models"), tmp_path, "http://localhost:9997", "rtsp://localhost:8554")
    platform.save_state({"settings": {"theme": "dark"}})
    await platform.close()

    assert json.loads((tmp_path / "state.json").read_text()) == {"settings": {"theme": "dark"}}
