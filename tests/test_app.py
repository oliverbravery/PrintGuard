"""Hub application static asset behaviour."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

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
    app.state.engine = SimpleNamespace(platform=SimpleNamespace(version="2.3.7"))

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
    platform = SimpleNamespace(view_camera=AsyncMock())
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
