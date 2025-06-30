import logging

from ..models import SavedConfig, SavedKey, SiteStartupMode
from .config import SSL_CERT_FILE, get_config, get_key


def setup_ngrok_tunnel(close: bool = False) -> bool:
    """
    Start a ngrok tunnel at port 8000 using the provided auth key and domain.
    Requirements:
        - TUNNEL_API_KEY must be set.
        - SITE_DOMAIN must be set.

    Args:
        close (bool | optional): If True, disconnect the tunnel after starting. Defaults to False.

    Returns:
        bool: True if the tunnel was successfully started, False otherwise.
    """
    config = get_config()
    tunnel_auth_key = get_key(SavedKey.TUNNEL_API_KEY)
    tunnel_domain = config.get(SavedConfig.SITE_DOMAIN, None)
    if not tunnel_auth_key and not tunnel_domain:
        return False
    try:
        # pylint: disable=import-outside-toplevel
        import ngrok
        # pylint: disable=E1101
        listener = ngrok.forward(8000, authtoken=tunnel_auth_key, domain=tunnel_domain)
        if listener:
            if close:
                ngrok.disconnect()
            return True
        else:
            return False
    except Exception as e:
        logging.error("Failed to start ngrok tunnel. Error: %s", e)
        return False

def check_ssl_certificates_exist() -> bool:
    """
    Check if SSL certificates exist.
    
    Requirements:
        - SSL private key must exist.
        - SITE_DOMAIN must be set.
        - SSL_CERT_FILE must be set.
    
    Returns:
        bool: True if SSL requirements exist, False otherwise.
    """
    config = get_config()
    site_domain = config.get(SavedConfig.SITE_DOMAIN, None)
    return True if (
        get_key(SavedKey.SSL_PRIVATE_KEY)
        and site_domain
        and SSL_CERT_FILE
        ) else False

def check_vapid_keys_exist() -> bool:
    """
    Check if VAPID keys exist.

    Requirements:
        - VAPID private key must exist.
        - VAPID public key must exist.
        - VAPID claims must be set.

    Returns:
        bool: True if VAPID requirements exist, False otherwise.
    """
    config = get_config()
    vapid_public_key = config.get(SavedConfig.VAPID_PUBLIC_KEY, None)
    vapid_subject = config.get(SavedConfig.VAPID_SUBJECT, None)
    return True if (
        get_key(SavedKey.VAPID_PRIVATE_KEY)
        and vapid_subject
        and vapid_public_key
        ) else False

def check_tunnel_requirements_met() -> bool:
    """
    Check if the requirements for the tunnel are met.
    
    Requirements:
        - TUNNEL_PROVIDER must be set.
        - Tunnel API keys must exist.
    
    Returns:
        bool: True if tunnel requirements are met, False otherwise.
    """
    config = get_config()
    tunnel_provider = config.get(SavedConfig.TUNNEL_PROVIDER, None)
    return True if (
        tunnel_provider
        and get_key(SavedKey.TUNNEL_API_KEY)
        ) else False

def startup_mode_requirements_met() -> SiteStartupMode:
    """
    Check if the requirements for the current startup mode are met.
    
    Returns:
        SiteStartupMode: The site startup mode if requirements are met, SETUP otherwise.
    """
    startup_mode = get_config().get(SavedConfig.STARTUP_MODE, None)
    match startup_mode:
        case SiteStartupMode.SETUP:
            return SiteStartupMode.SETUP
        case SiteStartupMode.LOCAL:
            if check_ssl_certificates_exist() and check_vapid_keys_exist():
                return SiteStartupMode.LOCAL
        case SiteStartupMode.TUNNEL:
            if check_vapid_keys_exist() and check_tunnel_requirements_met():
                return SiteStartupMode.TUNNEL
    return SiteStartupMode.SETUP
