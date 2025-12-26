import json
import base64
import logging
import shutil
import asyncio
import httpx
import secrets
from typing import Tuple, Optional, List
from ..core.models import CFTunnel, CFAccount, CFZone, CFDNSRecord

logger = logging.getLogger(__name__)

def is_cloudflared_installed() -> bool:
    """Check if the cloudflared binary is installed and in PATH."""
    return shutil.which("cloudflared") is not None

async def run_tunnel(tunnel_id: str, tunnel_secret: str, account_id: str, port: int = 8000):
    """Run the cloudflared tunnel in a background process."""
    if not is_cloudflared_installed():
        logger.error("cloudflared binary not found. Cannot run tunnel.")
        return None
    if tunnel_id and tunnel_secret and account_id:
        token_data = {
            "a": account_id,
            "t": tunnel_id,
            "s": tunnel_secret
        }
        token = base64.b64encode(json.dumps(token_data).encode()).decode()
        cmd = [
            "cloudflared", "tunnel", "--no-autoupdate", "run",
            "--url", f"http://localhost:{port}",
            "--token", token
        ]
    else:
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
        async def log_output(stream, name):
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded = line.decode().strip()
                if "error" in decoded.lower():
                    logger.error(f"cloudflared {name}: {decoded}")
                else:
                    logger.debug(f"cloudflared {name}: {decoded}")

        asyncio.create_task(log_output(process.stdout, "stdout"))
        asyncio.create_task(log_output(process.stderr, "stderr"))
        
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

    async def list_paginated(self, method: str, path: str, **kwargs):
        """Helper to list all results from a paginated Cloudflare API endpoint."""
        page = 1
        per_page = kwargs.setdefault("params", {}).setdefault("per_page", 50)
        all_results = []
        while True:
            kwargs["params"]["page"] = page
            data = await self._request(method, path, **kwargs)
            all_results.extend(data.get("result", []))
            info = data.get("result_info") or {}
            if page >= info.get("total_pages", page):
                break
            page += 1
        return all_results

    async def list_accounts(self) -> List[CFAccount]:
        results = await self.list_paginated("GET", "accounts")
        return [CFAccount(id=a["id"], name=a["name"]) for a in results]

    async def list_zones(self, name: Optional[str] = None) -> List[CFZone]:
        params = {"name": name} if name else {}
        results = await self.list_paginated("GET", "zones", params=params)
        return [CFZone(id=z["id"], name=z["name"]) for z in results]

    async def create_tunnel(self, account_id: str, name: str, overwrite: bool = False) -> CFTunnel:
        """Create a new tunnel or get an existing one. If overwrite is True, it will delete and recreate."""
        if overwrite:
            # Try to find and delete existing tunnel
            params = {"name": name, "is_deleted": "false"}
            results = await self.list_paginated("GET", f"accounts/{account_id}/cfd_tunnel", params=params)
            for t in results:
                if t["name"] == name:
                    logger.info(f"Deleting existing tunnel {t['id']} before recreate")
                    try:
                        await self._request("DELETE", f"accounts/{account_id}/cfd_tunnel/{t['id']}")
                    except Exception as e:
                        logger.warning(f"Failed to delete tunnel during overwrite: {e}")

        try:
            payload = {
                "name": name,
                "config_src": "local"
            }
            data = await self._request("POST", f"accounts/{account_id}/cfd_tunnel", json=payload)
            res = data["result"]
            return CFTunnel(id=res["id"], name=res["name"], tunnel_secret=res.get("tunnel_secret", ""), account_id=account_id)
        except Exception as e:
            if "already exists" in str(e).lower():
                params = {"name": name, "is_deleted": "false"}
                results = await self.list_paginated("GET", f"accounts/{account_id}/cfd_tunnel", params=params)
                for t in results:
                    if t["name"] == name:
                        return CFTunnel(id=t["id"], name=t["name"], account_id=account_id)
            raise e

    async def get_tunnel_by_name(self, account_id: str, name: str) -> Optional[CFTunnel]:
        """Check if a tunnel with the given name exists."""
        params = {"name": name, "is_deleted": "false"}
        results = await self.list_paginated("GET", f"accounts/{account_id}/cfd_tunnel", params=params)
        for t in results:
            if t["name"] == name:
                return CFTunnel(id=t["id"], name=t["name"], account_id=account_id)
        return None

    async def reset_tunnel_secret(self, account_id: str, tunnel_id: str) -> str:
        """Reset the secret for an existing tunnel and return it."""
        try:
            new_secret = base64.b64encode(secrets.token_bytes(32)).decode()
            payload = {"tunnel_secret": new_secret}
            await self._request("PATCH", f"accounts/{account_id}/cfd_tunnel/{tunnel_id}", json=payload)
            return new_secret
        except Exception as e:
            logger.error(f"Failed to reset tunnel secret: {e}")
            raise e

    async def get_dns_record(self, zone_id: str, name: str) -> Optional[CFDNSRecord]:
        """Check if a DNS record with the given name exists."""
        params = {"name": name}
        results = await self.list_paginated("GET", f"zones/{zone_id}/dns_records", params=params)
        for record in results:
            if record["name"] == name or record["name"].startswith(f"{name}."):
                return CFDNSRecord(id=record["id"], name=record["name"])
        return None

    async def create_dns_record(self, zone_id: str, name: str, tunnel_id: str, overwrite: bool = False):
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
            if "already exists" in str(e).lower() or "81057" in str(e) or overwrite:
                params = {"name": name}
                results = await self.list_paginated("GET", f"zones/{zone_id}/dns_records", params=params)
                if not results and "." not in name:
                    results = await self.list_paginated("GET", f"zones/{zone_id}/dns_records")

                for record in results:
                    if record["name"] == name or record["name"].startswith(f"{name}."):
                        logger.info(f"Updating existing DNS record {record['id']} ({record['name']})")
                        payload = {
                            "name": record["name"],
                            "type": "CNAME",
                            "content": content,
                            "proxied": True
                        }
                        return await self._request("PUT", f"zones/{zone_id}/dns_records/{record['id']}", json=payload)
                
                if "already exists" in str(e).lower() or "81057" in str(e):
                    logger.warning(f"Cloudflare says record exists but we couldn't find it to update: {name}")
            
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
