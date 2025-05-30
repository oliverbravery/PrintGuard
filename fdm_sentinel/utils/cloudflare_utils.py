from typing import Any, Dict, List, Optional

import requests


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
