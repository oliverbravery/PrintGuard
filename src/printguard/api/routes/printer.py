"""Printer control endpoints."""

import logging
from typing import Any, Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Security

from ...core.models import (
    PrinterConfig, PrinterInfo, PrinterStatus, FeedSettings,
    ComponentConfig
)
from ...core.model import get_model
from ...core.inference import predict
from ...providers import list_providers as get_available_providers, get_provider
from ...providers.base import StatusSource, CameraSource, ControlSink
from ...services.webrtc import start_track_processing
from ...services.streams import stream_manager
from ..crypto_utils import EncryptedRoute
from ..auth_utils import get_current_identity

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/printer", tags=["printer"], route_class=EncryptedRoute)


class PrinterInstance(BaseModel):
    """Internal runtime state of a printer."""
    config: PrinterConfig
    status: Optional[StatusSource] = None
    camera: Optional[CameraSource] = None
    control: Optional[ControlSink] = None

    model_config = {"arbitrary_types_allowed": True}


_printers: dict[str, PrinterInstance] = {}


def _resolve_component(comp_config: ComponentConfig) -> Any:
    """Instantiate a provider component from config."""
    prov_cls = get_provider(comp_config.provider)
    if not prov_cls:
        return None
    return prov_cls(**comp_config.config)


@router.get("/providers")
async def list_providers(_: any = Security(get_current_identity, scopes=["printer:read"])) -> list[str]:
    """List available printer providers."""
    return get_available_providers()


@router.post("/", response_model=PrinterInfo)
async def register_printer(config: PrinterConfig, _: any = Security(get_current_identity, scopes=["printer:write"])) -> PrinterInfo:
    """Register a new modular printer."""
    if config.id in _printers:
        raise HTTPException(status_code=409, detail="Printer ID already exists")
    instance = PrinterInstance(config=config)
    for role in ["status", "camera", "control"]:
        if role_cfg := getattr(config.components, role):
            setattr(instance, role, _resolve_component(role_cfg))
    _printers[config.id] = instance
    return await get_printer(config.id, _)


@router.get("/", response_model=list[PrinterInfo])
async def list_printers(_: any = Security(get_current_identity, scopes=["printer:read"])) -> list[PrinterInfo]:
    """List all registered printers."""
    return [await get_printer(pid, _) for pid in _printers]


@router.get("/{printer_id}", response_model=PrinterInfo)
async def get_printer(printer_id: str, _: any = Security(get_current_identity, scopes=["printer:read"])) -> PrinterInfo:
    """Get printer status."""
    if printer_id not in _printers:
        raise HTTPException(status_code=404, detail="Printer not found")
    instance = _printers[printer_id]
    status = PrinterStatus.DISCONNECTED
    if instance.status:
        try:
            is_printing = await instance.status.is_printing()
            status = PrinterStatus.PRINTING if is_printing else PrinterStatus.IDLE
        except Exception:
            status = PrinterStatus.ERROR
    return PrinterInfo(
        id=printer_id,
        name=instance.config.name,
        status=status,
        linked_session_id=instance.config.linked_session_id,
        has_control=instance.control is not None,
        has_camera=instance.camera is not None
    )


@router.post("/{printer_id}/stream", response_model=dict)
async def link_printer_stream(printer_id: str, session_id: str, settings: FeedSettings = FeedSettings(), _: any = Security(get_current_identity, scopes=["printer:write", "rtc:stream"])) -> dict:
    """Ensure printer camera is multiplexed and active."""
    if printer_id not in _printers:
        raise HTTPException(status_code=404, detail="Printer not found")
    instance = _printers[printer_id]
    if not instance.camera:
        raise HTTPException(status_code=400, detail="Printer has no camera source")
    if stream_manager.get_source(printer_id):
        stream_manager.add_alias(printer_id, session_id)
        return {"status": "success", "session_id": session_id, "multiplexed": True}
    track, pc = await instance.camera.get_camera_track()
    if not track:
        raise HTTPException(status_code=404, detail="Camera track not available")
    model_info = get_model()
    processor = await start_track_processing(track, predict, model_info, settings, session_id)
    if processor.relayed_track:
        stream_manager.register_source(
            printer_id, 
            processor.relayed_track, 
            processor,
            pc=pc,
            device_name=f"{instance.config.name} Camera",
            settings=settings
        )
        stream_manager.add_alias(printer_id, session_id)
    instance.config.linked_session_id = session_id
    return {"status": "success", "session_id": session_id}


@router.delete("/{printer_id}")
async def remove_printer(printer_id: str, _: any = Security(get_current_identity, scopes=["admin"])) -> dict:
    """Remove a printer."""
    if printer_id not in _printers:
        raise HTTPException(status_code=404, detail="Printer not found")
    _printers.pop(printer_id)
    return {"status": "removed", "id": printer_id}


@router.post("/{printer_id}/{command}")
async def printer_command(printer_id: str, command: str, _: any = Security(get_current_identity, scopes=["printer:write"])) -> dict:
    """Send command to printer."""
    if printer_id not in _printers:
        raise HTTPException(status_code=404, detail="Printer not found")
    instance = _printers[printer_id]
    if not instance.control:
        raise HTTPException(status_code=400, detail="Printer does not support control")
    if command == "start": await instance.control.start()
    elif command == "pause": await instance.control.pause()
    elif command == "resume": await instance.control.resume()
    elif command == "stop": await instance.control.stop()
    else: raise HTTPException(status_code=400, detail="Invalid command")
    return {"status": "ok", "command": command}
