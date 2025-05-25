import os
from fastapi import Request
from fastapi.responses import RedirectResponse
from .config import (load_config,
                     VAPID_PUBLIC_KEY,
                     VAPID_SUBJECT,
                     SSL_CERT_FILE,
                     TUNNEL_PROVIDER,
                     SITE_DOMAIN,
                     get_tunnel_api_key,
                     get_vapid_private_key,
                     get_ssl_private_key)

def has_ssl_certificates():
    return os.path.exists(SSL_CERT_FILE) and bool(get_ssl_private_key())

def has_vapid_keys():
    return bool(VAPID_SUBJECT) and bool(VAPID_PUBLIC_KEY) and bool(get_vapid_private_key())

def is_setup_complete():
    load_config()
    if TUNNEL_PROVIDER:
        return has_vapid_keys() and bool(SITE_DOMAIN) and bool(get_tunnel_api_key())
    else:
        return has_ssl_certificates() and has_vapid_keys() and bool(SITE_DOMAIN)

async def verify_setup_complete(request: Request):
    setup_routes = ['/setup', '/setup/', '/static/']
    setup_api_routes = ['/setup/generate-vapid-keys', '/setup/save-vapid-settings', 
                       '/setup/generate-ssl-cert', '/setup/upload-ssl-cert', '/setup/complete',
                       '/setup/save-tunnel-settings', '/setup/initialize-tunnel-provider']
    if (any(request.url.path.startswith(route) for route in setup_routes) or
        request.url.path in setup_api_routes):
        return None
    if not is_setup_complete():
        return RedirectResponse('/setup', status_code=303)
    return None

def setup_ngrok_tunnel():
    tunnel_auth_key = get_tunnel_api_key()
    tunnel_domain = SITE_DOMAIN
    if not tunnel_auth_key and not tunnel_domain:
        return False
    try:
        # pylint: disable=import-outside-toplevel
        import ngrok
        # pylint: disable=E1101
        listener = ngrok.forward(8000, authtoken=tunnel_auth_key, domain=tunnel_domain)
        if listener:
            # pylint: disable=E1101
            ngrok.disconnect()
            return True
        else:
            return False
    except Exception as e:
        return False
