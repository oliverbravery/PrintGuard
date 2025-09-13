from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, field_validator
from schemas.schemas_setup import OperatingSystem


class TunnelProvider(str, Enum):
    NGROK = "ngrok"
    CLOUDFLARE = "cloudflare"

class TunnelSettings(BaseModel):
    provider: TunnelProvider
    token: str
    domain: str = ""
    email: Optional[str] = None

    @field_validator('domain')
    @classmethod
    def validate_domain_for_ngrok(cls, v, info):
        if info.data.get('provider') == TunnelProvider.NGROK and not v:
            raise ValueError('Domain is required for ngrok provider')
        return v
    
class CloudflareTunnelConfig(BaseModel):
    account_id: str
    zone_id: str
    subdomain: str

class CloudflareDownloadConfig(BaseModel):
    operating_system: OperatingSystem

class WarpDeviceConfig(BaseModel):
    device_id: Optional[str] = None
    user_email: Optional[str] = None


class CloudflareCommandSet(BaseModel):
    operating_system: OperatingSystem
    install_command: str
    enable_command: str = ""
    start_command: str
    stop_command: str
    restart_command: str = ""
    setup_sequence: List[str]

class WarpDeviceEnrollmentRule(BaseModel):
    name: str
    precedence: int = 0
    require: List[str] = []
    include: List[str] = []