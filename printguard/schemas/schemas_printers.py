from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

class FileInfo(BaseModel):
    name: Optional[str] = None
    origin: Optional[str] = None
    size: Optional[int] = None
    date: Optional[int] = None


class Progress(BaseModel):
    completion: Optional[float] = None
    filepos: Optional[int] = None
    printTime: Optional[int] = None
    printTimeLeft: Optional[int] = None


class JobInfoResponse(BaseModel):
    job: Dict = Field(default_factory=dict)
    progress: Optional[Progress] = None
    state: str
    error: Optional[str] = None

    model_config = {
        "extra": "ignore"
    }


class TemperatureReading(BaseModel):
    actual: float
    target: Optional[float]
    offset: Optional[float]


class TemperatureReadings(BaseModel):
    temperature: Dict[str, TemperatureReading]
    
class PrinterTemperatures(BaseModel):
    nozzle_actual: Optional[float] = None
    nozzle_target: Optional[float] = None
    bed_actual: Optional[float] = None
    bed_target: Optional[float] = None

class PrinterState(BaseModel):
    jobInfoResponse: Optional[JobInfoResponse] = None
    temperatureReading: Optional[PrinterTemperatures] = None

class CurrentPayload(BaseModel):
    state: dict
    job: Any
    progress: Progress
    temps: Optional[list] = Field(None, alias="temps")

class PrinterType(str, Enum):
    OCTOPRINT = "octoprint"

class PrinterConfig(BaseModel):
    name: str
    printer_type: PrinterType
    camera_uuid: str
    base_url: str
    api_key: str

class PrinterConfigRequest(BaseModel):
    name: str
    printer_type: PrinterType
    camera_uuid: str
    base_url: str
    api_key: str