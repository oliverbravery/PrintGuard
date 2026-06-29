"""Adapter contracts: notifier payloads, integration request shapes,
multipart encoding, printer sanitisation and the vision score maths."""

from __future__ import annotations

import json as jsonlib
from typing import Any

import numpy as np
import pytest

from printguard.engine import vision
from printguard.engine.cameras import webrtc_endpoint
from printguard.engine.integrations import INTEGRATIONS, DeviceAction, DeviceStatus
from printguard.engine.monitors import monitor_watching, sanitise_monitor
from printguard.engine.notifiers import NOTIFIERS
from printguard.engine.notifiers.base import multipart_form
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


async def test_klipper_skips_webrtc_with_no_ingestible_endpoint() -> None:
    body = {"result": {"webcams": [
        {"name": "WHEP", "uid": "u1", "stream_url": "whep://kl/webcam", "enabled": True},
    ]}}
    assert await INTEGRATIONS["klipper"].cameras(RecordingHttp(body=body), {"base_url": "http://kl"}) == [], \
        "a feed that stays WebRTC with no derivable MJPEG is skipped, never registered as a dead camera"


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
def test_webrtc_endpoint_flags_only_uningestible_streams(url: str, is_webrtc: bool) -> None:
    assert webrtc_endpoint(url) is is_webrtc


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
    report = {"gcode_state": gcode_state, "mc_percent": 42, "subtask_name": "z.3mf"}
    monkeypatch.setattr(INTEGRATIONS["bambu"], "_pull_report", lambda config: report)
    state = await INTEGRATIONS["bambu"].fetch_state(None, BAMBU_CONFIG)
    assert state.status is expected
    assert state.progress == 42.0
    assert state.job == "z.3mf"


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


PRUSA_CONFIG = {"base_url": "http://192.168.1.80", "password": "secret"}


def _prusa_job(value: Any):
    async def _job(config: dict[str, Any]) -> Any:
        return value

    return _job


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
    job = {"id": 3, "state": job_state, "progress": 42, "file": {"display_name": "boat.gcode", "name": "BOAT~1.GCO"}}
    monkeypatch.setattr(INTEGRATIONS["prusa"], "_job", _prusa_job(job))
    state = await INTEGRATIONS["prusa"].fetch_state(None, PRUSA_CONFIG)
    assert state.status is expected
    assert state.progress == 42.0
    assert state.job == "boat.gcode"


async def test_prusa_no_active_job_is_idle(monkeypatch) -> None:
    monkeypatch.setattr(INTEGRATIONS["prusa"], "_job", _prusa_job(None))
    state = await INTEGRATIONS["prusa"].fetch_state(None, PRUSA_CONFIG)
    assert state.status is DeviceStatus.IDLE
    assert state.job is None, "204 No Content from /api/v1/job is idle, not a phantom job"


async def test_prusa_unreachable_is_offline(monkeypatch) -> None:
    async def boom(config: dict[str, Any]) -> Any:
        raise ConnectionError("no route to printer")

    monkeypatch.setattr(INTEGRATIONS["prusa"], "_job", boom)
    state = await INTEGRATIONS["prusa"].fetch_state(None, PRUSA_CONFIG)
    assert state.status is DeviceStatus.OFFLINE, "an unreachable or unauthorised printer keeps inference watching"


async def test_prusa_falls_back_to_raw_filename(monkeypatch) -> None:
    job = {"id": 1, "state": "PRINTING", "progress": 0, "file": {"name": "BOAT~1.GCO"}}
    monkeypatch.setattr(INTEGRATIONS["prusa"], "_job", _prusa_job(job))
    state = await INTEGRATIONS["prusa"].fetch_state(None, PRUSA_CONFIG)
    assert state.job == "BOAT~1.GCO", "without a display name the raw 8.3 file name is used"


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
