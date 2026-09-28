#!/usr/bin/env bash
# Compile Tailwind into storefront/static/storefront/css/tailwind.css.
# Uses the official Tailwind v3.4.17 standalone CLI (no Node.js needed), verified by SHA-256.
set -o errexit -o nounset -o pipefail

VERSION="3.4.17"
cd "$(dirname "$0")/.."

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)  ASSET="tailwindcss-linux-x64";   SHA256="7d24f7fa191d2193b78cd5f5a42a6093e14409521908529f42d80b11fde1f1d4" ;;
  Darwin-arm64)  ASSET="tailwindcss-macos-arm64"; SHA256="a1d0c7985759accca0bf12e51ac1dcbf0f6cf2fffb62e6e0f62d091c477a10a3" ;;
  *) echo "build_css.sh: unsupported platform $(uname -s)-$(uname -m)" >&2; exit 1 ;;
esac

BIN_DIR=".tailwind-bin"
BIN="$BIN_DIR/$ASSET-$VERSION"
if [ ! -x "$BIN" ]; then
  mkdir -p "$BIN_DIR"
  curl -sSfL -o "$BIN.tmp" "https://github.com/tailwindlabs/tailwindcss/releases/download/v$VERSION/$ASSET"
  echo "$SHA256  $BIN.tmp" | shasum -a 256 -c - >/dev/null 2>&1 || echo "$SHA256  $BIN.tmp" | sha256sum -c - >/dev/null
  chmod +x "$BIN.tmp" && mv "$BIN.tmp" "$BIN"
fi

"$BIN" -c tailwind.config.js -i storefront/tailwind/input.css -o storefront/static/storefront/css/tailwind.css --minify
