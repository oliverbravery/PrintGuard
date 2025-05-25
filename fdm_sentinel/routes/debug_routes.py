import logging

from fastapi import APIRouter, Request
from fastapi.exceptions import HTTPException
from ..models import Notification
from ..utils.notification_utils import send_notification
from ..utils.config import reset_all

router = APIRouter()

@router.post("/debug/setup/reset", include_in_schema=False)
async def debug_setup_reset():
    try:
        reset_all()
        logging.debug("Debug reset completed successfully")
        return {"success": True, "message": "All saved keys and config have been reset"}
    except Exception as e:
        logging.error("Error during debug reset: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to reset: {str(e)}")

@router.post("/notification/push")
async def push(notification: Notification, request: Request):
    success = send_notification(notification, request.app)
    return {"success": success}
