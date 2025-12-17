"""Cloudflare Tunnel setup utility."""

import logging
import shutil
import asyncio
from typing import Tuple, Optional

try:
    from cloudflare import AsyncCloudflare
except ImportError:
    AsyncCloudflare = None

logger = logging.getLogger(__name__)

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
        if AsyncCloudflare is None:
            raise ImportError("cloudflare-python package is not installed. Run 'pip install cloudflare'")
        self.client = AsyncCloudflare(api_token=api_token)

    async def list_accounts(self):
        accounts = await self.client.accounts.list()
        return [account async for account in accounts]

    async def list_zones(self):
        zones = await self.client.zones.list()
        return [zone async for zone in zones]

    async def create_tunnel(self, account_id: str, name: str):
        try:
            return await self.client.zero_trust.tunnels.create(
                account_id=account_id,
                name=name,
                config_src="local"
            )
        except Exception as e:
            if "already exists" in str(e).lower():
                tunnels = await self.client.zero_trust.tunnels.list(account_id=account_id, name=name)
                async for t in tunnels:
                    if t.name == name:
                        return t
            raise e

    async def create_dns_record(self, zone_id: str, name: str, tunnel_id: str):
        content = f"{tunnel_id}.cfargotunnel.com"
        try:
            return await self.client.dns.records.create(
                zone_id=zone_id,
                name=name,
                type="CNAME",
                content=content,
                proxied=True
            )
        except Exception as e:
            if "already exists" in str(e).lower() or "81057" in str(e):
                records = await self.client.dns.records.list(zone_id=zone_id, name=name)
                async for record in records:
                    if record.name.startswith(name):
                        return await self.client.dns.records.update(
                            dns_record_id=record.id,
                            zone_id=zone_id,
                            name=name,
                            type="CNAME",
                            content=content,
                            proxied=True
                        )
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
        zones = await manager.client.zones.list(name=domain_name)
        zone_id = None
        async for zone in zones:
            zone_id = zone.id
            break
        if not zone_id:
            logger.error(f"Zone not found for domain: {domain_name}")
            return None
        # 3. Create the Tunnel
        logger.info(f"Creating Cloudflare tunnel: {tunnel_name}")
        tunnel = await manager.create_tunnel(account_id, tunnel_name)
        # 4. Create the CNAME Record
        logger.info(f"Creating DNS record: {subdomain}.{domain_name} -> {tunnel.id}.cfargotunnel.com")
        await manager.create_dns_record(zone_id, subdomain, tunnel.id)
        secret = getattr(tunnel, "tunnel_secret", "") or ""
        return tunnel.id, secret
    except Exception as e:
        logger.exception(f"Failed to set up Cloudflare tunnel: {e}")
        return None
