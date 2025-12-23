"""Printer control endpoints."""

import logging
from fastapi import APIRouter, HTTPException

from ...core.models import PrinterConfig, PrinterInfo, PrinterStatus, FeedSettings
from ...core.model import get_model
from ...core.inference import predict
from ...providers import list_providers as get_available_providers, get_provider
from ...providers.base import PrinterProvider
from ...services.webrtc import start_track_processing
from ...services.streams import stream_manager
from ..crypto_utils import EncryptedRoute

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/printer", tags=["printer"], route_class=EncryptedRoute)

_printers: dict[str, tuple[PrinterConfig, PrinterProvider | None]] = {}


@router.get("/providers")
async def list_providers() -> list[str]:
    """List available printer providers."""
    return get_available_providers()


@router.post("/", response_model=PrinterInfo)
async def register_printer(config: PrinterConfig) -> PrinterInfo:
    """Register a new printer."""
    if config.id in _printers:
        raise HTTPException(status_code=409, detail="Printer ID already exists")
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


@router.get("/{printer_id}/health")
async def get_printer_health(printer_id: str) -> dict:
    """Check printer connection health."""
    if printer_id not in _printers:
        raise HTTPException(status_code=404, detail="Printer not found")
    _, provider = _printers[printer_id]
    if not provider:
        return {"status": "disconnected", "error": "No provider connected"}
    try:
        await provider.is_printing()
        return {"status": "healthy"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/{printer_id}/stream", response_model=dict)
async def link_printer_stream(printer_id: str, session_id: str, settings: FeedSettings = FeedSettings()) -> dict:
    """Import the printer's camera as a PrintGuard session."""
    logger.info(f"Linking stream for printer {printer_id} with session {session_id}")
    if (existing_source := stream_manager.get_source(printer_id)):
        logger.info(f"Using existing multiplexed stream for printer {printer_id}")
        stream_manager.add_alias(printer_id, session_id)
        return {"status": "success", "session_id": session_id, "multiplexed": True}
    if printer_id not in _printers:
        logger.warning(f"Printer {printer_id} not found for streaming")
        raise HTTPException(status_code=404, detail="Printer not found")
    config, provider = _printers[printer_id]
    if not provider:
        logger.warning(f"No provider for printer {printer_id}")
        raise HTTPException(status_code=400, detail="Printer provider not connected")
    try:
        track, pc = await provider.get_camera_track()
        if not track:
            logger.warning(f"Provider for {printer_id} returned no camera track")
            raise HTTPException(status_code=404, detail="Printer has no camera or WebRTC not supported")
        logger.info(f"Successfully got camera track for {printer_id}")
        model_info = get_model()
        processor = await start_track_processing(
            track,
            predict,
            model_info,
            settings,
            session_id
        )
        if processor.relayed_track:
            stream_manager.register_source(
                printer_id, 
                processor.relayed_track, 
                processor,
                pc=pc,
                device_name=f"{config.name} Camera",
                settings=settings
            )
            stream_manager.add_alias(printer_id, session_id)
        config.linked_session_id = session_id
        return {"status": "success", "session_id": session_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to link printer stream: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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


@router.post("/{printer_id}/resume")
async def resume_print(printer_id: str) -> dict:
    """Resume the current print."""
    if printer_id not in _printers:
        raise HTTPException(status_code=404, detail="Printer not found")

    _, provider = _printers[printer_id]
    if not provider:
        raise HTTPException(status_code=400, detail="No provider connected")

    await provider.resume()
    return {"status": "resumed"}


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
