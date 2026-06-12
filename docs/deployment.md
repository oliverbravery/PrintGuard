# Deploying a hub securely

A hub exposes the dashboard and engine socket on `:8000` and MediaMTX on `:8554`/`:1935`
(stream ingest), `:8889` (WebRTC negotiation) and `:8189/udp` (WebRTC media). PrintGuard
ships **no authentication**: anyone who can reach `:8000` sees every camera and can pause
or cancel your printers. Never port-forward these from the internet — put one of the
following in front instead.

Live video is WebRTC, and its UDP media can ride a VPN
but **cannot traverse an HTTP tunnel or reverse proxy**. So a VPN gives you everything;
an HTTP auth layer gives you everything except remote live playback.

## Option 1 — Tailscale (recommended)

Private access for you and people you invite, with full functionality — live video
included, because the tailnet is a (WireGuard) VPN. Authentication is your tailnet
identity; nothing is reachable from the public internet.

1. Install [Tailscale](https://tailscale.com/download) on the hub machine and your
   devices, and `tailscale up` on each.
2. Open `http://<hub-machine-name>:8000` from any device on the
   tailnet. Invite others from the Tailscale admin console if they should have access.
3. For HTTPS — which browsers require before they allow camera access, so it is needed
   for local mode and "this device" publishing from phones — serve both the app and the
   WebRTC endpoint over the tailnet with TLS:

   ```bash
   sudo tailscale serve --bg --https=443 8000
   sudo tailscale serve --bg --https=8889 8889
   ```

   and let MediaMTX advertise the hub's tailnet address for the media path, in
   [`mediamtx.yml`](../mediamtx.yml):

   ```yaml
   webrtcAdditionalHosts: [100.x.y.z]   # tailscale ip -4
   ```

   Then open `https://<hub-machine-name>.<tailnet>.ts.net`.

## Option 2 — Cloudflare Tunnel + Access

A public HTTPS URL with no open ports on your network; every request (including the
WebSocket) must pass a Cloudflare Access policy first.

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

**Caveat:** WebRTC media cannot traverse the tunnel, so remote visitors get monitoring,
scores, alerts, snapshots and printer control — but live playback stays black, and
publishing a remote device's camera won't work. On the LAN everything still plays
directly. If remote live view matters, use Tailscale instead (or as well).

## Option 3 — oauth2-proxy on your own domain

For a hub behind a reverse proxy you manage —
[oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/) authenticates against
GitHub/Google/any OIDC provider and proxies everything, WebSocket included, to
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
and bind PrintGuard's own port to localhost so the proxy is the only way in. The WebRTC
caveat from Option 2 applies; do **not** "fix" it by exposing `:8889`/`:8189` publicly —
WHEP has no authentication, so that would let anyone watch your cameras by guessing path
names.

## Hardening checklist

- No router port-forwards for `8000`, `8554`, `1935`, `8889` or `8189`.
- There are no per-user roles: anyone who authenticates sees every camera and can control
  every printer. Only let in people you would hand the printer to.
- The MediaMTX API (`:9997`) is deliberately not published by the compose file — it can
  add and remove streams, so keep it inside the compose network.
- When a proxy on the same host is the only intended client, bind ports to
  `127.0.0.1:…` in the compose file.
- Update with `docker compose pull && docker compose up -d` — `latest` moves on every
  release.
