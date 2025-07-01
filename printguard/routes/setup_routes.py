import base64
import logging

import trustme
from cryptography.hazmat.primitives import serialization
from fastapi import APIRouter, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import RedirectResponse
from py_vapid import Vapid

from ..models import (TunnelProvider, TunnelSettings, SavedConfig,
                      VapidSettings, SavedKey, SetupCompletion,
                      CloudflareTunnelConfig, CloudflareDownloadConfig)
from ..utils.config import (SSL_CA_FILE, SSL_CERT_FILE,
                            store_key, get_config, update_config, get_key)
from ..utils.setup_utils import setup_ngrok_tunnel
from ..utils.cloudflare_utils import CloudflareAPI, get_cloudflare_setup_sequence

router = APIRouter()

@router.get("/setup", include_in_schema=False)
async def serve_setup(request: Request):
    """Serve the setup page for initial application configuration.

    Args:
        request (Request): The FastAPI request object.

    Returns:
        TemplateResponse: Rendered setup.html template for configuration.
    """
    # pylint:disable=import-outside-toplevel
    from ..app import templates
    return templates.TemplateResponse("setup.html", {
        "request": request
    })

@router.post("/setup/generate-vapid-keys", include_in_schema=False)
async def generate_vapid_keys():
    """Generate new VAPID key pair for push notification authentication.

    Returns:
        dict: Generated VAPID public key, private key, and default subject.

    Raises:
        HTTPException: If key generation fails due to cryptographic errors.
    """
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
    """Save VAPID settings for push notification configuration.

    Args:
        settings (VapidSettings): VAPID configuration including public key,
                                 private key, subject, and base URL.

    Returns:
        dict: Success status indicating settings were saved.

    Raises:
        HTTPException: If saving VAPID settings fails due to validation or storage errors.
    """
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
    """Generate self-signed SSL certificate for HTTPS communication.

    Returns:
        dict: Success status and message indicating certificate was generated.

    Raises:
        HTTPException: If SSL certificate generation fails or domain is not configured.
    """
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
    """Upload custom SSL certificate and key files.

    Args:
        request (Request): The FastAPI request object containing uploaded files.

    Returns:
        dict: Success status and message indicating certificate was uploaded.

    Raises:
        HTTPException: If both certificate and key files are not provided or upload fails.
    """
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
    """Save tunnel configuration settings for external access.

    Args:
        settings (TunnelSettings): Tunnel configuration including provider and API key.

    Returns:
        dict: Success status indicating tunnel settings were saved.

    Raises:
        HTTPException: If saving tunnel settings fails due to validation or storage errors.
    """
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

@router.post("/setup/initialize-ngrok-tunnel", include_in_schema=False)
async def initialize_ngrok_tunnel():
    """Initialize and start an ngrok tunnel for external access.

    Returns:
        RedirectResponse: Redirect to setup page after tunnel initialization.

    Raises:
        HTTPException: If tunnel provider or domain is not configured, or ngrok setup fails.
    """
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
    return RedirectResponse('/setup', status_code=303)

@router.post("/setup/complete", include_in_schema=False)
async def complete_setup(completion: SetupCompletion):
    """Complete the initial setup process and mark configuration as finished.

    Args:
        completion (SetupCompletion): Setup completion status and configuration.

    Returns:
        dict: Success status indicating setup was completed successfully.

    Raises:
        HTTPException: If completing setup fails due to configuration errors.
    """
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

@router.get("/setup/cloudflare/accounts-zones", include_in_schema=False)
async def get_cloudflare_accounts_zones():
    """Retrieve Cloudflare accounts and zones for tunnel configuration.

    Returns:
        dict: Available Cloudflare accounts and zones for domain setup.

    Raises:
        HTTPException: If API key is invalid or Cloudflare API request fails.
    """
    try:
        config = get_config()
        api_token = get_key(SavedKey.TUNNEL_API_KEY)
        email = config.get(SavedConfig.CLOUDFLARE_EMAIL)
        if not api_token:
            raise HTTPException(
                status_code=400,
                detail="Cloudflare API token not found. Please configure tunnel settings first."
            )
        cf = CloudflareAPI(api_token, email)
        accounts_response = cf.get_accounts()
        accounts = accounts_response.get("result", [])
        zones_response = cf.get_zones()
        zones = zones_response.get("result", [])
        return {
            "success": True,
            "accounts": accounts,
            "zones": zones
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.error("Error fetching Cloudflare accounts and zones: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch Cloudflare accounts and zones: {str(e)}"
        )

@router.post("/setup/cloudflare/create-tunnel", include_in_schema=False)
async def create_cloudflare_tunnel(config: CloudflareTunnelConfig):
    """Create a new Cloudflare tunnel with specified configuration.

    Args:
        config (CloudflareTunnelConfig): Tunnel configuration including account,
                                       zone, subdomain, and tunnel name.

    Returns:
        dict: Success status and tunnel creation details.

    Raises:
        HTTPException: If tunnel creation fails due to API errors or invalid configuration.
    """
    try:
        api_token = get_key(SavedKey.TUNNEL_API_KEY)
        cf_config = get_config()
        email = cf_config.get(SavedConfig.CLOUDFLARE_EMAIL)
        if not api_token:
            raise HTTPException(
                status_code=400,
                detail="Cloudflare API token not found"
            )
        cf = CloudflareAPI(api_token, email)
        tunnel_name = config.subdomain
        tunnel_response = cf.create_tunnel(config.account_id, tunnel_name)
        tunnel_id = tunnel_response["result"]["id"]
        tunnel_token = tunnel_response["result"]["token"]
        zones_response = cf.get_zones()
        zone_name = next((z["name"] for z in zones_response["result"] if (
            z["id"] == config.zone_id)), "")
        tunnel_url = f"{config.subdomain}.{zone_name}"
        _ = cf.create_dns_record(config.zone_id, tunnel_id, config.subdomain)
        store_key(SavedKey.TUNNEL_TOKEN, tunnel_token)
        return {
            "success": True,
            "url": tunnel_url,
            "tunnel_token": tunnel_token
        }
    except Exception as e:
        logging.error(
            "Error creating Cloudflare tunnel. Ensure the DNS record and tunnel do not already exist: %s",
            e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create Cloudflare tunnel: {str(e)}"
        )

@router.post("/setup/cloudflare/save-os", include_in_schema=False)
async def save_cloudflare_os(config: CloudflareDownloadConfig):
    """Save operating system selection for Cloudflare tunnel client download.

    Args:
        config (CloudflareDownloadConfig): Operating system configuration for
                                         tunnel client download.

    Returns:
        dict: Success status indicating OS selection was saved.

    Raises:
        HTTPException: If saving OS configuration fails.
    """
    try:
        update_config({SavedConfig.USER_OPERATING_SYSTEM: config.operating_system})
        cf_config = get_config()
        site_domain = cf_config.get(SavedConfig.SITE_DOMAIN)
        tunnel_token_from_store = get_key(SavedKey.TUNNEL_TOKEN)
        processed_tunnel_token = ""
        if not site_domain:
            raise HTTPException(
                status_code=400,
                detail="Site domain not found. Please complete tunnel setup first for automatic flow."
            )
        if not tunnel_token_from_store or not tunnel_token_from_store.strip():
            raise HTTPException(
                status_code=400,
                detail="Tunnel token not found or is invalid. Please complete tunnel setup first for automatic flow."
            )
        processed_tunnel_token = tunnel_token_from_store.strip()
        setup_commands = get_cloudflare_setup_sequence(
            config.operating_system,
            processed_tunnel_token,
            8000
        )
        return {
            "success": True,
            "tunnel_token": processed_tunnel_token,
            "operating_system": config.operating_system,
            "setup_commands": setup_commands
        }
    except Exception as e:
        logging.error("Error saving operating system selection: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save operating system selection: {str(e)}"
        )

@router.get("/setup/cloudflare/add-device", include_in_schema=False)
async def serve_cloudflare_add_device(request: Request):
    """Serve the Cloudflare device addition page for tunnel setup.

    Args:
        request (Request): The FastAPI request object.

    Returns:
        TemplateResponse: Rendered cloudflare_setup.html template with setup instructions.

    Raises:
        HTTPException: If tunnel configuration is incomplete or template rendering fails.
    """
    try:
        # pylint:disable=import-outside-toplevel
        from ..app import templates
        config = get_config()
        site_domain = config.get(SavedConfig.SITE_DOMAIN, "")
        return templates.TemplateResponse("warp_device_enrollment.html", {
            "request": request,
            "site_domain": site_domain
        })
    except Exception as e:
        logging.error("Error serving WARP device enrollment page: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to serve WARP device enrollment page: {str(e)}"
        )

@router.get("/setup/cloudflare/organisation", include_in_schema=False)
async def get_cloudflare_organisation(request: Request):
    """Get Cloudflare organization information for tunnel configuration.

    Args:
        request (Request): The FastAPI request object for client validation.

    Returns:
        dict: Cloudflare organization details and configuration options.

    Raises:
        HTTPException: If access is not from localhost or API request fails.
    """
    client_host = request.client.host if request.client else "unknown"
    if client_host not in ["127.0.0.1", "localhost", "::1"]:
        raise HTTPException(
            status_code=403,
            detail="This endpoint is only accessible from localhost"
        )
    try:
        config = get_config()
        api_token = get_key(SavedKey.TUNNEL_API_KEY)
        email = config.get(SavedConfig.CLOUDFLARE_EMAIL)
        site_domain = config.get(SavedConfig.SITE_DOMAIN, "")
        if not api_token:
            raise HTTPException(
                status_code=400,
                detail="Cloudflare API token not found. Please complete tunnel setup first."
            )
        cf = CloudflareAPI(api_token, email)
        accounts_response = cf.get_accounts()
        accounts = accounts_response.get("result", [])
        if not accounts:
            raise HTTPException(
                status_code=400,
                detail="No Cloudflare accounts found"
            )
        account_id = accounts[0]["id"]
        try:
            org_response = cf.get_organization(account_id)
            org_result = org_response.get("result")
            if org_result:
                team_name = org_result.get("name", "your-organization")
                return {
                    "success": True,
                    "team_name": team_name,
                    "site_domain": site_domain
                }
            else:
                return {
                    "success": False,
                    "team_name": "your-organization",
                    "site_domain": site_domain
                }
        except Exception as api_error:
            logging.warning("Could not fetch team name from Cloudflare API: %s", api_error)
            return {
                "success": False,
                "team_name": "your-organization",
                "site_domain": site_domain
            }
    except Exception as e:
        logging.error("Error fetching Cloudflare team name: %s", e)
        return {
            "success": False,
            "team_name": "your-organization",
            "site_domain": ""
        }
