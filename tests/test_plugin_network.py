"""Where a plugin's requests, sockets and sign-in may go, and what it hears."""

from __future__ import annotations

import asyncio
import base64
import gzip
import io
import json
import socket
import zipfile
from contextlib import asynccontextmanager
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fakes import FakePlatform, FakeSocket, redirected_socket

from printguard.engine import engine as engine_module
from printguard.engine import oauth, plugins, sockets, urls
from printguard.engine.engine import MAX_PLUGIN_BODY, Engine
from printguard.server.platform import ServerPlatform
from printguard.server.public_network import PublicOnlyTransport

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


async def install(engine: Engine, declared: dict) -> None:
    """Installs a zip over the demo plugin."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("plugin.json", json.dumps(declared))
        archive.writestr("plugin.js", "plugin.render(() => null);")
    await engine.request({"cmd": "plugin.install", "source": {"kind": "file"}, "zip": base64.b64encode(buffer.getvalue()).decode()})


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

    client = httpx.AsyncClient(follow_redirects=True, transport=httpx.MockTransport(streamed))
    hub = SimpleNamespace(_client=client, _public_client=client)
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
        with pytest.raises(RuntimeError, match=f"the answer is larger than {MAX_PLUGIN_BODY // 1024} KB"):
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


@pytest.mark.parametrize("body", ['{"temp": 1e999}', '{"temp": NaN}', "[Infinity]"])
async def test_an_answer_holding_a_number_json_does_not_allow_is_handed_over_as_text(body: str) -> None:
    """A dashboard drops its socket on an event it cannot parse, so this must never reach one as a number."""
    platform = FakePlatform()
    over_httpx(platform, lambda request: httpx.Response(200, content=body.encode()))
    async with engine_with(platform, manifest("net", urls=[f"{API}/v1/*"])) as engine:
        answer = await engine.request({"cmd": "plugin.http", "id": "demo", "url": f"{API}/v1/feed"})

    assert next(e["body"] for e in answer if e["event"] == "http") == body
    json.dumps(answer, allow_nan=False)


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

    with pytest.raises(RuntimeError, match="the answer is larger than 256 KB"):
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

    with pytest.raises(RuntimeError, match="the answer is in an encoding that was not asked for"):
        await ServerPlatform.http(hub, "GET", f"{API}/v1/feed", max_bytes=MAX_PLUGIN_BODY)


async def test_a_socket_redirected_off_its_declared_address_is_refused() -> None:
    platform = FakePlatform()
    platform.open_socket = lambda url, arrived, public_only=False: ServerPlatform.open_socket(None, url, arrived, public_only)
    async with redirected_socket() as (declared, reached):
        async with engine_with(platform, manifest("net", "net:local", urls=[f"{declared}/*"])) as engine:
            with pytest.raises(RuntimeError, match="InvalidStatus"):
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
    assert exchange["redirects"] == "answer", "the token endpoint was followed"
    assert exchange["max_bytes"] == oauth.MAX_TOKEN_RESPONSE_BYTES and exchange["public_only"] is True


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


@pytest.mark.parametrize("headers", [{"Host": "other.example"}, {"hOsT": "other.example"}, [["host", "other.example"]]])
async def test_a_request_cannot_name_a_host_its_address_did_not(headers: object) -> None:
    platform = FakePlatform()
    async with engine_with(platform, manifest("net", urls=[f"{API}/v1/*"])) as engine:
        with pytest.raises(RuntimeError, match="may not set the Host header"):
            await engine.request({"cmd": "plugin.http", "id": "demo", "url": f"{API}/v1/now", "headers": headers})
        await engine.request({"cmd": "plugin.http", "id": "demo", "url": f"{API}/v1/now", "headers": {"X-Forwarded-Host": "kept"}})

    assert [sent["headers"] for sent in platform.http_requests if sent["url"].startswith(API)] == [{"X-Forwarded-Host": "kept"}]


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


def test_an_error_that_answers_a_command_is_never_handed_to_a_plugin() -> None:
    """A command's error quotes what its sender chose, with each stored credential in it redacted."""
    assert plugins.project_event({"event": "error", "message": "no monitor [redacted]", "req_id": "r1"}, ["state:read"]) is None
    assert plugins.project_event({"event": "error", "message": "ntfy notification failed"}, ["state:read"]) is not None


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


@pytest.mark.parametrize("endpoint", plugins.SIGN_IN_ENDPOINTS)
async def test_a_sign_in_on_this_network_needs_the_grant_that_covers_it(endpoint: str) -> None:
    sign_in = {"authorize_url": f"{API}/authorize", "token_url": f"{API}/token", endpoint: f"{ROUTER}/apply.cgi"}
    with pytest.raises(ValueError, match=rf"reaching {ROUTER}/apply.cgi needs the net:local permission"):
        plugins.sanitise_manifest(manifest("oauth", oauth=sign_in))
    assert "net:local" in plugins.restored_manifest(manifest("oauth", oauth=sign_in))["permissions"], "one saved by 2.5 was not asked again"

    platform = FakePlatform()
    platform.responses[sign_in["token_url"]] = (200, {"access_token": "at-1"})
    async with engine_with(platform, manifest("oauth", "net:local", oauth=sign_in)) as engine:
        assert await engine.finish_sign_in((await start_sign_in(engine))["state"][0], "code-1") == "demo"
        waiting = (await start_sign_in(engine))["state"][0]
        platform.http_calls.clear()
        await engine.request({"cmd": "plugin.update", "id": "demo", "patch": {"granted": ["oauth"], "enabled": False}})
        with pytest.raises(PermissionError, match="net:local"):
            await engine.finish_sign_in(waiting, "code-2")
        with pytest.raises(RuntimeError, match="net:local"):
            await start_sign_in(engine)

    assert not platform.http_calls, "the hub posted a code for a plugin that may not reach this network"


@pytest.mark.parametrize("address", ["https://localhost./authorize", "https://127.0.0.1./authorize", "https://printer.lan./authorize"])
def test_a_sign_in_on_this_network_needs_the_grant_however_its_host_ends(address: str) -> None:
    """A dot after the host hid it from the check, so it installed with the oauth permission alone."""
    sign_in = {"authorize_url": address, "token_url": f"{API}/token"}
    with pytest.raises(ValueError, match="needs the net:local permission"):
        plugins.sanitise_manifest(manifest("oauth", oauth=sign_in))
    plugins.sanitise_manifest(manifest("oauth", "net:local", oauth=sign_in))


async def test_a_request_body_nested_too_deep_is_refused_before_it_is_sent() -> None:
    """The hub walks a body to fill in its secrets, and Python walks JSON one call per level."""
    body: dict = {}
    for _ in range(plugins.MAX_DEPTH):
        body = {"a": body}
    platform = FakePlatform()
    async with engine_with(platform, manifest("net", urls=[f"{API}/v1/*"])) as engine:
        platform.http_calls.clear()
        with pytest.raises(RuntimeError, match=f"nested more than {plugins.MAX_DEPTH} deep"):
            await engine.request({"cmd": "plugin.http", "id": "demo", "url": f"{API}/v1/now", "method": "POST", "json": body})
        assert platform.http_calls == []
        await engine.request({"cmd": "plugin.http", "id": "demo", "url": f"{API}/v1/now", "method": "POST", "json": body["a"]})

    assert len(platform.http_calls) == 1


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


async def test_two_requests_on_an_expired_token_refresh_it_once() -> None:
    """A provider that rotates refresh tokens retires the one the second refresh would send."""
    platform = FakePlatform()
    platform.responses[f"{API}/token"] = (200, {"access_token": "at-1", "refresh_token": "rt-1"})
    async with engine_with(platform, SIGNS_IN) as engine:
        await engine.finish_sign_in((await start_sign_in(engine))["state"][0], "code-1")
        engine.plugins.get("demo").secrets[oauth.EXPIRES] = "0"
        platform.responses[f"{API}/token"] = (200, {"access_token": "at-2", "refresh_token": "rt-2"})
        platform.http_requests.clear()

        ask = {"cmd": "plugin.http", "id": "demo", "url": f"{API}/v1/now"}
        await asyncio.gather(engine.request(ask), engine.request(ask))

        refreshes = [r for r in platform.http_requests if r["url"] == f"{API}/token"]
        assert len(refreshes) == 1, "the second request refreshed with a token the first had already used"
        sent = [r for r in platform.http_requests if r["url"] == f"{API}/v1/now"]
        assert len(sent) == 2


class SlowPlatform(FakePlatform):
    """Holds every socket open until told, the way a slow handshake does."""

    def __init__(self) -> None:
        super().__init__()
        self.connect = asyncio.Event()

    async def open_socket(self, url: str, arrived, public_only: bool = False) -> FakeSocket:
        await self.connect.wait()
        return await super().open_socket(url, arrived, public_only)


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


def test_an_update_that_answers_on_a_new_channel_or_asks_for_a_new_scope_is_wider() -> None:
    sign_in = {**SIGNS_IN["oauth"], "scopes": ["read"]}

    def declared(**fields) -> dict:
        asked = {"urls": SIGNS_IN["urls"], "oauth": sign_in, "provides": {"status": "what is playing"}, **fields}
        return plugins.sanitise_manifest(manifest("net", "oauth", "link:provide", **asked))

    accepted = declared()
    assert not plugins.widens(accepted, declared())
    assert not plugins.widens(accepted, declared(provides={}, oauth={**sign_in, "scopes": []}))
    assert plugins.widens(accepted, declared(provides={"status": "what is playing", "queue": "what is next"}))
    assert plugins.widens(accepted, declared(oauth={**sign_in, "scopes": ["read", "write"]}))


def test_an_address_that_differs_only_in_the_case_of_its_path_is_not_wider() -> None:
    saved = plugins.sanitise_manifest(manifest("net", urls=["https://api.telegram.org/bot*/sendmessage"]))
    reinstalled = plugins.sanitise_manifest(manifest("net", urls=["https://api.telegram.org/bot*/sendMessage"]))

    assert not plugins.widens(saved, reinstalled)
    assert plugins.widens(saved, plugins.sanitise_manifest(manifest("net", urls=["https://api.telegram.org/bot*/getUpdates"])))


async def test_a_plugin_that_fails_is_handed_back_to_its_runtime_without_it() -> None:
    reloads: list[list[str]] = []

    class Runtime:
        def attach(self, request, failed) -> None:
            pass

        def on_event(self, event) -> None:
            pass

        async def reload(self, running, failed_gates) -> None:
            reloads.append([plugin.id for plugin in running])

        async def close(self) -> None:
            pass

    platform = FakePlatform()
    platform.plugin_runtime = Runtime()
    async with engine_with(platform, manifest("net", urls=["wss://93.184.216.34/*"])) as engine:
        engine.plugin_failed("demo", "answered with a status of its own making")
        await asyncio.sleep(0.05)

    assert reloads[-1] == []


TOKEN_PAGE = {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600}


async def test_a_sign_in_and_a_refresh_go_through_the_hub_http_method() -> None:
    """The fake platform once took any keyword, so a renamed parameter broke every sign-in on a real hub."""
    forms: list[dict[str, list[str]]] = []

    def serve(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/token":
            return httpx.Response(200, json={})
        forms.append(parse_qs(request.content.decode()))
        return httpx.Response(200, json=TOKEN_PAGE if forms[-1]["grant_type"] == ["authorization_code"] else {"access_token": "at-2", "expires_in": 3600})

    platform = FakePlatform()
    over_httpx(platform, serve)
    async with engine_with(platform, SIGNS_IN) as engine:
        assert await engine.finish_sign_in((await start_sign_in(engine))["state"][0], "code-1") == "demo"
        plugin = engine.plugins.get("demo")
        assert plugin.secrets[oauth.ACCESS] == "at-1" and plugin.secrets[oauth.REFRESH] == "rt-1"

        plugin.secrets[oauth.EXPIRES] = "0"
        await engine.request({"cmd": "plugin.http", "id": "demo", "url": f"{API}/v1/now", "headers": {"Authorization": "Bearer {{secret.oauth}}"}})

    assert [form["grant_type"] for form in forms] == [["authorization_code"], ["refresh_token"]]
    assert plugin.secrets[oauth.ACCESS] == "at-2" and plugin.secrets[oauth.REFRESH] == "rt-1"


def failing(error: Exception):
    def serve(request: httpx.Request) -> httpx.Response:
        raise error

    return serve


@pytest.mark.parametrize(
    ("answer", "complaint"),
    [
        (failing(httpx.ConnectTimeout("timed out")), r"Example sign-in failed \(ConnectTimeout\)"),
        (failing(httpx.ConnectError("refused")), r"Example sign-in failed \(ConnectError\)"),
        (lambda request: httpx.Response(200, content=b'{"access_token": "' + b"a" * oauth.MAX_TOKEN_RESPONSE_BYTES + b'"}'), "the answer is larger than 64 KB"),
        (lambda request: httpx.Response(302, headers={"Location": "https://elsewhere.example/token"}), r"refused the sign-in \(302\)"),
    ],
)
async def test_a_token_endpoint_that_fails_or_overruns_is_a_failed_sign_in(answer, complaint: str) -> None:
    """The callback answers a RuntimeError with the reason and anything else with a bare 500."""
    platform = FakePlatform()
    over_httpx(platform, answer)
    async with engine_with(platform, SIGNS_IN) as engine:
        with pytest.raises(RuntimeError, match=complaint):
            await engine.finish_sign_in((await start_sign_in(engine))["state"][0], "code-1")

        assert oauth.ACCESS not in engine.plugins.get("demo").secrets


async def test_a_name_that_resolves_to_this_network_gets_no_request_from_a_plugin_without_the_grant(monkeypatch: pytest.MonkeyPatch) -> None:
    """The name is looked up again to connect, and a resolver the plugin's author runs answers differently the second time."""
    received: list[bytes] = []

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        received.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\nConnection: close\r\n\r\nsecret")
        await writer.drain()
        writer.close()

    lookups: list[str] = []
    real = socket.getaddrinfo

    def getaddrinfo(host, port, *args, **kwargs):
        host = host.decode() if isinstance(host, bytes) else host
        if not host.endswith(".attacker.example"):
            return real(host, port, *args, **kwargs)
        lookups.append(host)
        answers = ["93.184.216.34", "127.0.0.1"] if len(lookups) == 1 else ["127.0.0.1"]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port)) for address in answers]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    platform = FakePlatform()
    hub = SimpleNamespace(_client=httpx.AsyncClient(), _public_client=httpx.AsyncClient(transport=PublicOnlyTransport()))
    platform.http = lambda method, url, **kwargs: ServerPlatform.http(hub, method, url, **kwargs)
    async with await asyncio.start_server(serve, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with engine_with(platform, manifest("net", urls=[f"http://*.attacker.example:{port}/*"])) as engine:
            for _ in range(3):
                with pytest.raises(RuntimeError, match="may not reach this network"):
                    await engine.request({"cmd": "plugin.http", "id": "demo", "url": f"http://page.attacker.example:{port}/admin"})

    assert received == [], "a plugin without Reach your own network read a page on this machine"


SECRET = "hunter2pass"


def probes(candidate: str) -> list[dict]:
    """Every command a plugin sends, with the plugin's own text put in each field it may choose."""
    return [
        {"cmd": "plugin.http", "url": f"https://{candidate}.attacker.example/x"},
        {"cmd": "plugin.http", "url": f"{API}:{candidate}/v1/x"},
        {"cmd": "plugin.http", "url": f"{API}/v1/x", "headers": {"X": f"{{{{secret.{candidate}}}}}"}},
        {"cmd": "plugin.http", "url": f"{API}/v1/x", "headers": {"X": "{{secret.oauth_refresh}}"}},
        {"cmd": "plugin.http", "url": f"{API}/v1/echo", "headers": {"X": candidate}},
        {"cmd": "plugin.http", "url": f"{{{{secret.{candidate}}}}}.example/v1/x"},
        {"cmd": "plugin.socket", "action": "send", "tag": candidate, "text": "x"},
        {"cmd": "plugin.socket", "action": "open", "tag": "t", "url": f"wss://{candidate}.attacker.example/"},
        {"cmd": "plugin.socket", "action": "open", "tag": candidate, "url": "wss://93.184.216.34/echo"},
        {"cmd": "plugin.call", "to": candidate, "channel": candidate},
        {"cmd": "plugin.call", "to": "other", "channel": "feed", "tag": candidate},
        {"cmd": "plugin.publish", "channel": candidate},
        {"cmd": "plugin.answer", "call_id": candidate},
        {"cmd": "plugin.effect", "effect": {"kind": candidate}},
    ]


class EchoingPlatform(FakePlatform):
    """Fails the way a library does, with the address or header it was handed in the message."""

    async def http(self, method, url, **kwargs):
        if url.endswith("/echo"):
            raise httpx.LocalProtocolError(f"Illegal header value {kwargs['headers']!r}")
        return await super().http(method, url, **kwargs)

    async def open_socket(self, url, arrived, public_only=False):
        if url.endswith("/echo"):
            raise ValueError(f"invalid frame from {url}")
        return await super().open_socket(url, arrived, public_only)


@pytest.mark.parametrize("candidate", [SECRET, "plainword"])
async def test_no_plugin_command_answers_with_text_the_plugin_chose(candidate: str) -> None:
    """Every error reaches plugins holding state:read with each stored credential replaced, so an echo is a way to test guesses against them."""
    declared = manifest(
        "net", "link:provide", "link:consume", "notify",
        urls=[f"{API}/v1/*", "wss://93.184.216.34/*"], secrets={"key": "A key"}, provides={"feed": "what it knows"}, consumes=["other:feed"],
    )
    platform = EchoingPlatform()
    async with engine_with(platform, declared) as engine:
        await engine.request({"cmd": "plugin.secrets", "id": "demo", "secrets": {"key": SECRET}})
        heard: list[str] = []
        engine.add_sink(lambda event: heard.append(event["message"]) if event["event"] == "error" else None)
        for probe in probes(candidate):
            with pytest.raises(Exception) as refusal:
                await engine.request({**probe, "id": "demo"})
            assert candidate not in str(refusal.value) and "[redacted]" not in str(refusal.value), f"{probe['cmd']} answered {refusal.value}"
        engine.plugin_failed("demo", f"Error: {candidate}")

    assert len(heard) >= len(probes(candidate)) + 1
    assert not [message for message in heard if candidate in message or "[redacted]" in message]


async def test_a_plugin_held_at_its_rate_limit_is_let_through_once_its_earlier_requests_age_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refused attempts used to count, so a plugin polling faster than its limit was shut out for good."""
    monkeypatch.setattr(engine_module, "PLUGIN_RATE_LIMIT", 3)
    monkeypatch.setattr(engine_module, "PLUGIN_RATE_WINDOW_S", 1.0)
    async with engine_with(FakePlatform(), manifest("net", urls=[f"{API}/v1/*"])) as engine:
        outcomes = []
        for _ in range(25):
            try:
                await engine.request({"cmd": "plugin.http", "id": "demo", "url": f"{API}/v1/now"})
                outcomes.append(True)
            except RuntimeError as refusal:
                assert "faster than 3 a minute" in str(refusal)
                outcomes.append(False)
            await asyncio.sleep(0.1)

    assert outcomes[:3] == [True] * 3 and outcomes[3] is False
    assert True in outcomes[4:], "a plugin that kept asking was never let through again"


async def test_a_plugin_opening_sockets_counts_against_the_same_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_module, "PLUGIN_RATE_LIMIT", 3)
    platform = FakePlatform()
    async with engine_with(platform, manifest("net", urls=["wss://93.184.216.34/*"])) as engine:
        feed = {"cmd": "plugin.socket", "id": "demo", "tag": "feed", "url": "wss://93.184.216.34/feed"}
        for _ in range(3):
            await engine.request({**feed, "action": "open"})
            await engine.request({**feed, "action": "close"})
        with pytest.raises(RuntimeError, match="faster than 3 a minute"):
            await engine.request({**feed, "action": "open"})

    assert len(platform.sockets) == 3


async def test_a_sign_in_to_an_endpoint_the_manifest_has_since_changed_sends_the_code_nowhere() -> None:
    platform = FakePlatform()
    platform.responses[f"{API}/token"] = (200, TOKEN_PAGE)
    async with engine_with(platform, SIGNS_IN) as engine:
        state = (await start_sign_in(engine))["state"][0]
        moved = {**SIGNS_IN, "oauth": {**SIGNS_IN["oauth"], "token_url": "https://93.184.216.35/token"}}
        await install(engine, moved)
        await engine.request({"cmd": "plugin.secrets", "id": "demo", "secrets": {oauth.CLIENT_ID: "my-client"}})
        await engine.request({"cmd": "plugin.update", "id": "demo", "patch": {"granted": moved["permissions"], "enabled": True}})

        with pytest.raises(PermissionError, match="signs in somewhere new"):
            await engine.finish_sign_in(state, "code-1")

    assert not [call for call in platform.http_calls if call[0] == "POST"], "the code went to an endpoint the user never accepted"


async def test_a_sign_in_cannot_finish_once_the_plugin_may_no_longer_connect_an_account() -> None:
    platform = FakePlatform()
    platform.responses[f"{API}/token"] = (200, TOKEN_PAGE)
    async with engine_with(platform, SIGNS_IN) as engine:
        state = (await start_sign_in(engine))["state"][0]
        await engine.request({"cmd": "plugin.update", "id": "demo", "patch": {"granted": ["net"]}})

        with pytest.raises(PermissionError, match="may not connect an account"):
            await engine.finish_sign_in(state, "code-1")

    assert not [call for call in platform.http_calls if call[0] == "POST"]


@pytest.mark.parametrize("name", ["oauth_refresh", "oauth_expires", "oauth_client_id"])
async def test_a_request_carries_the_access_token_and_nothing_else_of_a_sign_in(name: str) -> None:
    platform = FakePlatform()
    platform.responses[f"{API}/token"] = (200, TOKEN_PAGE)
    async with engine_with(platform, SIGNS_IN) as engine:
        await engine.finish_sign_in((await start_sign_in(engine))["state"][0], "code-1")
        platform.http_requests.clear()
        await engine.request({"cmd": "plugin.http", "id": "demo", "url": f"{API}/v1/now", "headers": {"A": "Bearer {{secret.oauth}}"}})
        with pytest.raises(RuntimeError, match="refers to a secret it does not hold"):
            await engine.request({"cmd": "plugin.http", "id": "demo", "url": f"{API}/v1/now", "headers": {"A": f"{{{{secret.{name}}}}}"}})

    assert [r["headers"] for r in platform.http_requests] == [{"A": "Bearer at-1"}]


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://accounts.spotify.com\\@evil.example/api/token",
        "https://accounts.spotify.com%2eevil.example/api/token",
        "https://user@accounts.spotify.com/api/token",
        "https://accounts.spotify.com:443@evil.example/api/token",
        "https://accounts.spotify.com\t.evil.example/api/token",
        "https://accounts.spotify.com:99999/api/token",
        "https://ａccounts.example/api/token",
        "https://256.256.256.256/api/token",
        "https://1.2.3.4.5/api/token",
        "https://x.0x/api/token",
    ],
)
def test_a_sign_in_endpoint_names_the_same_host_to_python_and_a_browser(endpoint: str) -> None:
    good = "https://auth.example.com/authorize"
    for block in ({"authorize_url": good, "token_url": endpoint}, {"authorize_url": endpoint, "token_url": good}):
        with pytest.raises(ValueError, match="plain host"):
            plugins.sanitise_sign_in(block)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.com\\@evil.example/v1/x",
        "https://api.example.com%2eevil.example/v1/x",
        "https://api.example.com:443@evil.example/v1/x",
        "https://api.example.com\t.evil.example/v1/x",
        " https://api.example.com/v1/x",
    ],
)
def test_a_request_address_that_two_parsers_read_differently_matches_no_pattern(url: str) -> None:
    assert not urls.matches("https://api.example.com/*", url)
    assert not urls.matches("https://*/*", url)


@pytest.mark.parametrize(("permissions", "public_only"), [(["net"], True), (["net", "net:local"], False)])
async def test_a_plugin_is_connected_to_public_addresses_only_unless_it_holds_net_local(permissions: list[str], public_only: bool) -> None:
    platform = FakePlatform()
    async with engine_with(platform, manifest(*permissions, urls=[f"{API}/*", "wss://93.184.216.34/*"])) as engine:
        await engine.request({"cmd": "plugin.http", "id": "demo", "url": f"{API}/v1/now"})
        await engine.request({"cmd": "plugin.socket", "id": "demo", "action": "open", "tag": "feed", "url": "wss://93.184.216.34/feed"})

    assert platform.http_requests[-1]["public_only"] is public_only
    assert platform.sockets[0].public_only is public_only
