"""Printer control endpoints."""

import logging
from typing import Any, Optional, Union
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Security, Depends
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ...core.models import (
    PrinterConfig, PrinterInfo, PrinterStatus, FeedSettings,
    ComponentConfig, ComponentInfo
)
from ...core.database import get_db, AsyncSession
from ...core.db_models import Printer, Component, PrinterComponentLink
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


async def _resolve_component(comp_config: Union[ComponentConfig, Component], db: AsyncSession) -> Any:
    """Instantiate a provider component from config or DB model."""
    if isinstance(comp_config, Component):
        provider = comp_config.provider
        config = comp_config.config
    else:
        provider = comp_config.provider
        config = comp_config.config

    prov_cls = get_provider(provider)
    if not prov_cls:
        return None
    return prov_cls(**config)


async def _get_or_create_printer_instance(printer_id: str, db: AsyncSession) -> Optional[PrinterInstance]:
    """Get printer instance from cache or initialize from DB."""
    if printer_id in _printers:
        return _printers[printer_id]
    result = await db.execute(
        select(Printer).where(Printer.id == printer_id).options(
            selectinload(Printer.component_links).joinedload(PrinterComponentLink.component)
        )
    )
    db_printer = result.scalar_one_or_none()
    if not db_printer:
        return None
    comp_map = {link.role: link.component for link in db_printer.component_links}
    config = PrinterConfig(
        id=db_printer.id,
        name=db_printer.name,
        components={role: ComponentConfig(id=c.id, provider=c.provider, config=c.config) for role, c in comp_map.items()},
        client_public_key=db_printer.client_public_key
    )
    instance = PrinterInstance(config=config)
    for role, db_comp in comp_map.items():
        setattr(instance, role, await _resolve_component(db_comp, db))
    _printers[printer_id] = instance
    return instance


@router.get("/providers")
async def list_providers(_: any = Security(get_current_identity, scopes=["printer:read"])) -> list[str]:
    """List available printer providers."""
    return get_available_providers()


@router.post("/", response_model=PrinterInfo)
async def register_printer(
    config: PrinterConfig, 
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["printer:write"])
) -> PrinterInfo:
    """Register a new modular printer."""
    db_printer = Printer(
        name=config.name,
        client_public_key=config.client_public_key
    )
    if config.id:
        db_printer.id = config.id
    db.add(db_printer)
    await db.flush()
    roles = ["status", "camera", "control"]
    for role in roles:
        comp_data = getattr(config.components, role)
        if not comp_data:
            continue
        db_comp = None
        if isinstance(comp_data, str):
            res = await db.execute(select(Component).where(Component.id == comp_data))
            db_comp = res.scalar_one_or_none()
            if not db_comp:
                raise HTTPException(status_code=400, detail=f"Component {comp_data} not found")
        elif isinstance(comp_data, ComponentConfig):
            if comp_data.id:
                res = await db.execute(select(Component).where(Component.id == comp_data.id))
                db_comp = res.scalar_one_or_none()
                if not db_comp:
                    raise HTTPException(status_code=400, detail=f"Component {comp_data.id} not found")
            else:
                db_comp = Component(
                    name=comp_data.name,
                    provider=comp_data.provider,
                    config=comp_data.config
                )
                db.add(db_comp)
                await db.flush()
        if db_comp:
            link = PrinterComponentLink(
                printer_id=db_printer.id,
                component_id=db_comp.id,
                role=role
            )
            db.add(link)
    await db.commit()
    return await get_printer(db_printer.id, db, _)


@router.get("/", response_model=list[PrinterInfo])
async def list_printers(
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["printer:read"])
) -> list[PrinterInfo]:
    """List all registered printers."""
    result = await db.execute(select(Printer.id))
    printer_ids = result.scalars().all()
    return [await get_printer(pid, db, _) for pid in printer_ids]


@router.get("/{printer_id}", response_model=PrinterInfo)
async def get_printer(
    printer_id: str, 
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["printer:read"])
) -> PrinterInfo:
    """Get printer status."""
    instance = await _get_or_create_printer_instance(printer_id, db)
    if not instance:
        raise HTTPException(status_code=404, detail="Printer not found")
    status = PrinterStatus.DISCONNECTED
    if instance.status:
        try:
            is_printing = await instance.status.is_printing()
            status = PrinterStatus.PRINTING if is_printing else PrinterStatus.IDLE
        except Exception:
            status = PrinterStatus.ERROR
    result = await db.execute(
        select(PrinterComponentLink).where(PrinterComponentLink.printer_id == printer_id).options(
            selectinload(PrinterComponentLink.component)
        )
    )
    links = result.scalars().all()
    components_info = {
        link.role: ComponentInfo(
            id=link.component.id,
            name=link.component.name,
            provider=link.component.provider,
            config=link.component.config
        ) for link in links
    }
    return PrinterInfo(
        id=printer_id,
        name=instance.config.name,
        status=status,
        linked_session_id=instance.config.linked_session_id,
        has_control=instance.control is not None,
        has_camera=instance.camera is not None,
        components=components_info
    )


@router.post("/{printer_id}/stream", response_model=dict)
async def link_printer_stream(
    printer_id: str, 
    session_id: str, 
    settings: FeedSettings = FeedSettings(), 
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["printer:write", "rtc:stream"])
) -> dict:
    """Ensure printer camera is multiplexed and active."""
    instance = await _get_or_create_printer_instance(printer_id, db)
    if not instance:
        raise HTTPException(status_code=404, detail="Printer not found")
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
async def remove_printer(
    printer_id: str, 
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["admin"])
) -> dict:
    """Remove a printer."""
    result = await db.execute(select(Printer).where(Printer.id == printer_id))
    db_printer = result.scalar_one_or_none()
    if not db_printer:
        raise HTTPException(status_code=404, detail="Printer not found")
    await db.delete(db_printer)
    await db.commit()
    if printer_id in _printers:
        _printers.pop(printer_id)
    return {"status": "removed", "id": printer_id}


@router.post("/{printer_id}/{command}")
async def printer_command(
    printer_id: str, 
    command: str, 
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["printer:write"])
) -> dict:
    """Send command to printer."""
    instance = await _get_or_create_printer_instance(printer_id, db)
    if not instance:
        raise HTTPException(status_code=404, detail="Printer not found")
    if not instance.control:
        raise HTTPException(status_code=400, detail="Printer does not support control")
    if command == "start": await instance.control.start()
    elif command == "pause": await instance.control.pause()
    elif command == "resume": await instance.control.resume()
    elif command == "stop": await instance.control.stop()
    else: raise HTTPException(status_code=400, detail="Invalid command")
    return {"status": "ok", "command": command}
