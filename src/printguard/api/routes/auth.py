from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.db_models import User, M2MApplication
from ...core.hashing import verify_password
from ..auth_utils import create_access_token, get_current_identity

router = APIRouter(prefix="/auth", tags=["auth"])

@router.get("/me")
async def get_me(
    current_user: Annotated[User, Depends(get_current_identity)]
):
    """Get current user information."""
    return {
        "username": current_user.username,
        "scopes": current_user.scopes.split()
    }

@router.post("/token")
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.username == form_data.username))
    user = result.scalar_one_or_none()
    if user and verify_password(form_data.password, user.hashed_password):
        user_scopes = user.scopes.split()
        for scope in form_data.scopes:
            if scope not in user_scopes:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Requested scope not authorized for user"
                )
        access_token = create_access_token(
            data={"sub": user.username, "scopes": " ".join(form_data.scopes or user_scopes)}
        )
        return {"access_token": access_token, "token_type": "bearer"}
    result = await db.execute(select(M2MApplication).where(M2MApplication.client_id == form_data.username))
    m2m = result.scalar_one_or_none()
    if m2m and verify_password(form_data.password, m2m.hashed_client_secret):
        m2m_scopes = m2m.scopes.split()
        for scope in form_data.scopes:
            if scope not in m2m_scopes:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Requested scope not authorized for application"
                )
        access_token = create_access_token(
            data={"sub": m2m.client_id, "scopes": " ".join(form_data.scopes or m2m_scopes)}
        )
        return {"access_token": access_token, "token_type": "bearer"}
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username/client_id or password/secret",
        headers={"WWW-Authenticate": "Bearer"},
    )

