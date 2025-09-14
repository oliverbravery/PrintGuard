import asyncio
from typing import Optional, Dict, List
from pydantic import BaseModel, Field

def _get_config_value(key: str):
    # pylint: disable=import-outside-toplevel
    from printguard.utils import (BRIGHTNESS, CONTRAST,
                              FOCUS, SENSITIVITY,
                              COUNTDOWN_TIME, COUNTDOWN_ACTION,
                              DETECTION_VOTING_THRESHOLD,
                              DETECTION_VOTING_WINDOW)
    config_map = {
        'BRIGHTNESS': BRIGHTNESS,
        'CONTRAST': CONTRAST,
        'FOCUS': FOCUS,
        'SENSITIVITY': SENSITIVITY,
        'COUNTDOWN_TIME': COUNTDOWN_TIME,
        'COUNTDOWN_ACTION': COUNTDOWN_ACTION,
        'DETECTION_VOTING_THRESHOLD': DETECTION_VOTING_THRESHOLD,
        'DETECTION_VOTING_WINDOW': DETECTION_VOTING_WINDOW,
    }
    return config_map[key]

class CameraState(BaseModel):
    nickname: str
    source: str
    lock: asyncio.Lock = Field(default_factory=asyncio.Lock, exclude=True)
    current_alert_id: Optional[str] = None
    detection_history: List[tuple] = []
    live_detection_running: bool = False
    live_detection_task: Optional[str] = None
    last_result: Optional[str] = None
    last_time: Optional[float] = None
    start_time: Optional[float] = None
    error: Optional[str] = None
    brightness: float = None
    contrast: float = None
    focus: float = None
    sensitivity: float = None
    countdown_time: float = None
    countdown_action: str = None
    majority_vote_threshold: int = None
    majority_vote_window: int = None
    printer_id: Optional[str] = None
    printer_config: Optional[Dict] = None

    def __init__(self, **data):
        if 'brightness' not in data:
            data['brightness'] = _get_config_value('BRIGHTNESS')
        if 'contrast' not in data:
            data['contrast'] = _get_config_value('CONTRAST')
        if 'focus' not in data:
            data['focus'] = _get_config_value('FOCUS')
        if 'sensitivity' not in data:
            data['sensitivity'] = _get_config_value('SENSITIVITY')
        if 'countdown_time' not in data:
            data['countdown_time'] = _get_config_value('COUNTDOWN_TIME')
        if 'countdown_action' not in data:
            data['countdown_action'] = _get_config_value('COUNTDOWN_ACTION')
        if 'majority_vote_threshold' not in data:
            data['majority_vote_threshold'] = _get_config_value('DETECTION_VOTING_THRESHOLD')
        if 'majority_vote_window' not in data:
            data['majority_vote_window'] = _get_config_value('DETECTION_VOTING_WINDOW')
        super().__init__(**data)
    model_config = {
        "arbitrary_types_allowed": True
    }

class PollingTask(BaseModel):
    task: Optional[asyncio.Task] = None
    stop_event: Optional[asyncio.Event] = None
    model_config = {
        "arbitrary_types_allowed": True
    }
