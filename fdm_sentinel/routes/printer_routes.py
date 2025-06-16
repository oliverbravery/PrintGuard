import logging

from fastapi import APIRouter, HTTPException

from ..models import PrinterConfigRequest
from ..utils.printer_services.octoprint import OctoPrintClient
from ..utils.printer_utils import get_printer_id, remove_printer, set_printer

router = APIRouter()

@router.post("/printer/add/{camera_index}", include_in_schema=False)
async def add_printer_ep(camera_index: int, printer_config: PrinterConfigRequest):
    try:
        client = OctoPrintClient(printer_config.base_url, printer_config.api_key)
        client.get_job_info()
        printer_id = f"{camera_index}_{printer_config.name.replace(' ', '_')}"
        await set_printer(camera_index, printer_id, printer_config.model_dump())
        return {"success": True, "printer_id": printer_id}
    except Exception as e:
        logging.error("Error adding printer: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to add printer: {str(e)}")

@router.post("/printer/remove/{camera_index}", include_in_schema=False)
async def remove_printer_ep(camera_index: int):
    try:
        printer_id = get_printer_id(camera_index)
        if printer_id:
            await remove_printer(camera_index)
            return {"success": True, "message": f"Printer removed from camera {camera_index}"}
        else:
            return {"success": False, "error": "No printer configured for this camera"}
    except Exception as e:
        logging.error("Error removing printer from camera %d: %s", camera_index, e)
        raise HTTPException(status_code=500, detail=f"Failed to remove printer: {str(e)}")
