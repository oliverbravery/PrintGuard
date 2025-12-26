import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Security, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...core.database import get_db
from ...core.db_models import Connection, Component
from ...core.models import ConnectionInfo, ConnectionCreate, ConnectionUpdate
from ..auth_utils import get_current_identity
from ..crypto_utils import EncryptedRoute
from ...providers.registry import get_provider

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/connections", tags=["connections"], route_class=EncryptedRoute)

@router.get("", response_model=List[ConnectionInfo])
async def list_connections(
    provider: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["printer:read"])
):
    """List all connections."""
    stmt = select(Connection)
    if provider:
        stmt = stmt.where(Connection.provider == provider)
    result = await db.execute(stmt)
    connections = result.scalars().all()
    return [
        ConnectionInfo(
            id=c.id,
            name=c.name,
            provider=c.provider,
            config={k: (v if k not in ["token", "api_key", "access_code"] else "********") for k, v in (c.config or {}).items()}
        ) for c in connections
    ]

@router.get("/{id}", response_model=ConnectionInfo)
async def get_connection(
    id: str,
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["printer:read"])
):
    """Get single connection by id."""
    result = await db.execute(select(Connection).where(Connection.id == id))
    connection = result.scalar_one_or_none()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    return ConnectionInfo(
        id=connection.id,
        name=connection.name,
        provider=connection.provider,
        config={k: (v if k not in ["token", "api_key", "access_code"] else "********") for k, v in (connection.config or {}).items()}
    )

@router.post("", response_model=ConnectionInfo)
async def create_connection(
    request: ConnectionCreate,
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["printer:write"])
):
    """Create a new connection."""
    connection = Connection(
        name=request.name,
        provider=request.provider,
        config=request.config
    )
    db.add(connection)
    await db.commit()
    await db.refresh(connection)
    return ConnectionInfo(
        id=connection.id,
        name=connection.name,
        provider=connection.provider,
        config={k: (v if k not in ["token", "api_key", "access_code"] else "********") for k, v in (connection.config or {}).items()}
    )

@router.put("/{id}", response_model=ConnectionInfo)
async def update_connection(
    id: str,
    request: ConnectionUpdate,
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["printer:write"])
):
    """Update connection credentials."""
    result = await db.execute(select(Connection).where(Connection.id == id))
    connection = result.scalar_one_or_none()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    if request.name is not None:
        connection.name = request.name
    if request.config is not None:
        connection.config.update(request.config)
        
    await db.commit()
    await db.refresh(connection)
    return ConnectionInfo(
        id=connection.id,
        name=connection.name,
        provider=connection.provider,
        config={k: (v if k not in ["token", "api_key", "access_code"] else "********") for k, v in (connection.config or {}).items()}
    )

@router.delete("/{id}")
async def delete_connection(
    id: str,
    cascade: bool = False,
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["admin"])
):
    """Delete connection."""
    result = await db.execute(select(Connection).where(Connection.id == id).options(selectinload(Connection.components)))
    connection = result.scalar_one_or_none()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    if connection.components and not cascade:
        component_names = [c.name for c in connection.components]
        raise HTTPException(
            status_code=409, 
            detail={"message": "Connection in use by components", "components": component_names}
        )
    
    await db.delete(connection)
    await db.commit()
    return {"status": "success"}

@router.get("/{id}/health")
async def check_connection_health(
    id: str,
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["printer:read"])
):
    """Test connection health."""
    result = await db.execute(select(Connection).where(Connection.id == id))
    connection = result.scalar_one_or_none()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    prov_cls = get_provider(connection.provider)
    if not prov_cls:
        raise HTTPException(status_code=400, detail="Provider not found")
    
    is_healthy = await prov_cls.validate_connection(connection.config)
    return {"healthy": is_healthy}

@router.get("/{id}/components")
async def list_connection_components(
    id: str,
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["printer:read"])
):
    """List components using this connection."""
    result = await db.execute(select(Component).where(Component.connection_id == id))
    components = result.scalars().all()
    return [{"id": c.id, "name": c.name, "type": c.type} for c in components]

@router.get("/{id}/entities")
async def list_connection_entities(
    id: str,
    type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _: any = Security(get_current_identity, scopes=["printer:read"])
):
    """Fetch available entities from provider."""
    result = await db.execute(select(Connection).where(Connection.id == id))
    connection = result.scalar_one_or_none()
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    prov_cls = get_provider(connection.provider)
    if not prov_cls:
        return []
    
    entities = await prov_cls.list_entities(connection.config)
    if type:
        entities = [e for e in entities if e["type"] == type]
    return entities

