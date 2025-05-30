import base64
import logging
import random

import trustme
from cryptography.hazmat.primitives import serialization
from fastapi import APIRouter, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import RedirectResponse
from py_vapid import Vapid

from ..models import (TunnelProvider, TunnelSettings, SavedConfig,
                      VapidSettings, SavedKey, SetupCompletion)
from ..utils.config import (SSL_CA_FILE, SSL_CERT_FILE,
                            store_key, get_config, update_config)
from ..utils.setup_utils import setup_ngrok_tunnel

router = APIRouter()

@router.get("/setup", include_in_schema=False)
async def serve_setup(request: Request):
    from ..app import templates
    return templates.TemplateResponse("setup.html", {
        "request": request
    })

@router.post("/setup/generate-vapid-keys", include_in_schema=False)
async def generate_vapid_keys():
    try:
        vapid = Vapid()
        vapid.generate_keys()
        public_key_raw = vapid.public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint
        )
        public_key = base64.urlsafe_b64encode(public_key_raw).decode('utf-8')
        private_key_raw = vapid.private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        private_key = base64.urlsafe_b64encode(private_key_raw).decode('utf-8')
        return {
            "public_key": public_key,
            "private_key": private_key,
            "subject": "mailto:",
        }
    except Exception as e:
        logging.error("Error generating VAPID keys: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate VAPID keys: {str(e)}"
        )

@router.post("/setup/save-vapid-settings", include_in_schema=False)
async def save_vapid_settings(settings: VapidSettings):
    try:
        domain = settings.base_url
        if domain.startswith(('http://', 'https://')):
            domain = domain.split('://')[1]
        if domain.endswith('/'):
            domain = domain[:-1]

        config_data = {
            SavedConfig.VAPID_PUBLIC_KEY: settings.public_key,
            SavedConfig.VAPID_SUBJECT: settings.subject,
            SavedConfig.SITE_DOMAIN: domain
        }
        store_key(SavedKey.VAPID_PRIVATE_KEY, settings.private_key)
        update_config(config_data)
        return {"success": True}
    except Exception as e:
        logging.error("Error saving VAPID settings: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save VAPID settings: {str(e)}"
        )

@router.post("/setup/generate-ssl-cert", include_in_schema=False)
async def generate_ssl_cert():
    config = get_config()
    try:
        ca = trustme.CA()
        domain = config.get(SavedConfig.SITE_DOMAIN, None)
        if not domain:
            raise HTTPException(status_code=400, 
                                detail="Site domain is not set in the configuration.")
        if domain.startswith(('http://', 'https://')):
            domain = domain.split('://')[1]
        if domain.endswith('/'):
            domain = domain[:-1]
        server_cert = ca.issue_cert(domain)
        with open(SSL_CERT_FILE, "wb") as f:
            f.write(server_cert.cert_chain_pems[0].bytes())
        with open(SSL_CA_FILE, "wb") as f:
            f.write(ca.cert_pem.bytes())
        store_key(SavedKey.SSL_PRIVATE_KEY, server_cert.private_key_pem.bytes().decode('utf-8'))
        logging.debug("SSL certificate and key generated successfully.")
        return {"success": True, "message": "SSL certificate and key saved."}
    except Exception as e:
        logging.error("Error generating SSL certificate: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to generate SSL certificate: {str(e)}")

@router.post("/setup/upload-ssl-cert", include_in_schema=False)
async def upload_ssl_cert(request: Request):
    form = await request.form()
    cert_file = form.get("cert_file")
    key_file = form.get("key_file")
    if not cert_file or not key_file:
        raise HTTPException(status_code=400, detail="Both certificate and key files are required")
    try:
        cert_content = await cert_file.read()
        with open(SSL_CERT_FILE, "wb") as f:
            f.write(cert_content)
        key_content = await key_file.read()
        store_key(SavedKey.SSL_PRIVATE_KEY, key_content.decode('utf-8'))
        logging.debug("SSL certificate and key uploaded successfully.")
        return {"success": True, "message": "SSL certificate and key uploaded successfully."}
    except Exception as e:
        logging.error("Error uploading SSL certificate: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to upload SSL certificate: {str(e)}")

@router.post("/setup/save-tunnel-settings", include_in_schema=False)
async def save_tunnel_settings(settings: TunnelSettings):
    try:
        config_data = {
            SavedConfig.TUNNEL_PROVIDER: settings.provider,
            SavedConfig.SITE_DOMAIN: settings.domain
        }
        if settings.email:
            config_data[SavedConfig.CLOUDFLARE_EMAIL] = settings.email
        store_key(SavedKey.TUNNEL_API_KEY, settings.token)
        update_config(config_data)
        logging.debug("Tunnel settings saved successfully.")
        return {"success": True, "message": "Tunnel settings saved successfully."}
    except Exception as e:
        logging.error("Error saving tunnel settings: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to save tunnel settings: {str(e)}")

@router.post("/setup/initialize-tunnel-provider", include_in_schema=False)
async def initialize_tunnel_provider():
    config = get_config()
    provider = config.get(SavedConfig.TUNNEL_PROVIDER, None)
    site_domain = config.get(SavedConfig.SITE_DOMAIN, None)
    if not provider or not site_domain:
        return RedirectResponse('/setup', status_code=303)
    if provider == TunnelProvider.NGROK:
        if setup_ngrok_tunnel(close=True):
            return {
                "success": True,
                "provider": "Ngrok",
                "url": site_domain,
                "message": "Ngrok tunnel initialized successfully"
                }
        else:
            return {
                "success": False,
                "message": "Failed to initialize Ngrok tunnel. Please check the auth token and domain."
            }
    elif provider == TunnelProvider.CLOUDFLARE:
        # Simulating Cloudflare tunnel initialization
        tunnel_url = f"https://tunnel-{random.randint(1000, 9999)}.example.com"
        return {
            "success": True,
            "provider": "Cloudflare",
            "url": tunnel_url,
            "message": "Cloudflare tunnel initialized successfully"
        }
    return RedirectResponse('/setup', status_code=303)

@router.post("/setup/complete", include_in_schema=False)
async def complete_setup(completion: SetupCompletion):
    try:
        config_data = {
            SavedConfig.STARTUP_MODE: completion.startup_mode
        }
        if completion.tunnel_provider:
            config_data[SavedConfig.TUNNEL_PROVIDER] = completion.tunnel_provider
        update_config(config_data)
        logging.debug("Setup completed successfully with startup mode: %s", completion.startup_mode)
        return {"success": True, "message": "Setup completed successfully"}
    except Exception as e:
        logging.error("Error completing setup: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to complete setup: {str(e)}")
