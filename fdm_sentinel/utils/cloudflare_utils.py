from typing import Any, Dict, List, Optional

import requests
from ..models import OperatingSystem


class CloudflareAPI:
    def __init__(self, api_token: str, email: Optional[str] = None):
        self.api_token = api_token
        self.email = email
        self.base_url = "https://api.cloudflare.com/client/v4"
        if email:
            self.headers = {
                "X-Auth-Email": email,
                "X-Auth-Key": api_token,
                "Content-Type": "application/json"
            }
        else:
            self.headers = {
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json"
            }

    def _request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        response = requests.request(method, url, headers=self.headers, json=data, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_accounts(self) -> Dict[str, Any]:
        return self._request("GET", "/accounts")

    def get_zones(self, per_page: int = 50) -> Dict[str, Any]:
        return self._request("GET", f"/zones?per_page={per_page}")

    def create_tunnel(self, account_id: str, name: str) -> Dict[str, Any]:
        data = {"name": name, "config_src": "cloudflare"}
        return self._request("POST", f"/accounts/{account_id}/cfd_tunnel", data)

    def update_tunnel_config(self, account_id: str, tunnel_id: str, config: Dict) -> Dict[str, Any]:
        return self._request("PUT", f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/config", config)

    def create_dns_record(self, zone_id: str, tunnel_id: str,
                          name: str, ttl: int = 120) -> Dict[str, Any]:
        data = {
            "type": "CNAME",
            "name": name,
            "content": f"{tunnel_id}.cfargotunnel.com",
            "ttl": ttl,
            "proxied": True
        }
        return self._request("POST", f"/zones/{zone_id}/dns_records", data)

    def create_device_list(self, account_id: str, name: str) -> Dict[str, Any]:
        data = {"name": name, "kind": "device_id_list"}
        return self._request("POST", f"/accounts/{account_id}/gateway/lists", data)

    def add_devices_to_list(self, account_id: str, list_id: str,
                            device_ids: List[str]) -> Dict[str, Any]:
        data = {"items": [{"value": device_id} for device_id in device_ids]}
        return self._request("POST", f"/accounts/{account_id}/gateway/lists/{list_id}/items", data)

    def create_access_app(self, account_id: str, name: str, domain: str,
                          session_duration: str = "24h") -> Dict[str, Any]:
        data = {
            "name": name,
            "domain": domain,
            "session_duration": session_duration
        }
        return self._request("POST", f"/accounts/{account_id}/access/apps", data)

    def create_access_policy(self, account_id: str, app_id: str, name: str,
                             list_id: str) -> Dict[str, Any]:
        data = {
            "name": name,
            "decision": "allow",
            "include": [{"device_id_list": {"list_id": list_id}}],
            "require": []
        }
        return self._request("POST", f"/accounts/{account_id}/access/apps/{app_id}/policies", data)

def setup_tunnel(api_token: str, account_id: str, zone_id: str, tunnel_name: str, domain_name: str, email: Optional[str] = None) -> Dict[str, Any]:
    cf = CloudflareAPI(api_token, email)
    tunnel_response = cf.create_tunnel(account_id, tunnel_name)
    tunnel_id = tunnel_response["result"]["id"]
    tunnel_token = tunnel_response["result"]["token"]
    dns_response = cf.create_dns_record(zone_id, tunnel_id, domain_name)
    return {
        "tunnel_id": tunnel_id,
        "tunnel_token": tunnel_token,
        "dns_record": dns_response["result"]
    }


def setup_warp_access(api_token: str, account_id: str, app_name: str,
                      domain: str, device_ids: List[str],
                      email: Optional[str] = None) -> Dict[str, Any]:
    cf = CloudflareAPI(api_token, email)
    list_response = cf.create_device_list(account_id, f"{app_name} Devices")
    list_id = list_response["result"]["id"]
    cf.add_devices_to_list(account_id, list_id, device_ids)
    app_response = cf.create_access_app(account_id, app_name, domain)
    app_id = app_response["result"]["id"]
    policy_response = cf.create_access_policy(account_id,
                                              app_id,
                                              f"Allow {app_name} Devices",
                                              list_id)
    return {
        "app_id": app_id,
        "list_id": list_id,
        "policy_id": policy_response["result"]["id"]
    }

class CloudflareOSCommands:
    @staticmethod
    def get_install_command(os: OperatingSystem, token: str = "") -> str:
        commands = {
            OperatingSystem.LINUX: (
                "curl -L https://github.com/cloudflare/cloudflared/releases/latest/"
                "download/cloudflared-linux-amd64 -o ~/bin/cloudflared && \ "
                "chmod +x ~/bin/cloudflared"
            ),
            OperatingSystem.MACOS: "brew install cloudflared",
            OperatingSystem.WINDOWS: "winget install --id Cloudflare.cloudflared"
        }
        return commands[os]

    @staticmethod
    def get_authenticate_command(os: OperatingSystem) -> str:
        return "cloudflared tunnel login"

    @staticmethod
    def get_create_tunnel_command(os: OperatingSystem, tunnel_name: str) -> str:
        return f"cloudflared tunnel create {tunnel_name}"

    @staticmethod
    def get_route_dns_command(os: OperatingSystem, tunnel_name: str, hostname: str) -> str:
        return f"cloudflared tunnel route dns {tunnel_name} {hostname}"

    @staticmethod
    def get_start_command(os: OperatingSystem, tunnel_name: str = "", 
                          token: str = "", local_port: int = 8000) -> str:
        base = (
            f"cloudflared tunnel run {tunnel_name}"
            if tunnel_name else
            f"cloudflared tunnel run --token {token} --url http://localhost:{local_port}"
        )
        if os == OperatingSystem.WINDOWS:
            parts = base.split(" ", 1)
            executable = parts[0]
            arguments = parts[1] if len(parts) > 1 else ""
            return f"Start-Process -FilePath '{executable}' -ArgumentList '{arguments}' -NoNewWindow"
        elif os in (OperatingSystem.LINUX, OperatingSystem.MACOS):
            return f"nohup {base} > /tmp/cloudflared_tunnel.log 2>&1 &"
        return f"echo 'Error: Unsupported operating system for start command {os}'"

    @staticmethod
    def get_stop_command(os: OperatingSystem) -> str:
        if os in (OperatingSystem.LINUX, OperatingSystem.MACOS):
            return "pkill cloudflared"
        return "Stop-Process -Name cloudflared"

    @staticmethod
    def get_restart_command(os: OperatingSystem, tunnel_name: str = "",
                            token: str = "", local_port: int = 8000) -> str:
        stop = CloudflareOSCommands.get_stop_command(os)
        start = CloudflareOSCommands.get_start_command(os, tunnel_name, token, local_port)
        return f"{stop} && {start}" if (
            os in (OperatingSystem.LINUX, OperatingSystem.MACOS)) else f"{stop}; {start}"

    @staticmethod
    def get_all_commands(os: OperatingSystem, tunnel_name: str,
                         token: str, local_port: int = 8000) -> Dict[str, str]:
        return {
            "install": CloudflareOSCommands.get_install_command(os, token),
            "authenticate": CloudflareOSCommands.get_authenticate_command(os),
            "create": CloudflareOSCommands.get_create_tunnel_command(os, tunnel_name),
            "route_dns": CloudflareOSCommands.get_route_dns_command(os, tunnel_name, "example.com"),
            "start": CloudflareOSCommands.get_start_command(os, tunnel_name, token, local_port),
            "stop": CloudflareOSCommands.get_stop_command(os),
            "restart": CloudflareOSCommands.get_restart_command(os, tunnel_name, token, local_port)
        }

    @staticmethod
    def get_setup_sequence(os: OperatingSystem, token: str, local_port: int = 8000) -> List[str]:
        seq = [
            CloudflareOSCommands.get_install_command(os, token),
            CloudflareOSCommands.get_authenticate_command(os),
        ]
        seq.append(CloudflareOSCommands.get_start_command(os, "", token, local_port))
        return seq

def get_cloudflare_commands(os: OperatingSystem, tunnel_name: str, token: str, local_port: int = 8000) -> Dict[str, str]:
    return CloudflareOSCommands.get_all_commands(os, tunnel_name, token, local_port)

def get_cloudflare_setup_sequence(os: OperatingSystem, token: str,
                                  local_port: int = 8000) -> List[str]:
    return CloudflareOSCommands.get_setup_sequence(os, token, local_port=local_port)
