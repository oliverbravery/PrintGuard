"""Versioned REST surface over the engine protocol.

Every route delegates to the same engine command/event protocol the UI speaks,
so the REST API, the MCP tools derived from it and the dashboard can never
drift. Routes are tagged with the scope they require (read, control or manage);
the same tags drive both this API's bearer-scope guard and the MCP tool filter.
"""

from __future__ import annotations

import hmac
import logging
from importlib.metadata import version as package_version
from typing import Annotated, Any, Awaitable, Callable, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import AfterValidator, BaseModel, ConfigDict

from ..engine.engine import Engine
from ..engine.tokens import SCOPE_ORDER, expand_scope, hash_secret
from .events import require_finite
from .prints import PrintUpload, capped, file_response, receive_print

logger = logging.getLogger(__name__)


def route_scope(tags: list[str] | None) -> str:
    """Reads the scope a route requires from its tags, defaulting to read."""
    present = [tag for tag in (tags or []) if tag in SCOPE_ORDER]
    return max(present, key=SCOPE_ORDER.index) if present else "read"


class ApiAuth:
    """Resolves a bearer token to the scopes it grants.

    Tokens are issued and revoked from the UI and live in engine state, so the
    current set is supplied per request rather than captured here. With none
    issued the surface trusts whatever fronts it (a reverse proxy or the local
    network) and grants read access anonymously; control and management stay
    closed until the operator issues a token. Once any token exists a valid
    bearer is required for every request. The internal token authenticates the
    in-process MCP loopback and always grants full scope without affecting
    whether operator authentication is required.
    """

    def __init__(self, internal_token: str | None = None) -> None:
        self._internal = internal_token

    def resolve(self, header: str | None, tokens: dict[str, str]) -> set[str] | None:
        """Returns the granted scopes, or None when a required token is missing."""
        token = ""
        if header and header.lower().startswith("bearer "):
            token = header[7:].strip()
        if self._internal and token and hmac.compare_digest(self._internal.encode(), token.encode()):
            return expand_scope("manage")
        if token:
            digest = hash_secret(token)
            for known, scope in tokens.items():
                if hmac.compare_digest(known, digest):
                    return expand_scope(scope)
        if not tokens:
            return expand_scope("read")
        return None


class ScopedRoute(APIRoute):
    """A route that checks the caller's token before anything of the request is read.

    A dependency runs after FastAPI has read and parsed the body, so a caller
    with no token could have the hub take in a body of any size first.
    """

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        """Wraps the route's handler in the scope check."""
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            """Rejects a request whose token does not cover this route's scope.

            Raises:
                HTTPException: 401 for a missing or invalid token, 403 for one
                    whose scope is too narrow.
            """
            auth: ApiAuth = request.app.state.api_auth
            granted = auth.resolve(request.headers.get("authorization"), request.app.state.engine.token_scopes())
            if granted is None:
                logger.warning("rejected API request with missing or invalid token: %s %s", request.method, request.url.path)
                raise HTTPException(401, "missing or invalid token", {"WWW-Authenticate": "Bearer"})
            required = route_scope(self.tags)
            if required not in granted:
                logger.warning("rejected API request lacking %s scope: %s %s", required, request.method, request.url.path)
                raise HTTPException(403, f"requires {required} scope")
            return await handler(request)

        return guarded


def get_engine(request: Request) -> Engine:
    return request.app.state.engine


FiniteObject = Annotated[dict[str, Any], AfterValidator(require_finite)]


class PrinterFields(BaseModel):
    name: str | None = None
    provider: str | None = None
    config: FiniteObject | None = None


class _FiniteNumbers(BaseModel):
    """Base for the request bodies that carry a number, refusing NaN, Infinity and text or a boolean in place of one."""

    model_config = ConfigDict(allow_inf_nan=False, strict=True)


class MonitorFields(_FiniteNumbers):
    name: str | None = None
    camera_id: str | None = None
    printer_id: str | None = None
    enabled: bool | None = None
    threshold: float | None = None
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


class CameraPatch(_FiniteNumbers):
    name: str | None = None
    brightness: float | None = None
    contrast: float | None = None
    sharpness: float | None = None
    crop: dict[str, float] | None = None
    rotation: int | None = None
    detect_fps: float | None = None


class ProviderTest(BaseModel):
    provider: str
    config: FiniteObject = {}


class SettingsPatch(BaseModel):
    notifiers: dict[str, FiniteObject] | None = None
    mqtt: FiniteObject | None = None
    inference_runtime: Literal["auto", "litert", "onnx"] | None = None
    preheat: list[FiniteObject] | None = None


class ActionBody(BaseModel):
    action: Literal["pause", "resume", "cancel"]


class HeatBody(_FiniteNumbers):
    nozzle: float | None = None
    bed: float | None = None


class PrintFields(BaseModel):
    name: str | None = None
    printer_ids: list[str] | None = None


class StartBody(BaseModel):
    printer_id: str


UPLOAD_TIMEOUT_S = 600.0
UPLOAD_BODY = {
    "requestBody": {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
}
MAX_FRAME_BYTES = 32 * 1024 * 1024
FRAME_BODY = {
    "requestBody": {
        "required": True,
        "content": {"image/jpeg": {"schema": {"type": "string", "format": "binary"}}},
    }
}


class _ReadModel(BaseModel):
    """Base for the read-surface response models, documenting each field for
    `/api/v1/openapi.json` yet passes any unlisted field straight through and tolerates
    absent ones, so a response still mirrors the resource's `.public()` exactly."""

    model_config = ConfigDict(extra="allow")


class LastResult(_ReadModel):
    prediction: Literal["success", "failure", "unknown"] | None = None
    distances: dict[str, float] | None = None
    margin: float | None = None


class CameraOut(_ReadModel):
    id: str
    name: str | None = None
    source: dict[str, Any] | None = None
    printer_id: str | None = None
    max_fps: float | None = None
    detect_fps: float | None = None
    target_fps: float | None = None
    achieved_fps: float | None = None
    inferring: bool | None = None
    in_use: bool | None = None
    online: bool | None = None
    standby: bool | None = None
    reason: str | None = None
    last_result: LastResult | None = None
    brightness: float | None = None
    contrast: float | None = None
    sharpness: float | None = None
    crop: dict[str, float] | None = None
    rotation: int | None = None


class MonitorAlert(_ReadModel):
    score: float | None = None
    action: str | None = None
    ts: float | None = None


class MonitorResult(_ReadModel):
    score: float | None = None
    ts: float | None = None


class MonitorOut(_ReadModel):
    id: str
    name: str | None = None
    camera_id: str | None = None
    printer_id: str | None = None
    enabled: bool | None = None
    threshold: float | None = None
    consecutive: int | None = None
    notify: bool | None = None
    on_defect: Literal["none", "pause", "cancel"] | None = None
    cooldown_s: int | None = None
    watching: bool | None = None
    result: MonitorResult | None = None
    alert: MonitorAlert | None = None


def _find(items: list[dict[str, Any]], item_id: str, kind: str) -> dict[str, Any]:
    for item in items:
        if item["id"] == item_id:
            return item
    raise HTTPException(404, f"no {kind} {item_id!r}")


def public_state(engine: Engine) -> dict[str, Any]:
    """The engine snapshot without what only the dashboard is given.

    The snapshot already carries no stored secret. A plugin's store is left
    out whatever the token's scope, since a plugin may keep a session or
    anything else it was told in it, and nothing on this surface writes one.
    The API tokens are left out as well, since only the dashboard issues and
    revokes them and a read token has no call to list the others.
    """
    state = engine.state_event()
    del state["tokens"]
    state["plugins"] = [{key: value for key, value in plugin.items() if key != "config"} for plugin in state["plugins"]]
    return state


def build_api_app(auth: ApiAuth) -> FastAPI:
    """Builds the /api/v1 sub-application, with the engine attached at startup."""
    api = FastAPI(
        title="PrintGuard API",
        version=package_version("printguard"),
        docs_url=None,
        redoc_url=None,
        summary="Monitor and control 3D printers through PrintGuard.",
    )
    api.router.route_class = ScopedRoute
    api.state.api_auth = auth

    @api.exception_handler(RuntimeError)
    async def command_failed(request: Request, exc: RuntimeError) -> JSONResponse:
        """Maps a rejected engine command to a 400 instead of a bare 500."""
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @api.exception_handler(RequestValidationError)
    async def body_refused(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Answers 422 without echoing the input, since a NaN in it cannot be written as JSON."""
        errors = [{key: value for key, value in error.items() if key != "input"} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})

    @api.exception_handler(TimeoutError)
    async def command_timeout(request: Request, exc: TimeoutError) -> JSONResponse:
        """Maps an engine command that outran its deadline to a 504."""
        return JSONResponse(status_code=504, content={"detail": "engine command timed out"})

    @api.get("/state", operation_id="get_state", tags=["read"])
    async def get_state(engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Returns the full snapshot of cameras, printers, monitors, settings and stats."""
        return public_state(engine)

    @api.get("/monitors", operation_id="list_monitors", tags=["read"], response_model=list[MonitorOut])
    async def list_monitors(engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Lists every monitor with its camera, linked printer and latest alert."""
        return public_state(engine)["monitors"]

    @api.get("/monitors/{monitor_id}", operation_id="get_monitor", tags=["read"], response_model=MonitorOut)
    async def get_monitor(monitor_id: str, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Returns one monitor's settings, bindings and latest alert."""
        return _find(public_state(engine)["monitors"], monitor_id, "monitor")

    @api.post("/monitors", operation_id="add_monitor", tags=["manage"], response_model=list[MonitorOut])
    async def add_monitor(body: MonitorFields, engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Creates a monitor binding a camera and an optional printer."""
        await engine.request({"cmd": "monitor.add", "monitor": body.model_dump(exclude_none=True)})
        return public_state(engine)["monitors"]

    @api.patch("/monitors/{monitor_id}", operation_id="update_monitor", tags=["manage"], response_model=MonitorOut)
    async def update_monitor(monitor_id: str, body: MonitorFields, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Updates a monitor's bindings, thresholds or defect response."""
        await engine.request({"cmd": "monitor.update", "id": monitor_id, "patch": body.model_dump(exclude_none=True)})
        return _find(public_state(engine)["monitors"], monitor_id, "monitor")

    @api.delete("/monitors/{monitor_id}", operation_id="remove_monitor", tags=["manage"], response_model=list[MonitorOut])
    async def remove_monitor(monitor_id: str, engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Removes a monitor and returns the updated monitor list."""
        await engine.request({"cmd": "monitor.remove", "id": monitor_id})
        return public_state(engine)["monitors"]

    @api.get("/monitors/{monitor_id}/history", operation_id="get_monitor_history", tags=["read"])
    async def get_monitor_history(monitor_id: str, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Returns a monitor's rolled-up risk buckets, snapshot index and summary stats."""
        _find(public_state(engine)["monitors"], monitor_id, "monitor")
        events = await engine.request({"cmd": "history.get", "monitor_id": monitor_id})
        history = next((e for e in events if e.get("event") == "history"), {})
        return {key: value for key, value in history.items() if key not in ("event", "req_id")}

    @api.get(
        "/monitors/{monitor_id}/snapshots/{snap_id}",
        operation_id="get_monitor_snapshot",
        tags=["read"],
        responses={200: {"content": {"image/jpeg": {}}}},
        response_class=Response,
    )
    async def get_monitor_snapshot(monitor_id: str, snap_id: str, engine: Engine = Depends(get_engine)) -> Response:
        """Returns a captured risky-moment snapshot as a JPEG image."""
        jpeg = await engine.monitor_snapshot(monitor_id, snap_id)
        if jpeg is None:
            raise HTTPException(404, f"no snapshot {snap_id!r} for monitor {monitor_id!r}")
        return Response(jpeg, media_type="image/jpeg")

    @api.get("/printers", operation_id="list_printers", tags=["read"])
    async def list_printers(engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Lists every registered printer with its live status, progress and job."""
        return public_state(engine)["printers"]

    @api.get("/printers/{printer_id}", operation_id="get_printer", tags=["read"])
    async def get_printer(printer_id: str, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Returns one printer's connection and latest service state."""
        return _find(public_state(engine)["printers"], printer_id, "printer")

    @api.post("/printers/{printer_id}/action", operation_id="control_printer", tags=["control"])
    async def control_printer(printer_id: str, body: ActionBody, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Pauses, resumes or cancels the print through the printer's service."""
        _find(public_state(engine)["printers"], printer_id, "printer")
        await engine.request({"cmd": "printer.action", "id": printer_id, "action": body.action})
        return _find(public_state(engine)["printers"], printer_id, "printer")

    @api.post("/printers/{printer_id}/heat", operation_id="heat_printer", tags=["control"])
    async def heat_printer(printer_id: str, body: HeatBody, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Sets the nozzle and bed targets in degrees Celsius through the printer's service, 0 turning a heater off."""
        _find(public_state(engine)["printers"], printer_id, "printer")
        await engine.request({"cmd": "printer.heat", "id": printer_id, **body.model_dump(exclude_none=True)})
        return _find(public_state(engine)["printers"], printer_id, "printer")

    @api.post("/printers", operation_id="add_printer", tags=["manage"])
    async def add_printer(body: PrinterFields, engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Registers a printer and returns the updated printer list."""
        await engine.request({"cmd": "printer.add", "printer": body.model_dump(exclude_none=True)})
        return public_state(engine)["printers"]

    @api.patch("/printers/{printer_id}", operation_id="update_printer", tags=["manage"])
    async def update_printer(printer_id: str, body: PrinterFields, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Updates a printer's name or connection details.

        A secret config field left out or blank keeps its stored value, and null clears it.
        """
        await engine.request({"cmd": "printer.update", "id": printer_id, "patch": body.model_dump(exclude_none=True)})
        return _find(public_state(engine)["printers"], printer_id, "printer")

    @api.delete("/printers/{printer_id}", operation_id="remove_printer", tags=["manage"])
    async def remove_printer(printer_id: str, engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Removes a printer and returns the updated printer list."""
        await engine.request({"cmd": "printer.remove", "id": printer_id})
        return public_state(engine)["printers"]

    @api.post("/printers/test", operation_id="test_printer", tags=["manage"])
    async def test_printer(body: ProviderTest, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Checks whether a printer service is reachable with the given config."""
        events = await engine.request({"cmd": "printer.test", "provider": body.provider, "config": body.config})
        return next((e for e in events if e.get("event") == "printer_test"), {"ok": False})

    @api.get("/prints", operation_id="list_prints", tags=["read"])
    async def list_prints(engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Lists every sliced file in the print library with the printers it is tagged for."""
        return public_state(engine)["prints"]

    @api.get("/prints/{print_id}", operation_id="get_print", tags=["read"])
    async def get_print(print_id: str, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Returns one print file's record: name, format, size, tags and what the slicer wrote into it."""
        return _find(public_state(engine)["prints"], print_id, "print")

    @api.get(
        "/prints/{print_id}/file",
        operation_id="get_print_file",
        tags=["read"],
        responses={200: {"content": {"application/octet-stream": {}}}},
        response_class=Response,
    )
    async def get_print_file(print_id: str, engine: Engine = Depends(get_engine)) -> Response:
        """Downloads a print file as the library keeps it."""
        return file_response(engine, print_id)

    @api.post("/prints", operation_id="add_print", tags=["manage"], openapi_extra=UPLOAD_BODY)
    async def add_print(
        request: Request,
        upload: Annotated[PrintUpload, Query()],
        engine: Engine = Depends(get_engine),
    ) -> dict[str, Any]:
        """Uploads a sliced file, sent as the raw body, into the print library.

        ``nozzle`` and ``bed`` rewrite the file so its first layer heats to them,
        moving its other print temperatures by the same amount.
        """
        record = await receive_print(engine, upload, request.stream())
        return record.public()

    @api.patch("/prints/{print_id}", operation_id="update_print", tags=["manage"])
    async def update_print(print_id: str, body: PrintFields, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Renames a print file or changes the printers it is tagged for."""
        await engine.request({"cmd": "print.update", "id": print_id, "patch": body.model_dump(exclude_none=True)})
        return _find(public_state(engine)["prints"], print_id, "print")

    @api.delete("/prints/{print_id}", operation_id="remove_print", tags=["manage"])
    async def remove_print(print_id: str, engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Removes a print file and returns the updated library."""
        await engine.request({"cmd": "print.remove", "id": print_id})
        return public_state(engine)["prints"]

    @api.post("/prints/{print_id}/start", operation_id="start_print", tags=["control"])
    async def start_print(print_id: str, body: StartBody, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Sends a print file to an idle printer it is tagged for and starts it."""
        await engine.request({"cmd": "print.start", "id": print_id, "printer_id": body.printer_id}, timeout=UPLOAD_TIMEOUT_S)
        return _find(public_state(engine)["printers"], body.printer_id, "printer")

    @api.get("/cameras", operation_id="list_cameras", tags=["read"], response_model=list[CameraOut])
    async def list_cameras(engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Lists every camera with its rate, health and latest score."""
        return public_state(engine)["cameras"]

    @api.get("/cameras/{camera_id}", operation_id="get_camera", tags=["read"], response_model=CameraOut)
    async def get_camera(camera_id: str, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Returns one camera's settings and live statistics."""
        return _find(public_state(engine)["cameras"], camera_id, "camera")

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

    @api.post("/classify", operation_id="classify_frame", tags=["read"], openapi_extra=FRAME_BODY)
    async def classify_frame(request: Request, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Classifies a supplied JPEG frame - the model's verdict without a registered camera."""
        return await engine.classify(b"".join([chunk async for chunk in capped(request.stream(), MAX_FRAME_BYTES)]))

    @api.post("/cameras", operation_id="add_camera", tags=["manage"], response_model=list[CameraOut])
    async def add_camera(body: CameraCreate, engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Registers a camera and returns the updated camera list."""
        payload = {"cmd": "camera.add", "source": body.source.model_dump(exclude_none=True)}
        if body.name is not None:
            payload["name"] = body.name
        await engine.request(payload)
        return public_state(engine)["cameras"]

    @api.patch("/cameras/{camera_id}", operation_id="update_camera", tags=["manage"], response_model=CameraOut)
    async def update_camera(camera_id: str, body: CameraPatch, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Updates a camera's name or image adjustments."""
        await engine.request({"cmd": "camera.update", "id": camera_id, "patch": body.model_dump(exclude_none=True)})
        return _find(public_state(engine)["cameras"], camera_id, "camera")

    @api.delete("/cameras/{camera_id}", operation_id="remove_camera", tags=["manage"], response_model=list[CameraOut])
    async def remove_camera(camera_id: str, engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Removes a camera and returns the updated camera list."""
        await engine.request({"cmd": "camera.remove", "id": camera_id})
        return public_state(engine)["cameras"]

    @api.post("/cameras/discover", operation_id="discover_cameras", tags=["manage"])
    async def discover_cameras(engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Lists attachable camera sources that are not yet registered."""
        events = await engine.request({"cmd": "discover"})
        return next((e["sources"] for e in events if e.get("event") == "discovered"), [])

    @api.post("/cameras/refresh-printers", operation_id="refresh_printer_cameras", tags=["manage"])
    async def refresh_printer_cameras(engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Re-checks every registered printer and registers any newly exposed cameras."""
        await engine.request({"cmd": "printer.cameras.refresh"})
        return public_state(engine)["cameras"]

    @api.get("/events", operation_id="recent_events", tags=["read"])
    async def recent_events(engine: Engine = Depends(get_engine)) -> list[dict[str, Any]]:
        """Returns recent alerts, warnings and errors."""
        return engine.recent_events()

    @api.patch("/settings", operation_id="update_settings", tags=["manage"])
    async def update_settings(body: SettingsPatch, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Updates engine settings such as configured notifiers.

        A notifier secret or the MQTT password left out or blank keeps its stored value, and null clears it.
        """
        await engine.request({"cmd": "settings.update", "patch": body.model_dump(exclude_none=True)})
        return public_state(engine)["settings"]

    @api.post("/notifiers/test", operation_id="test_notifier", tags=["manage"])
    async def test_notifier(body: ProviderTest, engine: Engine = Depends(get_engine)) -> dict[str, Any]:
        """Sends a test notification through a configured notifier."""
        events = await engine.request({"cmd": "notify.test", "provider": body.provider, "config": body.config})
        return next((e for e in events if e.get("event") == "notify_test"), {"ok": False})

    return api
