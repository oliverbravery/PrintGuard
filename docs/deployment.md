# Deploying a hub securely

A hub exposes everything a browser needs — dashboard, engine socket, live video and
device publishing — on a single HTTP port, `:8000`. The streaming server is built into the
same image and listens on `:8554`/`:1935` only so LAN cameras can push streams in (its
control API and HLS muxer bind to localhost inside the container); nothing else needs to be
reachable. PrintGuard ships **no authentication**: anyone who can reach `:8000` sees every
camera and can pause or cancel your printers. Never port-forward it from the internet — put
one of the following in front instead. Each one carries full functionality, live video
included, because video is plain HTTP through the same port.

## Option 1 — Tailscale (recommended for private hubs)

Private access for you and people you invite; nothing is reachable from the public
internet. Authentication is your tailnet identity.

1. Install [Tailscale](https://tailscale.com/download) on the hub machine and your
   devices, and `tailscale up` on each.
2. Open `http://<hub-machine-name>:8000` from any device on the tailnet. Invite others
   from the Tailscale admin console if they should have access.
3. For HTTPS — which browsers require before they allow camera access, so it is needed
   for local mode and "this device" publishing from phones:

   ```bash
   sudo tailscale serve --bg --https=443 8000
   ```

   Then open `https://<hub-machine-name>.<tailnet>.ts.net`.

## Option 2 — Cloudflare Tunnel + Access

A public HTTPS URL with no open ports on your network; every request (including the
WebSockets and video) must pass a Cloudflare Access policy first.

1. In [Zero Trust](https://one.dash.cloudflare.com) → Networks → Tunnels, create a
   tunnel and copy its token, then add the connector to `docker-compose.yaml`:

   ```yaml
     cloudflared:
       image: cloudflare/cloudflared:latest
       restart: unless-stopped
       command: tunnel run --token ${TUNNEL_TOKEN}
   ```

2. Give the tunnel a public hostname (e.g. `hub.example.com`) pointing at
   `http://printguard:8000`.
3. In Zero Trust → Access → Applications, add a self-hosted application for that
   hostname with a policy such as *Allow → Emails →* the people you trust. Visitors now
   authenticate (email code or your SSO) before anything reaches PrintGuard.
4. If the host machine sits on a network you don't fully trust, also bind the local
   ports so only the tunnel can reach the app: `"127.0.0.1:8000:8000"`.

## Option 3 — oauth2-proxy on your own domain

For a hub behind a reverse proxy you manage —
[oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/) authenticates against
GitHub/Google/any OIDC provider and proxies everything, WebSockets included, to
PrintGuard:

```yaml
  oauth2-proxy:
    image: quay.io/oauth2-proxy/oauth2-proxy:latest
    restart: unless-stopped
    command:
      - --http-address=0.0.0.0:4180
      - --upstream=http://printguard:8000
      - --provider=github
      - --github-user=your-github-username
      - --email-domain=*
      - --redirect-url=https://hub.example.com/oauth2/callback
      - --cookie-secure=true
      - --reverse-proxy=true
    environment:
      OAUTH2_PROXY_CLIENT_ID: "…"
      OAUTH2_PROXY_CLIENT_SECRET: "…"
      OAUTH2_PROXY_COOKIE_SECRET: "…"   # openssl rand -base64 32 | tr -- '+/' '-_'
    ports:
      - "4180:4180"
```

Terminate TLS in front with Caddy or nginx (or a Cloudflare Tunnel pointed at `:4180`),
and bind PrintGuard's own port to localhost so the proxy is the only way in.

The hub rejects any WebSocket whose `Origin` is not its own — the auth proxy checks the
session cookie, which the browser also attaches to sockets opened by other sites, so this
is what stops a logged-in user's other tabs from driving the engine. It recognises the
dashboard automatically when the proxy preserves the `Host` or sends `X-Forwarded-Host`
(Tailscale, Cloudflare and oauth2-proxy all do). If yours rewrites the host, list your
public origin so the hub trusts it:

```yaml
    environment:
      PRINTGUARD_ORIGINS: "https://hub.example.com"   # comma-separate several
```

## Hardening checklist

- No router port-forwards for `8000`, `8554` or `1935`.
- There are no per-user roles: anyone who authenticates sees every camera and can control
  every printer. Only let in people you would hand the printer to.
- The streaming server's control API (`:9997`) and HLS muxer (`:8888`) bind to `127.0.0.1`
  inside the container, so they stay unreachable from outside even if a port is published —
  the hub talks to them over loopback and proxies HLS out through `:8000`.
- When a proxy on the same host is the only intended client, bind ports to
  `127.0.0.1:…` in the compose file.
- WebSocket handshakes are origin-checked, so the auth proxy is not relied on to block
  cross-site sockets. Set `PRINTGUARD_ORIGINS` only if your proxy rewrites the host header.
- Update with `docker compose pull && docker compose up -d` — `latest` moves on every
  release.
