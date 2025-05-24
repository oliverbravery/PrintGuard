import os
from fastapi import Request
from fastapi.responses import RedirectResponse
from .config import load_config, VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_SUBJECT, BASE_URL, SSL_CERT_FILE, SSL_KEY_FILE

def has_ssl_certificates():
    return os.path.exists(SSL_CERT_FILE) and os.path.exists(SSL_KEY_FILE)

def has_vapid_keys():
    return bool(VAPID_SUBJECT) and bool(VAPID_PUBLIC_KEY) and bool(VAPID_PRIVATE_KEY)

def is_setup_complete():
    load_config()
    return has_ssl_certificates() and has_vapid_keys() and bool(BASE_URL)

async def verify_setup_complete(request: Request):
    setup_routes = ['/setup', '/setup/', '/static/']
    setup_api_routes = ['/setup/generate-vapid-keys', '/setup/save-vapid-settings', 
                       '/setup/generate-ssl-cert', '/setup/upload-ssl-cert', '/setup/complete']
    if (any(request.url.path.startswith(route) for route in setup_routes) or
        request.url.path in setup_api_routes):
        return None
    if not is_setup_complete():
        return RedirectResponse('/setup', status_code=303)
    return None
