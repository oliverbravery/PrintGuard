from enum import Enum
from typing import Optional
from pydantic import BaseModel
from schemas.schemas_networking import TunnelProvider

class SiteStartupMode(str, Enum):
    SETUP = "setup"
    LOCAL = "local"
    TUNNEL = "tunnel"

class OperatingSystem(str, Enum):
    MACOS = "macos"
    WINDOWS = "windows"
    LINUX = "linux"

class SetupCompletion(BaseModel):
    startup_mode: SiteStartupMode
    tunnel_provider: Optional[TunnelProvider] = None