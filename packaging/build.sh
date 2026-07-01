#!/usr/bin/env bash
# Builds the PrintGuard desktop app for the host OS: builds the web UI, fetches
# MediaMTX, generates a platform icon, runs PyInstaller, and packages the result
# as a .dmg (macOS) or .zip (Windows) under dist/. The desktop app targets macOS
# and Windows; Linux is served by the container image. Run after `uv sync`.
set -euo pipefail

MEDIAMTX_VERSION="${MEDIAMTX_VERSION:-1.18.2}"
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
curl -fsSL -o "build/desktop/${mtx}" \
  "https://github.com/bluenviron/mediamtx/releases/download/v${MEDIAMTX_VERSION}/${mtx}"
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
  hdiutil create -volname PrintGuard -srcfolder dist/PrintGuard.app -ov -format UDZO "$out" >/dev/null
else
  out="dist/PrintGuard-${LABEL}.zip"
  powershell -NoProfile -Command "Compress-Archive -Path dist/PrintGuard -DestinationPath '$out' -Force"
fi
echo "$out"
