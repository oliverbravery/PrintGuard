"""Hub stream routing through MediaMTX."""

from __future__ import annotations

import base64
import json
import socket
import sys
from pathlib import Path

import httpx
import pytest
import yaml

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


def test_the_shipped_config_grants_the_control_api_to_nobody() -> None:
    """A web page in a browser on the same computer can reach the loopback listeners.

    The control API reads camera URLs with their passwords and can add a path
    that runs a command, so nobody may hold it until the hub adds its own login,
    and neither listener may answer a page from another origin.
    """
    config = yaml.safe_load(SHIPPED_CONFIG.read_text())

    assert config["authInternalUsers"] == [
        {"user": "any", "permissions": [{"action": "publish"}, {"action": "read"}, {"action": "playback"}]}
    ]
    assert config["apiAllowOrigins"] == []
    assert config["hlsAllowOrigins"] == []


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
    server = EmbeddedMediaMTX(sys.executable, str(stand_in), f"http://127.0.0.1:{port}", ("printguard", "secret"))

    await server.start()
    await server.stop()

    assert json.loads(seen.read_text()) == {
        "MTX_AUTHINTERNALUSERS_1_USER": "printguard",
        "MTX_AUTHINTERNALUSERS_1_PASS": "secret",
        "MTX_AUTHINTERNALUSERS_1_PERMISSIONS_0_ACTION": "api",
    }
