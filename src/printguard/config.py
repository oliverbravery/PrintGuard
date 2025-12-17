"""Configuration settings using pydantic-settings."""

from pathlib import Path
from functools import lru_cache
from enum import Enum

from pydantic_settings import BaseSettings, SettingsConfigDict


class TunnelProvider(str, Enum):
    """Available tunnel providers."""
    LOCAL = "local"
    CLOUDFLARE = "cloudflare"
    NGROK = "ngrok"


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    # Tunnel Settings
    tunnel_provider: TunnelProvider = TunnelProvider.LOCAL

    # Cloudflare Tunnel Settings
    cloudflare_api_token: str = ""
    cloudflare_domain: str = ""
    cloudflare_tunnel_name: str = "printguard-tunnel"
    cloudflare_subdomain: str = "camera"

    # ngrok Settings
    ngrok_authtoken: str = ""
    ngrok_domain: str = ""
    ngrok_edge: str = ""


MODEL_DIR = Path(__file__).parent / "model"


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings.
    
    Returns:
        Settings: The application settings instance.
    """
    return Settings()
