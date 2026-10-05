#!/usr/bin/env bash
# Builds the PrintGuard desktop app for the host OS: builds the web UI, fetches
# MediaMTX, generates a platform icon, runs PyInstaller, and packages the result
# as a .dmg (macOS) or .zip (Windows) under dist/. The desktop app targets macOS
# and Windows; Linux is served by the container image. Run after `uv sync`.
# On macOS, APPLE_SIGNING_IDENTITY signs the app and disk image, and APPLE_API_KEY
# (with APPLE_API_KEY_ID and APPLE_API_ISSUER) notarises the disk image.
set -euo pipefail

MEDIAMTX_VERSION=1.18.2
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
rm -rf dist build/desktop build/pyinstaller
mkdir -p build/desktop

(cd web && npm ci && npm run build)

case "$(uname -m)" in
  arm64 | aarch64) ARCH=arm64 ;;
  *) ARCH=amd64 ;;
esac
case "$(uname -s)" in
  Darwin) OS=darwin; MTX_EXT=tar.gz; MTX_BIN=mediamtx; LABEL="macos-${ARCH}" ;;
  MINGW* | MSYS* | CYGWIN* | Windows_NT) OS=windows; ARCH=amd64; MTX_EXT=zip; MTX_BIN=mediamtx.exe; LABEL="windows-x64" ;;
  *) echo "the desktop app targets macOS and Windows only; use the Docker image on Linux" >&2; exit 1 ;;
esac

mtx="mediamtx_v${MEDIAMTX_VERSION}_${OS}_${ARCH}.${MTX_EXT}"
case "$mtx" in
  mediamtx_v1.18.2_darwin_arm64.tar.gz) MTX_SHA256=6a9273ae22a9d0ba85d00d03fdd1b13b9eeaf129ea8b90999ec746367f20449a ;;
  mediamtx_v1.18.2_darwin_amd64.tar.gz) MTX_SHA256=d0f9b2f67da6bbed0b8e01d6baea07d9e5e9b2b617d6c421fc9b1a98d232bfca ;;
  mediamtx_v1.18.2_windows_amd64.zip) MTX_SHA256=945ab46c5fc6d2802ad18e2f1d7e49245ca5609657d85e310aa6eda4cdd72eec ;;
  *) echo "no pinned checksum for ${mtx}, add it from the release's checksums.sha256" >&2; exit 1 ;;
esac
curl -fsSL -o "build/desktop/${mtx}" \
  "https://github.com/bluenviron/mediamtx/releases/download/v${MEDIAMTX_VERSION}/${mtx}"
[ "$(openssl dgst -sha256 -r "build/desktop/${mtx}" | cut -d' ' -f1)" = "$MTX_SHA256" ] \
  || { echo "${mtx} does not match its pinned checksum" >&2; exit 1; }
if [ "$MTX_EXT" = zip ]; then
  powershell -NoProfile -Command "Expand-Archive -Path 'build/desktop/${mtx}' -DestinationPath build/desktop -Force"
else
  tar -xzf "build/desktop/${mtx}" -C build/desktop "$MTX_BIN"
fi
export MEDIAMTX_BUNDLE="$ROOT/build/desktop/${MTX_BIN}"

ICON_SRC="web/public/apple-touch-icon.png"
if [ "$OS" = darwin ]; then
  iconset="build/desktop/icon.iconset"; mkdir -p "$iconset"
  for s in 16 32 64 128 256 512; do sips -z "$s" "$s" "$ICON_SRC" --out "$iconset/icon_${s}x${s}.png" >/dev/null; done
  iconutil -c icns "$iconset" -o build/desktop/icon.icns
  export PRINTGUARD_ICON="$ROOT/build/desktop/icon.icns"
elif [ "$OS" = windows ]; then
  uv run --extra desktop python -c \
    "from PIL import Image; Image.open('$ICON_SRC').save('build/desktop/icon.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
  export PRINTGUARD_ICON="$ROOT/build/desktop/icon.ico"
fi

uv run --extra desktop pyinstaller packaging/printguard.spec --noconfirm --distpath dist --workpath build/pyinstaller

if [ "$OS" = darwin ]; then
  out="dist/PrintGuard-${LABEL}.dmg"
  command -v create-dmg >/dev/null || HOMEBREW_NO_AUTO_UPDATE=1 brew install create-dmg
  staging="build/desktop/dmg"; rm -rf "$staging"; mkdir -p "$staging"
  cp -R dist/PrintGuard.app "$staging/"
  create-dmg \
    --volname PrintGuard \
    --volicon build/desktop/icon.icns \
    --window-size 600 400 \
    --icon-size 128 \
    --icon PrintGuard.app 160 185 \
    --app-drop-link 440 185 \
    --hide-extension PrintGuard.app \
    "$out" "$staging"
  if [ -n "${APPLE_SIGNING_IDENTITY:-}" ]; then
    codesign -s "$APPLE_SIGNING_IDENTITY" --timestamp "$out"
  fi
  if [ -n "${APPLE_API_KEY:-}" ]; then
    printf '%s' "$APPLE_API_KEY" > build/desktop/notary.p8
    xcrun notarytool submit "$out" --key build/desktop/notary.p8 --key-id "$APPLE_API_KEY_ID" --issuer "$APPLE_API_ISSUER" --wait
    xcrun stapler staple "$out"
  fi
else
  out="dist/PrintGuard-${LABEL}.zip"
  # Explorer marks every file of a downloaded zip as from the internet, and .NET refuses
  # to load the window's assemblies with that mark unless the exe's config allows it.
  cp packaging/PrintGuard.exe.config dist/PrintGuard/
  powershell -NoProfile -Command "Compress-Archive -Path dist/PrintGuard -DestinationPath '$out' -Force"
fi
echo "$out"
