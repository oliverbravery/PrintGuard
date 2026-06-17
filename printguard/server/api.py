"""Versioned REST surface over the engine protocol (hub mode only).

Every route delegates to the same engine command/event protocol the UI speaks,
so the REST API, the MCP tools derived from it and the dashboard can never
drift. Routes are tagged with the scope they require (read, control or manage);
the same tags drive both this API's bearer-scope guard and the MCP tool filter.
"""

from __future__ import annotations

import hmac
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..engine.engine import Engine

SCOPE_ORDER = ("read", "control", "manage")


def expand_scope(scope: str) -> set[str]:
    """Returns the cumulative set a granted scope implies."""
    return set(SCOPE_ORDER[: SCOPE_ORDER.index(scope) + 1])


def route_scope(tags: list[str] | None) -> str:
    """Reads the scope a route requires from its tags, defaulting to read."""
    present = [tag for tag in (tags or []) if tag in SCOPE_ORDER]
    return max(present, key=SCOPE_ORDER.index) if present else "read"


class ApiAuth:
    """Resolves a bearer token to the scopes it grants.

    With no tokens configured the surface trusts whatever fronts it (a reverse
    proxy or the local network) and grants read access anonymously; control and
    management stay closed until the operator issues scoped tokens. Once any
    token exists a valid bearer is required for every request. The internal token
    authenticates the in-process MCP loopback and always grants full scope
    without affecting whether operator authentication is required.
    """

    def __init__(self, tokens: dict[str, str], internal_token: str | None = None) -> None:
        self.tokens = tokens
        self._internal = internal_token

    @property
    def enabled(self) -> bool:
        return bool(self.tokens)

    def resolve(self, header: str | None) -> set[str] | None:
        """Returns the granted scopes, or None when a required token is missing."""
        token = ""
        if header and header.lower().startswith("bearer "):
            token = header[7:].strip()
        if self._internal and token and hmac.compare_digest(self._internal, token):
            return expand_scope("manage")
        for known, scope in self.tokens.items():
            if hmac.compare_digest(known, token):
                return expand_scope(scope)
        if not self.enabled:
            return expand_scope("read")
        return None


def parse_tokens(raw: str) -> dict[str, str]:
    """Parses PRINTGUARD_API_TOKENS ("token:scope,token:scope") into a map."""
    tokens: dict[str, str] = {}
    for item in raw.split(","):
        token, _, scope = item.strip().partition(":")
        scope = scope.strip() or "read"
        if token.strip() and scope in SCOPE_ORDER:
            tokens[token.strip()] = scope
    return tokens


async def scope_guard(request: Request) -> None:
    """Rejects requests whose token does not cover the matched route's scope."""
    auth: ApiAuth = request.app.state.api_auth
    granted = auth.resolve(request.headers.get("authorization"))
    if granted is None:
        raise HTTPException(401, "missing or invalid token", {"WWW-Authenticate": "Bearer"})
    required = route_scope(getattr(request.scope.get("route"), "tags", None))
    if required not in granted:
        raise HTTPException(403, f"requires {required} scope")


def get_engine(request: Request) -> Engine:
    return request.app.state.engine


class PrinterFields(BaseModel):
    name: str | None = None
    provider: str | None = None
    config: dict[str, Any] | None = None


class MonitorFields(BaseModel):
    name: str | None = None
    camera_id: str | None = None
    printer_id: str | None = None
    enabled: bool | None = None
    threshold: float | None = None
    sensitivity: float | None = None
    consecutive: int | None = None
    notify: bool | None = None
    on_defect: Literal["none", "pause", "cancel"] | None = None
    cooldown_s: int | None = None


class CameraSource(BaseModel):
    kind: str
    device_id: str | None = None
    path: str | None = None
    url: str | None = None


class CameraCreate(BaseModel):
    name: str | None = None
    source: CameraSource


class CameraPatch(BaseModel):
    name: str | None = None
    brightness: float | None = None
    contrast: float | None = None
    sharpness: float | None = None
    crop: dict[str, float] | None = None


class ProviderTest(BaseModel):
    provider: str
    config: dict[str, Any] = {}


class SettingsPatch(BaseModel):
    notifiers: dict[str, dict[str, Any]] | None = None


class ActionBody(BaseModel):
    action: Literal["pause", "resume", "cancel"]


def _find(items: list[dict[str, Any]], item_id: str, kind: str) -> dict[str, Any]:
    for item in items:
        if item["id"] == item_id:
            return item
    raise HTTPException(404, f"no {kind} {item_id!r}")


def build_api_app(auth: ApiAuth) -> FastAPI:
    """Builds the /api/v1 sub-application; the engine is attached at startup."""
    api = FastAPI(
        title="PrintGuard API",
        version="1",
        summary="Monitor and control 3D printers through PrintGuard.",
        dependencies=[Depends(scope_guard)],
    )
    api.state.api_auth = auth

    @api.exception_handler(RuntimeError)
    async def command_failed(request: Request, exc: RuntimeError) -> JSONResponse:
        """Maps a rejected engine command to a 400 instead of a bare 500."""
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @api.exception_handler(TimeoutError)
    async def command_timeout(request: Request, exc: TimeoutError) -> JSONResponse:
        """Maps an engine command that outran its deadline to a 504."""
        return JSONResponse(status_code=504, content={"detail": "engine command timed out"})

    @api.get("/state", operation_id="get_state", tags=["read"])
    async def get_state(engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Returns the full snapshot: cameras, printers, monitors, settings and stats."""
        return engine.state_event()

    @api.get("/monitors", operation_id="list_monitors", tags=["read"])
    async def list_monitors(engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Lists every monitor with its camera, linked printer and latest alert."""
        return engine.state_event()["monitors"]

    @api.get("/monitors/{monitor_id}", operation_id="get_monitor", tags=["read"])
    async def get_monitor(monitor_id: str, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Returns one monitor's settings, bindings and latest alert."""
        return _find(engine.state_event()["monitors"], monitor_id, "monitor")

    @api.post("/monitors", operation_id="add_monitor", tags=["manage"])
    async def add_monitor(body: MonitorFields, engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Creates a monitor binding a camera and an optional printer."""
        await engine.request({"cmd": "monitor.add", "monitor": body.model_dump(exclude_none=True)})
        return engine.state_event()["monitors"]

    @api.patch("/monitors/{monitor_id}", operation_id="update_monitor", tags=["manage"])
    async def update_monitor(monitor_id: str, body: MonitorFields, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Updates a monitor's bindings, thresholds or defect response."""
        await engine.request({"cmd": "monitor.update", "id": monitor_id, "patch": body.model_dump(exclude_none=True)})
        return _find(engine.state_event()["monitors"], monitor_id, "monitor")

    @api.delete("/monitors/{monitor_id}", operation_id="remove_monitor", tags=["manage"])
    async def remove_monitor(monitor_id: str, engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Removes a monitor and returns the updated monitor list."""
        await engine.request({"cmd": "monitor.remove", "id": monitor_id})
        return engine.state_event()["monitors"]

    @api.get("/printers", operation_id="list_printers", tags=["read"])
    async def list_printers(engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Lists every registered printer with its live status, progress and job."""
        return engine.state_event()["printers"]

    @api.get("/printers/{printer_id}", operation_id="get_printer", tags=["read"])
    async def get_printer(printer_id: str, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Returns one printer's connection and latest service state."""
        return _find(engine.state_event()["printers"], printer_id, "printer")

    @api.post("/printers/{printer_id}/action", operation_id="control_printer", tags=["control"])
    async def control_printer(printer_id: str, body: ActionBody, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Pauses, resumes or cancels the print through the printer's service."""
        _find(engine.state_event()["printers"], printer_id, "printer")
        await engine.request({"cmd": "printer.action", "id": printer_id, "action": body.action})
        return _find(engine.state_event()["printers"], printer_id, "printer")

    @api.post("/printers", operation_id="add_printer", tags=["manage"])
    async def add_printer(body: PrinterFields, engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Registers a printer and returns the updated printer list."""
        await engine.request({"cmd": "printer.add", "printer": body.model_dump(exclude_none=True)})
        return engine.state_event()["printers"]

    @api.patch("/printers/{printer_id}", operation_id="update_printer", tags=["manage"])
    async def update_printer(printer_id: str, body: PrinterFields, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Updates a printer's name or connection details."""
        await engine.request({"cmd": "printer.update", "id": printer_id, "patch": body.model_dump(exclude_none=True)})
        return _find(engine.state_event()["printers"], printer_id, "printer")

    @api.delete("/printers/{printer_id}", operation_id="remove_printer", tags=["manage"])
    async def remove_printer(printer_id: str, engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Removes a printer and returns the updated printer list."""
        await engine.request({"cmd": "printer.remove", "id": printer_id})
        return engine.state_event()["printers"]

    @api.post("/printers/test", operation_id="test_printer", tags=["manage"])
    async def test_printer(body: ProviderTest, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Checks whether a printer service is reachable with the given config."""
        events = await engine.request({"cmd": "printer.test", "provider": body.provider, "config": body.config})
        return next((e for e in events if e.get("event") == "printer_test"), {"ok": False})

    @api.get("/cameras", operation_id="list_cameras", tags=["read"])
    async def list_cameras(engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Lists every camera with its rate, health and latest score."""
        return engine.state_event()["cameras"]

    @api.get("/cameras/{camera_id}", operation_id="get_camera", tags=["read"])
    async def get_camera(camera_id: str, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Returns one camera's settings and live statistics."""
        return _find(engine.state_event()["cameras"], camera_id, "camera")

    @api.get(
        "/cameras/{camera_id}/frame",
        operation_id="get_camera_frame",
        tags=["read"],
        responses={200: {"content": {"image/jpeg": {}}}},
        response_class=Response,
    )
    async def get_camera_frame(camera_id: str, engine: Engine = Depends(get_engine)) -> Response:
        """Returns the freshest frame from a camera as a JPEG image."""
        jpeg = await engine.snapshot(camera_id)
        if jpeg is None:
            raise HTTPException(404, f"no frame available for camera {camera_id!r}")
        return Response(jpeg, media_type="image/jpeg")

    @api.post("/cameras", operation_id="add_camera", tags=["manage"])
    async def add_camera(body: CameraCreate, engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Registers a camera and returns the updated camera list."""
        payload = {"cmd": "camera.add", "source": body.source.model_dump(exclude_none=True)}
        if body.name is not None:
            payload["name"] = body.name
        await engine.request(payload)
        return engine.state_event()["cameras"]

    @api.patch("/cameras/{camera_id}", operation_id="update_camera", tags=["manage"])
    async def update_camera(camera_id: str, body: CameraPatch, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Updates a camera's name or image adjustments."""
        await engine.request({"cmd": "camera.update", "id": camera_id, "patch": body.model_dump(exclude_none=True)})
        return _find(engine.state_event()["cameras"], camera_id, "camera")

    @api.delete("/cameras/{camera_id}", operation_id="remove_camera", tags=["manage"])
    async def remove_camera(camera_id: str, engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Removes a camera and returns the updated camera list."""
        await engine.request({"cmd": "camera.remove", "id": camera_id})
        return engine.state_event()["cameras"]

    @api.post("/cameras/discover", operation_id="discover_cameras", tags=["manage"])
    async def discover_cameras(engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Lists attachable camera sources that are not yet registered."""
        events = await engine.request({"cmd": "discover"})
        return next((e["sources"] for e in events if e.get("event") == "discovered"), [])

    @api.get("/events", operation_id="recent_events", tags=["read"])
    async def recent_events(engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Returns recent alerts, warnings, device changes and errors."""
        return engine.recent_events()

    @api.patch("/settings", operation_id="update_settings", tags=["manage"])
    async def update_settings(body: SettingsPatch, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Updates engine settings such as configured notifiers."""
        await engine.request({"cmd": "settings.update", "patch": body.model_dump(exclude_none=True)})
        return engine.state_event()["settings"]

    @api.post("/notifiers/test", operation_id="test_notifier", tags=["manage"])
    async def test_notifier(body: ProviderTest, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Sends a test notification through a configured notifier."""
        events = await engine.request({"cmd": "notify.test", "provider": body.provider, "config": body.config})
        return next((e for e in events if e.get("event") == "notify_test"), {"ok": False})

    return api
