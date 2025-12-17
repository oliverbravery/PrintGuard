#!/bin/bash
set -e

# Check if cloudflared is needed and not already installed
if [ "$TUNNEL_PROVIDER" = "cloudflare" ]; then
    if ! command -v cloudflared &> /dev/null; then
        echo "Cloudflare tunnel provider selected. Installing cloudflared..."
        ARCH=$(dpkg --print-architecture)
        TEMP_DEB="$(mktemp).deb"
        if curl -L --output "$TEMP_DEB" "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb"; then
            dpkg -i "$TEMP_DEB"
            rm "$TEMP_DEB"
            echo "cloudflared installed successfully."
        else
            echo "Failed to download cloudflared. Tunnel setup may fail."
            rm -f "$TEMP_DEB"
        fi
    else
        echo "cloudflared is already installed."
    fi
fi

# Execute the main command
exec "$@"
