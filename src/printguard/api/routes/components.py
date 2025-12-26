import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Security, status, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...core.database import get_db
from ...core.db_models import Component, Connection, PrinterComponentLink
from ...core.models import ComponentCreate, ComponentUpdate, ComponentInfo, FeedSettings
from ...core.model import get_model
from ...core.inference import predict
from ...providers import get_provider
from ...services.webrtc import start_track_processing
from ...services.streams import stream_manager
from ..auth_utils import get_current_identity
from ..crypto_utils import EncryptedRoute

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/components", tags=["components"], route_class=EncryptedRoute)

@router.get("", response_model=List[ComponentInfo])
async def list_components(
    type: Optional[str] = None,
    provider: Optional[str] = None,
    connection_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["printer:read"])
):
    """List all components."""
    stmt = select(Component).options(selectinload(Component.connection))
    if type:
        stmt = stmt.where(Component.type == type)
    if provider:
        stmt = stmt.where(Component.provider == provider)
    if connection_id:
        stmt = stmt.where(Component.connection_id == connection_id)
    
    result = await db.execute(stmt)
    components = result.scalars().all()
    return [
        ComponentInfo(
            id=c.id,
            name=c.name,
            type=c.type,
            provider=c.provider,
            entity_config=c.entity_config or {}
        ) for c in components
    ]

@router.get("/{id}", response_model=ComponentInfo)
async def get_component(
    id: str,
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["printer:read"])
):
    """Get single component by id."""
    result = await db.execute(select(Component).where(Component.id == id))
    component = result.scalar_one_or_none()
    if not component:
        raise HTTPException(status_code=404, detail="Component not found")
    return ComponentInfo(
        id=component.id,
        name=component.name,
        type=component.type,
        provider=component.provider,
        entity_config=component.entity_config or {}
    )

@router.post("", response_model=ComponentInfo)
async def create_component(
    request: ComponentCreate,
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["printer:write"])
):
    """Create a new component."""
    component = Component(
        name=request.name,
        type=request.type,
        provider=request.provider,
        connection_id=request.connection_id,
        entity_config=request.entity_config
    )
    db.add(component)
    await db.commit()
    await db.refresh(component)
    return ComponentInfo(
        id=component.id,
        name=component.name,
        type=component.type,
        provider=component.provider,
        entity_config=component.entity_config or {}
    )

@router.put("/{id}", response_model=ComponentInfo)
async def update_component(
    id: str,
    request: ComponentUpdate,
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["printer:write"])
):
    """Update component config."""
    result = await db.execute(select(Component).where(Component.id == id))
    component = result.scalar_one_or_none()
    if not component:
        raise HTTPException(status_code=404, detail="Component not found")
    
    if request.name is not None:
        component.name = request.name
    if request.entity_config is not None:
        component.entity_config.update(request.entity_config)
        
    await db.commit()
    await db.refresh(component)
    return ComponentInfo(
        id=component.id,
        name=component.name,
        type=component.type,
        provider=component.provider,
        entity_config=component.entity_config or {}
    )

@router.delete("/{id}")
async def delete_component(
    id: str,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["printer:write"])
):
    """Delete component."""
    result = await db.execute(
        select(Component)
        .where(Component.id == id)
        .options(selectinload(Component.printer_links))
    )
    component = result.scalar_one_or_none()
    if not component:
        raise HTTPException(status_code=404, detail="Component not found")
    
    if component.printer_links and not force:
        printer_ids = [link.printer_id for link in component.printer_links]
        raise HTTPException(
            status_code=409, 
            detail={"message": "Component in use by printers", "printers": printer_ids}
        )
    
    await db.delete(component)
    await db.commit()
    return {"status": "success"}

@router.get("/{id}/health")
async def check_component_health(
    id: str,
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["printer:read"])
):
    """Test component connection health."""
    result = await db.execute(select(Component).where(Component.id == id).options(selectinload(Component.connection)))
    component = result.scalar_one_or_none()
    if not component:
        raise HTTPException(status_code=404, detail="Component not found")
    
    prov_cls = get_provider(component.provider)
    if not prov_cls:
        raise HTTPException(status_code=400, detail="Provider not found")
    
    config = {}
    if component.connection:
        config.update(component.connection.config)
    config.update(component.entity_config or {})
    
    is_healthy = await prov_cls.validate_component(config)
    return {"healthy": is_healthy}

@router.get("/{id}/printers")
async def list_component_printers(
    id: str,
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["printer:read"])
):
    """List printers using this component."""
    result = await db.execute(select(PrinterComponentLink).where(PrinterComponentLink.component_id == id))
    links = result.scalars().all()
    return [{"printer_id": link.printer_id, "role": link.role} for link in links]

@router.post("/{id}/stream", response_model=dict)
async def link_component_stream(
    id: str, 
    session_id: str = Query(...), 
    settings: FeedSettings = FeedSettings(), 
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["printer:write", "rtc:stream"])
) -> dict:
    """Ensure component camera is multiplexed and active for preview."""
    result = await db.execute(select(Component).where(Component.id == id).options(selectinload(Component.connection)))
    db_comp = result.scalar_one_or_none()
    if not db_comp:
        raise HTTPException(status_code=404, detail="Component not found")
    
    if db_comp.type != "camera":
        raise HTTPException(status_code=400, detail="Only camera components can be streamed")

    if stream_manager.get_source(id):
        stream_manager.add_alias(id, session_id)
        return {"status": "success", "session_id": session_id, "multiplexed": True}

    prov_cls = get_provider(db_comp.provider)
    if not prov_cls:
        raise HTTPException(status_code=400, detail=f"Provider {db_comp.provider} not found")
    
    config = {}
    if db_comp.connection:
        config.update(db_comp.connection.config)
    config.update(db_comp.entity_config)
    
    instance = prov_cls(**config)
    track, pc = await instance.get_camera_track()
    
    if not track:
        raise HTTPException(status_code=404, detail="Camera track not available")
        
    model_info = get_model()
    processor = await start_track_processing(track, predict, model_info, settings, session_id)
    
    if processor.relayed_track:
        stream_manager.register_source(
            id, 
            processor.relayed_track, 
            processor,
            pc=pc,
            device_name=f"{db_comp.name} Preview",
            settings=settings
        )
        stream_manager.add_alias(id, session_id)
        
    return {"status": "success", "session_id": session_id}

