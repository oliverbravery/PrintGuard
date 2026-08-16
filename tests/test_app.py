"""Hub application static asset behaviour."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from printguard.server.app import ASSET_CACHE_CONTROL, REVALIDATE_CACHE_CONTROL, WebStaticFiles, create_app
from printguard.server.events import ConflatedEventQueue


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


async def test_health_reports_ready_version_without_caching() -> None:
    app = create_app()
    app.state.engine = SimpleNamespace(platform=SimpleNamespace(version="2.3.7", plugin_runtime=None))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "version": "2.3.7"}
    assert response.headers["cache-control"] == "no-store"


async def test_event_queue_conflates_telemetry_without_dropping_ordered_events() -> None:
    queue = ConflatedEventQueue()
    queue.put({"event": "state", "version": "old"})
    queue.put({"event": "result", "monitor_id": "one", "score": 0.1})
    queue.put({"event": "warning", "message": "camera stalled"})
    queue.put({"event": "state", "version": "new"})
    queue.put({"event": "result", "monitor_id": "one", "score": 0.9})
    queue.put({"event": "result", "monitor_id": "two", "score": 0.4})
    queue.put({"event": "state", "req_id": 7, "version": "command"})

    assert await queue.get() == {"event": "warning", "message": "camera stalled"}
    assert await queue.get() == {"event": "state", "req_id": 7, "version": "command"}
    assert await queue.get() == {"event": "state", "version": "new"}
    assert await queue.get() == {"event": "result", "monitor_id": "one", "score": 0.9}
    assert await queue.get() == {"event": "result", "monitor_id": "two", "score": 0.4}


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


class StubRuntime:
    """Stands in for the plugin sandbox to exercise the hub's wiring."""

    def __init__(self, answer=None, verdict=None) -> None:
        self.answer = answer
        self.verdict = verdict
        self.seen: list[dict] = []

    async def serve(self, plugin_id: str, request: dict):
        self.seen.append(request)
        return self.answer

    async def authorise(self, request: dict):
        self.seen.append(request)
        return self.verdict


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
        health = await client.get("/api/health")

    assert refused.status_code == 403
    assert own.status_code == 200, "the gate locked out the very page that signs you in"
    assert health.status_code == 200, "readiness is never gated, so an uptime check still works"
