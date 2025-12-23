"""Cloudflare Tunnel setup utility."""

import logging
import shutil
import asyncio
import httpx
from typing import Tuple, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class CFTunnel:
    id: str
    name: str
    tunnel_secret: str = ""

@dataclass
class CFAccount:
    id: str
    name: str

@dataclass
class CFZone:
    id: str
    name: str

@dataclass
class CFDNSRecord:
    id: str
    name: str

def is_cloudflared_installed() -> bool:
    """Check if the cloudflared binary is installed and in PATH."""
    return shutil.which("cloudflared") is not None

async def run_tunnel(tunnel_id: str, tunnel_secret: str, port: int = 8000):
    """Run the cloudflared tunnel in a background process."""
    if not is_cloudflared_installed():
        logger.error("cloudflared binary not found. Cannot run tunnel.")
        return None
    cmd = [
        "cloudflared", "tunnel", "--no-autoupdate", "run",
        "--url", f"http://localhost:{port}",
        tunnel_id
    ]
    logger.info(f"Starting cloudflared tunnel {tunnel_id}...")
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        return process
    except Exception as e:
        logger.error(f"Failed to start cloudflared process: {e}")
        return None

class CloudflareManager:
    def __init__(self, api_token: str):
        self.api_token = api_token
        self.base_url = "https://api.cloudflare.com/client/v4"
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/{path.lstrip('/')}"
            response = await client.request(method, url, headers=self.headers, **kwargs)
            data = response.json()
            if not data.get("success"):
                errors = data.get("errors", [])
                error_msg = errors[0].get("message") if errors else response.text
                raise Exception(f"Cloudflare API error: {error_msg}")
            return data

    async def list_accounts(self) -> List[CFAccount]:
        data = await self._request("GET", "accounts")
        return [CFAccount(id=a["id"], name=a["name"]) for a in data["result"]]

    async def list_zones(self, name: Optional[str] = None) -> List[CFZone]:
        params = {"name": name} if name else {}
        data = await self._request("GET", "zones", params=params)
        return [CFZone(id=z["id"], name=z["name"]) for z in data["result"]]

    async def create_tunnel(self, account_id: str, name: str) -> CFTunnel:
        try:
            payload = {
                "name": name,
                "config_src": "local"
            }
            data = await self._request("POST", f"accounts/{account_id}/cfd_tunnels", json=payload)
            res = data["result"]
            return CFTunnel(id=res["id"], name=res["name"], tunnel_secret=res.get("tunnel_secret", ""))
        except Exception as e:
            if "already exists" in str(e).lower():
                data = await self._request("GET", f"accounts/{account_id}/cfd_tunnels", params={"name": name, "is_deleted": "false"})
                for t in data["result"]:
                    if t["name"] == name:
                        return CFTunnel(id=t["id"], name=t["name"])
            raise e

    async def create_dns_record(self, zone_id: str, name: str, tunnel_id: str):
        content = f"{tunnel_id}.cfargotunnel.com"
        try:
            payload = {
                "name": name,
                "type": "CNAME",
                "content": content,
                "proxied": True
            }
            return await self._request("POST", f"zones/{zone_id}/dns_records", json=payload)
        except Exception as e:
            if "already exists" in str(e).lower() or "81057" in str(e):
                data = await self._request("GET", f"zones/{zone_id}/dns_records", params={"name": name})
                for record in data["result"]:
                    # In some cases Cloudflare returns the full name, check if it matches
                    if record["name"].startswith(name):
                        payload = {
                            "name": name,
                            "type": "CNAME",
                            "content": content,
                            "proxied": True
                        }
                        return await self._request("PUT", f"zones/{zone_id}/dns_records/{record['id']}", json=payload)
            raise e

async def setup_tunnel(
    api_token: str, 
    domain_name: str, 
    tunnel_name: str,
    subdomain: str = "camera"
) -> Optional[Tuple[str, str]]:
    """Set up a Cloudflare tunnel and CNAME record automatically."""
    if not is_cloudflared_installed():
        logger.error("cloudflared binary not found. Please install it to use tunnels.")
        return None
    try:
        manager = CloudflareManager(api_token)
        # 1. Get Account ID
        accounts = await manager.list_accounts()
        if not accounts:
            logger.error("No Cloudflare accounts found.")
            return None
        account_id = accounts[0].id
        # 2. Get Zone ID
        zones = await manager.list_zones(name=domain_name)
        zone_id = None
        if zones:
            zone_id = zones[0].id
        if not zone_id:
            logger.error(f"Zone not found for domain: {domain_name}")
            return None
        # 3. Create the Tunnel
        logger.info(f"Creating Cloudflare tunnel: {tunnel_name}")
        tunnel = await manager.create_tunnel(account_id, tunnel_name)
        # 4. Create the CNAME Record
        logger.info(f"Creating DNS record: {subdomain}.{domain_name} -> {tunnel.id}.cfargotunnel.com")
        await manager.create_dns_record(zone_id, subdomain, tunnel.id)
        return tunnel.id, tunnel.tunnel_secret
    except Exception as e:
        logger.exception(f"Failed to set up Cloudflare tunnel: {e}")
        return None
