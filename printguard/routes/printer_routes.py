import logging

from fastapi import APIRouter, HTTPException

from ..models import PrinterConfigRequest, AlertAction
from ..utils.printer_services.octoprint import OctoPrintClient
from ..utils.printer_utils import (get_printer_id, remove_printer,
                                   set_printer, suspend_print_job)
from ..utils.camera_utils import get_camera_state

router = APIRouter()

@router.post("/printer/add/{camera_uuid}", include_in_schema=False)
async def add_printer_ep(camera_uuid: str, printer_config: PrinterConfigRequest):
    """Add a printer configuration to a specific camera.

    Args:
        camera_uuid (str): UUID of the camera to associate the printer with.
        printer_config (PrinterConfigRequest): Printer configuration including
                                              base URL, API key, and name.

    Returns:
        dict: Success status and generated printer ID, or error details.

    Raises:
        HTTPException: If printer connection test fails or configuration is invalid.
    """
    try:
        client = OctoPrintClient(printer_config.base_url, printer_config.api_key)
        client.get_job_info()
        printer_id = f"{camera_uuid}_{printer_config.name.replace(' ', '_')}"
        await set_printer(camera_uuid, printer_id, printer_config.model_dump())
        return {"success": True, "printer_id": printer_id}
    except Exception as e:
        logging.error("Error adding printer: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to add printer: {str(e)}")

@router.post("/printer/remove/{camera_uuid}", include_in_schema=False)
async def remove_printer_ep(camera_uuid: str):
    """Remove printer configuration from a specific camera.

    Args:
        camera_uuid (str): UUID of the camera to remove printer configuration from.

    Returns:
        dict: Success status and confirmation message, or error if no printer configured.

    Raises:
        HTTPException: If removal fails due to system errors.
    """
    try:
        printer_id = get_printer_id(camera_uuid)
        if printer_id:
            await remove_printer(camera_uuid)
            camera_state = await get_camera_state(camera_uuid)
            camera_nickname = camera_state.nickname if camera_state else camera_uuid
            return {"success": True, "message": f"Printer removed from camera {camera_nickname}"}
        else:
            return {"success": False, "error": "No printer configured for this camera"}
    except Exception as e:
        logging.error("Error removing printer from camera %s: %s", camera_uuid, e)
        raise HTTPException(status_code=500, detail=f"Failed to remove printer: {str(e)}")

@router.post("/printer/cancel/{camera_uuid}", include_in_schema=False)
async def cancel_print_job_ep(camera_uuid: str):
    """Cancel the current print job for a specific camera's printer.

    Args:
        camera_uuid (str): UUID of the camera whose printer job should be cancelled.

    Returns:
        dict: Success status and confirmation message.
    """
    suspend_print_job(camera_uuid, AlertAction.CANCEL_PRINT)
    camera_state = await get_camera_state(camera_uuid)
    camera_nickname = camera_state.nickname if camera_state else camera_uuid
    return {"success": True, "message": f"Print job cancelled for camera {camera_nickname}"}

@router.post("/printer/pause/{camera_uuid}", include_in_schema=False)
async def pause_print_job_ep(camera_uuid: str):
    """Pause the current print job for a specific camera's printer.

    Args:
        camera_uuid (str): UUID of the camera whose printer job should be paused.

    Returns:
        dict: Success status and confirmation message.
    """
    suspend_print_job(camera_uuid, AlertAction.PAUSE_PRINT)
    camera_state = await get_camera_state(camera_uuid)
    camera_nickname = camera_state.nickname if camera_state else camera_uuid
    return {"success": True, "message": f"Print job paused for camera {camera_nickname}"}
