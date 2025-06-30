# Setup Documentation
> This is the technical documentation for PrintGuard's setup process, if you are looking for guides on how to install and use PrintGuard, please refer to the [README](../README.md).

## Table of Contents
- [Network Configuration](#network-configuration)
  - [Local Network](#local-network)
  - [External Access](#external-access)
    - [Ngrok](#ngrok)
    - [Cloudflare](#cloudflare)
- [VAPID Keys Setup](#vapid-keys-setup)
- [SSL Certificate Setup](#ssl-certificate-setup)
- [Startup Process](#startup-process)

## Network Configuration
PrintGuard can run in two modes:

### Local Network
- Runs the FastAPI server on `https://localhost:8000`.
- No external access required.
- Recommended for secure LAN-only deployments.
- Requires SSL certificate and VAPID keys, generated during setup.

### External Access
External access allows you to expose PrintGuard outside your local network.

#### Ngrok
[Ngrok](https://ngrok.com) is a reverse proxy tool, enabling secure internet access to your local server with minimal configuration through both free and paid plans. The setup uses your ngrok API to create and configure tunnels via the official [ngrok python package](https://pypi.org/project/ngrok/).
1. Obtain an Ngrok authtoken from https://dashboard.ngrok.com/get-started/your-authtoken
2. In the setup UI, select **Ngrok** and enter your authtoken and desired subdomain (e.g., `myprintguard`).
3. The token is stored securely using the system keyring under the service `printguard` and key `TUNNEL_API_KEY`.
4. The domain (e.g., `myprintguard.ngrok.io`) is saved in the JSON config file (`~/.config/printguard/config.json`) under `SITE_DOMAIN`.
5. The setup code uses `ngrok.forward(8000, authtoken=<token>, domain=<domain>)` to establish the tunnel.

#### Cloudflare
[Cloudflare tunnels](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) provide a secure way to expose your local web interface to the internet,  offering a reliable and secure connection without needing to open ports on your router. Cloudflare tunnels are free to use and offer a simple setup process; however, a domain connected to your Cloudflare account is required. Restricted access to your PrintGuard site can be set up through [Cloudflare Access](https://one.dash.cloudflare.com/) (configurable at setup). During setup, your API key is used to create a tunnel to your local server and insert a DNS record for the tunnel, allowing you to access your PrintGuard instance via your custom domain or subdomain.

1. Create a Cloudflare account and obtain an API Token with *Tunnel* and *DNS:Edit* permissions.
2. In the setup UI, select **Cloudflare**, enter your API token, and check **Use Global API Key** if desired.
3. The token is stored securely via keyring under key `TUNNEL_API_KEY` and optional `CLOUDFLARE_EMAIL` in config.
4. The setup contacts Cloudflare API (`CloudflareAPI` in [`printguard/utils/cloudflare_utils.py`](../printguard/utils/cloudflare_utils.py)) to list accounts and zones.
5. Select an account, zone, and subdomain (e.g., `printguard.example.com`).
6. A Cloudflare Tunnel is created via `/api/tunnels` endpoint; the tunnel token returned is stored under key `TUNNEL_TOKEN` in the keyring.
7. A DNS CNAME record is created pointing your subdomain to the tunnel using the Cloudflare API.
8. The final domain is saved as `SITE_DOMAIN` in `config.json`.

## VAPID Keys Setup
PrintGuard uses Web Push notifications.
1. In the setup UI, generate or import existing VAPID keys. 
   - If generating, the keys are created using the [py_vapid library](https://pypi.org/project/py_vapid/).
   - If importing, the public key must be in base64 format.
2. Public key, subject (`mailto:`) and private key:
   - Public and subject stored in `config.json` under `VAPID_PUBLIC_KEY` and `VAPID_SUBJECT`.
   - Private key stored in keyring under key `VAPID_PRIVATE_KEY`.

## SSL Certificate Setup
HTTPS is required for secure web push and SSE.
1. Generate a self-signed certificate using `trustme.CA()` and `issue_cert(domain)`. The [trustme library](https://pypi.org/project/trustme/) is used to give a fake certificate authority (CA) and issue trusted SSL certificates on your local machine.
   - Alternatively, import an existing certificate and private key.
2. In the setup UI, click **Generate Self-Signed Certificate** or import your own.
3. Certificate is saved to in the app directory as `cert.pem` (`SSL_CERT_FILE`).
4. Private key is stored in keyring under `SSL_PRIVATE_KEY`.
5. On startup, FastAPI loads these files for TLS.

## Startup Process
When you execute `printguard`, the application follows these steps to determine how to launch the server:

1. **Initialize configuration**: `init_config()` creates or loads the JSON config file stored in the application data directory and ensures default values.
2. **Determine startup mode**: `startup_mode_requirements_met()` inspects `config.json` and keyring entries to select one of these startup modes:
   - `SETUP`: missing required keys or certificates → launch the setup UI at `http://localhost:8000/setup`.
   - `LOCAL`: all SSL and VAPID requirements met → start FastAPI with HTTPS on port 8000 using `SSL_CERT_FILE` and the key from keyring.
   - `TUNNEL`: VAPID keys and tunnel credentials exist → continue to tunnel provider logic.
3. **Ngrok tunnel** (_if `TUNNEL_PROVIDER` is NGROK_):
   - Calls `setup_ngrok_tunnel()` to forward port 8000 to your custom `SITE_DOMAIN` through the ngrok package.
   - On success, runs Uvicorn normally; on failure, resets `STARTUP_MODE` to `SETUP` and restarts.
4. **Cloudflare tunnel** (_if `TUNNEL_PROVIDER` is CLOUDFLARE_):
   - Executes `stop_cloudflare_tunnel()` to clear any previous session.
   - Uses `start_cloudflare_tunnel()` to invoke `cloudflared` on your OS (brew, curl, or winget commands) using the stored tunnel credentials.
   - On failure, resets `STARTUP_MODE` to `SETUP` and restarts.
5. **Final launch**: Uvicorn serves the app at `0.0.0.0:8000`, secured by HTTPS for LOCAL or routed through the external domain for TUNNEL modes.

This logic ensures the server automatically falls back to setup if any required credentials, certificates, or tunnels are missing or fail to start.