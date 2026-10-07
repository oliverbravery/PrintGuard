"""Hub application static asset behaviour."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from contextlib import asynccontextmanager
from importlib.metadata import version as package_version
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from printguard.server import app as app_module
from printguard.server.app import ASSET_CACHE_CONTROL, REVALIDATE_CACHE_CONTROL, WebStaticFiles, create_app, host_trusted
from printguard.server.events import ConflatedEventQueue, parse_json


class AsyncContent(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"#EXTM3U"


async def test_web_static_files_revalidate_html_and_cache_hashed_assets(tmp_path) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html></html>")
    (tmp_path / "assets" / "index-abc123.js").write_text("export {}")
    transport = httpx.ASGITransport(app=WebStaticFiles(directory=tmp_path, html=True))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        html = await client.get("/")
        asset = await client.get("/assets/index-abc123.js")
        unchanged = await client.get("/", headers={"If-None-Match": html.headers["etag"]})

    assert html.headers["cache-control"] == REVALIDATE_CACHE_CONTROL
    assert asset.headers["cache-control"] == ASSET_CACHE_CONTROL
    assert unchanged.status_code == 304 and unchanged.headers["cache-control"] == REVALIDATE_CACHE_CONTROL
    assert "etag" in html.headers and "etag" in asset.headers


@pytest.mark.parametrize(
    ("listed", "policy", "legacy_header"),
    [
        ("", "frame-ancestors 'self'", "SAMEORIGIN"),
        ("https://ha.example.com:443, http://hass.local:8123", "frame-ancestors 'self' http://hass.local:8123 https://ha.example.com", None),
    ],
)
async def test_the_dashboard_and_its_files_are_framed_only_by_the_hub_and_the_origins_listed(
    tmp_path, monkeypatch, listed: str, policy: str, legacy_header: str | None
) -> None:
    """The dashboard frames its own sandbox pages, and X-Frame-Options cannot name a second origin, so it goes when one is listed."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html></html>")
    (tmp_path / "plugin-sandbox.html").write_text("<html></html>")
    (tmp_path / "assets" / "index-abc123.js").write_text("export {}")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    monkeypatch.setenv("PRINTGUARD_ORIGINS", listed)
    app = create_app()
    app.state.engine = SimpleNamespace(platform=SimpleNamespace(version="2.6.0", plugin_runtime=None))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for path in ("/", "/assets/index-abc123.js", "/plugin-sandbox.html"):
            response = await client.get(path)
            assert response.headers.get("x-frame-options") == legacy_header, path
            assert response.headers["content-security-policy"] == policy, path


async def test_the_hub_serves_no_interactive_api_pages_and_no_root_schema(monkeypatch) -> None:
    """The pages load Swagger UI and ReDoc from a CDN on the hub's own origin, and the root schema lists internal routes."""
    app = create_app()
    app.state.engine = SimpleNamespace(platform=SimpleNamespace(version="2.6.0", plugin_runtime=None))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for path in ("/docs", "/redoc", "/openapi.json", "/api/v1/docs", "/api/v1/redoc"):
            assert (await client.get(path)).status_code == 404, path
        schema = await client.get("/api/v1/openapi.json")

    assert schema.status_code == 200 and schema.json()["info"]["version"] == package_version("printguard")


async def test_health_reports_ready_version_without_caching() -> None:
    app = create_app()
    app.state.engine = SimpleNamespace(platform=SimpleNamespace(version="2.3.7", plugin_runtime=None))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "version": "2.3.7"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "host",
    ["192.168.1.20:8000", "203.0.113.7", "[fd00::1]:8000", "localhost:8000", "printguard.local", "tower:8000", "hub.lan", "HUB.example.com"],
)
def test_a_hub_answers_to_addresses_and_local_names_with_no_setup(host: str) -> None:
    assert host_trusted(host, {"hub.example.com"})


@pytest.mark.parametrize("host", ["evil.example:8000", "hub.example.com.evil.example", "localhost.evil.example", "192.168.1.20.nip.io"])
def test_a_hub_does_not_answer_to_a_public_name_nobody_listed(host: str) -> None:
    assert not host_trusted(host, {"hub.example.com"})


@asynccontextmanager
async def named_hub(monkeypatch):
    """Yields a hub that lists one proxied name, a client for it and the warnings it logs."""
    monkeypatch.setenv("PRINTGUARD_ORIGINS", "https://hub.example.com")
    app = create_app()
    app.state.engine = SimpleNamespace(platform=SimpleNamespace(version="2.5.1", plugin_runtime=None))
    told: list[str] = []
    monkeypatch.setattr("printguard.server.app.logger.warning", lambda message, *args: told.append(message % args))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield app, client, told


async def handshake_answer(app, path: str, headers: dict[str, str]) -> str:
    """Opens a WebSocket against the app and returns the kind of message that answered it."""
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "websocket.connect"}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {
        "type": "websocket",
        "scheme": "ws",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(name.encode(), value.encode()) for name, value in headers.items()],
        "subprotocols": [],
    }
    await app(scope, receive, send)
    return sent[0]["type"]


class Tab:
    """Plays a browser tab on one of the hub's sockets, a frame at a time."""

    def __init__(self, app, path: str = "/api/ws", headers: dict[str, str] | None = None) -> None:
        self._app = app
        self._path = path
        self._headers = headers or {"host": "test", "origin": "http://test"}
        self._inbound: asyncio.Queue[dict] = asyncio.Queue()
        self._sent: list[dict] = []
        self._inbound.put_nowait({"type": "websocket.connect"})

    async def __aenter__(self) -> "Tab":
        scope = {
            "type": "websocket",
            "scheme": "ws",
            "path": self._path,
            "raw_path": self._path.encode(),
            "root_path": "",
            "query_string": b"",
            "headers": [(name.encode(), value.encode()) for name, value in self._headers.items()],
            "subprotocols": [],
        }
        self._socket = asyncio.ensure_future(self._app(scope, self._inbound.get, self._keep))
        return self

    async def __aexit__(self, *_) -> None:
        self._inbound.put_nowait({"type": "websocket.disconnect", "code": 1001})
        async with asyncio.timeout(2):
            await self._socket

    async def _keep(self, message: dict) -> None:
        self._sent.append(message)

    def send(self, **frame) -> None:
        self._inbound.put_nowait({"type": "websocket.receive", **frame})

    def events(self, kind: str) -> list[dict]:
        received = [json.loads(message["text"]) for message in self._sent if message["type"] == "websocket.send"]
        return [event for event in received if event["event"] == kind]

    async def until(self, kind: str) -> dict:
        async with asyncio.timeout(2):
            while not self.events(kind):
                await asyncio.sleep(0.01)
        return self.events(kind)[0]

    async def closed(self) -> int:
        """Waits for the hub to close the socket and returns the code it gave."""
        async with asyncio.timeout(2):
            while not [message for message in self._sent if message["type"] == "websocket.close"]:
                await asyncio.sleep(0.01)
        return next(message["code"] for message in self._sent if message["type"] == "websocket.close")


async def test_a_slow_command_does_not_hold_the_next_one_from_the_same_tab(monkeypatch) -> None:
    """Registering a stream waits up to 25 s on the camera, and a pause pressed meanwhile cannot."""
    from fakes import FakePlatform

    from printguard.engine.engine import Engine

    platform = FakePlatform()
    opening, abandoned = asyncio.Event(), asyncio.Event()

    async def never_opens(camera_id: str, source: dict) -> None:
        opening.set()
        try:
            await asyncio.Event().wait()
        finally:
            abandoned.set()

    monkeypatch.setattr(platform, "open_camera", never_opens)
    engine = Engine(platform)
    await engine.start()
    app = create_app()
    app.state.engine = engine
    try:
        async with Tab(app) as other, Tab(app) as tab:
            tab.send(text=json.dumps({"cmd": "camera.add", "name": "slow", "source": {"kind": "url", "url": "rtsp://cam/stream"}}))
            await opening.wait()
            tab.send(text=json.dumps({"cmd": "token.create", "name": "ci", "scope": "read", "req_id": 2}))
            assert (await tab.until("token_created"))["req_id"] == 2
            assert not other.events("token_created"), "a reply meant for the tab that asked reached another"

            tab.send(text="not json")
            tab.send(bytes=b"\x00")
            tab.send(text="[1]")
            async with asyncio.timeout(2):
                while len(tab.events("error")) < 3:
                    await asyncio.sleep(0.01)
            assert {event["message"] for event in tab.events("error")} == {"a command must be a JSON object"}
            assert not abandoned.is_set()
        assert abandoned.is_set(), "a command still running when its tab closed was left behind"
    finally:
        await engine.stop()


async def test_a_command_sent_as_its_tab_closes_still_runs() -> None:
    from fakes import FakePlatform

    from printguard.engine.engine import Engine

    engine = Engine(FakePlatform())
    await engine.start()
    app = create_app()
    app.state.engine = engine
    try:
        async with Tab(app) as tab:
            tab.send(text=json.dumps({"cmd": "settings.update", "patch": {"fault_grace_s": 300}}))
        assert engine.settings["fault_grace_s"] == 300
    finally:
        await engine.stop()


async def test_a_tab_cannot_have_more_than_a_few_commands_running_at_once(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "SOCKET_COMMANDS_IN_FLIGHT", 2)
    started: list[int] = []
    release = asyncio.Event()

    async def handle(command: dict, reply) -> None:
        started.append(command["n"])
        await release.wait()

    app = create_app()
    app.state.engine = SimpleNamespace(
        platform=SimpleNamespace(plugin_runtime=None), handle=handle, add_sink=lambda sink: None, remove_sink=lambda sink: None
    )
    async with Tab(app) as tab:
        for n in range(5):
            tab.send(text=json.dumps({"n": n}))
        await asyncio.sleep(0.05)
        assert started == [0, 1]
        release.set()
        async with asyncio.timeout(2):
            while len(started) < 5:
                await asyncio.sleep(0.01)
    assert started == [0, 1, 2, 3, 4]


async def test_a_text_frame_on_the_publish_socket_closes_it(monkeypatch) -> None:
    """A recording is binary, and a frame that is not used to end the handler in a KeyError."""
    received = bytearray()

    def drain(source, url: str) -> None:
        while chunk := source.read(1):
            received.extend(chunk)

    monkeypatch.setattr(app_module, "remux", drain)
    app = create_app()
    app.state.engine = SimpleNamespace(platform=SimpleNamespace(plugin_runtime=None))
    async with Tab(app, "/api/publish/cam") as camera:
        camera.send(bytes=b"\x1a\x45")
        camera.send(text="not a recording")
        assert await camera.closed() == 1003
    assert bytes(received) == b"\x1a\x45"


async def test_the_two_sockets_take_no_handshake_without_an_origin(monkeypatch) -> None:
    """Every browser names one, so a handshake without it is not a dashboard. An upload may still be a script's."""
    async with named_hub(monkeypatch) as (app, client, _told):
        app.state.engine.prints = SimpleNamespace(get=lambda print_id: None)
        assert await handshake_answer(app, "/api/ws", {"host": "test"}) == "websocket.close"
        assert await handshake_answer(app, "/api/publish/cam", {"host": "test"}) == "websocket.close"
        assert (await client.post("/api/prints?filename=a.stl", content=b"solid")).status_code == 400


async def test_a_rebinding_page_is_refused_whatever_it_asks_for(monkeypatch) -> None:
    """Its origin and host agree, so only knowing the host is not the hub's stops it."""
    rebound = {"host": "evil.example:8000", "origin": "http://evil.example:8000"}
    forged = {"host": "192.168.1.20:8000", "x-forwarded-host": "evil.example", "origin": "http://evil.example"}
    async with named_hub(monkeypatch) as (app, client, told):
        read = await client.get("/api/health", headers={"host": "evil.example:8000"})
        assert read.status_code == 403
        assert "PRINTGUARD_ORIGINS=http://evil.example:8000" in read.text
        assert (await client.get("/api/v1/state", headers=rebound)).status_code == 403
        assert (await client.post("/api/prints?filename=a.gcode", content=b"G28", headers=rebound)).status_code == 403
        assert await handshake_answer(app, "/api/ws", rebound) == "websocket.close"
        assert await handshake_answer(app, "/api/publish/cam", rebound) == "websocket.close"
        assert (await client.get("/api/health", headers=forged)).status_code == 403

    assert len(told) == 2, "one line a name, however many requests it sends"
    assert "PRINTGUARD_ORIGINS=http://evil.example:8000" in told[0]


async def test_a_request_naming_no_host_is_refused(monkeypatch) -> None:
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request"}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {"type": "http", "method": "GET", "scheme": "http", "path": "/api/health", "raw_path": b"/api/health", "root_path": "", "query_string": b"", "headers": []}
    async with named_hub(monkeypatch) as (app, _client, told):
        await app(scope, receive, send)
        assert sent[0]["status"] == 403
        assert await handshake_answer(app, "/api/ws", {"origin": "http://test"}) == "websocket.close"

    assert told == ["PrintGuard refused a request that names no host."]


async def test_a_proxied_hub_answers_to_the_name_in_printguard_origins(monkeypatch) -> None:
    proxied = {"host": "printguard:8000", "x-forwarded-host": "hub.example.com", "x-forwarded-proto": "https"}
    async with named_hub(monkeypatch) as (_app, client, _told):
        assert (await client.get("/api/health", headers=proxied)).status_code == 200
        assert (await client.get("/api/health", headers={"host": "hub.example.com"})).status_code == 200
        unlisted = await client.get("/api/health", headers={**proxied, "x-forwarded-host": "other.example.com"})
        assert unlisted.status_code == 403 and "PRINTGUARD_ORIGINS=https://other.example.com" in unlisted.text


async def test_event_queue_conflates_telemetry_without_dropping_ordered_events() -> None:
    queue = ConflatedEventQueue()
    queue.put({"event": "state", "version": "old"})
    queue.put({"event": "result", "monitor_id": "one", "score": 0.1})
    queue.put({"event": "warning", "message": "camera stalled"})
    queue.put({"event": "state", "version": "new"})
    queue.put({"event": "result", "monitor_id": "one", "score": 0.9})
    queue.put({"event": "result", "monitor_id": "two", "score": 0.4})
    queue.put({"event": "state", "req_id": 7, "version": "command"})
    queue.put({"event": "state", "version": "newest"})

    assert await queue.get() == {"event": "warning", "message": "camera stalled"}
    assert await queue.get() == {"event": "state", "req_id": 7, "version": "command"}
    assert await queue.get() == {"event": "state", "version": "newest"}
    assert await queue.get() == {"event": "result", "monitor_id": "one", "score": 0.9}
    assert await queue.get() == {"event": "result", "monitor_id": "two", "score": 0.4}


async def test_a_tick_state_queued_before_a_commands_state_is_not_delivered_after_it() -> None:
    queue = ConflatedEventQueue()
    queue.put({"event": "state", "version": "before the command"})
    queue.put({"event": "state", "req_id": 7, "version": "command"})
    queue.put({"event": "warning", "message": "camera stalled"})

    assert await queue.get() == {"event": "state", "req_id": 7, "version": "command"}
    assert await queue.get() == {"event": "warning", "message": "camera stalled"}
    assert queue._state is None and not queue._events


async def test_hls_view_wakes_camera_before_proxying() -> None:
    platform = SimpleNamespace(view_camera=AsyncMock(), plugin_runtime=None)
    app = create_app()
    app.state.engine = SimpleNamespace(platform=platform)
    app.state.hls = httpx.AsyncClient(
        base_url="http://mediamtx",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=AsyncContent(), request=request)),
    )

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/hls/camera-one/index.m3u8")
    finally:
        await app.state.hls.aclose()

    assert response.content == b"#EXTM3U"
    platform.view_camera.assert_awaited_once_with("camera-one")


async def test_hls_answers_502_while_the_streaming_server_is_unreachable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    app = create_app()
    app.state.engine = SimpleNamespace(platform=SimpleNamespace(view_camera=AsyncMock(), plugin_runtime=None))
    app.state.hls = httpx.AsyncClient(base_url="http://mediamtx", transport=httpx.MockTransport(refuse))

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            responses = [await client.get("/hls/camera-one/index.m3u8") for _ in range(2)]
    finally:
        await app.state.hls.aclose()

    assert [response.status_code for response in responses] == [502, 502]


async def test_a_sandboxed_page_cannot_pull_a_camera_stream() -> None:
    """A plugin's own pages are served into an opaque origin.

    Nothing else in a browser sends ``Origin: null``, so refusing it is what
    stops a plugin serving itself a page that reads the live feed without ever
    asking for a camera permission.
    """
    platform = SimpleNamespace(view_camera=AsyncMock(), plugin_runtime=None)
    app = create_app()
    app.state.engine = SimpleNamespace(platform=platform)
    app.state.hls = httpx.AsyncClient(
        base_url="http://mediamtx",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=AsyncContent(), request=request)),
    )

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            refused = await client.get("/hls/camera-one/index.m3u8", headers={"origin": "null"})
            allowed = await client.get("/hls/camera-one/index.m3u8", headers={"origin": "http://test"})
    finally:
        await app.state.hls.aclose()

    assert refused.status_code == 403
    assert allowed.status_code == 200
    platform.view_camera.assert_awaited_once_with("camera-one")


async def test_a_page_on_another_origin_cannot_read_a_camera_stream() -> None:
    """The auth proxy lets the request through with the session cookie, and MediaMTX may answer any origin."""
    platform = SimpleNamespace(view_camera=AsyncMock(), plugin_runtime=None)
    app = create_app()
    app.state.engine = SimpleNamespace(platform=platform)
    open_cors = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Credentials": "true", "Content-Type": "application/vnd.apple.mpegurl"}
    app.state.hls = httpx.AsyncClient(
        base_url="http://mediamtx",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, headers=open_cors, stream=AsyncContent(), request=request)),
    )

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            foreign = await client.get("/hls/camera-one/index.m3u8", headers={"origin": "https://evil.example"})
            own = await client.get("/hls/camera-one/index.m3u8", headers={"origin": "http://test"})
            player = await client.get("/hls/camera-one/index.m3u8")
    finally:
        await app.state.hls.aclose()

    assert foreign.status_code == 403
    assert own.status_code == player.status_code == 200
    assert own.headers["content-type"] == "application/vnd.apple.mpegurl"
    assert not [name for name in own.headers if name.startswith("access-control-")]
    assert platform.view_camera.await_count == 2, "a refused request woke the camera"


async def test_failed_startup_stops_the_streaming_server(monkeypatch, tmp_path) -> None:
    """A hub that cannot finish starting takes the streaming server down with it.

    Left running, it holds the streaming ports for as long as the process lives and
    blocks the next hub started on that host, so an engine that will not start must
    not strand it.
    """
    binary = tmp_path / "mediamtx"
    binary.touch()
    streamer = SimpleNamespace(start=AsyncMock(), stop=AsyncMock())
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAMTX_BINARY", str(binary))
    monkeypatch.setattr("printguard.server.app.EmbeddedMediaMTX", lambda *_: streamer)
    monkeypatch.setattr(
        "printguard.server.app.Engine",
        lambda _: SimpleNamespace(start=AsyncMock(side_effect=RuntimeError("no model runtime"))),
    )
    app = create_app()

    with pytest.raises(RuntimeError):
        async with app.router.lifespan_context(app):
            pass

    streamer.stop.assert_awaited_once()


async def test_a_proxy_in_the_environment_is_never_sent_the_hubs_calls_to_its_own_streaming_server(tmp_path, monkeypatch) -> None:
    """With HTTP_PROXY set and no NO_PROXY, the proxy was sent the login the bundled server answers to."""
    proxy = socket.create_server(("127.0.0.1", 0))
    proxy.setblocking(False)
    with socket.create_server(("127.0.0.1", 0)) as unused:
        streaming_server = f"http://127.0.0.1:{unused.getsockname()[1]}"
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PRINTGUARD_PLUGINS", "off")
    monkeypatch.setenv("MEDIAMTX_API", streaming_server)
    monkeypatch.setenv("MEDIAMTX_HLS", streaming_server)
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy.getsockname()[1]}")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    app = create_app()

    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client,
        ):
            with pytest.raises(httpx.ConnectError):
                await app.state.engine.platform.mediamtx.list_paths()
            assert (await client.get("/hls/camera-one/index.m3u8")).status_code == 502
        with pytest.raises(BlockingIOError):
            proxy.accept()
    finally:
        proxy.close()


class StubRuntime:
    """Stands in for the plugin sandbox to exercise the hub's wiring."""

    def __init__(self, answer=None, verdict=None, gate: str = "accounts") -> None:
        self.answer = answer
        self.verdict = verdict
        self.gate = gate
        self.seen: list[dict] = []

    async def serve(self, plugin_id: str, request: dict):
        self.seen.append(request)
        return self.answer

    async def authorise(self, request: dict):
        self.seen.append(request)
        return self.verdict

    def gate_paths(self) -> tuple[str, ...]:
        return (f"/plugins/{self.gate}/",)


def app_with(runtime: StubRuntime):
    app = create_app()
    app.state.engine = SimpleNamespace(platform=SimpleNamespace(version="2.4.0", plugin_runtime=runtime))
    return app


async def test_plugin_routes_are_served_into_a_sandboxed_origin() -> None:
    runtime = StubRuntime(answer={"status": 201, "type": "text/html", "body": "<p>hi</p>", "headers": {"set-cookie": "s=1", "x-evil": "no"}})
    app = app_with(runtime)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/plugins/accounts/login?next=/", content=b"user=me")

    assert response.status_code == 201 and response.text == "<p>hi</p>"
    assert "sandbox" in response.headers["content-security-policy"], "a plugin's page was served as the dashboard's origin"
    assert response.headers["set-cookie"] == "s=1"
    assert "x-evil" not in response.headers, "a plugin set a header it has no business setting"
    assert runtime.seen[0]["body"] == "user=me" and runtime.seen[0]["query"] == {"next": "/"}


async def test_a_gating_plugin_can_refuse_a_request_but_never_its_own_routes() -> None:
    runtime = StubRuntime(answer={"status": 200, "body": "login"}, verdict=False)
    app = app_with(runtime)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        refused = await client.get("/")
        own = await client.get("/plugins/accounts/login")
        other = await client.get("/plugins/reports/index")
        health = await client.get("/api/health")

    assert refused.status_code == 403
    assert own.status_code == 200, "the gate locked out the very page that signs you in"
    assert other.status_code == 403, "another plugin's pages went out without the gate seeing them"
    assert health.status_code == 200, "readiness is never gated, so an uptime check still works"


async def test_an_unknown_host_is_told_the_setting_before_a_gating_plugin_is_asked() -> None:
    runtime = StubRuntime(verdict=False)
    app = app_with(runtime)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        refused = await client.get("/", headers={"host": "hub.example.com"})

    assert refused.status_code == 403 and "PRINTGUARD_ORIGINS=http://hub.example.com" in refused.text
    assert not runtime.seen, "a plugin was handed a request for a name the hub does not answer to"


async def test_a_plugin_route_stops_reading_a_body_at_its_limit(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "PLUGIN_BODY_LIMIT", 16)
    runtime = StubRuntime(answer={"body": "ok"})
    app = app_with(runtime)
    read = 0

    async def endless():
        nonlocal read
        while True:
            read += 8
            yield b"x" * 8

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async with asyncio.timeout(2):
            response = await client.post("/plugins/accounts/login", content=endless())

    assert response.status_code == 200 and runtime.seen[-1]["body"] == "x" * 16
    assert read <= 32


async def test_a_flood_of_made_up_cookies_cannot_grow_the_gate_cache(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "GATE_CACHE_ENTRIES", 2)
    runtime = StubRuntime(verdict=True)
    app = app_with(runtime)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for session in ("a", "b", "c"):
            await client.get("/", headers={"cookie": f"s={session}"})
        asked = len(runtime.seen)
        await client.get("/", headers={"cookie": "s=c"})
        await client.get("/", headers={"cookie": "s=a"})

    assert len(runtime.seen) == asked + 1, "the newest answer should still be cached and the oldest pushed out"


async def test_the_dashboard_inspects_a_sample_before_uploading(monkeypatch) -> None:
    from test_gcode import CURA, PRUSA

    from fakes import FakePlatform

    from printguard.engine.engine import Engine
    from printguard.server import prints

    engine = Engine(FakePlatform())
    await engine.start()
    app = create_app()
    app.state.engine = engine
    octet = {"Content-Type": "application/octet-stream", "origin": "http://test"}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            foreign = await client.post("/api/prints/inspect?ext=gcode", content=PRUSA, headers={**octet, "origin": "https://evil.example"})
            assert foreign.status_code == 403
            prusa = (await client.post("/api/prints/inspect?ext=gcode", content=PRUSA, headers=octet)).json()
            assert prusa["thumbnail"] is True and prusa["meta"]["printer_model"] == "MK4"
            cura = (await client.post("/api/prints/inspect?ext=gcode", content=CURA, headers=octet)).json()
            assert cura["thumbnail"] is False, "the dashboard draws one for a file that carries none"
            assert (await client.post("/api/prints/inspect?ext=stl", content=b"solid", headers=octet)).status_code == 400
            assert (await client.post("/api/prints/inspect?ext=bgcode", content=CURA, headers=octet)).status_code == 400
            monkeypatch.setattr(prints, "MAX_SAMPLE_BYTES", 16)
            assert (await client.post("/api/prints/inspect?ext=gcode", content=CURA, headers=octet)).status_code == 413
    finally:
        await engine.stop()


async def test_dashboard_upload_is_same_origin_and_feeds_the_viewer(tmp_path) -> None:
    from fakes import FakePlatform
    from test_gcode import PRUSA

    from printguard.engine.engine import Engine
    from printguard.server.platform import DiskFileStore

    platform = FakePlatform()
    platform.files = DiskFileStore(tmp_path)
    engine = Engine(platform)
    await engine.start()
    app = create_app()
    app.state.engine = engine
    octet = {"Content-Type": "application/octet-stream"}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            foreign = await client.post("/api/prints?filename=benchy.gcode", content=PRUSA, headers={**octet, "origin": "https://evil.example"})
            assert foreign.status_code == 403, "a cross-site page cannot fill the library through the session cookie"
            uploaded = await client.post("/api/prints?filename=benchy.gcode&name=Boat", content=PRUSA, headers={**octet, "origin": "http://test"})
            assert uploaded.status_code == 200, uploaded.text
            print_id = uploaded.json()["id"]
            assert engine.prints.get(print_id).name == "Boat"
            cold = await client.post("/api/prints?filename=benchy.gcode&bed=60", content=PRUSA, headers={**octet, "origin": "http://test"})
            assert cold.status_code == 400 and "never heats the bed" in cold.json()["detail"]
            empty = await client.post("/api/prints?filename=empty.gcode", content=b"", headers={**octet, "origin": "http://test"})
            assert empty.status_code == 400 and "empty" in empty.json()["detail"]
            assert len(list(engine.prints.values())) == 1

            text = await client.get(f"/api/prints/{print_id}/gcode")
            assert text.status_code == 200 and text.content == PRUSA and text.headers["content-type"].startswith("text/plain")
            image = await client.get(f"/api/prints/{print_id}/thumbnail")
            assert image.status_code == 200 and image.content == b"BIG" and image.headers["content-type"] == "image/png"
            assert "immutable" in image.headers["cache-control"]
            assert (await client.get("/api/prints/nope/gcode")).status_code == 404
    finally:
        await engine.stop()


async def test_the_viewer_unpacks_a_3mf_off_the_event_loop(tmp_path, monkeypatch) -> None:
    from printguard.engine.registry import PrintFile, PrintRegistry
    from printguard.server import prints
    from printguard.server.platform import DiskFileStore

    unpacked_on: list[threading.Thread] = []

    def plate_gcode(data: bytes) -> tuple[str, bytes]:
        unpacked_on.append(threading.current_thread())
        return "Metadata/plate_1.gcode", data

    monkeypatch.setattr(prints.gcode, "plate_gcode", plate_gcode)
    library = PrintRegistry()
    library.add(PrintFile(id="plate", name="Plate", filename="plate.3mf", ext="3mf", size=3, printer_ids=[], uploaded=0.0, meta={}))
    (tmp_path / "plate.3mf").write_bytes(b"G28")
    app = create_app()
    app.state.engine = SimpleNamespace(platform=SimpleNamespace(plugin_runtime=None, files=DiskFileStore(tmp_path)), prints=library)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/prints/plate/gcode")).content == b"G28"
    assert unpacked_on and unpacked_on[0] is not threading.main_thread()


async def test_an_upload_the_engine_never_finishes_adding_leaves_no_file(tmp_path, monkeypatch) -> None:
    from fakes import FakePlatform
    from test_gcode import PRUSA

    from printguard.engine.engine import Engine
    from printguard.server import prints
    from printguard.server.platform import DiskFileStore

    monkeypatch.setattr(prints, "ADD_TIMEOUT_S", 0.05)
    monkeypatch.setattr(prints.gcode, "inspect", lambda data, ext: time.sleep(0.3))
    platform = FakePlatform()
    platform.files = DiskFileStore(tmp_path)
    engine = Engine(platform)
    await engine.start()
    app = create_app()
    app.state.engine = engine
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            late = await client.post("/api/prints?filename=benchy.gcode", content=PRUSA, headers={"origin": "http://test"})
            assert late.status_code == 504 and "took too long" in late.json()["detail"]
        assert not engine.prints.values() and not list(tmp_path.iterdir())
    finally:
        await engine.stop()


async def test_a_starting_hub_clears_the_files_no_print_or_review_names(tmp_path) -> None:
    from fakes import FakePlatform
    from test_gcode import PRUSA

    from printguard.engine.engine import Engine
    from printguard.engine.platform import as_chunks
    from printguard.engine.reviews import frame_key
    from printguard.server import prints
    from printguard.server.platform import DiskFileStore

    platform = FakePlatform()
    platform.files = DiskFileStore(tmp_path)
    engine = Engine(platform)
    await engine.start()
    try:
        record = await prints.receive_print(engine, prints.PrintUpload(filename="benchy.gcode"), as_chunks(PRUSA))
        engine.reviews.restore([{"id": "a1", "monitor_id": "m1", "started": 0.0, "spacing_s": 5.0, "frames": [{"id": "f1"}]}])
        kept = {record.file_key, record.thumbnail_key, frame_key("a1", "f1"), "notes.txt", "my print.gcode", "0badf00d.stl", "@eaDir"}
        orphans = {frame_key("a1", "f2"), "deadbeef.gcode.part", "0badf00d.gcode", "0badf00d.thumb"}
        for name in {frame_key("a1", "f1")} | orphans | kept - {record.file_key, record.thumbnail_key, "@eaDir"}:
            (tmp_path / name).write_bytes(b"x")
        (tmp_path / "@eaDir").mkdir()

        await prints.sweep_orphans(engine, unnamed=False)
        assert {path.name for path in tmp_path.iterdir()} == kept | orphans - {"deadbeef.gcode.part"}, (
            "a damaged state file may yet be put back, and it may name these"
        )
        await prints.sweep_orphans(engine, unnamed=True)
        assert {path.name for path in tmp_path.iterdir()} == kept, "only names the hub generates are deleted"
    finally:
        await engine.stop()


async def test_a_starting_hub_keeps_the_files_of_a_record_it_could_not_read(tmp_path) -> None:
    from fakes import FakePlatform

    from printguard.engine.engine import Engine
    from printguard.server import prints
    from printguard.server.platform import DiskFileStore

    platform = FakePlatform()
    platform.files = DiskFileStore(tmp_path)
    platform.state = {"prints": [{"id": "abcd1234", "filename": "benchy.gcode"}]}
    for name in ("abcd1234.gcode", "abcd1234.thumb", "0badf00d.gcode"):
        (tmp_path / name).write_bytes(b"x")
    engine = Engine(platform)
    await engine.start()
    try:
        await prints.sweep_orphans(engine, unnamed=True)
        assert sorted(path.name for path in tmp_path.iterdir()) == ["abcd1234.gcode", "abcd1234.thumb"]
        assert "its file stays in the data directory until the hub next starts" in engine.startup_warnings[0]
        engine.save()
    finally:
        await engine.stop()
    restarted = Engine(platform)
    await restarted.start()
    try:
        await prints.sweep_orphans(restarted, unnamed=True)
        assert not list(tmp_path.iterdir()), "the warning says the file goes at the next start"
    finally:
        await restarted.stop()


async def test_an_upload_with_an_absurd_estimate_is_refused_and_leaves_nothing(tmp_path) -> None:
    from fakes import FakePlatform

    from printguard.engine.engine import Engine
    from printguard.server.platform import DiskFileStore

    platform = FakePlatform()
    platform.files = DiskFileStore(tmp_path)
    engine = Engine(platform)
    await engine.start()
    app = create_app()
    app.state.engine = engine
    crafted = b"; estimated printing time (normal mode) = " + b"9" * 4300 + b"d\nG28\nM104 S210\n"
    octet = {"Content-Type": "application/octet-stream", "origin": "http://test"}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            upload = await client.post("/api/prints?filename=evil.gcode", content=crafted, headers=octet)
            assert upload.status_code == 400 and "a number in this file" in upload.json()["detail"]
            assert (await client.post("/api/prints/inspect?ext=gcode", content=crafted, headers=octet)).status_code == 400
        assert not engine.prints.values() and not list(tmp_path.iterdir())
    finally:
        await engine.stop()


def test_a_host_that_cannot_be_read_is_not_trusted() -> None:
    assert not host_trusted("[::1", set())


def test_a_hub_answers_to_a_home_arpa_name_with_no_setup() -> None:
    """RFC 8375 keeps it for home networks, and it is the domain pfSense hands out."""
    assert host_trusted("tower.home.arpa:8000", set())
    assert not host_trusted("tower.in-addr.arpa", set())


async def test_an_origin_listed_in_another_case_or_with_its_own_port_is_still_allowed(monkeypatch) -> None:
    """A proxy that rewrites Host leaves the list as the only thing the socket's origin can match."""
    monkeypatch.setenv("PRINTGUARD_ORIGINS", "https://Hub.Example.com:443/, hub.example.net")
    told: list[str] = []
    monkeypatch.setattr("printguard.server.app.logger.warning", lambda message, *args: told.append(message % args))
    app = create_app()
    app.state.engine = SimpleNamespace(platform=SimpleNamespace(version="2.6.0", plugin_runtime=None))

    async def upload_from(origin: str) -> int:
        headers = {"host": "printguard:8000", "origin": origin}
        return (await client.post("/api/prints?filename=a.stl", content=b"solid", headers=headers)).status_code

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert await upload_from("https://hub.example.com") == 400, "the origin was refused, where the file should have been"
        assert await upload_from("https://hub.example.com:8443") == 403
        assert await upload_from("http://hub.example.com") == 403
        assert await upload_from("null") == 403, "an entry with no scheme let a sandboxed page in"
        assert (await client.get("/api/health", headers={"host": "hub.example.net"})).status_code == 403

    assert len(told) == 2 and "hub.example.net is ignored because it has no scheme" in told[0]


async def test_a_recording_sent_faster_than_it_plays_closes_the_publish_socket(monkeypatch) -> None:
    from printguard.server import publish

    stalled = threading.Event()
    monkeypatch.setattr(publish, "MAX_QUEUED_BYTES", 4)
    monkeypatch.setattr(app_module, "remux", lambda source, url: stalled.wait(2))
    app = create_app()
    app.state.engine = SimpleNamespace(platform=SimpleNamespace(plugin_runtime=None))
    try:
        async with Tab(app, "/api/publish/cam") as camera:
            for _ in range(3):
                camera.send(bytes=b"\x1a\x45\xdf\xa3")
            assert await camera.closed() == 1009
    finally:
        stalled.set()


async def test_a_gate_answer_is_not_reused_for_another_query() -> None:
    runtime = StubRuntime(verdict=True)
    app = app_with(runtime)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/?share=one")
        await client.get("/?share=two")
        await client.get("/?share=one")

    assert [request["query"] for request in runtime.seen] == [{"share": "one"}, {"share": "two"}]


def mounted(app, path: str):
    """The sub-application the hub mounts at a path."""
    return next(route.app for route in app.routes if getattr(route, "path", None) == path)


async def test_the_mcp_server_answers_without_the_trailing_slash(tmp_path, monkeypatch) -> None:
    """The static mount took the bare path and answered a POST with a 405."""
    from fakes import FakePlatform

    from printguard.engine.engine import Engine

    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    engine = Engine(FakePlatform())
    await engine.start()
    app = create_app()
    mounted(app, "/api/v1").state.engine = app.state.engine = engine
    handshake = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
    }
    accept = {"Accept": "application/json, text/event-stream"}
    try:
        async with (
            mounted(app, "/mcp").lifespan(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client,
        ):
            for path in ("/mcp", "/mcp/"):
                answer = await client.post(path, json=handshake, headers=accept)
                assert answer.status_code == 200 and "PrintGuard" in answer.text, path
    finally:
        await engine.stop()


async def test_a_print_whose_file_is_gone_is_a_404_that_names_no_path(tmp_path) -> None:
    from fakes import FakePlatform
    from test_gcode import PRUSA

    from printguard.engine.engine import Engine
    from printguard.server.platform import DiskFileStore

    platform = FakePlatform()
    platform.files = DiskFileStore(tmp_path)
    engine = Engine(platform)
    await engine.start()
    app = create_app()
    mounted(app, "/api/v1").state.engine = app.state.engine = engine
    octet = {"Content-Type": "application/octet-stream", "origin": "http://test"}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            print_id = (await client.post("/api/prints?filename=benchy.gcode", content=PRUSA, headers=octet)).json()["id"]
            for kept in tmp_path.iterdir():
                kept.unlink()
            for path in (f"/api/prints/{print_id}/gcode", f"/api/prints/{print_id}/thumbnail", f"/api/v1/prints/{print_id}/file"):
                gone = await client.get(path)
                assert gone.status_code == 404 and str(tmp_path) not in gone.text, path
    finally:
        await engine.stop()


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
def test_a_number_that_is_not_finite_is_refused_when_a_command_is_read(literal: str) -> None:
    from printguard.server.app import parse_command

    assert parse_command('{"cmd": "printer.heat", "nozzle": 1.5}') == {"cmd": "printer.heat", "nozzle": 1.5}
    assert parse_command('{"cmd": "printer.update", "patch": {"config": {"note": %s}}}' % literal) is None


async def test_the_engine_socket_refuses_a_command_carrying_nan_and_never_sends_one() -> None:
    from fakes import FakePlatform

    from printguard.engine.engine import Engine

    engine = Engine(FakePlatform())
    await engine.start()
    app = create_app()
    app.state.engine = engine
    try:
        async with Tab(app) as tab:
            tab.send(text='{"cmd": "settings.update", "patch": {"mqtt": {"keepalive": NaN}}}')
            await tab.until("error")
        assert "keepalive" not in (engine.settings.get("mqtt") or {})
        for message in tab._sent:
            parse_json(message.get("text") or "{}")
    finally:
        await engine.stop()


def test_an_event_holding_nan_cannot_be_written_to_a_dashboard() -> None:
    from printguard.server.events import encode_event

    assert encode_event({"event": "state", "n": 1.5}) == '{"event": "state", "n": 1.5}'
    with pytest.raises(ValueError):
        encode_event({"event": "state", "settings": {"mqtt": {"keepalive": float("nan")}}})


@pytest.mark.parametrize(
    ("host", "origin", "extra", "answered"),
    [
        ("192.168.1.20:80", "http://192.168.1.20", {}, 400),
        ("192.168.1.20", "http://192.168.1.20:80", {}, 400),
        ("tower:8000", "http://tower:8000", {}, 400),
        ("tower:8000", "file://tower:8000", {}, 403),
        ("tower:8000", "chrome-extension://tower:8000", {}, 403),
        ("tower:8000", "https://tower:8000", {}, 403),
        ("tower", "https://tower", {"x-forwarded-proto": "https"}, 400),
        ("tower", "http://tower", {"x-forwarded-proto": "https"}, 403),
    ],
)
async def test_an_origin_is_the_hubs_own_only_with_the_scheme_and_port_it_was_asked_on(
    monkeypatch, host: str, origin: str, extra: dict[str, str], answered: int
) -> None:
    """A 400 is the empty upload the origin let through."""
    async with named_hub(monkeypatch) as (_app, client, _told):
        headers = {"host": host, "origin": origin, **extra}
        assert (await client.post("/api/prints?filename=a.stl", content=b"solid", headers=headers)).status_code == answered


PROXIED_SOCKET_CASES = [
    ({}, "http://test", True),
    ({"x-forwarded-proto": "ws"}, "http://test", True),
    ({"x-forwarded-proto": "wss"}, "https://test", True),
    ({"x-forwarded-proto": "wss"}, "http://test", False),
    ({"x-forwarded-proto": "https"}, "https://test", True),
    ({"x-forwarded-proto": "HTTPS"}, "https://test", True),
    ({"x-forwarded-proto": "https,http"}, "https://test", True),
    ({"x-forwarded-proto": "https,http"}, "http://test", False),
    ({"x-forwarded-proto": "gopher"}, "http://test", False),
    ({"x-forwarded-proto": "gopher"}, "https://hub.example.com", False),
]


@pytest.mark.parametrize("listed", [False, True])
@pytest.mark.parametrize("path", ["/api/ws", "/api/publish/cam"])
@pytest.mark.parametrize(("forwarded", "origin", "own"), PROXIED_SOCKET_CASES)
async def test_a_socket_is_let_in_by_the_scheme_a_proxy_forwards_whatever_word_it_uses(
    monkeypatch, forwarded: dict[str, str], origin: str, own: bool, path: str, listed: bool
) -> None:
    """Traefik sends ws or wss on an upgrade, and a value that is no scheme can only fail the hub's own origin."""
    from fakes import FakePlatform

    from printguard.engine.engine import Engine

    monkeypatch.setattr(app_module, "remux", lambda source, url: [None for _chunk in iter(lambda: source.read(1), b"")])
    if listed:
        monkeypatch.setenv("PRINTGUARD_ORIGINS", "https://hub.example.com")
    engine = Engine(FakePlatform())
    await engine.start()
    app = create_app()
    app.state.engine = engine
    try:
        for asked, expected in ((origin, own or (listed and origin == "https://hub.example.com")), ("https://hub.example.com", listed)):
            async with Tab(app, path, {"host": "test", "origin": asked, **forwarded}) as tab:
                async with asyncio.timeout(2):
                    while not tab._sent:
                        await asyncio.sleep(0.01)
                assert (tab._sent[0]["type"] == "websocket.accept") is expected, (asked, forwarded, listed)
    finally:
        await engine.stop()


@pytest.mark.parametrize("origin", ["http://test:abc", "http://test:99999", "http://[::1"])
async def test_an_origin_that_cannot_be_read_is_refused_not_answered_with_a_crash(monkeypatch, origin: str) -> None:
    async with named_hub(monkeypatch) as (app, client, _told):
        headers = {"host": "test", "origin": origin}
        assert (await client.post("/api/prints?filename=a.stl", content=b"solid", headers=headers)).status_code == 403
        assert (await client.post("/api/prints/inspect?ext=gcode", content=b"G28", headers=headers)).status_code == 403
        assert (await client.get("/hls/camera-one/index.m3u8", headers=headers)).status_code == 403
        assert await handshake_answer(app, "/api/ws", headers) == "websocket.close"
        assert await handshake_answer(app, "/api/publish/cam", headers) == "websocket.close"


@pytest.mark.parametrize("host", ["localhost.", "localhost.:8000", "printguard.local.", "192.168.1.20.:8000", "hub.example.com."])
def test_a_host_written_with_a_trailing_dot_is_the_same_host(host: str) -> None:
    assert host_trusted(host, {"hub.example.com"})


def test_a_trailing_dot_does_not_make_a_public_name_trusted() -> None:
    assert not host_trusted("evil.example.", {"hub.example.com"})


async def test_an_origin_entry_with_a_trailing_dot_still_names_the_hub(monkeypatch) -> None:
    monkeypatch.setenv("PRINTGUARD_ORIGINS", "https://hub.example.com.")
    app = create_app()
    app.state.engine = SimpleNamespace(platform=SimpleNamespace(version="2.6.0", plugin_runtime=None))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/health", headers={"host": "hub.example.com"})).status_code == 200
        assert (await client.get("/api/health", headers={"host": "hub.example.com."})).status_code == 200
        upload = await client.post("/api/prints?filename=a.stl", content=b"solid", headers={"host": "printguard:8000", "origin": "https://hub.example.com"})
        assert upload.status_code == 400, "the origin was refused, where the file should have been"


@pytest.mark.parametrize(
    ("listed", "sent"),
    [("https://drucker.müller.example", "drucker.xn--mller-kva.example"), ("https://Straße.example", "xn--strae-oqa.example")],
)
async def test_an_internationalised_origin_entry_names_the_hub_the_way_a_browser_sends_it(monkeypatch, listed: str, sent: str) -> None:
    """It was taken as written, which no browser sends, so the name was refused with nothing logged."""
    monkeypatch.setenv("PRINTGUARD_ORIGINS", listed)
    app = create_app()
    app.state.engine = SimpleNamespace(platform=SimpleNamespace(version="2.6.0", plugin_runtime=None))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/health", headers={"host": sent})).status_code == 200
        upload = await client.post("/api/prints?filename=a.stl", content=b"solid", headers={"host": "printguard:8000", "origin": f"https://{sent}"})
        assert upload.status_code == 400, "the origin was refused, where the file should have been"


async def test_an_origin_entry_with_another_scheme_is_ignored_and_names_no_host(monkeypatch) -> None:
    monkeypatch.setenv("PRINTGUARD_ORIGINS", "ftp://ftp.example.io, https://ok.example.com")
    told: list[str] = []
    monkeypatch.setattr("printguard.server.app.logger.warning", lambda message, *args: told.append(message % args))
    app = create_app()
    app.state.engine = SimpleNamespace(platform=SimpleNamespace(version="2.6.0", plugin_runtime=None))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/health", headers={"host": "ok.example.com"})).status_code == 200
        assert (await client.get("/api/health", headers={"host": "ftp.example.io"})).status_code == 403

    assert any("ftp://ftp.example.io is ignored" in line for line in told)


async def test_an_origin_entry_that_cannot_be_read_is_ignored_and_the_hub_still_starts(monkeypatch) -> None:
    monkeypatch.setenv("PRINTGUARD_ORIGINS", "https://hub.example.com:abc, http://[::1, https://ok.example.com")
    told: list[str] = []
    monkeypatch.setattr("printguard.server.app.logger.warning", lambda message, *args: told.append(message % args))
    app = create_app()
    app.state.engine = SimpleNamespace(platform=SimpleNamespace(version="2.6.0", plugin_runtime=None))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/health", headers={"host": "ok.example.com"})).status_code == 200
        assert (await client.get("/api/health", headers={"host": "hub.example.com"})).status_code == 403

    ignored = [line for line in told if "is ignored" in line]
    assert len(ignored) == 2 and "https://hub.example.com:abc" in ignored[0] and "http://[::1" in ignored[1]


def test_the_hub_takes_a_websocket_message_big_enough_for_a_plugin_zip(monkeypatch) -> None:
    """A 12 MiB zip travels as base64 in one frame, which uvicorn's own 16 MiB limit already closes."""
    served: dict = {}
    monkeypatch.setattr(app_module.uvicorn, "run", lambda app, **options: served.update(options))
    app_module.main()

    assert served["ws_max_size"] == app_module.WEBSOCKET_MAX_BYTES
    assert app_module.WEBSOCKET_MAX_BYTES > 12 * 1024 * 1024 * 4 // 3


def test_the_desktop_app_serves_the_same_websocket_limit(monkeypatch) -> None:
    from printguard.server import desktop

    configs: list[dict] = []
    monkeypatch.setattr(desktop.uvicorn, "Config", lambda app, **options: configs.append(options))
    monkeypatch.setattr(desktop.uvicorn, "Server", lambda config: SimpleNamespace())
    desktop._Server(8000)

    assert configs[0]["ws_max_size"] == app_module.WEBSOCKET_MAX_BYTES


@pytest.mark.parametrize(
    "answer",
    [
        {"status": "abc"},
        {"status": "201"},
        {"status": True},
        {"status": 99},
        {"status": 600},
        {"status": 200.5},
        {"status": None},
        {"headers": "set-cookie: a=1"},
        {"headers": ["set-cookie"]},
        {"headers": {"set-cookie": 1}},
    ],
)
async def test_a_plugin_route_answering_with_a_bad_status_or_headers_is_that_plugin_failing(answer: dict) -> None:
    failed: list[tuple[str, str]] = []
    app = app_with(StubRuntime(answer={"body": "x", **answer}))
    app.state.engine.plugin_failed = lambda plugin_id, reason: failed.append((plugin_id, reason))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/plugins/accounts/login")

    assert response.status_code == 502 and "accounts" in response.text
    assert [plugin_id for plugin_id, _ in failed] == ["accounts"] and failed[0][1]


async def test_a_plugin_route_answering_without_a_status_or_headers_is_served() -> None:
    failed: list[str] = []
    app = app_with(StubRuntime(answer={"body": "x", "headers": None}))
    app.state.engine.plugin_failed = lambda plugin_id, reason: failed.append(plugin_id)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/plugins/accounts/login")

    assert response.status_code == 200 and not failed


async def test_a_start_that_finds_no_state_file_keeps_what_the_print_store_holds(tmp_path, monkeypatch) -> None:
    """With state.json gone, nothing was named, so the library, the review frames and the alert pictures were all deleted."""
    with socket.create_server(("127.0.0.1", 0)) as unused:
        streaming_server = f"http://127.0.0.1:{unused.getsockname()[1]}"
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PRINTGUARD_PLUGINS", "off")
    monkeypatch.setenv("MEDIAMTX_API", streaming_server)
    store = tmp_path / "prints"
    store.mkdir()
    for name in ("0badf00d.gcode", "deadbeef.gcode.part"):
        (store / name).write_bytes(b"x")

    app = create_app()
    async with app.router.lifespan_context(app):
        assert [path.name for path in store.iterdir()] == ["0badf00d.gcode"], "a state file put back later may name it"

    (tmp_path / "state.json").write_text("{}")
    app = create_app()
    async with app.router.lifespan_context(app):
        assert not list(store.iterdir()), "a state that names no such file leaves it an orphan"


@pytest.mark.parametrize("frame", ["[" * 100_000 + "]" * 100_000, '{"a":' * 1_100 + "1" + "}" * 1_100])
def test_a_frame_nested_deeper_than_the_parser_goes_is_not_a_command(frame: str) -> None:
    """The RecursionError ended the socket's handler, where any other malformed frame gets an error back."""
    from printguard.server.app import parse_command

    assert parse_command(frame) is None


async def test_a_gate_answer_is_not_reused_for_another_client_address_or_browser() -> None:
    """A gate is handed both headers, so one that decides by them approved others from the cache."""
    runtime = StubRuntime(verdict=True)
    app = app_with(runtime)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for headers in (
            {"x-forwarded-for": "192.168.1.5", "user-agent": "kiosk"},
            {"x-forwarded-for": "203.0.113.9", "user-agent": "kiosk"},
            {"x-forwarded-for": "192.168.1.5", "user-agent": "other"},
            {"x-forwarded-for": "192.168.1.5", "user-agent": "kiosk"},
        ):
            await client.get("/", headers=headers)

    assert [request["headers"]["x-forwarded-for"] for request in runtime.seen] == ["192.168.1.5", "203.0.113.9", "192.168.1.5"]


async def test_a_failed_publish_closes_its_socket_without_the_streaming_servers_login(monkeypatch) -> None:
    """PyAV quotes the address it could not reach, and the dashboard shows the reason."""

    def refused(source, url: str) -> None:
        raise OSError(f"[Errno 61] Connection refused: '{url}'")

    monkeypatch.setenv("MEDIAMTX_RTSP", "rtsp://hub:RTSP-PASS-77@mediamtx:8554")
    monkeypatch.setattr(app_module, "remux", refused)
    app = create_app()
    app.state.engine = SimpleNamespace(platform=SimpleNamespace(plugin_runtime=None))
    async with Tab(app, "/api/publish/cam") as camera:
        await asyncio.sleep(0.05)
        camera.send(bytes=b"\x1a\x45")
        assert await camera.closed() == 1011
        reason = next(message["reason"] for message in camera._sent if message["type"] == "websocket.close")

    assert "Connection refused" in reason and "RTSP-PASS-77" not in reason


@pytest.mark.parametrize("path", ["/hls/%00", "/hls/%ff%fe", "/hls/cam/%7f.m3u8"])
async def test_a_stream_path_that_cannot_be_asked_for_is_a_404(path: str) -> None:
    """These answered 500 with a traceback in the log, to anyone who could reach the hub."""
    platform = SimpleNamespace(view_camera=AsyncMock(), plugin_runtime=None)
    app = create_app()
    app.state.engine = SimpleNamespace(platform=platform)
    app.state.hls = httpx.AsyncClient(
        base_url="http://mediamtx",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=AsyncContent(), request=request)),
    )

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            answer = await client.get(path)
    finally:
        await app.state.hls.aclose()

    assert answer.status_code == 404
    platform.view_camera.assert_not_awaited()


async def test_an_origin_entry_with_a_wildcard_is_ignored_and_frames_nothing(monkeypatch, tmp_path) -> None:
    """It matched no host and went into frame-ancestors as it was written, with no warning."""
    (tmp_path / "index.html").write_text("<html></html>")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    monkeypatch.setenv("PRINTGUARD_ORIGINS", "https://*.wild.example, https://ok.example.com")
    told: list[str] = []
    monkeypatch.setattr("printguard.server.app.logger.warning", lambda message, *args: told.append(message % args))
    app = create_app()
    app.state.engine = SimpleNamespace(platform=SimpleNamespace(version="2.6.0", plugin_runtime=None))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/health", headers={"host": "hub.wild.example"})).status_code == 403
        policy = (await client.get("/")).headers["content-security-policy"]

    assert policy == "frame-ancestors 'self' https://ok.example.com"
    assert any("https://*.wild.example is ignored because a wildcard" in line for line in told)


async def test_a_page_on_another_site_cannot_call_the_rest_api_or_the_mcp_server(monkeypatch) -> None:
    """With no token issued both answer anyone, and a browser posts a plain body to them without asking first."""
    from fakes import FakePlatform

    from printguard.engine.engine import Engine

    monkeypatch.setenv("PRINTGUARD_ORIGINS", "https://panel.example.com")
    engine = Engine(FakePlatform())
    await engine.start()
    app = create_app()
    mounted(app, "/api/v1").state.engine = app.state.engine = engine
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            elsewhere = {"origin": "https://evil.example"}
            assert (await client.post("/api/v1/classify", content=b"\xff\xd8jpeg", headers=elsewhere)).status_code == 403
            assert (await client.get("/api/v1/state", headers=elsewhere)).status_code == 403
            assert (await client.post("/mcp", json={}, headers=elsewhere)).status_code == 403
            assert (await client.post("/mcp/", json={}, headers={"origin": "null"})).status_code == 403
            for allowed in ({}, {"origin": "http://test"}, {"origin": "https://panel.example.com"}):
                assert (await client.post("/api/v1/classify", content=b"\xff\xd8jpeg", headers=allowed)).status_code == 200, allowed
    finally:
        await engine.stop()
