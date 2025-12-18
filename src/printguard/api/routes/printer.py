"""Printer control endpoints."""

import logging
from fastapi import APIRouter, HTTPException

from ...core.models import PrinterConfig, PrinterInfo, PrinterStatus
from ...providers import list_providers as get_available_providers, get_provider
from ...providers.base import PrinterProvider

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/printer", tags=["printer"])

_printers: dict[str, tuple[PrinterConfig, PrinterProvider | None]] = {}


@router.get("/providers")
async def list_providers() -> list[str]:
    """List available printer providers."""
    return get_available_providers()


@router.post("/", response_model=PrinterInfo)
async def register_printer(config: PrinterConfig) -> PrinterInfo:
    """Register a new printer."""
    if config.id in _printers:
        raise HTTPException(status_code=400, detail="Printer ID already exists")

    provider_cls = get_provider(config.provider)
    provider_instance: PrinterProvider | None = None
    status = PrinterStatus.DISCONNECTED

    if provider_cls:
        try:
            provider_instance = provider_cls(**config.config)
            await provider_instance.connect()
            status = PrinterStatus.IDLE
        except Exception as e:
            logger.warning(f"Failed to connect provider {config.provider}: {e}")
            status = PrinterStatus.ERROR

    _printers[config.id] = (config, provider_instance)

    return PrinterInfo(
        id=config.id,
        name=config.name,
        provider=config.provider,
        status=status,
        linked_session_id=config.linked_session_id,
    )


@router.get("/", response_model=list[PrinterInfo])
async def list_printers() -> list[PrinterInfo]:
    """List all registered printers."""
    results = []
    for printer_id, (config, provider) in _printers.items():
        status = PrinterStatus.DISCONNECTED
        if provider:
            try:
                is_printing = await provider.is_printing()
                status = PrinterStatus.PRINTING if is_printing else PrinterStatus.IDLE
            except Exception:
                status = PrinterStatus.ERROR
        results.append(
            PrinterInfo(
                id=printer_id,
                name=config.name,
                provider=config.provider,
                status=status,
                linked_session_id=config.linked_session_id,
            )
        )
    return results


@router.get("/{printer_id}", response_model=PrinterInfo)
async def get_printer(printer_id: str) -> PrinterInfo:
    """Get printer status."""
    if printer_id not in _printers:
        raise HTTPException(status_code=404, detail="Printer not found")

    config, provider = _printers[printer_id]
    status = PrinterStatus.DISCONNECTED
    if provider:
        try:
            is_printing = await provider.is_printing()
            status = PrinterStatus.PRINTING if is_printing else PrinterStatus.IDLE
        except Exception:
            status = PrinterStatus.ERROR

    return PrinterInfo(
        id=printer_id,
        name=config.name,
        provider=config.provider,
        status=status,
        linked_session_id=config.linked_session_id,
    )


@router.delete("/{printer_id}")
async def remove_printer(printer_id: str) -> dict:
    """Remove a registered printer."""
    if printer_id not in _printers:
        raise HTTPException(status_code=404, detail="Printer not found")

    config, provider = _printers.pop(printer_id)
    if provider:
        try:
            await provider.disconnect()
        except Exception as e:
            logger.warning(f"Error disconnecting printer {printer_id}: {e}")

    return {"status": "removed", "id": printer_id}


@router.post("/{printer_id}/start")
async def start_print(printer_id: str) -> dict:
    """Start/resume the print job."""
    if printer_id not in _printers:
        raise HTTPException(status_code=404, detail="Printer not found")

    _, provider = _printers[printer_id]
    if not provider:
        raise HTTPException(status_code=400, detail="No provider connected")

    await provider.start()
    return {"status": "started"}


@router.post("/{printer_id}/pause")
async def pause_print(printer_id: str) -> dict:
    """Pause the current print."""
    if printer_id not in _printers:
        raise HTTPException(status_code=404, detail="Printer not found")

    _, provider = _printers[printer_id]
    if not provider:
        raise HTTPException(status_code=400, detail="No provider connected")

    await provider.pause()
    return {"status": "paused"}


@router.post("/{printer_id}/stop")
async def stop_print(printer_id: str) -> dict:
    """Stop/cancel the current print."""
    if printer_id not in _printers:
        raise HTTPException(status_code=404, detail="Printer not found")

    _, provider = _printers[printer_id]
    if not provider:
        raise HTTPException(status_code=400, detail="No provider connected")

    await provider.stop()
    return {"status": "stopped"}


@router.post("/{printer_id}/link/{session_id}", response_model=PrinterInfo)
async def link_stream(printer_id: str, session_id: str) -> PrinterInfo:
    """Link a WebRTC stream (session) to this printer."""
    if printer_id not in _printers:
        raise HTTPException(status_code=404, detail="Printer not found")

    config, provider = _printers[printer_id]
    config.linked_session_id = session_id
    _printers[printer_id] = (config, provider)

    status = PrinterStatus.DISCONNECTED
    if provider:
        try:
            is_printing = await provider.is_printing()
            status = PrinterStatus.PRINTING if is_printing else PrinterStatus.IDLE
        except Exception:
            status = PrinterStatus.ERROR

    return PrinterInfo(
        id=printer_id,
        name=config.name,
        provider=config.provider,
        status=status,
        linked_session_id=config.linked_session_id,
    )


@router.delete("/{printer_id}/link", response_model=PrinterInfo)
async def unlink_stream(printer_id: str) -> PrinterInfo:
    """Unlink the stream from this printer."""
    if printer_id not in _printers:
        raise HTTPException(status_code=404, detail="Printer not found")

    config, provider = _printers[printer_id]
    config.linked_session_id = None
    _printers[printer_id] = (config, provider)

    status = PrinterStatus.DISCONNECTED
    if provider:
        try:
            is_printing = await provider.is_printing()
            status = PrinterStatus.PRINTING if is_printing else PrinterStatus.IDLE
        except Exception:
            status = PrinterStatus.ERROR

    return PrinterInfo(
        id=printer_id,
        name=config.name,
        provider=config.provider,
        status=status,
        linked_session_id=None,
    )
