from sqlalchemy import String, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base
import uuid

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

class Printer(Base):
    __tablename__ = "printers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100))
    client_public_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    component_links: Mapped[list["PrinterComponentLink"]] = relationship(back_populates="printer", cascade="all, delete-orphan")

class Component(Base):
    __tablename__ = "components"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider: Mapped[str] = mapped_column(String(50))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    printer_links: Mapped[list["PrinterComponentLink"]] = relationship(back_populates="component")

class PrinterComponentLink(Base):
    __tablename__ = "printer_component_links"
    
    printer_id: Mapped[str] = mapped_column(ForeignKey("printers.id"), primary_key=True)
    component_id: Mapped[str] = mapped_column(ForeignKey("components.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), primary_key=True)
    printer: Mapped["Printer"] = relationship(back_populates="component_links")
    component: Mapped["Component"] = relationship(back_populates="printer_links")

