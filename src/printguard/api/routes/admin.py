from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Security, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from ...core.database import get_db
from ...core.db_models import User, M2MApplication
from ...core.hashing import get_password_hash
from ...core.utils import generate_random_string
from ..auth_utils import get_current_identity

router = APIRouter(prefix="/admin", tags=["admin"])

class M2MCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    scopes: str = Field(default="printer:read printer:write rtc:stream")

class M2MResponse(BaseModel):
    client_id: str
    client_secret: str
    name: str
    scopes: str

class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: Optional[str] = None
    scopes: str = Field(default="printer:read rtc:stream")

class UserResponse(BaseModel):
    username: str
    password: Optional[str] = None
    scopes: str

@router.post("/m2m", response_model=M2MResponse)
async def create_m2m_application(
    request: M2MCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin: any = Security(get_current_identity, scopes=["admin"])
):
    """Create a new M2M application for automated access."""
    client_id = f"m2m_{generate_random_string(8).lower()}"
    client_secret = generate_random_string(32)
    m2m = M2MApplication(
        name=request.name,
        client_id=client_id,
        hashed_client_secret=get_password_hash(client_secret),
        scopes=request.scopes
    )
    db.add(m2m)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail="M2M application with this name or ID already exists")
    return M2MResponse(
        client_id=client_id,
        client_secret=client_secret,
        name=m2m.name,
        scopes=m2m.scopes
    )

@router.post("/users", response_model=UserResponse)
async def create_user(
    request: UserCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin: any = Security(get_current_identity, scopes=["admin"])
):
    """Create a new user account."""
    password = request.password or generate_random_string(16)
    user = User(
        username=request.username,
        hashed_password=get_password_hash(password),
        scopes=request.scopes
    )
    db.add(user)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail="User already exists")
    return UserResponse(
        username=user.username,
        password=password if not request.password else None,
        scopes=user.scopes
    )

@router.get("/users", response_model=List[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    admin: any = Security(get_current_identity, scopes=["admin"])
):
    """List all users."""
    result = await db.execute(select(User))
    users = result.scalars().all()
    return [UserResponse(username=u.username, scopes=u.scopes) for u in users]

@router.delete("/users/{username}")
async def delete_user(
    username: str,
    db: AsyncSession = Depends(get_db),
    admin: any = Security(get_current_identity, scopes=["admin"])
):
    """Delete a user."""
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(user)
    await db.commit()
    return {"status": "success"}

@router.get("/m2m", response_model=List[M2MResponse])
async def list_m2m_applications(
    db: AsyncSession = Depends(get_db),
    admin: any = Security(get_current_identity, scopes=["admin"])
):
    """List all M2M applications."""
    result = await db.execute(select(M2MApplication))
    m2ms = result.scalars().all()
    return [
        M2MResponse(
            client_id=m.client_id,
            client_secret="********",
            name=m.name,
            scopes=m.scopes
        ) for m in m2ms
    ]

@router.delete("/m2m/{client_id}")
async def delete_m2m_application(
    client_id: str,
    db: AsyncSession = Depends(get_db),
    admin: any = Security(get_current_identity, scopes=["admin"])
):
    """Delete an M2M application."""
    result = await db.execute(select(M2MApplication).where(M2MApplication.client_id == client_id))
    m2m = result.scalar_one_or_none()
    if not m2m:
        raise HTTPException(status_code=404, detail="M2M application not found")
    await db.delete(m2m)
    await db.commit()
    return {"status": "success"}

