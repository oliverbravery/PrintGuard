"""The frames kept from each watched print, for the risk history and for review.

A review is one print as a monitor saw it: every frame that fired an alert, the
highest scoring frames that did not, and a spread of ordinary ones. Consecutive
frames are near-duplicates, so the spread is thinned as a print runs on and a
long print keeps no more than a short one. The JPEGs live in the platform's
file store and the records ride in the persisted state, so both survive a
restart.
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from . import vision
from .bounds import clamp
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
ENDED_STATUSES = ("idle", "error")
STATUSES = ("running", "ready", "dismissed", "queued", "sent")
FRAME_KINDS = ("alert", "near", "spaced")
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
            reviewed, ``dismissed`` when no review is wanted, ``queued`` while
            frames wait on the inbox and ``sent`` when all of them are in.
        submission: What the reviewer chose once they pressed Send: the label
            of every frame they kept, the printer model they typed, the frames
            already sent, and the refusal code and retry time when queued.
        frames: The kept frames in capture order, each with its id, time, score,
            kind (alert, near or spaced), stored size and an alert's action.
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


class ReviewLibrary:
    """Chooses which frames of a print to keep and stores them, within a cap."""

    def __init__(self, platform: Platform) -> None:
        self._platform = platform
        self._reviews: dict[str, Review] = {}
        self._stops = 0

    def restore(self, records: list[dict[str, Any]]) -> None:
        """Loads reviews a previous run persisted."""
        self._reviews.update({record["id"]: Review(**record) for record in records})

    def persisted(self) -> list[dict[str, Any]]:
        """Serialises every review for the state store."""
        return [asdict(review) for review in self._reviews.values()]

    def public(self) -> list[dict[str, Any]]:
        """Summarises every review for the state event."""
        return [review.public() for review in self._reviews.values()]

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

    async def sample(self, monitor: dict[str, Any], frame: Frame, score: float, ts: float) -> bool:
        """Considers one scored frame for a monitor's running print.

        A frame is kept as spaced when the print's current gap has passed since
        the last one, and otherwise as a near miss when it scored under the
        threshold but above the near misses already held.

        Args:
            monitor: The monitor record the score belongs to.
            frame: The frame that produced the score.
            score: Defect score in [0, 1].
            ts: Wall-clock time of the score.

        Returns:
            Whether the kept frames changed.
        """
        score = round(score, 4)
        stops = self._stops
        review = self._running(monitor["id"]) or await self._begin(monitor["id"], ts)
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
            ValueError: If the print is still running, was already sent, or no frame is left to send.
        """
        review = self._reviews.get(review_id)
        if review is None:
            raise LookupError(f"no review {review_id}")
        if review.status in ("running", "sent"):
            raise ValueError("a print is reviewed once, after it has finished")
        labels = {frame["id"]: "failure" if frame["id"] in failures else "good" for frame in review.frames if frame["id"] not in removed}
        if not labels:
            raise ValueError("there are no frames left to send")
        sent = [frame_id for frame_id in (review.submission or {}).get("sent", []) if frame_id in labels]
        review.submission = {"labels": labels, "printer": printer, "sent": sent, "code": None, "retry_at": None}
        review.status = "queued"
        return review

    def dismiss(self, review_id: str) -> None:
        """Stops a finished print waiting to be reviewed, keeping its frames.

        Raises:
            LookupError: If there is no such review.
            ValueError: If the print is still running or was already sent.
        """
        review = self._reviews.get(review_id)
        if review is None:
            raise LookupError(f"no review {review_id}")
        if review.status in ("running", "sent"):
            raise ValueError("only a finished, unsent print can be dismissed")
        review.submission, review.status = None, "dismissed"

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
        """Deletes every review of a monitor, with their frames."""
        for review in [review for review in self._reviews.values() if review.monitor_id == monitor_id]:
            await self._discard(review)

    def _running(self, monitor_id: str) -> Review | None:
        return next((review for review in self._reviews.values() if review.monitor_id == monitor_id and review.ended is None), None)

    async def _begin(self, monitor_id: str, ts: float) -> Review:
        """Opens a review, dropping the oldest finished ones to stay within the caps.

        Prints still running are not counted, so a hub with many monitors keeps finished ones too.
        A print queued to send is never dropped, since it leaves when it is sent or dismissed.
        """
        finished = [review for review in self._reviews.values() if review.ended is not None]
        droppable = sorted((review for review in finished if review.status != "queued"), key=lambda review: review.started)
        review = Review(id=uuid.uuid4().hex[:12], monitor_id=monitor_id, started=ts, spacing_s=SPACED_START_S)
        self._reviews[review.id] = review
        kept = len(finished)
        while droppable and (kept >= REVIEW_MAX or self._stored_bytes() > BYTES_MAX):
            await self._discard(droppable.pop(0))
            kept -= 1
        return review

    def _stored_bytes(self) -> int:
        return sum(frame["size"] for review in self._reviews.values() for frame in review.frames)

    async def _keep(self, review: Review, frame: Frame, record: dict[str, Any], stops: int) -> None:
        """Stores a frame, unless its review was deleted or the review was switched off since ``stops`` was read."""
        small = await asyncio.to_thread(vision.shrink, frame.rgb, SHORTEST_PX)
        jpeg = await self._platform.encode_jpeg(small)
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
