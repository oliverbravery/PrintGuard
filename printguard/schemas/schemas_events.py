from pydantic import BaseModel
from typing import Optional, List
from enum import Enum


class Alert(BaseModel):
    id: str
    snapshot: bytes
    title: str
    message: str
    timestamp: float
    countdown_time: float
    camera_uuid: str
    has_printer: bool = False
    countdown_action: str = "dismiss"

class AlertAction(str, Enum):
    DISMISS = "dismiss"
    CANCEL_PRINT = "cancel_print"
    PAUSE_PRINT = "pause_print"

class SSEDataType(str, Enum):
    ALERT = "alert"
    CAMERA_STATE = "camera_state"
    PRINTER_STATE = "printer_state"

class NotificationAction(BaseModel):
    action: str
    title: str
    icon: Optional[str] = None

class Notification(BaseModel):
    title: str
    body: str
    image_url: Optional[str] = None
    icon_url: Optional[str] = None
    badge_url: Optional[str] = None
    actions: List[NotificationAction] = []

class VapidSettings(BaseModel):
    public_key: str
    private_key: str
    subject: str
    base_url: str
