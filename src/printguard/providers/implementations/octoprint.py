"""OctoPrint printer provider implementation."""

import httpx
import logging
from typing import Optional

from ..base import PrinterProvider
from ..registry import register

logger = logging.getLogger(__name__)

@register("octoprint")
class OctoPrintProvider(PrinterProvider):
    """Provider for OctoPrint API."""

    def __init__(self, host: str, api_key: str):
        self.host = host.rstrip("/")
        self.api_key = api_key
        self.headers = {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json"
        }
        self.client: Optional[httpx.AsyncClient] = None

    @property
    def name(self) -> str:
        return "octoprint"

    async def connect(self) -> None:
        """Initialize the HTTP client and test connection."""
        if not self.client:
            self.client = httpx.AsyncClient(base_url=self.host, headers=self.headers)
        # Test connection by getting connection settings
        response = await self.client.get("/api/connection")
        response.raise_for_status()
        # Ensure printer is connected in OctoPrint
        data = response.json()
        if data.get("current", {}).get("state") == "Closed":
            await self.client.post("/api/connection", json={"command": "connect"})

    async def disconnect(self) -> None:
        """Close the HTTP client."""
        if self.client:
            await self.client.aclose()
            self.client = None

    async def is_printing(self) -> bool:
        """Check if the printer is currently printing."""
        if not self.client:
            await self.connect()
        response = await self.client.get("/api/job")
        response.raise_for_status()
        data = response.json()
        return data.get("state") == "Printing"

    async def start(self) -> None:
        """Start the current job."""
        if not self.client:
            await self.connect()
        response = await self.client.post("/api/job", json={"command": "start"})
        response.raise_for_status()

    async def pause(self) -> None:
        """Pause the current job."""
        if not self.client:
            await self.connect()
        response = await self.client.post("/api/job", json={"command": "pause", "action": "pause"})
        response.raise_for_status()

    async def resume(self) -> None:
        """Resume the current job."""
        if not self.client:
            await self.connect()
        response = await self.client.post("/api/job", json={"command": "pause", "action": "resume"})
        response.raise_for_status()

    async def stop(self) -> None:
        """Cancel the current job."""
        if not self.client:
            await self.connect()
        response = await self.client.post("/api/job", json={"command": "cancel"})
        response.raise_for_status()