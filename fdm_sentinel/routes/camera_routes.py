import logging

from fastapi import APIRouter, Request, Body
from fastapi.exceptions import HTTPException
from ..utils.camera_utils import get_camera_state
from ..utils.printer_utils import get_printer_id, set_printer, remove_printer
from ..utils.printer_services.octoprint import OctoPrintClient
from ..models import PrinterConfigRequest

router = APIRouter()

@router.post("/camera/state", include_in_schema=False)
async def get_camera_state_ep(request: Request, camera_index: int = Body(..., embed=True)):
    camera_state = get_camera_state(camera_index)
    detection_times = [t for t, _ in camera_state.detection_history] if (
        camera_state.detection_history
        ) else []
    response = {
        "start_time": camera_state.start_time,
        "last_result": camera_state.last_result,
        "last_time": camera_state.last_time,
        "detection_times": detection_times,
        "error": camera_state.error,
        "live_detection_running": camera_state.live_detection_running,
        "brightness": camera_state.brightness,
        "contrast": camera_state.contrast,
        "focus": camera_state.focus,
        "countdown_time": camera_state.countdown_time,
        "majority_vote_threshold": camera_state.majority_vote_threshold,
        "majority_vote_window": camera_state.majority_vote_window,
        "current_alert_id": camera_state.current_alert_id,
        "sensitivity": camera_state.sensitivity,
        "printer_id": camera_state.printer_id,
        "printer_config": camera_state.printer_config
    }
    return response

@router.post("/camera/add-printer", include_in_schema=False)
async def add_printer(printer_config: PrinterConfigRequest):
    try:
        client = OctoPrintClient(printer_config.base_url, printer_config.api_key)
        client.get_job_info()
        printer_id = f"{printer_config.camera_index}_{printer_config.name.replace(' ', '_')}"
        await set_printer(printer_config.camera_index, printer_id, printer_config.model_dump())
        return {"success": True, "printer_id": printer_id}
    except Exception as e:
        logging.error("Error adding printer: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to add printer: {str(e)}")

@router.post("/camera/remove-printer/{camera_index}", include_in_schema=False)
async def remove_printer_from_camera(camera_index: int):
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
