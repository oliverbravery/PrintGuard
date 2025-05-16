from pydantic import BaseModel
from enum import Enum
from typing import Optional, List

class Alert(BaseModel):
    id: str
    snapshot: bytes
    title: str
    message: str
    timestamp: float
    countdown_time: float
    camera_index: int

class AlertAction(str, Enum):
    DISMISS = "dismiss"
    CANCEL_PRINT = "cancel_print"
    
class SSEDataType(str, Enum):
    ALERT = "alert"
    CAMERA_STATE = "camera_state"

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
