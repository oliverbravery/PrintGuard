"""Where a plugin's requests, sockets and sign-in may go, and what it hears."""

from __future__ import annotations

import asyncio
import base64
import gzip
import io
import json
import zipfile
from contextlib import asynccontextmanager
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fakes import FakePlatform, FakeSocket, redirected_socket

from printguard.engine import oauth, plugins, sockets
from printguard.engine.engine import MAX_PLUGIN_BODY, Engine
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
    """Sends a fake platform's requests through the hub's real HTTP method.

    Each answer goes back as a stream, the way one off a socket does, since a
    capped request reads its body as it arrives.
    """

    def streamed(request: httpx.Request) -> httpx.Response:
        answer = handler(request)
        return httpx.Response(answer.status_code, headers=answer.headers, stream=answer.stream)

    hub = SimpleNamespace(_client=httpx.AsyncClient(follow_redirects=True, transport=httpx.MockTransport(streamed)))
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


@pytest.mark.parametrize("kind", ["application/json", "text/plain", "application/octet-stream"])
@pytest.mark.parametrize("gzipped", [True, False])
async def test_an_answer_over_the_cap_fails_the_request_whatever_it_holds(kind: str, gzipped: bool) -> None:
    """A parsed JSON answer used to go to every dashboard whole, however large."""
    body = b"[" + b"0," * MAX_PLUGIN_BODY + b"0]"
    sent = gzip.compress(body) if gzipped else body

    def serve(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sent, headers={"Content-Type": kind, **({"Content-Encoding": "gzip"} if gzipped else {})})

    platform = FakePlatform()
    over_httpx(platform, serve)
    async with engine_with(platform, manifest("net", urls=[f"{API}/v1/*"])) as engine:
        with pytest.raises(RuntimeError, match=f"93.184.216.34 answered with more than {MAX_PLUGIN_BODY // 1024} KB"):
            await engine.request({"cmd": "plugin.http", "id": "demo", "url": f"{API}/v1/feed", "binary": kind.endswith("stream")})


@pytest.mark.parametrize("gzipped", [True, False])
async def test_an_answer_at_the_cap_arrives_whole(gzipped: bool) -> None:
    body = json.dumps("a" * (MAX_PLUGIN_BODY - 2)).encode()
    asked: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/feed":
            asked.append(request.headers["accept-encoding"])
        return httpx.Response(200, content=gzip.compress(body) if gzipped else body, headers={"Content-Encoding": "gzip"} if gzipped else {})

    platform = FakePlatform()
    over_httpx(platform, serve)
    async with engine_with(platform, manifest("net", urls=[f"{API}/v1/*"])) as engine:
        answer = await engine.request({"cmd": "plugin.http", "id": "demo", "url": f"{API}/v1/feed", "headers": {"accept-encoding": "br"}})

    assert next(e["body"] for e in answer if e["event"] == "http") == "a" * (MAX_PLUGIN_BODY - 2)
    assert asked == ["gzip"], "the plugin asked for an encoding nothing here can count while it inflates"


async def test_a_compressed_answer_is_refused_while_it_inflates() -> None:
    """48 MB of zeros is 47 KB of gzip, and httpx inflates each chunk whole before handing it over."""
    bomb = gzip.compress(bytes(48 * 1024 * 1024))
    handed_over: list[int] = []

    class Counted(httpx.AsyncByteStream):
        async def __aiter__(self):
            for at in range(0, len(bomb), 1024):
                handed_over.append(at)
                yield bomb[at : at + 1024]

    hub = SimpleNamespace(
        _client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=Counted())))
    )

    with pytest.raises(RuntimeError, match="answered with more than 256 KB"):
        await ServerPlatform.http(hub, "GET", f"{API}/v1/feed", max_bytes=MAX_PLUGIN_BODY)
    assert len(handed_over) == 1, "the answer was read on after it had passed the cap"
    assert (await ServerPlatform.http(hub, "GET", f"{API}/v1/feed", binary=True))[1] == base64.b64encode(bytes(48 * 1024 * 1024)).decode(), (
        "a printer's or notifier's request was capped too"
    )


@pytest.mark.parametrize("encoding", ["br", "deflate", "zstd"])
async def test_an_answer_in_an_encoding_nobody_asked_for_is_refused_rather_than_handed_over_undecoded(encoding: str) -> None:
    hub = SimpleNamespace(
        _client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, headers={"Content-Encoding": encoding}, stream=httpx.ByteStream(b"\x1b\x03"))))
    )

    with pytest.raises(RuntimeError, match=f"93.184.216.34 answered in {encoding}, which was not asked for"):
        await ServerPlatform.http(hub, "GET", f"{API}/v1/feed", max_bytes=MAX_PLUGIN_BODY)


async def test_a_socket_redirected_off_its_declared_address_is_refused() -> None:
    platform = FakePlatform()
    platform.open_socket = lambda url, arrived: ServerPlatform.open_socket(None, url, arrived)
    async with redirected_socket() as (declared, reached):
        async with engine_with(platform, manifest("net", "net:local", urls=[f"{declared}/*"])) as engine:
            with pytest.raises(RuntimeError, match="HTTP 302"):
                await engine.request({"cmd": "plugin.socket", "id": "demo", "action": "open", "tag": "hop", "url": f"{declared}/feed"})
            with pytest.raises(RuntimeError):
                await engine.request({"cmd": "plugin.socket", "id": "demo", "action": "send", "tag": "hop", "text": '{"cmd":"token.create"}'})

    assert reached == [], "the plugin's socket went on to an address it never declared"


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


async def test_an_authorize_address_with_a_query_of_its_own_keeps_it() -> None:
    declared = manifest("oauth", oauth={"authorize_url": f"{API}/authorize?prompt=consent", "token_url": f"{API}/token"})
    async with engine_with(FakePlatform(), declared) as engine:
        query = await start_sign_in(engine)

    assert query["prompt"] == ["consent"]
    assert query["response_type"] == ["code"] and query["client_id"] == ["my-client"]


@pytest.mark.parametrize("lifetime", ["soon", "nan", "inf", [3600]])
async def test_a_token_lifetime_that_is_not_a_number_is_a_refused_sign_in(lifetime: object) -> None:
    """The callback page answers a RuntimeError with its message, and anything else with a 500."""
    platform = FakePlatform()
    platform.responses[f"{API}/token"] = (200, {"access_token": "at-1", "expires_in": lifetime})
    async with engine_with(platform, SIGNS_IN) as engine:
        with pytest.raises(RuntimeError, match="Example answered with a sign-in that cannot be read"):
            await engine.finish_sign_in((await start_sign_in(engine))["state"][0], "code-1")
        assert oauth.ACCESS not in engine.plugins.get("demo").secrets


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


@pytest.mark.parametrize(
    "stood_down",
    [
        {"cmd": "plugin.update", "id": "demo", "patch": {"enabled": False}},
        {"cmd": "plugin.update", "id": "demo", "patch": {"granted": ["notify"]}},
        {"cmd": "plugin.remove", "id": "demo"},
    ],
)
async def test_a_socket_still_connecting_when_its_plugin_is_stood_down_is_closed_as_it_lands(stood_down: dict) -> None:
    platform = SlowPlatform()
    async with engine_with(platform, manifest("net", "notify", urls=["wss://93.184.216.34/*"])) as engine:
        opening = asyncio.ensure_future(engine.request({"cmd": "plugin.socket", "id": "demo", "action": "open", "tag": "feed", "url": "wss://93.184.216.34/feed"}))
        await asyncio.sleep(0.05)
        await engine.request(stood_down)
        platform.connect.set()
        await opening

        assert platform.sockets[0].closed, "a socket that was mid-handshake outlived the grant it was opened under"
        with pytest.raises(RuntimeError):
            await engine.request({"cmd": "plugin.socket", "id": "demo", "action": "send", "tag": "feed", "text": "still here"})

    assert platform.sockets[0].sent == []


async def test_a_plugin_that_fails_loses_its_sockets() -> None:
    platform = FakePlatform()
    async with engine_with(platform, manifest("net", urls=["wss://93.184.216.34/*"])) as engine:
        await engine.request({"cmd": "plugin.socket", "id": "demo", "action": "open", "tag": "feed", "url": "wss://93.184.216.34/feed"})
        engine.plugin_failed("demo", "ran out of fuel")

        with pytest.raises(RuntimeError, match="may not reach the network"):
            await engine.request({"cmd": "plugin.socket", "id": "demo", "action": "send", "tag": "feed", "text": "still here"})
        await asyncio.sleep(0)
        assert platform.sockets[0].closed and platform.sockets[0].sent == []


async def test_a_socket_closing_late_does_not_cost_the_plugin_the_one_it_opened_since() -> None:
    """A socket the broker has lost track of is one no later revocation can close."""
    platform = FakePlatform()
    async with engine_with(platform, manifest("net", urls=["wss://93.184.216.34/*"])) as engine:
        feed = {"cmd": "plugin.socket", "id": "demo", "tag": "feed", "url": "wss://93.184.216.34/feed"}
        await engine.request({**feed, "action": "open"})
        await engine.request({**feed, "action": "close"})
        await engine.request({**feed, "action": "open"})
        platform.sockets[0].arrived("closed", "")
        await engine.request({"cmd": "plugin.update", "id": "demo", "patch": {"enabled": False}})

    assert platform.sockets[1].closed


async def test_a_background_that_is_not_a_picture_clears_it() -> None:
    picture = "data:image/png;base64,iVBORw0KGgo="
    async with engine_with(FakePlatform(), manifest("background")) as engine:
        async def shown(image: object) -> str:
            answer = await engine.request({"cmd": "plugin.effect", "id": "demo", "effect": {"kind": "background", "image": image}})
            return next(e["effect"]["image"] for e in answer if e["event"] == "plugin_effect")

        assert await shown(picture) == picture
        for bad in ("data:image/svg+xml;base64,PHN2Zz4=", "data:text/html;base64,PGI+", "https://example.com/a.png", f"{picture}\"><script>", "undefined", None):
            assert await shown(bad) == ""
