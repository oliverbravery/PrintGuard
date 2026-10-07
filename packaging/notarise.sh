#!/usr/bin/env bash
# Notarises the signed macOS disk image packaging/build.sh made and staples the ticket to it.
# Needs APPLE_API_KEY, the App Store Connect key's text, with APPLE_API_KEY_ID and
# APPLE_API_ISSUER. Nothing else in the build is handed them.
set -euo pipefail

disk_image="${1:?pass the disk image to notarise}"
key_dir="$(mktemp -d)"
trap 'rm -rf "$key_dir"' EXIT
printf '%s' "${APPLE_API_KEY:?a signed build is notarised, and APPLE_API_KEY is empty}" > "$key_dir/notary.p8"
xcrun notarytool submit "$disk_image" --key "$key_dir/notary.p8" --key-id "$APPLE_API_KEY_ID" --issuer "$APPLE_API_ISSUER" --wait
xcrun stapler staple "$disk_image"
