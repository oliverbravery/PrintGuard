"""The frames kept from each watched print, for the risk history and for review.

A review is one print as a monitor saw it: every frame that fired an alert, the
highest scoring frames that did not, and a spread of ordinary ones. Consecutive
frames are near-duplicates, so the spread is thinned as a print runs on and a
long print keeps no more than a short one. The JPEGs live in the platform's
file store and the records ride in the persisted state, so both survive a
restart.

A print is also recorded, one frame every few seconds, so its reviewer can
scrub through it and add frames of their own. A recording is one file of
JPEGs written end to end beside an index of fixed-size entries, and lasts only
until the print is reviewed or a set number of days has passed.
"""

from __future__ import annotations

import asyncio
import struct
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from . import vision
from .bounds import clamp
from .feedback import FRAMES_PER_DAY
from .platform import Frame, Platform, as_chunks

if TYPE_CHECKING:
    from .registry import PrinterRegistry

SHORTEST_PX = 512
SPACED_START_S = 60.0
SPACED_MAX = 20
NEAR_MAX = 5
NEAR_APART_S = 60.0
ALERT_MAX = 40
REVIEW_MAX = 20
BYTES_MAX = 200 * 1024 * 1024
UNLINKED_PRINT_S = 24 * 3600.0
RECORD_EVERY_S = 5.0
RECORDINGS_BYTES_MAX = 2 * 1024**3
DAY_S = 24 * 3600.0
INDEX_ENTRY = struct.Struct("<dfQI")
ENDED_STATUSES = ("idle", "error")
STATUSES = ("running", "ready", "dismissed", "skipped", "queued", "sent")
RECORDED_STATUSES = ("running", "ready")
FRAME_KINDS = ("alert", "near", "spaced", "added")
LABELS = ("failure", "good")


@dataclass
class Review:
    """One watched print and the frames kept from it.

    Attributes:
        monitor_id: The monitor that watched it.
        started: Wall-clock time of its first frame.
        spacing_s: The gap between spaced frames, doubled each time they are thinned.
        ended: When the print finished, or None while it runs.
        status: ``running`` while the print runs, ``ready`` once it waits to be
            reviewed, ``dismissed`` when no review is wanted, ``skipped`` when
            the reviewer chose not to send it, ``queued`` while
            frames wait on the inbox and ``sent`` when all of them are in.
        submission: What the reviewer chose once they pressed Send: the label
            of every frame they kept, the printer model they typed, the frames
            already sent, and the refusal code and retry time when queued.
        frames: The kept frames in capture order, each with its id, time, score,
            kind (alert, near, spaced or added from the recording), stored size,
            an alert's action and the label an added frame was added with.
    """

    id: str
    monitor_id: str
    started: float
    spacing_s: float
    ended: float | None = None
    status: str = "running"
    submission: dict[str, Any] | None = None
    frames: list[dict[str, Any]] = field(default_factory=list)

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        """The kept frames of one kind, in capture order."""
        return [frame for frame in self.frames if frame["kind"] == kind]

    def unsent(self) -> list[dict[str, Any]]:
        """The frames the reviewer kept that the inbox has not taken yet."""
        submission = self.submission or {"labels": {}, "sent": []}
        return [frame for frame in self.frames if frame["id"] in submission["labels"] and frame["id"] not in submission["sent"]]

    def public(self) -> dict[str, Any]:
        """Summarises the review for the state event, without its frame list."""
        submission = self.submission or {}
        return {
            "id": self.id,
            "monitor_id": self.monitor_id,
            "started": self.started,
            "ended": self.ended,
            "status": self.status,
            "frames": len(self.frames),
            "bytes": sum(frame["size"] for frame in self.frames),
            "alerts": len(self.of_kind("alert")),
            "chosen": len(submission.get("labels", {})),
            "sent": len(submission.get("sent", [])),
            "code": submission.get("code"),
            "retry_at": submission.get("retry_at"),
        }


def stored_review(record: dict[str, Any]) -> dict[str, Any]:
    """Checks a review read back from the state store.

    Args:
        record: One review as ``ReviewLibrary.persisted`` wrote it.

    Returns:
        The same record, with every kept frame and choice checked to be of the
        kind the rest of the engine reads it as.

    Raises:
        KeyError: If the record has no status.
        ValueError: If a value is not of the kind its field takes.
    """
    if not isinstance(record.get("monitor_id"), str):
        raise ValueError("its monitor is an id")
    if record["status"] not in STATUSES:
        raise ValueError("it has a status it cannot have")
    frames, submission = record.get("frames", []), record.get("submission")
    for frame in frames if isinstance(frames, list) else [None]:
        if not (isinstance(frame, dict) and isinstance(frame.get("id"), str) and frame.get("kind") in FRAME_KINDS):
            raise ValueError("its kept frames are not a list of frames")
        if frame["kind"] == "alert" and not isinstance(frame.get("action"), str):
            raise ValueError("a kept alert frame has no action")
        if frame["kind"] == "added" and frame.get("label") not in LABELS:
            raise ValueError("a frame added from the recording has no label")
        for key in ("ts", "score", "size"):
            clamp(f"a kept frame's {key}", frame.get(key), 0.0, sys.float_info.max)
    if submission is None:
        if record["status"] == "queued":
            raise ValueError("it is queued with nothing chosen to send")
    else:
        if not (
            isinstance(submission, dict)
            and {"labels", "printer", "sent", "code", "retry_at"} <= submission.keys()
            and isinstance(submission["labels"], dict)
            and all(isinstance(frame_id, str) and label in LABELS for frame_id, label in submission["labels"].items())
            and isinstance(submission["sent"], list)
            and all(isinstance(frame_id, str) for frame_id in submission["sent"])
            and isinstance(submission["printer"], str)
            and (submission["code"] is None or isinstance(submission["code"], str))
        ):
            raise ValueError("what was chosen to send is not a set of labels")
        if submission["retry_at"] is not None:
            clamp("the time to try sending again", submission["retry_at"], 0.0, sys.float_info.max)
    clamp("started", record.get("started"), 0.0, sys.float_info.max)
    clamp("spacing_s", record.get("spacing_s"), 0.0, sys.float_info.max)
    if record.get("ended") is not None:
        clamp("ended", record["ended"], 0.0, sys.float_info.max)
    return record


def _raise_first(outcomes: list[Any]) -> None:
    """Raises the first failure among gathered results, so one that failed does not hide the others having run."""
    for outcome in outcomes:
        if isinstance(outcome, Exception):
            raise outcome


def frame_key(review_id: str, frame_id: str) -> str:
    """The file store key a kept frame's JPEG lives under."""
    return f"review-{review_id}-{frame_id}.jpg"


def recording_key(review_id: str) -> str:
    """The file store key a print's recorded JPEGs are written end to end under."""
    return f"recording-{review_id}.frames"


def index_key(review_id: str) -> str:
    """The file store key of a recording's index, one ``INDEX_ENTRY`` per frame."""
    return f"recording-{review_id}.index"


@dataclass
class Recording:
    """The frames recorded through one print.

    Attributes:
        entries: Each frame's time, score, and where its JPEG begins and how
            long it runs in the recording file, in capture order.
        bytes: The size of every recorded JPEG together.
    """

    entries: list[tuple[float, float, int, int]] = field(default_factory=list)
    bytes: int = 0

    def add(self, ts: float, score: float, offset: int, size: int) -> None:
        """Notes one more recorded frame."""
        self.entries.append((ts, score, offset, size))
        self.bytes += size


class ReviewLibrary:
    """Chooses which frames of a print to keep and stores them, within a cap."""

    def __init__(self, platform: Platform) -> None:
        self._platform = platform
        self._reviews: dict[str, Review] = {}
        self._recordings: dict[str, Recording] = {}
        self._unrecorded: set[str] = set()
        self._stops = 0

    def restore(self, records: list[dict[str, Any]]) -> None:
        """Loads reviews a previous run persisted."""
        self._reviews.update({record["id"]: Review(**record) for record in records})

    def persisted(self) -> list[dict[str, Any]]:
        """Serialises every review for the state store."""
        return [asdict(review) for review in self._reviews.values()]

    async def load_recordings(self) -> None:
        """Reads back the index of every review's recording a previous run left.

        A frame whose entry was cut short when the hub stopped is left out.
        """
        for review_id in self._reviews:
            try:
                index = await self._platform.files.read(index_key(review_id))
            except FileNotFoundError:
                continue
            recording = self._recordings[review_id] = Recording()
            for entry in INDEX_ENTRY.iter_unpack(index[: len(index) - len(index) % INDEX_ENTRY.size]):
                recording.add(*entry)

    def public(self, recording_days: int) -> list[dict[str, Any]]:
        """Summarises every review for the state event.

        Args:
            recording_days: How many days a finished print's recording is kept.

        Returns:
            Each review's summary, with its recording's frame count, size and
            the time it will be deleted, or None for a print not recorded.
        """
        return [{**review.public(), "recording": self._recording_summary(review, recording_days)} for review in self._reviews.values()]

    def _recording_summary(self, review: Review, recording_days: int) -> dict[str, Any] | None:
        recording = self._recordings.get(review.id)
        if recording is None:
            return None
        expires = review.ended + recording_days * DAY_S if review.ended is not None else None
        return {"frames": len(recording.entries), "bytes": recording.bytes, "expires": expires}

    def timeline(self, review_id: str) -> list[list[float]]:
        """Each recorded frame's time and score, in capture order, or none for a print not recorded."""
        recording = self._recordings.get(review_id)
        return [[round(ts, 1), round(score, 4)] for ts, score, _, _ in recording.entries] if recording else []

    async def recorded_frame(self, review_id: str, index: int) -> tuple[float, float, bytes]:
        """Reads one frame of a print's recording.

        Args:
            review_id: The review the print belongs to.
            index: The frame's place in the recording, from 0.

        Returns:
            The frame's time, its score and its JPEG.

        Raises:
            LookupError: If the print has no recording or none that long.
        """
        recording = self._recordings.get(review_id)
        if recording is None or not 0 <= index < len(recording.entries):
            raise LookupError(f"no recorded frame {index} of review {review_id}")
        ts, score, offset, size = recording.entries[index]
        return ts, score, await self._platform.files.read_range(recording_key(review_id), offset, size)

    async def add(self, review_id: str, index: int, label: str) -> None:
        """Keeps a frame from a finished print's recording, so it can be sent with the rest.

        Args:
            review_id: The review the print belongs to.
            index: The frame's place in the recording, from 0.
            label: Whether the reviewer added it as ``good`` or as a ``failure``.

        Raises:
            LookupError: If there is no such review, or no such recorded frame.
            ValueError: If the print is running or was already sent, the frame
                was added before, the label is neither, or the print already
                holds as many added frames as can be sent in a day.
        """
        review = self._reviews.get(review_id)
        if review is None:
            raise LookupError(f"no review {review_id}")
        if review.status in ("running", "queued", "sent"):
            raise ValueError("frames are added to a print once it has finished, before it is sent")
        if label not in LABELS:
            raise ValueError("a frame is added as good or as a failure")
        ts, score, jpeg = await self.recorded_frame(review_id, index)
        added = review.of_kind("added")
        if any(frame["ts"] == ts for frame in added):
            raise ValueError("that frame was already added")
        if len(added) >= FRAMES_PER_DAY:
            raise ValueError(f"a print can have at most {FRAMES_PER_DAY} frames added")
        frame_id = uuid.uuid4().hex[:12]
        size = await self._platform.files.store(frame_key(review.id, frame_id), as_chunks(jpeg))
        review.frames.append({"id": frame_id, "ts": ts, "score": round(score, 4), "kind": "added", "label": label, "size": size})
        review.frames.sort(key=lambda frame: frame["ts"])

    def stop_recording(self, review_ids: list[str]) -> None:
        """Has the next tidy delete these prints' recordings, and records no more of a print still running."""
        self._unrecorded.update(review_ids)

    async def tidy_recordings(self, now: float, recording_days: int) -> bool:
        """Deletes every recording that is no longer wanted.

        A recording lasts while its print runs or waits to be reviewed, and
        until ``recording_days`` after the print ended. Pressing Send or Not
        this print, the review being switched off, the print being dropped and
        recording being switched off all end it, as does the reviewer deleting it.

        Args:
            now: Wall-clock time.
            recording_days: How many days a finished print's recording is kept, 0 when recording is off.

        Returns:
            Whether any recording was deleted.

        Raises:
            OSError: If a file could not be deleted, once all the rest were tried.
        """
        unwanted = [
            review_id
            for review_id in self._recordings
            if (review := self._reviews.get(review_id)) is None
            or review.status not in RECORDED_STATUSES
            or not recording_days
            or review_id in self._unrecorded
            or (review.ended is not None and review.ended + recording_days * DAY_S <= now)
        ]
        self._unrecorded &= {review.id for review in self._reviews.values() if review.ended is None}
        for review_id in unwanted:
            del self._recordings[review_id]
        outcomes = await asyncio.gather(*(self._remove_recording(review_id) for review_id in unwanted), return_exceptions=True)
        _raise_first(outcomes)
        return bool(unwanted)

    async def _remove_recording(self, review_id: str) -> None:
        await asyncio.gather(self._platform.files.remove(recording_key(review_id)), self._platform.files.remove(index_key(review_id)))

    async def _record(self, review: Review, frame: Frame, score: float, ts: float) -> None:
        """Adds a frame to a running print's recording once the gap since the last has passed.

        The oldest other recordings are deleted to make room under
        ``RECORDINGS_BYTES_MAX``, and the frame is passed over when that is not enough.
        """
        if review.id in self._unrecorded:
            return
        recording = self._recordings.setdefault(review.id, Recording())
        if recording.entries and ts - recording.entries[-1][0] < RECORD_EVERY_S:
            return
        jpeg = await self._jpeg(frame)
        if not jpeg or not await self._make_room(len(jpeg), review.id):
            return
        offset = await self._platform.files.append(recording_key(review.id), jpeg)
        if self._recordings.get(review.id) is not recording:
            await self._remove_recording(review.id)
            return
        await self._platform.files.append(index_key(review.id), INDEX_ENTRY.pack(ts, score, offset, len(jpeg)))
        recording.add(ts, score, offset, len(jpeg))

    async def _make_room(self, size: int, keeping: str) -> bool:
        """Deletes the recordings of the prints that began first until ``size`` more bytes fit, returning whether they do."""
        others = sorted((review_id for review_id in self._recordings if review_id != keeping), key=lambda review_id: self._reviews[review_id].started if review_id in self._reviews else 0.0)
        while others and sum(recording.bytes for recording in self._recordings.values()) + size > RECORDINGS_BYTES_MAX:
            review_id = others.pop(0)
            del self._recordings[review_id]
            await self._remove_recording(review_id)
        return sum(recording.bytes for recording in self._recordings.values()) + size <= RECORDINGS_BYTES_MAX

    def get(self, review_id: str) -> Review | None:
        """Returns a review by id, or None."""
        return self._reviews.get(review_id)

    def alert_frames(self, monitor_id: str) -> list[dict[str, Any]]:
        """Every kept alert frame of a monitor, oldest first."""
        return [frame for review in self._reviews.values() if review.monitor_id == monitor_id for frame in review.of_kind("alert")]

    async def read(self, monitor_id: str, frame_id: str) -> bytes | None:
        """Returns a kept frame's JPEG bytes, or None if the monitor has no such frame."""
        for review in self._reviews.values():
            if review.monitor_id == monitor_id and any(frame["id"] == frame_id for frame in review.frames):
                return await self._platform.files.read(frame_key(review.id, frame_id))
        return None

    async def sample(self, monitor: dict[str, Any], frame: Frame, score: float, ts: float, recording: bool) -> bool:
        """Considers one scored frame for a monitor's running print.

        A frame is kept as spaced when the print's current gap has passed since
        the last one, and otherwise as a near miss when it scored under the
        threshold but above the near misses already held.

        Args:
            monitor: The monitor record the score belongs to.
            frame: The frame that produced the score.
            score: Defect score in [0, 1].
            ts: Wall-clock time of the score.
            recording: Whether prints are recorded for scrubbing in their review.

        Returns:
            Whether the kept frames changed.
        """
        score = round(score, 4)
        stops = self._stops
        review = self._running(monitor["id"]) or await self._begin(monitor["id"], ts)
        if recording:
            await self._record(review, frame, score, ts)
        spaced = review.of_kind("spaced")
        if not spaced or ts - spaced[-1]["ts"] >= review.spacing_s:
            await self._keep(review, frame, {"ts": ts, "score": score, "kind": "spaced"}, stops)
            if len(spaced) + 1 >= SPACED_MAX:
                await self._drop(review, review.of_kind("spaced")[1::2])
                review.spacing_s *= 2
            return True
        if score >= monitor["threshold"]:
            return False
        near = review.of_kind("near")
        neighbour = next((kept for kept in near if ts - kept["ts"] < NEAR_APART_S), None)
        outscored = neighbour or (min(near, key=lambda kept: kept["score"]) if len(near) >= NEAR_MAX else None)
        if outscored and score <= outscored["score"]:
            return False
        await self._keep(review, frame, {"ts": ts, "score": score, "kind": "near"}, stops)
        if outscored:
            await self._drop(review, [outscored])
        return True

    async def keep_alert(self, monitor_id: str, alert: dict[str, Any], frame: Frame) -> None:
        """Keeps the frame that fired an alert in the monitor's running print."""
        review = self._running(monitor_id) or await self._begin(monitor_id, alert["ts"])
        await self._keep(review, frame, {"ts": alert["ts"], "score": alert["score"], "kind": "alert", "action": alert["action"]}, self._stops)
        await self._drop(review, review.of_kind("alert")[:-ALERT_MAX])

    def settle(self, monitors: dict[str, dict[str, Any]], printers: "PrinterRegistry", responding: set[str], wanted: bool) -> bool:
        """Ends the running review of every monitor whose print is over.

        A print is over once its printer positively reports it is idle or has
        failed, or the monitor is switched off. A monitor with no printer has
        no print end, so its print is over after a day. A pause is part of the
        same print, and a printer that cannot be read keeps the review running. So
        does a defect response still in flight, since the command that stops a
        print is sent before the frame that fired it is kept. A print with no
        frames kept has nothing to review, so it never waits for one.

        Args:
            monitors: Every monitor record by id.
            printers: The printer registry.
            responding: Ids of the monitors with a defect response in flight.
            wanted: Whether finished prints should wait to be reviewed.

        Returns:
            Whether any review ended.
        """
        ended = False
        now = time.time()
        for review in [review for review in self._reviews.values() if review.ended is None and review.monitor_id not in responding]:
            monitor = monitors.get(review.monitor_id)
            printer = printers.get(monitor.get("printer_id") or "") if monitor else None
            day_long = monitor and not monitor.get("printer_id") and now - review.started >= UNLINKED_PRINT_S
            if monitor and monitor.get("enabled") and not (printer and printer.reported_status in ENDED_STATUSES) and not day_long:
                continue
            review.ended = now
            review.status = "ready" if wanted and review.frames else "dismissed"
            ended = True
        return ended

    def submit(self, review_id: str, failures: set[str], removed: set[str], printer: str) -> Review:
        """Records the reviewer's choices for a finished print, ready to send.

        Frames an earlier send already got into the inbox, and that are still
        chosen, stay sent.

        Args:
            review_id: The review being sent.
            failures: Ids of the frames that show a failure. Every other kept frame is good.
            removed: Ids of the frames the reviewer chose not to send.
            printer: The printer model the reviewer typed, or an empty string.

        Raises:
            LookupError: If there is no such review.
            ValueError: If the print is still running, was already sent, or no
                frame or more than a day's frames are left to send.
        """
        review = self._reviews.get(review_id)
        if review is None:
            raise LookupError(f"no review {review_id}")
        if review.status in ("running", "sent"):
            raise ValueError("a print is reviewed once, after it has finished")
        labels = {frame["id"]: "failure" if frame["id"] in failures else "good" for frame in review.frames if frame["id"] not in removed}
        if not labels:
            raise ValueError("there are no frames left to send")
        if len(labels) > FRAMES_PER_DAY:
            raise ValueError(f"a print sends at most {FRAMES_PER_DAY} frames, as many as the inbox takes from a hub in a day")
        sent = [frame_id for frame_id in (review.submission or {}).get("sent", []) if frame_id in labels]
        review.submission = {"labels": labels, "printer": printer, "sent": sent, "code": None, "retry_at": None}
        review.status = "queued"
        return review

    def dismiss(self, review_id: str) -> None:
        """Marks a finished print as one the reviewer chose not to send, keeping its frames.

        Raises:
            LookupError: If there is no such review.
            ValueError: If the print is still running or was already sent.
        """
        review = self._reviews.get(review_id)
        if review is None:
            raise LookupError(f"no review {review_id}")
        if review.status in ("running", "sent"):
            raise ValueError("only a finished, unsent print can be dismissed")
        review.submission, review.status = None, "skipped"

    async def stop_asking(self) -> None:
        """Dismisses every print waiting to be reviewed or sent, and keeps only alert frames.

        The alert frames stay because the risk history shows them. A print
        still running loses the frames kept so far and is dismissed when it
        ends, and so does a frame that was still being stored. Every print is
        settled and every file is tried even when one cannot be deleted.

        Raises:
            OSError: If a frame's file could not be deleted, once all the rest were.
        """
        self._stops += 1
        reviews = list(self._reviews.values())
        for review in reviews:
            if review.status in ("ready", "queued"):
                review.submission, review.status = None, "dismissed"
        outcomes = await asyncio.gather(*(self._drop(review, [frame for frame in review.frames if frame["kind"] != "alert"]) for review in reviews), return_exceptions=True)
        _raise_first(outcomes)

    def due(self, now: float) -> list[Review]:
        """The queued reviews whose retry time has passed, or whose send was cut short before it set one."""
        return [review for review in self._reviews.values() if review.status == "queued" and (review.submission["retry_at"] or 0.0) <= now]

    async def forget(self, monitor_id: str) -> None:
        """Deletes every review of a monitor, with their frames.

        Every review is forgotten and every file is tried even when one cannot be deleted.

        Raises:
            OSError: If a frame's file could not be deleted, once all the rest were.
        """
        reviews = [review for review in self._reviews.values() if review.monitor_id == monitor_id]
        for review in reviews:
            self._reviews.pop(review.id)
        outcomes = await asyncio.gather(*(self._drop(review, list(review.frames)) for review in reviews), return_exceptions=True)
        _raise_first(outcomes)

    def _running(self, monitor_id: str) -> Review | None:
        return next((review for review in self._reviews.values() if review.monitor_id == monitor_id and review.ended is None), None)

    async def _begin(self, monitor_id: str, ts: float) -> Review:
        """Opens a review, dropping the oldest finished ones to stay within the caps.

        Prints still running are not counted, so a hub with many monitors keeps finished ones too.
        A print queued to send is never dropped, since it leaves when it is sent or dismissed, and
        is not counted either, or enough of them would have each new print drop the one before it.
        A print left with no frames goes before any that has some.
        """
        droppable = sorted(
            (review for review in self._reviews.values() if review.ended is not None and review.status != "queued"),
            key=lambda review: (bool(review.frames), review.started),
        )
        review = Review(id=uuid.uuid4().hex[:12], monitor_id=monitor_id, started=ts, spacing_s=SPACED_START_S)
        self._reviews[review.id] = review
        while droppable and (len(droppable) >= REVIEW_MAX or self._stored_bytes() > BYTES_MAX):
            await self._discard(droppable.pop(0))
        return review

    def _stored_bytes(self) -> int:
        return sum(frame["size"] for review in self._reviews.values() for frame in review.frames)

    async def _jpeg(self, frame: Frame) -> bytes | None:
        """Encodes a frame at the size kept for review and sent for training, or None if it could not be."""
        return await self._platform.encode_jpeg(await asyncio.to_thread(vision.shrink, frame.rgb, SHORTEST_PX))

    async def _keep(self, review: Review, frame: Frame, record: dict[str, Any], stops: int) -> None:
        """Stores a frame, unless its review was deleted or the review was switched off since ``stops`` was read."""
        jpeg = await self._jpeg(frame)
        if not jpeg:
            return
        frame_id = uuid.uuid4().hex[:12]
        size = await self._platform.files.store(frame_key(review.id, frame_id), as_chunks(jpeg))
        if self._reviews.get(review.id) is not review or (record["kind"] != "alert" and self._stops != stops):
            await self._platform.files.remove(frame_key(review.id, frame_id))
            return
        review.frames.append({"id": frame_id, **record, "size": size})

    async def _drop(self, review: Review, frames: list[dict[str, Any]]) -> None:
        """Forgets frames before deleting their files, so two drops that overlap cannot trip over each other.

        Raises:
            OSError: If a file could not be deleted, once the rest were tried.
        """
        review.frames = [kept for kept in review.frames if kept not in frames]
        outcomes = await asyncio.gather(*(self._platform.files.remove(frame_key(review.id, frame["id"])) for frame in frames), return_exceptions=True)
        _raise_first(outcomes)

    async def _discard(self, review: Review) -> None:
        """Forgets a review before deleting its files, so two prints that begin together cannot both evict it."""
        self._reviews.pop(review.id, None)
        await self._drop(review, list(review.frames))
