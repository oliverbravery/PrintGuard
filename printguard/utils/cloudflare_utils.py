import logging
import subprocess
from typing import Any, Dict, List, Optional

import requests

from ..models import OperatingSystem, SavedConfig, SavedKey
from ..utils.config import get_config


class CloudflareAPI:
    """API client for interacting with Cloudflare API v4 services.
    
    All responses follow the standard Cloudflare API format with 'result', 'success', 
    'errors', 'messages', and optionally 'result_info' fields.
    """

    def __init__(self, api_token: str, email: Optional[str] = None):
        """Initialize the Cloudflare API client.

        Args:
            api_token (str): The API token or key for authentication.
            email (Optional[str]): Email address for legacy authentication (when using API key).
        """
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
        """Make an authenticated request to the Cloudflare API.
        
        Args:
            method (str): HTTP method (GET, POST, etc.).
            endpoint (str): API endpoint to call.
            data (Optional[Dict]): JSON data to send with the request.
            
        Returns:
            Dict[str, Any]: Parsed JSON response from the API.
        """
        url = f"{self.base_url}{endpoint}"
        response = requests.request(method, url, headers=self.headers, json=data, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_accounts(self) -> Dict[str, Any]:
        """Retrieve all accounts accessible with the current API token.
        
        API Documentation: https://developers.cloudflare.com/api/resources/accounts/methods/list/

        Returns:
            Dict[str, Any]: API response containing account information.
        """
        return self._request("GET", "/accounts")

    def get_zones(self, per_page: int = 50) -> Dict[str, Any]:
        """Retrieve DNS zones for the account.

        API Documentation: https://developers.cloudflare.com/api/resources/zones/methods/list/
        
        Args:
            per_page (int): Number of zones to return per page.

        Returns:
            Dict[str, Any]: API response containing zone information.
        """
        return self._request("GET", f"/zones?per_page={per_page}")

    def get_organization(self, account_id: str) -> Dict[str, Any]:
        """Retrieve organization information for an account.

        API Documentation: https://developers.cloudflare.com/api/resources/zero_trust/subresources/organizations/methods/list/

        Args:
            account_id (str): The Cloudflare account ID.

        Returns:
            Dict[str, Any]: API response containing organization data.
        """
        return self._request("GET", f"/accounts/{account_id}/access/organizations")

    def create_tunnel(self, account_id: str, name: str) -> Dict[str, Any]:
        """Create a new Cloudflare tunnel.
        
        API Documentation: https://developers.cloudflare.com/api/resources/zero_trust/subresources/tunnels/subresources/cloudflared/methods/create/

        Args:
            account_id (str): The Cloudflare account ID.
            name (str): Name for the new tunnel.

        Returns:
            Dict[str, Any]: API response containing tunnel details.
        """
        data = {"name": name, "config_src": "cloudflare"}
        return self._request("POST", f"/accounts/{account_id}/cfd_tunnel", data)

    def create_dns_record(self, zone_id: str, tunnel_id: str,
                          name: str, ttl: int = 120) -> Dict[str, Any]:
        """Create a DNS CNAME record pointing to a tunnel.
        
        API Documentation: https://developers.cloudflare.com/api/resources/dns/subresources/records/methods/create/

        Args:
            zone_id (str): The DNS zone ID.
            tunnel_id (str): The tunnel ID to point to.
            name (str): The DNS record name (subdomain).
            ttl (int): Time-to-live for the DNS record in seconds.

        Returns:
            Dict[str, Any]: API response containing DNS record details.
        """
        data = {
            "type": "CNAME",
            "name": name,
            "content": f"{tunnel_id}.cfargotunnel.com",
            "ttl": ttl,
            "proxied": True
        }
        return self._request("POST", f"/zones/{zone_id}/dns_records", data)

class CloudflareOSCommands:
    """Static methods for generating OS-specific cloudflared commands."""

    @staticmethod
    def get_install_command(os: OperatingSystem, token: str = "") -> str:
        """Get the installation command for cloudflared based on the operating system.

        Args:
            os (OperatingSystem): The target operating system.
            token (str): Unused parameter, kept for compatibility.

        Returns:
            str: The shell command to install cloudflared.
        """
        commands = {
            OperatingSystem.LINUX: (
                "curl -L https://github.com/cloudflare/cloudflared/releases/latest/"
                "download/cloudflared-linux-amd64 -o ~/bin/cloudflared && \\ "
                "chmod +x ~/bin/cloudflared"
            ),
            OperatingSystem.MACOS: "brew install cloudflared",
            OperatingSystem.WINDOWS: "winget install --id Cloudflare.cloudflared"
        }
        return commands[os]

    @staticmethod
    def get_authenticate_command(os: OperatingSystem) -> str:
        """Get the command to authenticate cloudflared with Cloudflare.

        Args:
            os (OperatingSystem): The target operating system.

        Returns:
            str: The authentication command.
        """
        return "cloudflared tunnel login"

    @staticmethod
    def get_create_tunnel_command(os: OperatingSystem, tunnel_name: str) -> str:
        """Get the command to create a new tunnel.

        Args:
            os (OperatingSystem): The target operating system.
            tunnel_name (str): Name for the new tunnel.

        Returns:
            str: The tunnel creation command.
        """
        return f"cloudflared tunnel create {tunnel_name}"

    @staticmethod
    def get_route_dns_command(os: OperatingSystem, tunnel_name: str, hostname: str) -> str:
        """Get the command to route DNS to a tunnel.

        Args:
            os (OperatingSystem): The target operating system.
            tunnel_name (str): Name of the tunnel.
            hostname (str): Hostname to route to the tunnel.

        Returns:
            str: The DNS routing command.
        """
        return f"cloudflared tunnel route dns {tunnel_name} {hostname}"

    @staticmethod
    def get_start_command(os: OperatingSystem, tunnel_name: str = "",
                          token: str = "", local_port: int = 8000) -> str:
        """Get the command to start a cloudflared tunnel.

        Args:
            os (OperatingSystem): The target operating system.
            tunnel_name (str): Name of the tunnel to start.
            token (str): Tunnel token for quick start.
            local_port (int): Local port to tunnel from.

        Returns:
            str: The tunnel start command, formatted for the OS.
        """
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
        """Get the command to stop cloudflared tunnels.

        Args:
            os (OperatingSystem): The target operating system.

        Returns:
            str: The tunnel stop command.
        """
        if os in (OperatingSystem.LINUX, OperatingSystem.MACOS):
            return "pkill cloudflared"
        return "Stop-Process -Name cloudflared"

    @staticmethod
    def get_restart_command(os: OperatingSystem, tunnel_name: str = "",
                            token: str = "", local_port: int = 8000) -> str:
        """Get the command to restart cloudflared tunnels.

        Args:
            os (OperatingSystem): The target operating system.
            tunnel_name (str): Name of the tunnel.
            token (str): Tunnel token.
            local_port (int): Local port to tunnel from.

        Returns:
            str: The tunnel restart command.
        """
        stop = CloudflareOSCommands.get_stop_command(os)
        start = CloudflareOSCommands.get_start_command(os, tunnel_name, token, local_port)
        return f"{stop} && {start}" if (
            os in (OperatingSystem.LINUX, OperatingSystem.MACOS)) else f"{stop}; {start}"

    @staticmethod
    def get_all_commands(os: OperatingSystem, tunnel_name: str,
                         token: str, local_port: int = 8000) -> Dict[str, str]:
        """Get all cloudflared commands for the specified OS.

        Args:
            os (OperatingSystem): The target operating system.
            tunnel_name (str): Name of the tunnel.
            token (str): Tunnel token.
            local_port (int): Local port to tunnel from.

        Returns:
            Dict[str, str]: A dictionary mapping command names to shell commands.
                Structure:
                {
                    "install": str,
                    "authenticate": str,
                    "create": str,
                    "route_dns": str,
                    "start": str,
                    "stop": str,
                    "restart": str
                }
        """
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
        """Get the sequence of commands to set up and start a tunnel.

        Args:
            os (OperatingSystem): The target operating system.
            token (str): Tunnel token for quick start.
            local_port (int): Local port to tunnel from.

        Returns:
            List[str]: Ordered list of shell commands to execute.
        """
        seq = [
            CloudflareOSCommands.get_install_command(os, token),
            CloudflareOSCommands.get_authenticate_command(os),
        ]
        seq.append(CloudflareOSCommands.get_start_command(os, "", token, local_port))
        return seq

def get_cloudflare_commands(os: OperatingSystem, tunnel_name: str, token: str, local_port: int = 8000) -> Dict[str, str]:
    """Get all cloudflared commands for the specified OS and configuration.

    Args:
        os (OperatingSystem): The target operating system.
        tunnel_name (str): Name of the tunnel.
        token (str): Tunnel token.
        local_port (int): Local port to tunnel from.

    Returns:
        Dict[str, str]: A dictionary mapping command names to shell commands.
    """
    return CloudflareOSCommands.get_all_commands(os, tunnel_name, token, local_port)

def get_cloudflare_setup_sequence(os: OperatingSystem, token: str,
                                  local_port: int = 8000) -> List[str]:
    """Get the setup sequence for cloudflared on the specified OS.

    Args:
        os (OperatingSystem): The target operating system.
        token (str): Tunnel token for quick start.
        local_port (int): Local port to tunnel from.

    Returns:
        List[str]: Ordered list of shell commands to execute.
    """
    return CloudflareOSCommands.get_setup_sequence(os, token, local_port=local_port)

def setup_tunnel(api_token: str, account_id: str, zone_id: str, 
                 tunnel_name: str, domain_name: str, email: Optional[str] = None) -> Dict[str, Any]:
    """Create a complete tunnel setup including DNS record.

    Args:
        api_token (str): Cloudflare API token.
        account_id (str): Cloudflare account ID.
        zone_id (str): DNS zone ID.
        tunnel_name (str): Name for the new tunnel.
        domain_name (str): Domain name for the DNS record.
        email (Optional[str]): Email for legacy global API authentication.

    Returns:
        Dict[str, Any]: Setup results containing tunnel and DNS information.
            Structure:
            {
                "tunnel_id": str,
                "tunnel_token": str,
                "dns_record": {
                    "id": str,
                    "name": str,
                    ...
                }
            }
    """
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

def get_current_os() -> OperatingSystem:
    """Get the current operating system from configuration.

    Returns:
        OperatingSystem: The stored operating system enum value, or None if not set.
    """
    config = get_config()
    stored_os = config.get(SavedConfig.USER_OPERATING_SYSTEM)
    if stored_os:
        return OperatingSystem(stored_os)

def start_cloudflare_tunnel() -> bool:
    """Start the Cloudflare tunnel using stored configuration.

    Returns:
        bool: True if the tunnel was started successfully, False otherwise.
    """
    # pylint:disable=import-outside-toplevel
    from ..utils.config import get_key
    try:
        current_os = get_current_os()
        if not current_os:
            raise ValueError("Current OS not set in config.")
        tunnel_token = get_key(SavedKey.TUNNEL_TOKEN)
        if not tunnel_token:
            raise ValueError("Tunnel token not found. Please complete tunnel setup first.")
        start_command = CloudflareOSCommands.get_start_command(current_os, "", tunnel_token, 8000)
        logging.debug("Starting Cloudflare tunnel with command: %s", start_command)
        result = subprocess.run(start_command, shell=True,
                             capture_output=True, text=True,
                             timeout=30, check=False)
        if result.returncode == 0:
            logging.debug("Cloudflare tunnel started successfully")
            return True
        else:
            logging.warning("Non-privileged start failed: %s", result.stderr)
            logging.info("User may need to manually run command with elevated privileges")
            return True
    except subprocess.TimeoutExpired:
        logging.error("Timeout starting Cloudflare tunnel")
        return False
    except (OSError, ValueError) as e:
        logging.error("Error starting Cloudflare tunnel: %s", e)
        return False
    except Exception as e:
        logging.error("Unexpected error starting Cloudflare tunnel: %s", e)
        return False

def stop_cloudflare_tunnel() -> bool:
    """Stop the Cloudflare tunnel using stored configuration.

    Returns:
        bool: True if the tunnel was stopped successfully, False otherwise.
    """
    try:
        current_os = get_current_os()
        if not current_os:
            raise ValueError("Current OS not set in config.")
        stop_command = CloudflareOSCommands.get_stop_command(current_os)
        logging.debug("Stopping Cloudflare tunnel with command: %s", stop_command)
        result = subprocess.run(stop_command, shell=True,
                             capture_output=True, text=True,
                             timeout=30, check=False)
        if result.returncode == 0:
            logging.debug("Cloudflare tunnel stopped successfully")
            return True
        else:
            logging.warning("Non-privileged stop failed: %s", result.stderr)
            logging.info("User may need to manually run command with elevated privileges")
            return True
    except subprocess.TimeoutExpired:
        logging.error("Timeout stopping Cloudflare tunnel")
        return False
    except (OSError, ValueError) as e:
        logging.error("Error stopping Cloudflare tunnel: %s", e)
        return False
    except Exception as e:
        logging.error("Unexpected error stopping Cloudflare tunnel: %s", e)
        return False
