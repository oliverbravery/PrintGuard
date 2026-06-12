"""Adapter contracts: notifier payloads, integration request shapes,
multipart encoding, printer sanitisation and the vision score maths."""

from __future__ import annotations

import json as jsonlib
from typing import Any

import numpy as np
import pytest

from printguard.engine import vision
from printguard.engine.integrations import INTEGRATIONS, DeviceAction, DeviceStatus
from printguard.engine.notifiers import NOTIFIERS
from printguard.engine.notifiers.base import multipart_form
from printguard.engine.printers import printer_watching, sanitise_printer

JPEG = b"\xff\xd8demo-jpeg-bytes"


class RecordingHttp:
    """Platform HTTP stand-in that records every request it receives."""

    def __init__(self, status: int = 200, body: Any = None) -> None:
        self.status = status
        self.body = body
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, method, url, *, headers=None, json=None, data=None, timeout=10.0):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "json": json, "data": data})
        return self.status, self.body

    @property
    def last(self) -> dict[str, Any]:
        return self.calls[-1]


def test_multipart_form_builds_a_well_formed_body() -> None:
    headers, body = multipart_form({"chat_id": "7", "caption": "T\nB"}, "photo", "snap.jpg", JPEG)
    content_type = headers["Content-Type"]
    assert content_type.startswith("multipart/form-data; boundary=")
    boundary = content_type.split("boundary=")[1].encode()
    assert body.startswith(b"--" + boundary)
    assert body.endswith(b"--" + boundary + b"--\r\n")
    assert b'name="chat_id"\r\n\r\n7\r\n' in body
    assert b'name="caption"\r\n\r\nT\nB\r\n' in body
    assert b'name="photo"; filename="snap.jpg"' in body
    assert b"Content-Type: image/jpeg" in body
    assert JPEG in body


async def test_ntfy_attaches_snapshot_with_token() -> None:
    http = RecordingHttp()
    await NOTIFIERS["ntfy"].send(http, {"url": "https://ntfy.sh/t", "token": "tk"}, "Title", "Body", JPEG)
    call = http.last
    assert (call["method"], call["url"]) == ("PUT", "https://ntfy.sh/t")
    assert call["data"] == JPEG
    assert call["headers"]["Title"] == "Title"
    assert call["headers"]["Message"] == "Body"
    assert call["headers"]["Filename"] == "snapshot.jpg"
    assert call["headers"]["Authorization"] == "Bearer tk"


async def test_ntfy_posts_text_without_snapshot() -> None:
    http = RecordingHttp()
    await NOTIFIERS["ntfy"].send(http, {"url": "https://ntfy.sh/t"}, "Title", "Body", None)
    call = http.last
    assert call["method"] == "POST"
    assert call["data"] == b"Body"
    assert "Authorization" not in call["headers"]


async def test_ntfy_raises_on_rejection() -> None:
    with pytest.raises(RuntimeError, match="HTTP 403"):
        await NOTIFIERS["ntfy"].send(RecordingHttp(status=403), {"url": "u"}, "T", "B", None)


async def test_telegram_sends_photo_as_multipart() -> None:
    http = RecordingHttp(body={"ok": True})
    await NOTIFIERS["telegram"].send(http, {"bot_token": "12:ab", "chat_id": "77"}, "T", "B", JPEG)
    call = http.last
    assert call["url"] == "https://api.telegram.org/bot12:ab/sendPhoto"
    assert call["headers"]["Content-Type"].startswith("multipart/form-data")
    assert b'name="chat_id"\r\n\r\n77' in call["data"]
    assert b"T\nB" in call["data"]
    assert JPEG in call["data"]


async def test_telegram_text_message_without_snapshot() -> None:
    http = RecordingHttp(body={"ok": True})
    await NOTIFIERS["telegram"].send(http, {"bot_token": "12:ab", "chat_id": "77"}, "T", "B", None)
    call = http.last
    assert call["url"].endswith("/sendMessage")
    assert call["json"] == {"chat_id": "77", "text": "T\nB"}


async def test_telegram_surfaces_api_description() -> None:
    http = RecordingHttp(status=400, body={"ok": False, "description": "chat not found"})
    with pytest.raises(RuntimeError, match="chat not found"):
        await NOTIFIERS["telegram"].send(http, {"bot_token": "x", "chat_id": "0"}, "T", "B", None)


async def test_discord_uploads_snapshot_with_payload_json() -> None:
    http = RecordingHttp()
    await NOTIFIERS["discord"].send(http, {"webhook_url": "https://discord.com/api/webhooks/1/a"}, "T", "B", JPEG)
    call = http.last
    assert jsonlib.dumps({"content": "**T**\nB"}).encode() in call["data"]
    assert b'filename="snapshot.jpg"' in call["data"]
    assert JPEG in call["data"]


async def test_discord_posts_json_without_snapshot() -> None:
    http = RecordingHttp()
    await NOTIFIERS["discord"].send(http, {"webhook_url": "https://discord.com/api/webhooks/1/a"}, "T", "B", None)
    assert http.last["json"] == {"content": "**T**\nB"}


async def test_discord_raises_on_rejection() -> None:
    with pytest.raises(RuntimeError, match="HTTP 404"):
        await NOTIFIERS["discord"].send(RecordingHttp(status=404), {"webhook_url": "u"}, "T", "B", None)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Printing", DeviceStatus.PRINTING),
        ("Paused", DeviceStatus.PAUSED),
        ("Operational", DeviceStatus.IDLE),
        ("Offline after error", DeviceStatus.OFFLINE),
        ("Banana", DeviceStatus.UNKNOWN),
    ],
)
async def test_octoprint_normalises_states(text: str, expected: DeviceStatus) -> None:
    http = RecordingHttp(body={"state": text, "progress": {"completion": 42.0}, "job": {"file": {"name": "x.gcode"}}})
    state = await INTEGRATIONS["octoprint"].fetch_state(http, {"base_url": "http://op/", "api_key": "k"})
    assert state.status is expected
    assert state.progress == 42.0
    assert state.job == "x.gcode"
    assert http.last["url"] == "http://op/api/job"
    assert http.last["headers"] == {"X-Api-Key": "k"}


async def test_octoprint_unreachable_is_offline() -> None:
    state = await INTEGRATIONS["octoprint"].fetch_state(RecordingHttp(status=502, body="bad gateway"), {"base_url": "http://op"})
    assert state.status is DeviceStatus.OFFLINE


async def test_octoprint_action_payloads() -> None:
    http = RecordingHttp(status=204)
    await INTEGRATIONS["octoprint"].send(http, {"base_url": "http://op"}, DeviceAction.PAUSE)
    assert http.last["json"] == {"command": "pause", "action": "pause"}
    await INTEGRATIONS["octoprint"].send(http, {"base_url": "http://op"}, DeviceAction.RESUME)
    assert http.last["json"] == {"command": "pause", "action": "resume"}
    await INTEGRATIONS["octoprint"].send(http, {"base_url": "http://op"}, DeviceAction.CANCEL)
    assert http.last["json"] == {"command": "cancel"}
    with pytest.raises(RuntimeError, match="409"):
        await INTEGRATIONS["octoprint"].send(RecordingHttp(status=409), {"base_url": "http://op"}, DeviceAction.PAUSE)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("printing", DeviceStatus.PRINTING),
        ("paused", DeviceStatus.PAUSED),
        ("standby", DeviceStatus.IDLE),
        ("complete", DeviceStatus.IDLE),
        ("cancelled", DeviceStatus.IDLE),
        ("error", DeviceStatus.ERROR),
        ("", DeviceStatus.UNKNOWN),
    ],
)
async def test_klipper_normalises_states(text: str, expected: DeviceStatus) -> None:
    body = {"result": {"status": {"print_stats": {"state": text, "filename": "y.gcode"}, "virtual_sdcard": {"progress": 0.375}}}}
    state = await INTEGRATIONS["klipper"].fetch_state(RecordingHttp(body=body), {"base_url": "http://kl"})
    assert state.status is expected
    assert state.progress == 37.5
    assert state.job == "y.gcode"


async def test_klipper_actions_and_auth() -> None:
    http = RecordingHttp()
    await INTEGRATIONS["klipper"].send(http, {"base_url": "http://kl/", "api_key": "kk"}, DeviceAction.CANCEL)
    assert http.last["url"] == "http://kl/printer/print/cancel"
    assert http.last["headers"] == {"X-Api-Key": "kk"}

    state = await INTEGRATIONS["klipper"].fetch_state(RecordingHttp(status=500, body={}), {"base_url": "http://kl"})
    assert state.status is DeviceStatus.OFFLINE

    with pytest.raises(RuntimeError, match="pause"):
        await INTEGRATIONS["klipper"].send(RecordingHttp(status=400), {"base_url": "http://kl"}, DeviceAction.PAUSE)


def test_sanitise_clamps_and_defaults() -> None:
    record = sanitise_printer(
        "p1",
        {
            "name": "   ",
            "threshold": 9,
            "sensitivity": 0,
            "consecutive": 99,
            "device": {"cooldown_s": 10_000, "on_defect": "explode"},
        },
    )
    assert record["name"] == "Printer"
    assert record["threshold"] == 1.0
    assert record["sensitivity"] == 0.2
    assert record["consecutive"] == 30
    assert record["device"]["cooldown_s"] == 600
    assert record["device"]["on_defect"] == "none"


def test_printer_watching_fails_towards_watching() -> None:
    unlinked = sanitise_printer("p1", {})
    assert printer_watching(unlinked), "no service linked means always watched"

    linked = sanitise_printer("p1", {"device": {"provider": "octoprint"}})
    assert printer_watching(linked), "no state polled yet means watched"
    for status, watched in {
        "printing": True,
        "offline": True,
        "unknown": True,
        "idle": False,
        "paused": False,
        "error": False,
    }.items():
        linked["device_state"] = {"status": status, "progress": 0.0, "job": None}
        assert printer_watching(linked) is watched, f"{status} should be watched={watched}"

    linked["device_state"] = {"status": "printing", "progress": 0.0, "job": None}
    linked["enabled"] = False
    assert not printer_watching(linked), "disabled printers are never watched"


def test_defect_score_scales_with_sensitivity() -> None:
    failing = {"distances": {"success": 4.0, "failure": 2.0}}
    assert vision.defect_score(failing, 0.5) < vision.defect_score(failing, 1.0) < vision.defect_score(failing, 2.0)
    assert vision.defect_score(failing, 1.0) == 0.75
    healthy = {"distances": {"success": 2.0, "failure": 6.0}}
    assert vision.defect_score(healthy, 1.0) == 0.0
    assert vision.defect_score({"distances": {}}, 1.0) == 0.5, "missing distances must sit on the boundary"


def test_classify_rejects_non_finite_embeddings() -> None:
    assets = vision.Assets(
        mean=(0.5, 0.5, 0.5),
        std=(0.25, 0.25, 0.25),
        prototypes={"success": np.zeros(4, np.float32), "failure": np.ones(4, np.float32)},
    )
    bad = vision.classify(np.array([np.nan, 0, 0, 0], dtype=np.float32), assets)
    assert bad["prediction"] == "unknown"
    good = vision.classify(np.zeros(4, np.float32), assets)
    assert good["prediction"] == "success"
    assert good["margin"] == 2.0
