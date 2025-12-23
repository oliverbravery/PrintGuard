from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    scopes: Mapped[str] = mapped_column(String(255), default="")

class M2MApplication(Base):
    __tablename__ = "m2m_applications"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    client_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    hashed_client_secret: Mapped[str] = mapped_column(String(255))
    scopes: Mapped[str] = mapped_column(String(255), default="")

