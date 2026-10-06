"""Hub stream routing through MediaMTX."""

from __future__ import annotations

import asyncio
import base64
import json
import socket
import sys
from pathlib import Path

import httpx
import pytest

from printguard.server.mediamtx import EmbeddedMediaMTX, MediaMTX, pull_source

SHIPPED_CONFIG = Path(__file__).parent.parent / "mediamtx.yml"


@pytest.mark.parametrize(
    "url, pulled",
    [
        ("rtsp://cam:8554/live", "rtsp://cam:8554/live"),
        ("rtsps://cam:322/live", "rtsps://cam:322/live"),
        ("rtmp://cam/live", "rtmp://cam/live"),
        ("http://pi/webcam/?action=stream", None),
        ("https://pi/webcam/?action=stream", None),
        ("whep://pi:8889/cam/whep", "whep://pi:8889/cam/whep"),
        ("wheps://pi:8889/cam/whep", "wheps://pi:8889/cam/whep"),
        ("whep://pi:1984/api/webrtc?src=chamber", "whep://pi:1984/api/webrtc?src=chamber"),
        ("http://pi:8889/cam/whep", "whep://pi:8889/cam/whep"),
        ("https://pi:8889/cam/whep", "wheps://pi:8889/cam/whep"),
    ],
)
def test_pull_source_routes_urls(url: str, pulled: str | None) -> None:
    assert pull_source(url) == pulled


@pytest.mark.parametrize("url", ["webrtc://pi/cam", "http://pi/webcam/webrtc", "whip://pi/cam"])
def test_pull_source_rejects_non_whep_webrtc(url: str) -> None:
    with pytest.raises(ValueError, match="does not expose WHEP"):
        pull_source(url)


async def test_managed_pull_sources_start_on_demand() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        await MediaMTX("http://mediamtx", "rtsp://mediamtx", client).ensure_path("camera", "rtsp://camera/live")

    assert json.loads(requests[0].content) == {
        "source": "rtsp://camera/live",
        "sourceOnDemand": True,
        "sourceOnDemandStartTimeout": "30s",
        "sourceOnDemandCloseAfter": "10s",
    }


async def test_control_api_calls_carry_the_login() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"items": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        mediamtx = MediaMTX("http://mediamtx", "rtsp://mediamtx", client, ("printguard", "secret"))
        await mediamtx.list_paths()
        await mediamtx.ensure_path("camera", "rtsp://camera/live")
        await mediamtx.remove_path("camera")

    expected = f"Basic {base64.b64encode(b'printguard:secret').decode()}"
    assert [request.headers["authorization"] for request in requests] == [expected] * 3


async def test_an_existing_path_is_patched() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.startswith("/v3/config/paths/add/"):
            return httpx.Response(400, json={"error": "path already exists"})
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        await MediaMTX("http://mediamtx", "rtsp://mediamtx", client).ensure_path("camera", "rtsp://camera/live")

    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/v3/config/paths/add/camera"),
        ("PATCH", "/v3/config/paths/patch/camera"),
    ]


async def test_an_address_mediamtx_refuses_is_reported_without_its_credentials() -> None:
    requests: list[httpx.Request] = []
    source = "rtsp://admin:hunter22@camera/live"

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(400, json={"error": f"invalid source {source}: only rtsp is supported"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError, match="PrintGuard can't use that address") as refused:
            await MediaMTX("http://mediamtx", "rtsp://mediamtx", client).ensure_path("camera", source)

    assert "only rtsp is supported" in str(refused.value)
    assert "hunter22" not in str(refused.value)
    assert [request.method for request in requests] == ["POST"]


async def test_pull_paths_are_added_again_to_a_server_that_restarted() -> None:
    """A path added through the API is gone when MediaMTX restarts, and a sleeping camera never asks for it again."""
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        mediamtx = MediaMTX("http://mediamtx", "rtsp://mediamtx", client)
        await mediamtx.ensure_path("idle", "rtsps://printer:322/live", "ab12")
        await mediamtx.ensure_path("removed", "rtsp://camera/live")
        await mediamtx.remove_path("removed")
        requests.clear()
        await mediamtx.restore_paths()

    assert [(request.method, request.url.path) for request in requests] == [("POST", "/v3/config/paths/add/idle")]
    assert json.loads(requests[0].content)["source"] == "rtsps://printer:322/live"
    assert json.loads(requests[0].content)["sourceFingerprint"] == "ab12"


async def _nothing() -> None:
    """Stands in for restoring paths where a test never restarts the server."""


async def test_the_supervisor_restores_paths_once_a_restarted_server_answers(tmp_path, monkeypatch) -> None:
    """Only the server started in place of one that exited has anything to be given back."""
    monkeypatch.setattr("printguard.server.mediamtx.RESTART_DELAY_S", 0.05)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    started = tmp_path / "started"
    stand_in = tmp_path / "mediamtx.py"
    stand_in.write_text(
        "import pathlib, socket, sys, time\n"
        f"started = pathlib.Path({str(started)!r})\n"
        f"listener = socket.create_server(('127.0.0.1', {port}))\n"
        "first = not started.exists()\n"
        "started.write_text(started.read_text() + 'x' if started.exists() else 'x')\n"
        "time.sleep(0.5 if first else 60)\n"
    )
    restored = asyncio.Event()
    launches_at_restore: list[str] = []

    async def restore() -> None:
        launches_at_restore.append(started.read_text())
        restored.set()

    server = EmbeddedMediaMTX(sys.executable, str(stand_in), f"http://127.0.0.1:{port}", ("printguard", "secret"), restore)

    await server.start()
    assert not restored.is_set(), "the first start has no paths to give back"
    await asyncio.wait_for(restored.wait(), 15)
    await server.stop()

    assert launches_at_restore == ["xx"]


async def test_a_server_that_cannot_stay_up_is_logged_less_and_less_often(tmp_path, monkeypatch) -> None:
    """A line every restart filled the log tail a bug report attaches within minutes."""
    monkeypatch.setattr("printguard.server.mediamtx.RESTART_DELAY_S", 0)
    monkeypatch.setattr("printguard.server.mediamtx.READY_TIMEOUT_S", 1.0)
    launches = tmp_path / "launches"
    launches.write_text("")
    stand_in = tmp_path / "mediamtx.py"
    stand_in.write_text(f"open({str(launches)!r}, 'a').write('x')\nraise SystemExit(1)\n")
    logged: list[str] = []
    monkeypatch.setattr("printguard.server.mediamtx.logger.error", lambda message, *args: logged.append(message % args))
    server = EmbeddedMediaMTX(sys.executable, str(stand_in), "http://127.0.0.1:9", ("printguard", "secret"), _nothing)

    await server.start()
    async with asyncio.timeout(30):
        while len(launches.read_text()) < 9:
            await asyncio.sleep(0.01)
    await server.stop()

    exits = len(launches.read_text())
    restarts = [line for line in logged if line == "MediaMTX exited (code 1); restarting"]
    assert len(restarts) in ((exits - 1).bit_length(), exits.bit_length()), "one line for the first, second, fourth and eighth exit in a row"


def test_the_shipped_config_grants_the_control_api_to_nobody() -> None:
    """A web page in a browser on the same computer can reach the loopback listeners.

    The control API reads camera URLs with their passwords and can add a path
    that runs a command, so nobody may hold it until the hub adds its own login,
    and neither listener may answer a page from another origin.
    """
    config = SHIPPED_CONFIG.read_text()
    users = config.split("authInternalUsers:\n")[1].split("\n\n")[0]

    assert users == (
        "  - user: any\n"
        "    permissions:\n"
        "      - action: publish\n"
        "      - action: read\n"
        "      - action: playback"
    )
    assert "action: api" not in config
    assert "\napiAllowOrigins: []\n" in config
    assert "\nhlsAllowOrigins: []\n" in config


async def test_the_bundled_server_is_handed_the_api_login_in_its_environment(tmp_path) -> None:
    """The login is appended after the one user the shipped config declares."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    seen = tmp_path / "environment.json"
    stand_in = tmp_path / "mediamtx.py"
    stand_in.write_text(
        "import json, os, socket, time\n"
        f"json.dump({{k: v for k, v in os.environ.items() if k.startswith('MTX_')}}, open({str(seen)!r}, 'w'))\n"
        f"listener = socket.create_server(('127.0.0.1', {port}))\n"
        "time.sleep(60)\n"
    )
    server = EmbeddedMediaMTX(sys.executable, str(stand_in), f"http://127.0.0.1:{port}", ("printguard", "secret"), _nothing)

    await server.start()
    await server.stop()

    assert json.loads(seen.read_text()) == {
        "MTX_AUTHINTERNALUSERS_1_USER": "printguard",
        "MTX_AUTHINTERNALUSERS_1_PASS": "secret",
        "MTX_AUTHINTERNALUSERS_1_PERMISSIONS_0_ACTION": "api",
    }


async def test_stop_wins_against_a_server_that_is_still_launching(tmp_path) -> None:
    stand_in = tmp_path / "mediamtx.py"
    stand_in.write_text("import time\ntime.sleep(600)\n")
    server = EmbeddedMediaMTX(sys.executable, str(stand_in), "http://127.0.0.1:9", ("printguard", "secret"), _nothing)
    server._supervisor = asyncio.ensure_future(server._run())
    await asyncio.sleep(0)

    await asyncio.wait_for(server.stop(), 8)

    assert server._process is None or server._process.returncode is not None
