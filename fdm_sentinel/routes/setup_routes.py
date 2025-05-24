from fastapi import APIRouter, Request
from fastapi.exceptions import HTTPException
from py_vapid import Vapid
import logging
from ..models import VapidSettings
from ..utils.config import save_config
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
            "VAPID_PRIVATE_KEY": settings.private_key,
            "VAPID_SUBJECT": settings.subject,
            "BASE_URL": settings.base_url
        }
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
        server_cert = ca.issue_cert("localhost")
        cert_path = ".cert.pem"
        key_path = ".key.pem"
        with open(key_path, "wb") as f:
            f.write(server_cert.private_key_pem.bytes())
        with open(cert_path, "wb") as f:
            f.write(server_cert.cert_chain_pems[0].bytes())
        ca_cert_path = ".ca.pem"
        with open(ca_cert_path, "wb") as f:
            f.write(ca.cert_pem.bytes())
        logging.info("SSL certificate and key generated: %s, %s", cert_path, key_path)
        return {"success": True, "message": f"SSL certificate and key saved to {cert_path} and {key_path}"}
    except Exception as e:
        logging.error("Error generating SSL certificate: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to generate SSL certificate: {str(e)}")
