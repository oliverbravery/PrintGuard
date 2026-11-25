"""The frames kept from each watched print, for the risk history and for review.

A review is one print as a monitor saw it: every frame that fired an alert with
the streak behind it, the highest scoring frames over the threshold that fired
nothing and under it, and a spread of ordinary ones. Consecutive frames are
near-duplicates, so the spread is thinned as a print runs on and a long print
keeps no more than a short one. Each frame keeps what was true when it was
scored, so it can be judged later as it was seen then. The JPEGs live in the
platform's file store and the records ride in the persisted state, so both
survive a restart.

A print is also recorded, one frame every few seconds, so its reviewer can
scrub through it and add frames of their own. A recording is one file of
JPEGs written end to end beside an index of fixed-size entries, and lasts only
until the print is reviewed or a set number of days has passed.
"""

from __future__ import annotations

import asyncio
import bisect
import struct
import sys
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field, fields
from typing import TYPE_CHECKING, Any

from . import vision
from .bounds import clamp
from .feedback import FRAMES_PER_DAY
from .integrations import PrintOutcome
from .platform import Frame, Platform, as_chunks

if TYPE_CHECKING:
    from .registry import Printer, PrinterRegistry

SHORTEST_PX = 512
SPACED_START_S = 60.0
SPACED_MAX = 20
HIGHEST_MAX = 5
HIGHEST_APART_S = 60.0
ALERT_MAX = 40
STREAK_MAX = 60
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
FRAME_KINDS = ("alert", "streak", "spike", "near", "spaced", "added")
LABELS = ("failure", "good")
PAUSE_STEPS = {("sent", "paused"): "held", ("held", "printing"): "resumed"}
PAUSES = ("sent", "held", "resumed")
OUTCOMES = tuple(outcome.value for outcome in PrintOutcome)


@dataclass
class Scoring:
    """What was true when a frame was scored, kept beside it for training.

    Attributes:
        model: The detection model that scored it, as ``settings.model`` names it.
        runtime: The runtime the model ran on.
        tiled: Whether its camera has a crop, so it was scored square by square
            and took the worst, rather than by its middle square.
        streak: How many frames in a row, this one counted, scored at or over the
            threshold, which is 0 for one under it.
        status: What the monitor's printer reported, or None with no printer or
            before it has answered.
        progress: How far through the print the printer said it was, or None
            when the printer could not be read.
        threshold: The score the monitor alerts at.
        consecutive: How many frames in a row it alerts after.
        cooldown_s: How long it waits before alerting again.
        on_defect: What it does to the printer when it alerts.
    """

    model: str
    runtime: str
    tiled: bool
    streak: int
    status: str | None
    progress: float | None
    threshold: float
    consecutive: int
    cooldown_s: int
    on_defect: str


SCORED_KEYS = tuple(scored.name for scored in fields(Scoring))


@dataclass
class _Run:
    """The frames over the threshold of a monitor's current streak.

    Attributes:
        held: The last of them, each with its JPEG, or with None for one already
            kept as spaced, waiting to learn whether they build an alert.
        fired: Whether the streak has fired an alert.
    """

    held: deque[tuple[dict[str, Any], bytes | None]] = field(default_factory=deque)
    fired: bool = False


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
            of every frame they kept, the model set on the printer, the frames
            already sent, and the refusal code and retry time when queued.
        frames: The kept frames in capture order, each with its id, time, score,
            kind (alert, streak, spike, near, spaced or added from the
            recording), stored size and ``Scoring``. An alert frame has its
            action and, after a pause, where that pause got to, a frame that
            built an alert names it, and an added frame has the label it was
            added with.
        underway: Whether the printer has reported the print past 0%, which
            spaced frames and near misses wait for.
        outcome: How the print ended, as far as its printer said.
    """

    id: str
    monitor_id: str
    started: float
    spacing_s: float
    ended: float | None = None
    status: str = "running"
    submission: dict[str, Any] | None = None
    frames: list[dict[str, Any]] = field(default_factory=list)
    underway: bool = False
    outcome: str | None = None

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
        if frame["kind"] == "streak" and not isinstance(frame.get("alert"), str):
            raise ValueError("a kept streak frame names no alert")
        if frame.get("pause") not in (None, *PAUSES):
            raise ValueError("a kept alert frame's pause is in no state a pause can be in")
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
    if record.get("outcome") not in (None, *OUTCOMES):
        raise ValueError("it ended in a way no print can")
    if not isinstance(record.get("underway", False), bool):
        raise ValueError("whether it is underway is not a yes or no")
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
        self._unanswered: set[str] = set()
        self._not_prints: list[Review] = []
        self._runs: dict[str, _Run] = {}
        self._firing: dict[str, tuple[str, Scoring]] = {}
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

    def stored_keys(self) -> set[str]:
        """Every file store key a review names, its kept frames and its recording."""
        return {key for review_id, review in self._reviews.items() for key in (recording_key(review_id), index_key(review_id), *(frame_key(review_id, frame["id"]) for frame in review.frames))}

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
        await self._keep(review, {"ts": ts, "score": round(score, 4), "kind": "added", "label": label}, jpeg, self._stops)

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

    async def discard_not_prints(self) -> None:
        """Deletes the files of every watch that ``settle`` found was no print.

        Raises:
            OSError: If a file could not be deleted, once the rest were tried.
        """
        not_prints, self._not_prints = self._not_prints, []
        outcomes = await asyncio.gather(*(self._discard(review) for review in not_prints), return_exceptions=True)
        _raise_first(outcomes)

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
        if self._recordings.get(review.id) is not recording or self._reviews.get(review.id) is not review:
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

    async def sample(self, monitor: dict[str, Any], frame: Frame, score: float, ts: float, scoring: Scoring, fired: bool, recording: bool, answered: bool) -> bool:
        """Considers one scored frame for a monitor's running print.

        Every frame the monitor watches counts, so a print is kept and recorded
        from the moment its monitor starts watching. Spaced frames and near
        misses wait until the print is underway, meaning its printer reports
        printing past 0%, since a printer heating and levelling shows an empty
        bed. A monitor with no printer, or whose printer has not answered yet,
        cannot tell, so they start at once there, as watching does. A frame is kept as
        spaced when the print's current gap has passed since the last one, and
        otherwise as a near miss when it scored under the threshold but above
        the near misses already held.

        A frame at or over the threshold is held until it is known whether it
        builds an alert. The ``consecutive - 1`` held last are the streak behind
        the frame that fires, and are kept with it. One that drops out of that
        window, or whose streak breaks first, is a spike, kept as near misses
        are. One whose streak already fired is neither, since an alert-only
        monitor re-alerts on a lasting defect every cooldown. The frame that
        fires is kept by ``keep_alert``, under an id reserved here before
        anything is awaited, since its response is already scheduled.

        Args:
            monitor: The monitor record the score belongs to.
            frame: The frame that produced the score.
            score: Defect score in [0, 1].
            ts: Wall-clock time of the score.
            scoring: What was true when it was scored.
            fired: Whether it fired an alert.
            recording: Whether prints are recorded for scrubbing in their review.
            answered: Whether the monitor has no printer, or its printer has
                answered since it was linked or its connection was edited.

        Returns:
            Whether the kept frames changed.
        """
        monitor_id = monitor["id"]
        if fired:
            alert_id = uuid.uuid4().hex[:12]
            self._firing[monitor_id] = (alert_id, scoring)
        record = {"ts": ts, "score": round(score, 4), **asdict(scoring)}
        stops = self._stops
        review = self._running(monitor_id)
        if review is None:
            review = await self._begin(monitor_id, ts)
            if not answered:
                self._unanswered.add(review.id)
        elif answered:
            self._unanswered.discard(review.id)
        if recording:
            await self._record(review, frame, record["score"], ts)
        changed = not review.underway and scoring.status == "printing" and (scoring.progress or 0.0) > 0.0
        review.underway = review.underway or changed
        printing = review.underway or not monitor.get("printer_id") or not answered
        over = score >= monitor["threshold"]
        if monitor_id in self._runs and (not over or scoring.streak == 1):
            changed = await self._end_run(review, monitor_id, stops) or changed
        if fired:
            await self._promote(review, monitor_id, alert_id, stops)
            return True
        spaced = review.of_kind("spaced")
        spacing = printing and (not spaced or ts - spaced[-1]["ts"] >= review.spacing_s)
        kept_spaced = None
        if spacing:
            kept_spaced = await self._keep(review, {**record, "kind": "spaced"}, frame, stops)
            if len(spaced) + 1 >= SPACED_MAX:
                await self._drop(review, review.of_kind("spaced")[1::2])
                review.spacing_s *= 2
            changed = True
        if over:
            return await self._hold(review, monitor, record, kept_spaced, frame, stops) or changed
        if spacing or not printing:
            return changed
        return await self._contend(review, "near", record, frame, stops) or changed

    async def _hold(self, review: Review, monitor: dict[str, Any], record: dict[str, Any], spaced: dict[str, Any] | None, frame: Frame, stops: int) -> bool:
        """Holds a frame over the threshold in its monitor's streak, letting the oldest go as a spike once it is too old to build the alert.

        Returns:
            Whether the kept frames changed.
        """
        run = self._runs.setdefault(monitor["id"], _Run())
        if run.fired:
            return False
        run.held.append((spaced, None) if spaced else (record, await self._jpeg(frame)))
        if len(run.held) < monitor["consecutive"]:
            return False
        earliest, jpeg = run.held.popleft()
        return bool(jpeg) and await self._contend(review, "spike", earliest, jpeg, stops)

    async def _end_run(self, review: Review, monitor_id: str, stops: int) -> bool:
        """Ends a monitor's streak, keeping the highest of what it held as spikes unless it fired.

        Returns:
            Whether the kept frames changed.
        """
        run = self._runs.pop(monitor_id)
        if run.fired:
            return False
        changed = False
        for record, jpeg in sorted(((record, jpeg) for record, jpeg in run.held if jpeg), key=lambda held: held[0]["score"], reverse=True):
            changed = await self._contend(review, "spike", record, jpeg, stops) or changed
        return changed

    async def _promote(self, review: Review, monitor_id: str, alert_id: str, stops: int) -> None:
        """Keeps the frames a monitor held as the streak behind the alert it just fired.

        A frame already kept as spaced stays spaced and names the alert too. The
        print keeps at most STREAK_MAX streak frames, dropping the oldest alert's
        whole streak first.
        """
        run = self._runs.setdefault(monitor_id, _Run())
        held, run.held, run.fired = list(run.held), deque(), True
        for record, jpeg in held:
            if jpeg is None:
                record["alert"] = alert_id
            else:
                await self._keep(review, {**record, "kind": "streak", "alert": alert_id}, jpeg, stops)
        streaks = review.of_kind("streak")
        oldest = list(dict.fromkeys(kept["alert"] for kept in streaks))
        dropping: list[dict[str, Any]] = []
        while len(streaks) - len(dropping) > STREAK_MAX:
            first = oldest.pop(0)
            dropping += [kept for kept in streaks if kept["alert"] == first]
        await self._drop(review, dropping)

    async def _contend(self, review: Review, kind: str, record: dict[str, Any], image: Frame | bytes, stops: int) -> bool:
        """Keeps a frame among the highest scoring of its kind, HIGHEST_MAX a print and HIGHEST_APART_S apart.

        Returns:
            Whether it outscored the frames of its kind it competes with.
        """
        rivals = review.of_kind(kind)
        neighbour = next((kept for kept in rivals if abs(record["ts"] - kept["ts"]) < HIGHEST_APART_S), None)
        outscored = neighbour or (min(rivals, key=lambda kept: kept["score"]) if len(rivals) >= HIGHEST_MAX else None)
        if outscored and record["score"] <= outscored["score"]:
            return False
        await self._keep(review, {**record, "kind": kind}, image, stops)
        if outscored:
            await self._drop(review, [outscored])
        return True

    async def keep_alert(self, monitor_id: str, alert: dict[str, Any], frame: Frame) -> None:
        """Keeps the frame that fired an alert in the monitor's running print.

        It is kept under the id ``sample`` reserved for it, with what was true
        when it was scored, so the streak behind it names it. An alert dropped
        for being older than the last ALERT_MAX takes its streak with it. A
        pause the printer took starts out ``sent`` and is followed by ``settle``.
        """
        alert_id, scoring = self._firing.pop(monitor_id, (None, None))
        review = self._running(monitor_id) or await self._begin(monitor_id, alert["ts"])
        record = {"ts": alert["ts"], "score": alert["score"], **(asdict(scoring) if scoring else {}), "kind": "alert", "action": alert["action"]}
        if alert["action"] == "pause":
            record["pause"] = "sent"
        await self._keep(review, record, frame, self._stops, alert_id)
        dropped = {kept["id"] for kept in review.of_kind("alert")[:-ALERT_MAX]}
        await self._drop(review, [kept for kept in review.frames if kept["id"] in dropped or (kept["kind"] == "streak" and kept["alert"] in dropped)])

    def settle(self, monitors: dict[str, dict[str, Any]], printers: "PrinterRegistry", responding: set[str], wanted: bool) -> bool:
        """Follows every running print's printer, and ends the review of each print that is over.

        A print is over once its printer positively reports it is idle or has
        failed, or the monitor is switched off. A monitor with no printer has
        no print end, so its print is over after a day. A pause is part of the
        same print, and a printer that cannot be read keeps the review running. So
        does a defect response still in flight, since the command that stops a
        print is sent before the frame that fired it is kept. A print with no
        frames kept has nothing to review, so it never waits for one.

        A monitor watches a printer it has not heard from yet, as after its
        connection is edited. When that printer's first answer is that it is
        idle or has failed and nothing alerted, what was watched was no print,
        so it is dropped and ``discard_not_prints`` deletes its files.

        A print that ends keeps how, as its printer said on the read that ended
        it, and none when the printer does not say or the print ended by the
        monitor being switched off or a day passing. A pause an alert took
        counts as resumed only once the printer was seen paused and then
        printing again, since a read landing before the pause took effect
        still shows the print running.

        Args:
            monitors: Every monitor record by id.
            printers: The printer registry.
            responding: Ids of the monitors with a defect response in flight.
            wanted: Whether finished prints should wait to be reviewed.

        Returns:
            Whether any review ended or a pause it follows moved on.
        """
        changed = False
        now = time.time()
        for review in [review for review in self._reviews.values() if review.ended is None]:
            monitor = monitors.get(review.monitor_id)
            printer = printers.get(monitor.get("printer_id") or "") if monitor else None
            changed = self._follow_pause(review, printer) or changed
            day_long = monitor and not monitor.get("printer_id") and now - review.started >= UNLINKED_PRINT_S
            over = printer and printer.reported_status in ENDED_STATUSES
            if review.monitor_id in responding or (monitor and monitor.get("enabled") and not over and not day_long):
                continue
            review.ended = now
            review.outcome = printer.device_state["outcome"] if over and printer.device_state else None
            self._runs.pop(review.monitor_id, None)
            if review.id in self._unanswered and over and not review.of_kind("alert"):
                self._reviews.pop(review.id)
                self._not_prints.append(review)
            else:
                review.status = "ready" if wanted and review.frames else "dismissed"
            self._unanswered.discard(review.id)
            changed = True
        return changed

    def _follow_pause(self, review: Review, printer: "Printer | None") -> bool:
        """Moves the latest pause an alert took that is not yet resumed on by what its printer reports.

        Returns:
            Whether it moved on.
        """
        pausing = next((kept for kept in reversed(review.of_kind("alert")) if kept.get("pause") in ("sent", "held")), None)
        step = PAUSE_STEPS.get((pausing["pause"], printer.reported_status)) if pausing and printer else None
        if step:
            pausing["pause"] = step
        return step is not None

    def submit(self, review_id: str, failures: set[str], removed: set[str], printer: str) -> Review:
        """Records the reviewer's choices for a finished print, ready to send.

        Frames an earlier send already got into the inbox, and that are still
        chosen, stay sent.

        Args:
            review_id: The review being sent.
            failures: Ids of the frames that show a failure. Every other kept frame is good.
            removed: Ids of the frames the reviewer chose not to send.
            printer: The model set on the monitor's printer, or an empty string.

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

    async def delete(self, review_id: str) -> None:
        """Deletes a finished print the reviewer chose to ignore, with its frames and recording.

        Raises:
            LookupError: If there is no such review.
            ValueError: If the print is still running or its frames are being sent.
            OSError: If a file could not be deleted, once the rest were tried.
        """
        review = self._reviews.get(review_id)
        if review is None:
            raise LookupError(f"no review {review_id}")
        if review.status in ("running", "queued"):
            raise ValueError("a print can only be ignored once it has finished and is not being sent")
        await self._discard(review)

    async def stop_asking(self) -> None:
        """Dismisses every print waiting to be reviewed or sent, keeps only alert frames and deletes every recording.

        The alert frames stay because the risk history shows them. A print
        still running loses the frames kept so far and is dismissed when it
        ends, and so does a frame that was still being stored. Every print is
        settled and every file is tried even when one cannot be deleted.

        Raises:
            OSError: If a frame's file could not be deleted, once all the rest were.
        """
        self._stops += 1
        self._runs.clear()
        self._firing.clear()
        reviews = list(self._reviews.values())
        for review in reviews:
            if review.status in ("ready", "queued"):
                review.submission, review.status = None, "dismissed"
        recorded = list(self._recordings)
        self._recordings.clear()
        outcomes = await asyncio.gather(
            *(self._drop(review, [frame for frame in review.frames if frame["kind"] != "alert"]) for review in reviews),
            *(self._remove_recording(review_id) for review_id in recorded),
            return_exceptions=True,
        )
        _raise_first(outcomes)

    def due(self, now: float) -> list[Review]:
        """The queued reviews whose retry time has passed, or whose send was cut short before it set one."""
        return [review for review in self._reviews.values() if review.status == "queued" and (review.submission["retry_at"] or 0.0) <= now]

    async def forget(self, monitor_id: str) -> None:
        """Deletes every review of a monitor, with their frames and recordings.

        Every review is forgotten and every file is tried even when one cannot be deleted.

        Raises:
            OSError: If a frame's file could not be deleted, once all the rest were.
        """
        reviews = [review for review in self._reviews.values() if review.monitor_id == monitor_id]
        self._runs.pop(monitor_id, None)
        self._firing.pop(monitor_id, None)
        for review in reviews:
            self._reviews.pop(review.id)
        outcomes = await asyncio.gather(*(self._discard(review) for review in reviews), return_exceptions=True)
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

    async def _keep(self, review: Review, record: dict[str, Any], image: Frame | bytes, stops: int, frame_id: str | None = None) -> dict[str, Any] | None:
        """Stores a frame in capture order, unless its review was deleted or the review was switched off since ``stops`` was read.

        Args:
            review: The print it belongs to.
            record: Its time, score, kind and whatever else is kept of it.
            image: The frame, or its JPEG when that is already encoded.
            stops: How many times the review had been switched off when the frame was considered.
            frame_id: The id reserved for it, if one was.

        Returns:
            Its kept record, or None if it was not kept.
        """
        jpeg = image if isinstance(image, bytes) else await self._jpeg(image)
        if not jpeg:
            return None
        frame_id = frame_id or uuid.uuid4().hex[:12]
        size = await self._platform.files.store(frame_key(review.id, frame_id), as_chunks(jpeg))
        if self._reviews.get(review.id) is not review or (record["kind"] != "alert" and self._stops != stops):
            await self._platform.files.remove(frame_key(review.id, frame_id))
            return None
        kept = {"id": frame_id, **record, "size": size}
        bisect.insort(review.frames, kept, key=lambda frame: frame["ts"])
        return kept

    async def _drop(self, review: Review, frames: list[dict[str, Any]]) -> None:
        """Forgets frames before deleting their files, so two drops that overlap cannot trip over each other.

        Raises:
            OSError: If a file could not be deleted, once the rest were tried.
        """
        review.frames = [kept for kept in review.frames if kept not in frames]
        outcomes = await asyncio.gather(*(self._platform.files.remove(frame_key(review.id, frame["id"])) for frame in frames), return_exceptions=True)
        _raise_first(outcomes)

    async def _discard(self, review: Review) -> None:
        """Forgets a review and its recording before deleting their files, so two prints that begin together cannot both evict it.

        Raises:
            OSError: If a file could not be deleted, once the rest were tried.
        """
        self._reviews.pop(review.id, None)
        self._recordings.pop(review.id, None)
        outcomes = await asyncio.gather(self._drop(review, list(review.frames)), self._remove_recording(review.id), return_exceptions=True)
        _raise_first(outcomes)
