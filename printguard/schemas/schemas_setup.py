from enum import Enum
from typing import Optional
from pydantic import BaseModel
from printguard.schemas.schemas_settings import TunnelProvider

class SiteStartupMode(str, Enum):
    SETUP = "setup"
    LOCAL = "local"
    TUNNEL = "tunnel"

class SetupCompletion(BaseModel):
    startup_mode: SiteStartupMode
    tunnel_provider: Optional[TunnelProvider] = None