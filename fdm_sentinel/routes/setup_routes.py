from fastapi import APIRouter, Request
from fastapi.exceptions import HTTPException
from py_vapid import Vapid
import logging
from ..models import VapidSettings
from ..utils.config import (
    save_config, BASE_URL, SSL_CERT_FILE, SSL_CA_FILE,
    store_vapid_private_key, store_ssl_private_key
)
import trustme
from cryptography.hazmat.primitives import serialization
import base64

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
        config_data = {
            "VAPID_PUBLIC_KEY": settings.public_key,
            "VAPID_SUBJECT": settings.subject,
            "BASE_URL": settings.base_url
        }
        store_vapid_private_key(settings.private_key)
        save_config(config_data)
        return {"success": True}
    except Exception as e:
        logging.error("Error saving VAPID settings: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save VAPID settings: {str(e)}"
        )

@router.post("/setup/generate-ssl-cert", include_in_schema=False)
async def generate_ssl_cert():
    try:
        ca = trustme.CA()
        domain = BASE_URL
        if domain.startswith(('http://', 'https://')):
            domain = domain.split('://')[1]
        if domain.endswith('/'):
            domain = domain[:-1]
        server_cert = ca.issue_cert(domain)
        with open(SSL_CERT_FILE, "wb") as f:
            f.write(server_cert.cert_chain_pems[0].bytes())
        with open(SSL_CA_FILE, "wb") as f:
            f.write(ca.cert_pem.bytes())
        store_ssl_private_key(server_cert.private_key_pem.bytes().decode('utf-8'))
        logging.debug("SSL certificate and key generated successfully.")
        return {"success": True, "message": "SSL certificate and key saved."}
    except Exception as e:
        logging.error("Error generating SSL certificate: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to generate SSL certificate: {str(e)}")
