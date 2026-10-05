"""Where a plugin's requests, sockets and sign-in may go, and what it hears."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import zipfile
from contextlib import asynccontextmanager
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fakes import FakePlatform, FakeSocket

from printguard.engine import oauth, plugins, sockets
from printguard.engine.engine import Engine
from printguard.server.platform import ServerPlatform

API = "https://93.184.216.34"
ROUTER = "https://192.168.1.1"


def manifest(*permissions: str, **fields) -> dict:
    return {
        "id": "demo",
        "version": "1.0.0",
        "permissions": list(permissions),
        "reasons": dict.fromkeys(permissions, "to test"),
        **fields,
    }


SIGNS_IN = manifest(
    "net",
    "oauth",
    urls=[f"{API}/v1/*"],
    oauth={"label": "Example", "authorize_url": f"{API}/authorize", "token_url": f"{API}/token"},
)


@asynccontextmanager
async def engine_with(platform: FakePlatform, declared: dict, granted: list[str] | None = None):
    """Starts an engine with one plugin installed, accepted and enabled."""
    engine = Engine(platform)
    await engine.start()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("plugin.json", json.dumps(declared))
        archive.writestr("plugin.js", "plugin.render(() => null);")
    try:
        await engine.request({"cmd": "plugin.install", "source": {"kind": "file"}, "zip": base64.b64encode(buffer.getvalue()).decode()})
        accepted = declared["permissions"] if granted is None else granted
        await engine.request({"cmd": "plugin.update", "id": "demo", "patch": {"granted": accepted, "enabled": True}})
        yield engine
    finally:
        await engine.stop()


async def start_sign_in(engine: Engine, origin: str = "http://hub.example.com:8000") -> dict[str, list[str]]:
    """Starts the demo plugin's sign-in and returns the query the provider would get."""
    await engine.request({"cmd": "plugin.secrets", "id": "demo", "secrets": {oauth.CLIENT_ID: "my-client"}})
    answer = await engine.request({"cmd": "plugin.oauth", "id": "demo", "origin": origin})
    return parse_qs(urlsplit(next(e["url"] for e in answer if e["event"] == "plugin_oauth")).query)


def over_httpx(platform: FakePlatform, handler) -> None:
    """Sends a fake platform's requests through the hub's real HTTP method."""
    hub = SimpleNamespace(_client=httpx.AsyncClient(follow_redirects=True, transport=httpx.MockTransport(handler)))
    platform.http = lambda method, url, **kwargs: ServerPlatform.http(hub, method, url, **kwargs)


async def test_a_redirect_is_handed_back_to_the_plugin_and_never_followed() -> None:
    seen: list[tuple[str, str | None]] = []

    def serve(request: httpx.Request) -> httpx.Response:
        if request.url.host == "93.184.216.34":
            seen.append((str(request.url), request.headers.get("x-api-key")))
            return httpx.Response(302, headers={"Location": f"{ROUTER}/admin"})
        if request.url.host == "192.168.1.1":
            seen.append((str(request.url), request.headers.get("x-api-key")))
        return httpx.Response(200, json={"wifi_password": "hunter2"})

    platform = FakePlatform()
    over_httpx(platform, serve)
    async with engine_with(platform, manifest("net", urls=[f"{API}/v1/*"], secrets={"key": "An API key"})) as engine:
        await engine.request({"cmd": "plugin.secrets", "id": "demo", "secrets": {"key": "s3cr3t"}})
        answer = await engine.request({"cmd": "plugin.http", "id": "demo", "url": f"{API}/v1/hop", "headers": {"X-Api-Key": "{{secret.key}}"}})
        asked = list(seen)
        followed = await platform.http("GET", f"{API}/v1/hop")

    assert [e["status"] for e in answer if e["event"] == "http"] == [302]
    assert asked == [(f"{API}/v1/hop", "s3cr3t")], "the plugin's request went on to an address it never declared"
    assert followed == (200, {"wifi_password": "hunter2"}), "an adapter's request stopped following redirects"


async def test_a_sign_in_never_follows_a_redirect_from_the_token_endpoint() -> None:
    platform = FakePlatform()
    platform.responses[f"{API}/token"] = (200, {"access_token": "at-1"})
    async with engine_with(platform, SIGNS_IN) as engine:
        state = (await start_sign_in(engine))["state"][0]
        await engine.finish_sign_in(state, "code-1")

    exchange = next(r for r in platform.http_requests if r["url"] == f"{API}/token")
    assert exchange["follow_redirects"] is False


async def test_a_secret_cannot_move_a_request_off_the_address_that_was_checked() -> None:
    platform = FakePlatform()
    platform.responses[f"{API}/token"] = (200, {"access_token": "192.168.1.1/cgi-bin/config?"})
    async with engine_with(platform, SIGNS_IN) as engine:
        await engine.finish_sign_in((await start_sign_in(engine))["state"][0], "code-1")
        platform.http_calls.clear()
        for address in ("https://{{secret.oauth}}@93.184.216.34/v1/x", "https://93.184.216.34{{ secret.oauth }}/v1/x", "{{secret.oauth}}://93.184.216.34/v1/x"):
            with pytest.raises(RuntimeError, match="only use a secret in the path"):
                await engine.request({"cmd": "plugin.http", "id": "demo", "url": address})

    assert platform.http_calls == [], "a request left for an address a secret chose"


async def test_the_address_is_checked_again_with_its_secrets_filled_in() -> None:
    platform = FakePlatform()
    async with engine_with(platform, manifest("net", urls=[f"{API}/v1/*"], secrets={"key": "An API key"})) as engine:
        await engine.request({"cmd": "plugin.secrets", "id": "demo", "secrets": {"key": "user-7"}})
        await engine.request({"cmd": "plugin.http", "id": "demo", "url": API + "/v1/{{secret.key}}/files"})
        await engine.request({"cmd": "plugin.secrets", "id": "demo", "secrets": {"key": "../admin"}})
        platform.http_calls.clear()
        with pytest.raises(RuntimeError, match="did not declare where its secrets take") as refusal:
            await engine.request({"cmd": "plugin.http", "id": "demo", "url": API + "/v1/{{secret.key}}/files"})

    assert platform.http_calls == [] and "admin" not in str(refusal.value), "the refusal read the secret back to the plugin"


def test_scores_printer_status_and_errors_need_the_grant_that_reads_the_dashboard() -> None:
    private = [
        {"event": "result", "monitor_id": "m1", "score": 0.93},
        {"event": "alert", "monitor_id": "m1", "score": 0.93},
        {"event": "warning", "monitor_id": "m1", "message": "feed dropped"},
        {"event": "device", "printer_id": "p1", "job": "prototype_v7.gcode"},
        {"event": "error", "message": "ntfy notification failed"},
    ]

    for event in private:
        assert plugins.project_event(event, []) is None, f"{event['event']} reached a plugin holding nothing"
        assert plugins.project_event(event, ["state:read"]) == event


@pytest.mark.parametrize(
    "endpoint",
    ["http://auth.example.com/token", "ws://auth.example.com/token", "https://*.example.com/token", "https://*/token", "https:///token", "auth.example.com/token"],
)
def test_a_sign_in_endpoint_is_one_literal_https_address(endpoint: str) -> None:
    good = "https://auth.example.com/authorize"
    for block in ({"authorize_url": good, "token_url": endpoint}, {"authorize_url": endpoint, "token_url": good}):
        with pytest.raises(ValueError, match="https authorize_url and token_url"):
            plugins.sanitise_sign_in(block)


async def test_a_token_endpoint_on_this_network_needs_the_grant_that_covers_it() -> None:
    declared = manifest("oauth", oauth={"authorize_url": f"{API}/authorize", "token_url": f"{ROUTER}/apply.cgi"})
    platform = FakePlatform()
    async with engine_with(platform, declared) as engine:
        state = (await start_sign_in(engine))["state"][0]
        with pytest.raises(PermissionError, match="net:local"):
            await engine.finish_sign_in(state, "code-1")

    assert not [call for call in platform.http_calls if call[1].startswith(ROUTER)], "the hub posted to this network for a plugin that may not reach it"

    allowed = manifest("oauth", "net", "net:local", urls=[f"{ROUTER}/*"], oauth=declared["oauth"])
    platform = FakePlatform()
    platform.responses[f"{ROUTER}/apply.cgi"] = (200, {"access_token": "at-1"})
    async with engine_with(platform, allowed) as engine:
        assert await engine.finish_sign_in((await start_sign_in(engine))["state"][0], "code-1") == "demo"


async def test_a_sign_in_left_too_long_is_no_longer_honoured() -> None:
    platform = FakePlatform()
    platform.responses[f"{API}/token"] = (200, {"access_token": "at-1"})
    async with engine_with(platform, SIGNS_IN) as engine:
        state = (await start_sign_in(engine))["state"][0]
        engine.oauth._pending[state].started -= oauth.PENDING_TTL_S + 1
        provider = engine._provider(engine.plugins.get("demo"))

        assert await engine.finish_sign_in(state, "code-1") is None
        with pytest.raises(PermissionError, match="no sign-in is waiting"):
            await engine.oauth.finish(state, "code-1", provider)

    assert (("POST", f"{API}/token")) not in platform.http_calls


async def test_only_localhost_itself_becomes_the_loopback_address() -> None:
    async with engine_with(FakePlatform(), SIGNS_IN) as engine:
        named = await start_sign_in(engine, "http://localhost.lan:8000")
        loopback = await start_sign_in(engine, "http://localhost:8000/")

    assert named["redirect_uri"] == ["http://localhost.lan:8000/oauth/callback"]
    assert loopback["redirect_uri"] == ["http://127.0.0.1:8000/oauth/callback"]


async def test_a_sign_in_and_a_rotated_refresh_token_survive_a_restart() -> None:
    platform = FakePlatform()
    platform.responses[f"{API}/token"] = (200, {"access_token": "at-1", "refresh_token": "rt-1"})
    async with engine_with(platform, SIGNS_IN) as engine:
        await engine.finish_sign_in((await start_sign_in(engine))["state"][0], "code-1")
        stored = platform.state["plugins"][0]["secrets"]
        assert stored[oauth.REFRESH] == "rt-1", "a restart now would lose the sign-in"

        engine.plugins.get("demo").secrets[oauth.EXPIRES] = "0"
        platform.responses[f"{API}/token"] = (200, {"access_token": "at-2", "refresh_token": "rt-2"})
        platform.reject_actions = True
        with pytest.raises(RuntimeError, match="printer refused"):
            await engine.request({"cmd": "plugin.http", "id": "demo", "method": "POST", "url": f"{API}/v1/api/job"})

    assert platform.state["plugins"][0]["secrets"][oauth.REFRESH] == "rt-2", "the provider has retired the token a restart would bring back"


class SlowPlatform(FakePlatform):
    """Holds every socket open until told, the way a slow handshake does."""

    def __init__(self) -> None:
        super().__init__()
        self.connect = asyncio.Event()

    async def open_socket(self, url: str, arrived) -> FakeSocket:
        await self.connect.wait()
        return await super().open_socket(url, arrived)


async def test_sockets_opening_at_once_count_towards_the_cap_and_share_a_tag() -> None:
    platform = SlowPlatform()
    async with engine_with(platform, manifest("net", urls=["wss://93.184.216.34/*"])) as engine:
        def opening(tag: str) -> asyncio.Task:
            return asyncio.ensure_future(engine.request({"cmd": "plugin.socket", "id": "demo", "action": "open", "tag": tag, "url": "wss://93.184.216.34/feed"}))

        attempts = [opening(tag) for tag in ("a", "a", "b", "c", "d", "e", "f")]
        await asyncio.sleep(0.2)
        platform.connect.set()
        outcomes = await asyncio.gather(*attempts, return_exceptions=True)

        refused = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
        assert len(platform.sockets) == sockets.MAX_PER_PLUGIN, "a second transport opened past the cap, or twice under one tag"
        assert len(refused) == 2 and all("sockets at most" in str(outcome) for outcome in refused)


async def test_a_plugin_that_loses_its_network_grant_loses_its_sockets() -> None:
    platform = FakePlatform()
    async with engine_with(platform, manifest("net", "notify", urls=["wss://93.184.216.34/*"])) as engine:
        await engine.request({"cmd": "plugin.socket", "id": "demo", "action": "open", "tag": "feed", "url": "wss://93.184.216.34/feed"})
        await engine.request({"cmd": "plugin.update", "id": "demo", "patch": {"granted": ["notify"]}})

        assert platform.sockets[0].closed
        with pytest.raises(RuntimeError):
            await engine.request({"cmd": "plugin.socket", "id": "demo", "action": "send", "tag": "feed", "text": "still here"})

    assert platform.sockets[0].sent == []


async def test_a_background_that_is_not_a_picture_clears_it() -> None:
    picture = "data:image/png;base64,iVBORw0KGgo="
    async with engine_with(FakePlatform(), manifest("background")) as engine:
        async def shown(image: object) -> str:
            answer = await engine.request({"cmd": "plugin.effect", "id": "demo", "effect": {"kind": "background", "image": image}})
            return next(e["effect"]["image"] for e in answer if e["event"] == "plugin_effect")

        assert await shown(picture) == picture
        for bad in ("data:image/svg+xml;base64,PHN2Zz4=", "data:text/html;base64,PGI+", "https://example.com/a.png", f"{picture}\"><script>", "undefined", None):
            assert await shown(bad) == ""
