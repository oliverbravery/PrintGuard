"""Adapter contracts: notifier payloads, integration request shapes,
multipart encoding, printer sanitisation and the vision score maths."""

from __future__ import annotations

import json as jsonlib
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from printguard.engine import vision
from printguard.engine.cameras import webrtc_endpoint, whep_endpoint
from printguard.engine.integrations import INTEGRATIONS, DeviceAction, DeviceState, DeviceStatus, IntegrationAdapter
from printguard.engine.integrations.elegoo import ElegooAdapter
from printguard.engine.monitors import monitor_watching, sanitise_monitor
from printguard.engine.notifiers import NOTIFIERS
from printguard.engine.adapters import multipart_form
from printguard.engine.printers import sanitise_printer
from printguard.engine.registry import Printer, PrinterRegistry

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


class RoutedHttp(RecordingHttp):
    """Recording stand-in answering each URL substring with its own status and body."""

    def __init__(self, routes: dict[str, tuple[int, Any]]) -> None:
        super().__init__()
        self.routes = routes

    async def __call__(self, method, url, *, headers=None, json=None, data=None, timeout=10.0):
        await super().__call__(method, url, headers=headers, json=json, data=data, timeout=timeout)
        return next((answer for key, answer in self.routes.items() if key in url), (404, {}))


OCTOPRINT_HEATERS = {"temperature": {"tool0": {"actual": 209.6, "target": 210.0, "offset": 0}, "bed": {"actual": 60.2, "target": 60.0, "offset": 0}}}


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


async def test_pushover_attaches_snapshot_as_multipart() -> None:
    http = RecordingHttp(body={"status": 1})
    await NOTIFIERS["pushover"].send(http, {"api_token": "ap", "user_key": "uk"}, "T", "B", JPEG)
    call = http.last
    assert (call["method"], call["url"]) == ("POST", "https://api.pushover.net/1/messages.json")
    assert call["headers"]["Content-Type"].startswith("multipart/form-data")
    assert b'name="token"\r\n\r\nap\r\n' in call["data"]
    assert b'name="user"\r\n\r\nuk\r\n' in call["data"]
    assert b'name="message"\r\n\r\nB\r\n' in call["data"]
    assert b'name="attachment"; filename="snapshot.jpg"' in call["data"]
    assert JPEG in call["data"]


async def test_pushover_posts_form_without_snapshot() -> None:
    http = RecordingHttp(body={"status": 1})
    await NOTIFIERS["pushover"].send(http, {"api_token": "ap", "user_key": "uk"}, "T", "B", None)
    call = http.last
    assert call["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert call["data"] == b"token=ap&user=uk&title=T&message=B&priority=1"


async def test_pushover_surfaces_api_errors() -> None:
    http = RecordingHttp(status=400, body={"status": 0, "errors": ["application token is invalid"]})
    with pytest.raises(RuntimeError, match="application token is invalid"):
        await NOTIFIERS["pushover"].send(http, {"api_token": "x", "user_key": "y"}, "T", "B", None)


async def test_pushover_sends_the_configured_priority() -> None:
    http = RecordingHttp(body={"status": 1})
    await NOTIFIERS["pushover"].send(http, {"api_token": "ap", "user_key": "uk", "priority": "-1"}, "T", "B", None)
    assert http.last["data"] == b"token=ap&user=uk&title=T&message=B&priority=-1"


async def test_pushover_keeps_a_numeric_priority() -> None:
    for value, expected in ((0, b"priority=0"), (-1, b"priority=-1")):
        http = RecordingHttp(body={"status": 1})
        await NOTIFIERS["pushover"].send(http, {"api_token": "ap", "user_key": "uk", "priority": value}, "T", "B", None)
        assert http.last["data"].endswith(expected), value


async def test_pushover_defaults_priority_when_unset_or_invalid() -> None:
    for config in (
        {"api_token": "ap", "user_key": "uk"},
        {"api_token": "ap", "user_key": "uk", "priority": ""},
        {"api_token": "ap", "user_key": "uk", "priority": "2"},
    ):
        http = RecordingHttp(body={"status": 1})
        await NOTIFIERS["pushover"].send(http, config, "T", "B", None)
        assert http.last["data"].endswith(b"priority=1"), config


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


async def test_native_delivers_with_snapshot_written_to_disk(monkeypatch) -> None:
    sent: list[Any] = []

    async def deliver(title: str, body: str, snapshot: Any) -> None:
        sent.append((title, body, snapshot))

    monkeypatch.setattr(NOTIFIERS["native"], "_deliver", deliver)
    await NOTIFIERS["native"].send(None, {}, "Title", "Body", JPEG)
    title, body, snapshot = sent[-1]
    assert (title, body) == ("Title", "Body")
    assert snapshot is not None and snapshot.read_bytes() == JPEG, "the snapshot is written where the OS can attach it"


async def test_native_delivers_text_without_snapshot(monkeypatch) -> None:
    sent: list[Any] = []

    async def deliver(title: str, body: str, snapshot: Any) -> None:
        sent.append(snapshot)

    monkeypatch.setattr(NOTIFIERS["native"], "_deliver", deliver)
    await NOTIFIERS["native"].send(None, {}, "T", "B", None)
    assert sent == [None], "no snapshot means no attachment"


def test_native_runs_in_the_desktop_app_only() -> None:
    assert NOTIFIERS["native"].browser_ok is False
    assert NOTIFIERS["native"].desktop_only is True


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
    assert state.nozzle is None and state.bed is None and state.remaining_s is None
    assert [call["url"] for call in http.calls] == ["http://op/api/job", "http://op/api/printer?exclude=sd,state"]
    assert http.last["headers"] == {"X-Api-Key": "k"}


async def test_octoprint_reads_heaters_and_time_left() -> None:
    job = {"state": "Printing", "progress": {"completion": 42.0, "printTimeLeft": 4321}, "job": {"file": {"name": "x.gcode"}}}
    http = RoutedHttp({"/api/job": (200, job), "/api/printer": (200, OCTOPRINT_HEATERS)})
    state = await INTEGRATIONS["octoprint"].fetch_state(http, {"base_url": "http://op", "api_key": "k"})
    assert state.remaining_s == 4321
    assert state.public()["nozzle"] == {"actual": 209.6, "target": 210.0}
    assert state.public()["bed"] == {"actual": 60.2, "target": 60.0}
    disconnected = RoutedHttp({"/api/job": (200, {"state": "Offline"}), "/api/printer": (409, "Printer is not operational")})
    state = await INTEGRATIONS["octoprint"].fetch_state(disconnected, {"base_url": "http://op", "api_key": "k"})
    assert state.status is DeviceStatus.OFFLINE and state.nozzle is None, "a 409 from /api/printer means no heaters, not a failure"


async def test_octoprint_heater_targets() -> None:
    http = RecordingHttp(status=204)
    await INTEGRATIONS["octoprint"].heat(http, {"base_url": "http://op/", "api_key": "k"}, "nozzle", 215.0)
    assert (http.last["method"], http.last["url"]) == ("POST", "http://op/api/printer/tool")
    assert http.last["json"] == {"command": "target", "targets": {"tool0": 215.0}}
    assert http.last["headers"] == {"X-Api-Key": "k"}
    await INTEGRATIONS["octoprint"].heat(http, {"base_url": "http://op"}, "bed", 0.0)
    assert http.last["url"] == "http://op/api/printer/bed"
    assert http.last["json"] == {"command": "target", "target": 0.0}
    with pytest.raises(RuntimeError, match="409"):
        await INTEGRATIONS["octoprint"].heat(RecordingHttp(status=409), {"base_url": "http://op"}, "nozzle", 200.0)


async def test_octoprint_unreachable_is_offline() -> None:
    state = await INTEGRATIONS["octoprint"].fetch_state(RecordingHttp(status=502, body="bad gateway"), {"base_url": "http://op"})
    assert state.status is DeviceStatus.OFFLINE


async def test_octoprint_exposes_webcam_stream() -> None:
    http = RecordingHttp(body={"webcam": {"streamUrl": "/webcam/?action=stream"}})
    cams = await INTEGRATIONS["octoprint"].cameras(http, {"base_url": "http://op:5000", "api_key": "k"})
    assert http.last["url"] == "http://op:5000/api/settings"
    assert http.last["headers"] == {"X-Api-Key": "k"}
    assert cams == [
        {"key": "webcam", "name": "OctoPrint webcam", "source": {"kind": "url", "url": "http://op:5000/webcam/?action=stream"}}
    ]


async def test_octoprint_reads_19_plus_classicwebcam_location() -> None:
    http = RecordingHttp(body={"webcam": {}, "plugins": {"classicwebcam": {"stream": "http://cam.lan:8080/stream"}}})
    cams = await INTEGRATIONS["octoprint"].cameras(http, {"base_url": "http://op", "api_key": "k"})
    assert cams[0]["source"]["url"] == "http://cam.lan:8080/stream", "an absolute stream URL is used as-is"


async def test_octoprint_without_a_webcam_exposes_nothing() -> None:
    http = RecordingHttp(body={"webcam": {"streamUrl": ""}})
    assert await INTEGRATIONS["octoprint"].cameras(http, {"base_url": "http://op", "api_key": "k"}) == []
    assert await INTEGRATIONS["octoprint"].cameras(RecordingHttp(status=502), {"base_url": "http://op"}) == []


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
    body = {
        "result": {
            "status": {
                "print_stats": {"state": text, "filename": "y.gcode", "print_duration": 600.0},
                "virtual_sdcard": {"progress": 0.375},
                "extruder": {"temperature": 209.8, "target": 210.0, "power": 0.4},
                "heater_bed": {"temperature": 59.9, "target": 60.0, "power": 0.2},
            }
        }
    }
    http = RecordingHttp(body=body)
    state = await INTEGRATIONS["klipper"].fetch_state(http, {"base_url": "http://kl"})
    assert http.last["url"] == "http://kl/printer/objects/query?print_stats&virtual_sdcard&extruder&heater_bed"
    assert state.status is expected
    assert state.progress == 37.5
    assert state.job == "y.gcode"
    assert state.remaining_s == 1000, "the time left is projected from the run time against the file position"
    assert state.public()["nozzle"] == {"actual": 209.8, "target": 210.0}
    assert state.public()["bed"] == {"actual": 59.9, "target": 60.0}


async def test_klipper_without_progress_has_no_time_left() -> None:
    body = {"result": {"status": {"print_stats": {"state": "standby", "print_duration": 0.0}, "virtual_sdcard": {"progress": 0.0}}}}
    state = await INTEGRATIONS["klipper"].fetch_state(RecordingHttp(body=body), {"base_url": "http://kl"})
    assert state.remaining_s is None and state.nozzle is None


async def test_klipper_heater_targets_go_through_gcode_script() -> None:
    http = RecordingHttp()
    await INTEGRATIONS["klipper"].heat(http, {"base_url": "http://kl/", "api_key": "kk"}, "nozzle", 215.0)
    assert (http.last["method"], http.last["url"]) == ("POST", "http://kl/printer/gcode/script")
    assert http.last["json"] == {"script": "SET_HEATER_TEMPERATURE HEATER=extruder TARGET=215"}
    assert http.last["headers"] == {"X-Api-Key": "kk"}
    await INTEGRATIONS["klipper"].heat(http, {"base_url": "http://kl"}, "bed", 0.0)
    assert http.last["json"] == {"script": "SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET=0"}
    with pytest.raises(RuntimeError, match="bed"):
        await INTEGRATIONS["klipper"].heat(RecordingHttp(status=400), {"base_url": "http://kl"}, "bed", 60.0)


async def test_klipper_actions_and_auth() -> None:
    http = RecordingHttp()
    await INTEGRATIONS["klipper"].send(http, {"base_url": "http://kl/", "api_key": "kk"}, DeviceAction.CANCEL)
    assert http.last["url"] == "http://kl/printer/print/cancel"
    assert http.last["headers"] == {"X-Api-Key": "kk"}

    state = await INTEGRATIONS["klipper"].fetch_state(RecordingHttp(status=500, body={}), {"base_url": "http://kl"})
    assert state.status is DeviceStatus.OFFLINE

    with pytest.raises(RuntimeError, match="pause"):
        await INTEGRATIONS["klipper"].send(RecordingHttp(status=400), {"base_url": "http://kl"}, DeviceAction.PAUSE)


async def test_klipper_lists_enabled_webcams() -> None:
    body = {
        "result": {
            "webcams": [
                {"name": "Nozzle", "uid": "u1", "stream_url": "/webcam/?action=stream", "enabled": True},
                {"name": "Disabled", "uid": "u2", "stream_url": "/webcam2/?action=stream", "enabled": False},
                {"name": "No stream", "uid": "u3", "stream_url": "", "enabled": True},
            ]
        }
    }
    cams = await INTEGRATIONS["klipper"].cameras(RecordingHttp(body=body), {"base_url": "http://kl:7125"})
    assert cams == [
        {"key": "u1", "name": "Nozzle", "source": {"kind": "url", "url": "http://kl/webcam/?action=stream"}}
    ], "only enabled webcams with a stream are exposed, keyed by uid and resolved to the host's web port not the API port"


async def test_klipper_camera_streamer_webrtc_falls_back_to_mjpeg() -> None:
    body = {
        "result": {
            "webcams": [
                {
                    "name": "Chamber",
                    "uid": "u1",
                    "service": "webrtc-camerastreamer",
                    "stream_url": "/webcam/webrtc",
                    "snapshot_url": "/webcam/?action=snapshot",
                    "enabled": True,
                }
            ]
        }
    }
    cams = await INTEGRATIONS["klipper"].cameras(RecordingHttp(body=body), {"base_url": "http://kl:7125"})
    assert cams == [
        {"key": "u1", "name": "Chamber", "source": {"kind": "url", "url": "http://kl/webcam/?action=stream"}}
    ], "a WebRTC-only camera-streamer feed is registered via the MJPEG endpoint derived from its snapshot URL"


async def test_klipper_resolves_crowsnest_v5_webcams_to_mjpeg() -> None:
    """Real /server/webcams/list from a Crowsnest V5 / camera-streamer setup (issue #64)."""
    body = {"result": {"webcams": [
        {"name": "mjpeg", "enabled": True, "service": "uv4l-mjpeg",
         "stream_url": "/webcam/?action=stream", "snapshot_url": "/webcam/?action=snapshot",
         "uid": "9765408a-3251-40b1-836a-890c4db37aca"},
        {"name": "rtc", "enabled": True, "service": "webrtc-camerastreamer",
         "stream_url": "/webcam/webrtc", "snapshot_url": "/webcam/?action=snapshot",
         "uid": "e61f80ed-5eb9-4838-8579-4d8a38b061da"},
    ]}}
    cams = await INTEGRATIONS["klipper"].cameras(RecordingHttp(body=body), {"base_url": "http://printer.local:7125"})
    assert cams == [
        {"key": "9765408a-3251-40b1-836a-890c4db37aca", "name": "mjpeg",
         "source": {"kind": "url", "url": "http://printer.local/webcam/?action=stream"}},
        {"key": "e61f80ed-5eb9-4838-8579-4d8a38b061da", "name": "rtc",
         "source": {"kind": "url", "url": "http://printer.local/webcam/?action=stream"}},
    ], "the WebRTC entry is redirected to MJPEG and both resolve to the host's web port, where camera-streamer actually serves frames"


async def test_klipper_webrtc_without_snapshot_derives_mjpeg_from_stream_path() -> None:
    body = {"result": {"webcams": [
        {"name": "Cam", "uid": "u1", "service": "webrtc-camerastreamer", "stream_url": "/webcam/webrtc", "enabled": True},
    ]}}
    cams = await INTEGRATIONS["klipper"].cameras(RecordingHttp(body=body), {"base_url": "http://kl"})
    assert cams[0]["source"]["url"] == "http://kl/webcam/stream", "absent a snapshot URL the MJPEG path is derived from the WebRTC path"


async def test_klipper_preserves_whep_endpoint() -> None:
    body = {"result": {"webcams": [
        {"name": "WHEP", "uid": "u1", "stream_url": "/webcam/whep", "enabled": True},
    ]}}
    assert await INTEGRATIONS["klipper"].cameras(RecordingHttp(body=body), {"base_url": "http://kl"}) == [
        {"key": "u1", "name": "WHEP", "source": {"kind": "url", "url": "http://kl/webcam/whep"}}
    ]


async def test_klipper_without_webcams_api_exposes_nothing() -> None:
    assert await INTEGRATIONS["klipper"].cameras(RecordingHttp(status=404, body={}), {"base_url": "http://kl"}) == []


@pytest.mark.parametrize(
    "url, is_webrtc",
    [
        ("http://pi/webcam/webrtc", True),
        ("webrtc://pi/stream", True),
        ("whep://pi/whep", True),
        ("/webcam/webrtc", True),
        ("http://pi/webcam/?action=stream", False),
        ("http://pi/webcam/?action=snapshot", False),
        ("rtsp://pi:8554/stream.h264", False),
        ("http://pi:8080/stream", False),
    ],
)
def test_webrtc_endpoint_flags_signalling_urls(url: str, is_webrtc: bool) -> None:
    assert webrtc_endpoint(url) is is_webrtc


@pytest.mark.parametrize(
    "url, is_whep",
    [
        ("whep://pi:8889/cam/whep", True),
        ("wheps://pi:8889/cam/whep", True),
        ("https://pi:8889/cam/whep", True),
        ("/cam/whep", True),
        ("http://pi/webcam/webrtc", False),
        ("webrtc://pi/stream", False),
        ("whip://pi/stream", False),
    ],
)
def test_whep_endpoint_requires_explicit_whep_egress(url: str, is_whep: bool) -> None:
    assert whep_endpoint(url) is is_whep


BAMBU_CONFIG = {"host": "192.168.1.70", "serial": "01S00A", "access_code": "12345678"}


@pytest.mark.parametrize(
    ("gcode_state", "expected"),
    [
        ("RUNNING", DeviceStatus.PRINTING),
        ("PREPARE", DeviceStatus.PRINTING),
        ("PAUSE", DeviceStatus.PAUSED),
        ("IDLE", DeviceStatus.IDLE),
        ("FINISH", DeviceStatus.IDLE),
        ("FAILED", DeviceStatus.ERROR),
        ("", DeviceStatus.UNKNOWN),
    ],
)
async def test_bambu_normalises_states(monkeypatch, gcode_state: str, expected: DeviceStatus) -> None:
    report = {
        "gcode_state": gcode_state,
        "mc_percent": 42,
        "subtask_name": "z.3mf",
        "mc_remaining_time": 75,
        "nozzle_temper": 219.5,
        "nozzle_target_temper": 220,
        "bed_temper": 54.9,
        "bed_target_temper": 55,
    }
    monkeypatch.setattr(INTEGRATIONS["bambu"], "_pull_report", lambda config: report)
    state = await INTEGRATIONS["bambu"].fetch_state(None, BAMBU_CONFIG)
    assert state.status is expected
    assert state.progress == 42.0
    assert state.job == "z.3mf"
    assert state.remaining_s == 75 * 60, "the report counts minutes"
    assert state.public()["nozzle"] == {"actual": 219.5, "target": 220.0}
    assert state.public()["bed"] == {"actual": 54.9, "target": 55.0}


async def test_bambu_heater_targets_are_gcode_lines(monkeypatch) -> None:
    published: list[dict[str, Any]] = []
    monkeypatch.setattr(INTEGRATIONS["bambu"], "_publish", lambda config, payload: published.append(payload))
    await INTEGRATIONS["bambu"].heat(None, BAMBU_CONFIG, "nozzle", 220.0)
    await INTEGRATIONS["bambu"].heat(None, BAMBU_CONFIG, "bed", 0.0)
    assert published == [
        {"print": {"sequence_id": "0", "command": "gcode_line", "param": "M104 S220\n"}},
        {"print": {"sequence_id": "0", "command": "gcode_line", "param": "M140 S0\n"}},
    ]


async def test_bambu_silent_printer_is_offline(monkeypatch) -> None:
    monkeypatch.setattr(INTEGRATIONS["bambu"], "_pull_report", lambda config: None)
    state = await INTEGRATIONS["bambu"].fetch_state(None, BAMBU_CONFIG)
    assert state.status is DeviceStatus.OFFLINE


async def test_bambu_command_payloads(monkeypatch) -> None:
    published: list[dict[str, Any]] = []
    monkeypatch.setattr(INTEGRATIONS["bambu"], "_publish", lambda config, payload: published.append(payload))
    for action, command in [(DeviceAction.PAUSE, "pause"), (DeviceAction.RESUME, "resume"), (DeviceAction.CANCEL, "stop")]:
        await INTEGRATIONS["bambu"].send(None, BAMBU_CONFIG, action)
        assert published[-1] == {"print": {"sequence_id": "0", "command": command, "param": ""}}


async def test_bambu_exposes_rtsps_camera_for_x1_h2(monkeypatch) -> None:
    monkeypatch.setattr(INTEGRATIONS["bambu"], "_rtsps_fingerprint", lambda host: "ABCDEF")
    cams = await INTEGRATIONS["bambu"].cameras(None, BAMBU_CONFIG)
    assert cams == [
        {
            "key": "chamber",
            "name": "Chamber camera",
            "source": {
                "kind": "url",
                "url": "rtsps://bblp:12345678@192.168.1.70:322/streaming/live/1",
                "fingerprint": "ABCDEF",
            },
        }
    ]


async def test_bambu_exposes_port6000_camera_for_a1_p1(monkeypatch) -> None:
    monkeypatch.setattr(INTEGRATIONS["bambu"], "_rtsps_fingerprint", lambda host: None)
    monkeypatch.setattr(INTEGRATIONS["bambu"], "_port_open", lambda host, port: port == 6000)
    cams = await INTEGRATIONS["bambu"].cameras(None, BAMBU_CONFIG)
    assert cams == [
        {
            "key": "chamber",
            "name": "Chamber camera",
            "source": {"kind": "bambu", "host": "192.168.1.70", "access_code": "12345678"},
        }
    ], "A1/P1 have no RTSP, so the camera is read over the proprietary port-6000 protocol"


async def test_bambu_without_a_camera_exposes_nothing(monkeypatch) -> None:
    monkeypatch.setattr(INTEGRATIONS["bambu"], "_rtsps_fingerprint", lambda host: None)
    monkeypatch.setattr(INTEGRATIONS["bambu"], "_port_open", lambda host, port: False)
    assert await INTEGRATIONS["bambu"].cameras(None, BAMBU_CONFIG) == []


def test_bambu_runs_in_hub_mode_only() -> None:
    assert INTEGRATIONS["bambu"].browser_ok is False
    assert INTEGRATIONS["octoprint"].browser_ok is True


ELEGOO_CENTAURI_CONFIG = {"family": "centauri", "host": "192.168.1.90", "access_code": "Ab3dEf"}
ELEGOO_MOONRAKER_CONFIG = {"family": "moonraker", "host": "192.168.1.91", "api_key": "secret"}


class FakeCentauri:
    """pycentauri client stand-in for adapter contract tests."""

    def __init__(self, print_status: int = 13, camera_port: int = 3031) -> None:
        self.state = SimpleNamespace(
            print_status=print_status,
            progress=42,
            filename="boat.gcode",
            temp_nozzle=204.7,
            temp_nozzle_target=205.0,
            temp_bed=None,
            temp_bed_target=None,
            raw={"_cc2": {"remaining_time_sec": 900}},
        )
        self.camera_port = camera_port
        self.actions: list[str] = []
        self.targets: list[dict[str, float]] = []
        self.closed = False
        self._closed = False
        self.mainboard_id = "mainboard-id"

    async def status(self) -> Any:
        return self.state

    async def set_temperatures(self, **targets: float) -> None:
        self.targets.append(targets)

    async def pause(self) -> None:
        self.actions.append("pause")

    async def resume(self) -> None:
        self.actions.append("resume")

    async def stop(self) -> None:
        self.actions.append("stop")

    async def close(self) -> None:
        self.closed = True
        self._closed = True


def _fake_centauri(client: FakeCentauri):
    async def connect(config: dict[str, Any]) -> FakeCentauri:
        return client

    return connect


@pytest.mark.parametrize(
    ("print_status", "expected"),
    [
        (13, DeviceStatus.PRINTING),
        (27, DeviceStatus.PRINTING),
        (6, DeviceStatus.PAUSED),
        (0, DeviceStatus.IDLE),
        (9, DeviceStatus.IDLE),
        (14, DeviceStatus.ERROR),
        (99, DeviceStatus.UNKNOWN),
    ],
)
async def test_elegoo_centauri_normalises_states(monkeypatch, print_status: int, expected: DeviceStatus) -> None:
    client = FakeCentauri(print_status)
    monkeypatch.setattr(INTEGRATIONS["elegoo"], "_connect_centauri", _fake_centauri(client))
    state = await INTEGRATIONS["elegoo"].fetch_state(None, ELEGOO_CENTAURI_CONFIG)
    assert state.status is expected
    assert state.progress == 42.0
    assert state.job == "boat.gcode"
    assert state.remaining_s == 900
    assert state.public()["nozzle"] == {"actual": 204.7, "target": 205.0}
    assert state.bed is None, "a heater the printer does not report is absent"
    assert not client.closed


async def test_elegoo_centauri_heater_targets(monkeypatch) -> None:
    client = FakeCentauri()
    monkeypatch.setattr(INTEGRATIONS["elegoo"], "_connect_centauri", _fake_centauri(client))
    await INTEGRATIONS["elegoo"].heat(None, ELEGOO_CENTAURI_CONFIG, "nozzle", 205.0)
    await INTEGRATIONS["elegoo"].heat(None, ELEGOO_CENTAURI_CONFIG, "bed", 0.0)
    assert client.targets == [{"nozzle": 205.0}, {"bed": 0.0}]
    assert not client.closed


async def test_elegoo_centauri_actions_enable_control(monkeypatch) -> None:
    client = FakeCentauri()
    monkeypatch.setattr(INTEGRATIONS["elegoo"], "_connect_centauri", _fake_centauri(client))
    for action in (DeviceAction.PAUSE, DeviceAction.RESUME, DeviceAction.CANCEL):
        await INTEGRATIONS["elegoo"].send(None, ELEGOO_CENTAURI_CONFIG, action)
    assert client.actions == ["pause", "resume", "stop"]


@pytest.mark.parametrize(
    ("port", "url"),
    [(3031, "http://192.168.1.90:3031/video"), (8080, "http://192.168.1.90:8080/video")],
)
async def test_elegoo_centauri_exposes_built_in_camera(monkeypatch, port: int, url: str) -> None:
    monkeypatch.setattr(INTEGRATIONS["elegoo"], "_connect_centauri", _fake_centauri(FakeCentauri(camera_port=port)))
    cameras = await INTEGRATIONS["elegoo"].cameras(None, ELEGOO_CENTAURI_CONFIG)
    assert cameras == [
        {"key": "chamber", "name": "Chamber camera", "source": {"kind": "url", "url": url}}
    ]


async def test_elegoo_centauri_reuses_one_connection(monkeypatch) -> None:
    adapter = ElegooAdapter()
    client = FakeCentauri()
    connections: list[dict[str, Any]] = []

    async def discover_mainboard_id(host: str) -> str:
        return "discovered-id"

    async def connect_auto(host: str, **kwargs: Any) -> FakeCentauri:
        connections.append({"host": host, **kwargs})
        return client

    monkeypatch.setattr(adapter, "_discover_mainboard_id", discover_mainboard_id)
    monkeypatch.setattr("pycentauri.connect_auto", connect_auto)

    await adapter.fetch_state(None, ELEGOO_CENTAURI_CONFIG)
    await adapter.fetch_state(None, ELEGOO_CENTAURI_CONFIG)
    await adapter.cameras(None, ELEGOO_CENTAURI_CONFIG)

    assert connections == [
        {
            "host": "192.168.1.90",
            "access_code": "Ab3dEf",
            "enable_control": True,
            "mainboard_id": "discovered-id",
        }
    ]
    await adapter.close()
    assert client.closed


async def test_elegoo_centauri_reconnects_after_failure(monkeypatch) -> None:
    adapter = ElegooAdapter()

    class FailingCentauri(FakeCentauri):
        async def status(self) -> Any:
            raise RuntimeError("connection lost")

    failed_client = FailingCentauri()
    clients = [failed_client, FakeCentauri()]

    async def discover_mainboard_id(host: str) -> None:
        return None

    async def connect_auto(host: str, **kwargs: Any) -> FakeCentauri:
        return clients.pop(0)

    monkeypatch.setattr(adapter, "_discover_mainboard_id", discover_mainboard_id)
    monkeypatch.setattr("pycentauri.connect_auto", connect_auto)

    with pytest.raises(RuntimeError, match="connection lost"):
        await adapter.fetch_state(None, ELEGOO_CENTAURI_CONFIG)
    assert failed_client.closed
    state = await adapter.fetch_state(None, ELEGOO_CENTAURI_CONFIG)
    assert state.status is DeviceStatus.PRINTING
    await adapter.close()


async def test_elegoo_moonraker_reuses_klipper_protocol() -> None:
    body = {
        "result": {
            "status": {
                "print_stats": {"state": "printing", "filename": "part.gcode"},
                "virtual_sdcard": {"progress": 0.5},
            }
        }
    }
    http = RecordingHttp(body=body)
    state = await INTEGRATIONS["elegoo"].fetch_state(http, ELEGOO_MOONRAKER_CONFIG)
    assert state.status is DeviceStatus.PRINTING
    assert state.progress == 50.0
    assert http.last["url"] == "http://192.168.1.91:7125/printer/objects/query?print_stats&virtual_sdcard&extruder&heater_bed"
    assert http.last["headers"] == {"X-Api-Key": "secret"}
    await INTEGRATIONS["elegoo"].send(http, ELEGOO_MOONRAKER_CONFIG, DeviceAction.PAUSE)
    assert http.last["url"] == "http://192.168.1.91:7125/printer/print/pause"
    await INTEGRATIONS["elegoo"].heat(http, ELEGOO_MOONRAKER_CONFIG, "bed", 60.0)
    assert http.last["url"] == "http://192.168.1.91:7125/printer/gcode/script"
    assert http.last["json"] == {"script": "SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET=60"}


def test_elegoo_runs_in_hub_mode_only() -> None:
    adapter = INTEGRATIONS["elegoo"]
    assert adapter.browser_ok is False
    assert adapter.schema["properties"]["family"]["enum"] == ["centauri", "moonraker"]
    assert adapter.secret_keys() == {"access_code", "api_key"}


PRUSA_CONFIG = {"base_url": "http://192.168.1.80", "password": "secret"}
PRUSA_STATUS = {"printer": {"state": "PRINTING", "temp_nozzle": 214.8, "target_nozzle": 215.0, "temp_bed": 59.6, "target_bed": 60.0}}


def _prusa_job(value: Any):
    async def _job(config: dict[str, Any]) -> Any:
        return value

    return _job


def _prusa_read(job: Any, status: Any = PRUSA_STATUS):
    async def _read(config: dict[str, Any]) -> Any:
        return job, status

    return _read


@pytest.mark.parametrize(
    ("job_state", "expected"),
    [
        ("PRINTING", DeviceStatus.PRINTING),
        ("PAUSED", DeviceStatus.PAUSED),
        ("FINISHED", DeviceStatus.IDLE),
        ("STOPPED", DeviceStatus.IDLE),
        ("ERROR", DeviceStatus.ERROR),
        ("", DeviceStatus.UNKNOWN),
    ],
)
async def test_prusa_normalises_job_states(monkeypatch, job_state: str, expected: DeviceStatus) -> None:
    job = {"id": 3, "state": job_state, "progress": 42, "time_remaining": 1800, "file": {"display_name": "boat.gcode", "name": "BOAT~1.GCO"}}
    monkeypatch.setattr(INTEGRATIONS["prusa"], "_read", _prusa_read(job))
    state = await INTEGRATIONS["prusa"].fetch_state(None, PRUSA_CONFIG)
    assert state.status is expected
    assert state.progress == 42.0
    assert state.job == "boat.gcode"
    assert state.remaining_s == 1800
    assert state.public()["nozzle"] == {"actual": 214.8, "target": 215.0}
    assert state.public()["bed"] == {"actual": 59.6, "target": 60.0}


async def test_prusa_no_active_job_is_idle(monkeypatch) -> None:
    monkeypatch.setattr(INTEGRATIONS["prusa"], "_read", _prusa_read(None))
    state = await INTEGRATIONS["prusa"].fetch_state(None, PRUSA_CONFIG)
    assert state.status is DeviceStatus.IDLE
    assert state.job is None, "204 No Content from /api/v1/job is idle, not a phantom job"
    assert state.public()["bed"] == {"actual": 59.6, "target": 60.0}, "an idle printer still reports its heaters"


async def test_prusa_unreachable_is_offline(monkeypatch) -> None:
    async def boom(config: dict[str, Any]) -> Any:
        raise ConnectionError("no route to printer")

    monkeypatch.setattr(INTEGRATIONS["prusa"], "_read", boom)
    state = await INTEGRATIONS["prusa"].fetch_state(None, PRUSA_CONFIG)
    assert state.status is DeviceStatus.OFFLINE, "an unreachable or unauthorised printer keeps inference watching"


async def test_prusa_falls_back_to_raw_filename(monkeypatch) -> None:
    job = {"id": 1, "state": "PRINTING", "progress": 0, "file": {"name": "BOAT~1.GCO"}}
    monkeypatch.setattr(INTEGRATIONS["prusa"], "_read", _prusa_read(job, {"printer": {}}))
    state = await INTEGRATIONS["prusa"].fetch_state(None, PRUSA_CONFIG)
    assert state.job == "BOAT~1.GCO", "without a display name the raw 8.3 file name is used"
    assert state.nozzle is None and state.remaining_s is None


async def test_prusa_heaters_are_read_only() -> None:
    assert INTEGRATIONS["prusa"].heater_control is False, "PrusaLink has no endpoint that sets a temperature"
    with pytest.raises(RuntimeError, match="cannot set heater targets"):
        await INTEGRATIONS["prusa"].heat(None, PRUSA_CONFIG, "nozzle", 200.0)


async def test_prusa_commands_target_the_active_job_id(monkeypatch) -> None:
    commands: list[tuple[int, DeviceAction]] = []
    monkeypatch.setattr(INTEGRATIONS["prusa"], "_job", _prusa_job({"id": 7, "state": "PRINTING", "progress": 0}))

    async def record(config: dict[str, Any], job_id: int, action: DeviceAction) -> None:
        commands.append((job_id, action))

    monkeypatch.setattr(INTEGRATIONS["prusa"], "_command", record)
    for action in (DeviceAction.PAUSE, DeviceAction.RESUME, DeviceAction.CANCEL):
        await INTEGRATIONS["prusa"].send(None, PRUSA_CONFIG, action)
    assert commands == [(7, DeviceAction.PAUSE), (7, DeviceAction.RESUME), (7, DeviceAction.CANCEL)]


async def test_prusa_send_without_active_job_raises(monkeypatch) -> None:
    monkeypatch.setattr(INTEGRATIONS["prusa"], "_job", _prusa_job(None))
    with pytest.raises(RuntimeError, match="no active job"):
        await INTEGRATIONS["prusa"].send(None, PRUSA_CONFIG, DeviceAction.PAUSE)


def test_prusa_runs_in_hub_mode_only() -> None:
    assert INTEGRATIONS["prusa"].browser_ok is False


def test_sanitise_monitor_clamps_and_defaults() -> None:
    record = sanitise_monitor(
        "m1",
        {
            "name": "   ",
            "threshold": 9,
            "sensitivity": 0,
            "consecutive": 99,
            "cooldown_s": 10_000,
            "on_defect": "explode",
        },
    )
    assert record["name"] == "Monitor"
    assert record["threshold"] == 1.0
    assert record["sensitivity"] == 0.2
    assert record["consecutive"] == 30
    assert record["cooldown_s"] == 600
    assert record["on_defect"] == "none"


def test_sanitise_printer_validates_provider() -> None:
    record = sanitise_printer("p1", {"provider": "octoprint", "config": {"base_url": "http://op"}})
    assert record["provider"] == "octoprint"
    assert record["name"] == INTEGRATIONS["octoprint"].label, "an unnamed printer defaults to its service label"
    assert record["config"] == {"base_url": "http://op"}
    with pytest.raises(ValueError):
        sanitise_printer("p1", {})
    with pytest.raises(ValueError):
        sanitise_printer("p1", {"provider": "nope"})


def test_monitor_watching_fails_towards_watching() -> None:
    printers = PrinterRegistry()
    unlinked = sanitise_monitor("m1", {})
    assert monitor_watching(unlinked, printers), "no printer linked means always watched"

    printer = Printer(id="p1", name="P", provider="octoprint", config={})
    printers.add(printer)
    linked = sanitise_monitor("m1", {"printer_id": "p1"})
    assert monitor_watching(linked, printers), "no state polled yet means watched"
    for status, watched in {
        "printing": True,
        "offline": True,
        "unknown": True,
        "idle": False,
        "paused": False,
        "error": False,
    }.items():
        printer.device_state = {"status": status, "progress": 0.0, "job": None}
        assert monitor_watching(linked, printers) is watched, f"{status} should be watched={watched}"

    printer.device_state = {"status": "printing", "progress": 0.0, "job": None}
    linked["enabled"] = False
    assert not monitor_watching(linked, printers), "disabled monitors are never watched"


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


def test_print_formats_and_heater_control_travel_with_adapter_meta() -> None:
    meta = {m["id"]: (m["formats"], m["heater_control"]) for m in (adapter.meta() for adapter in INTEGRATIONS.values())}
    assert meta == {
        "octoprint": (["gcode", "gco", "g"], True),
        "klipper": (["gcode", "gco", "g"], True),
        "prusa": (["gcode", "bgcode"], False),
        "bambu": (["3mf"], True),
        "elegoo": (["gcode"], True),
    }


async def test_an_adapter_without_uploads_says_so() -> None:
    class Bare(IntegrationAdapter):
        id, label, docs_url, schema = "bare", "Bare", "", {}

        async def fetch_state(self, http, config):
            return DeviceState(DeviceStatus.IDLE)

        async def send(self, http, config, action):
            pass

    assert Bare().formats == () and Bare().heater_control is False
    with pytest.raises(RuntimeError, match="cannot receive print files"):
        await Bare().print_file(None, {}, "x.gcode", b"")
    with pytest.raises(RuntimeError, match="cannot set heater targets"):
        await Bare().heat(None, {}, "nozzle", 200.0)
    assert DeviceState(DeviceStatus.IDLE).public() == {"status": "idle", "progress": 0.0, "job": None, "remaining_s": None, "nozzle": None, "bed": None}


async def test_octoprint_uploads_selected_and_printing() -> None:
    http = RecordingHttp(status=201)
    await INTEGRATIONS["octoprint"].print_file(http, {"base_url": "http://op/", "api_key": "k"}, "benchy.gcode", b"G1 X1\n")
    call = http.last
    assert (call["method"], call["url"]) == ("POST", "http://op/api/files/local")
    assert call["headers"]["X-Api-Key"] == "k" and call["headers"]["Content-Type"].startswith("multipart/form-data")
    assert b'name="select"\r\n\r\ntrue\r\n' in call["data"] and b'name="print"\r\n\r\ntrue\r\n' in call["data"]
    assert b'name="file"; filename="benchy.gcode"\r\nContent-Type: application/octet-stream\r\n\r\nG1 X1\n' in call["data"]
    with pytest.raises(RuntimeError, match="HTTP 415"):
        await INTEGRATIONS["octoprint"].print_file(RecordingHttp(status=415), {"base_url": "http://op", "api_key": "k"}, "x.gcode", b"")


async def test_klipper_uploads_into_gcodes_and_prints() -> None:
    http = RecordingHttp(status=201)
    await INTEGRATIONS["klipper"].print_file(http, {"base_url": "http://mr:7125", "api_key": "s"}, "benchy.gcode", b"G1 X1\n")
    call = http.last
    assert (call["method"], call["url"]) == ("POST", "http://mr:7125/server/files/upload")
    assert call["headers"]["X-Api-Key"] == "s"
    assert b'name="root"\r\n\r\ngcodes\r\n' in call["data"] and b'name="print"\r\n\r\ntrue\r\n' in call["data"]
    assert b'filename="benchy.gcode"' in call["data"]
    with pytest.raises(RuntimeError, match="HTTP 400"):
        await INTEGRATIONS["klipper"].print_file(RecordingHttp(status=400), {"base_url": "http://mr:7125"}, "x.gcode", b"")


async def test_prusa_puts_onto_the_first_available_storage_and_prints_after_upload(monkeypatch) -> None:
    from contextlib import asynccontextmanager

    uploads: list[tuple[str, dict[str, str], bytes]] = []

    class FakeLink:
        async def get_storage(self):
            return [{"path": "/local", "available": False}, {"path": "/usb", "available": True}]

    @asynccontextmanager
    async def link(config):
        yield FakeLink()

    async def upload(config, path, headers, data):
        uploads.append((path, headers, data))

    monkeypatch.setattr(INTEGRATIONS["prusa"], "_link", link)
    monkeypatch.setattr(INTEGRATIONS["prusa"], "_upload", upload)
    await INTEGRATIONS["prusa"].print_file(None, PRUSA_CONFIG, "benchy.bgcode", b"GCDE")
    assert uploads == [
        (
            "/api/v1/files/usb/benchy.bgcode",
            {"Content-Type": "application/octet-stream", "Print-After-Upload": "?1", "Overwrite": "?1"},
            b"GCDE",
        )
    ]


async def test_prusa_without_storage_raises(monkeypatch) -> None:
    from contextlib import asynccontextmanager

    class FakeLink:
        async def get_storage(self):
            return [{"path": "/usb", "available": False}]

    @asynccontextmanager
    async def link(config):
        yield FakeLink()

    monkeypatch.setattr(INTEGRATIONS["prusa"], "_link", link)
    with pytest.raises(RuntimeError, match="no storage"):
        await INTEGRATIONS["prusa"].print_file(None, PRUSA_CONFIG, "benchy.gcode", b"G1")


async def test_bambu_uploads_over_ftps_then_prints_the_plate(monkeypatch) -> None:
    from test_gcode import sliced_3mf

    steps: list[Any] = []
    monkeypatch.setattr(INTEGRATIONS["bambu"], "_upload", lambda config, filename, data: steps.append(("upload", filename, data)))
    monkeypatch.setattr(INTEGRATIONS["bambu"], "_publish", lambda config, payload: steps.append(("publish", payload)))
    data = sliced_3mf(plate=3)
    await INTEGRATIONS["bambu"].print_file(None, BAMBU_CONFIG, "benchy.3mf", data)
    assert steps[0] == ("upload", "benchy.3mf", data), "the file is on the SD card before the print is asked for"
    assert steps[1] == (
        "publish",
        {
            "print": {
                "sequence_id": "0",
                "command": "project_file",
                "param": "Metadata/plate_3.gcode",
                "url": "file:///sdcard/benchy.3mf",
                "subtask_name": "benchy",
                "bed_type": "auto",
                "timelapse": False,
                "bed_leveling": True,
                "flow_cali": False,
                "vibration_cali": False,
                "layer_inspect": False,
                "use_ams": False,
                "ams_mapping": [0],
                "profile_id": "0",
                "project_id": "0",
                "subtask_id": "0",
                "task_id": "0",
            }
        },
    )


async def test_bambu_refuses_an_unsliced_3mf_before_touching_the_printer(monkeypatch) -> None:
    import io
    import zipfile

    touched: list[str] = []
    monkeypatch.setattr(INTEGRATIONS["bambu"], "_upload", lambda config, filename, data: touched.append(filename))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("3D/3dmodel.model", "<model/>")
    with pytest.raises(ValueError, match="not been sliced"):
        await INTEGRATIONS["bambu"].print_file(None, BAMBU_CONFIG, "model.3mf", buffer.getvalue())
    assert touched == []


async def test_elegoo_centauri_uploads_then_starts(monkeypatch) -> None:
    from pathlib import Path

    client = FakeCentauri()
    steps: list[Any] = []

    async def upload_file(path, *, remote_name=None):
        steps.append(("upload", remote_name, Path(path).read_bytes()))
        return remote_name

    async def start_print(filename, *, storage="local"):
        steps.append(("start", filename, storage))

    client.upload_file = upload_file
    client.start_print = start_print
    monkeypatch.setattr(INTEGRATIONS["elegoo"], "_connect_centauri", _fake_centauri(client))
    await INTEGRATIONS["elegoo"].print_file(None, ELEGOO_CENTAURI_CONFIG, "benchy.gcode", b"G1 X1\n")
    assert steps == [("upload", "benchy.gcode", b"G1 X1\n"), ("start", "benchy.gcode", "local")]
    assert not client.closed


async def test_elegoo_moonraker_family_uploads_through_moonraker() -> None:
    http = RecordingHttp(status=201)
    await INTEGRATIONS["elegoo"].print_file(http, ELEGOO_MOONRAKER_CONFIG, "benchy.gcode", b"G1\n")
    assert http.last["url"] == "http://192.168.1.91:7125/server/files/upload"
    assert http.last["headers"]["X-Api-Key"] == "secret"
