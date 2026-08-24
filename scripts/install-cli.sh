#!/bin/bash
# install-cli.sh — fetch the upstream Chameleon Ultra CLI (stock, unmodified).
#
# Rango drives the upstream CLI in-process but does not vendor it. This script
# gets you a working copy with zero manual steps:
#
#   scripts/install-cli.sh                 # clone ../ChameleonUltra (side-by-side with this repo)
#   scripts/install-cli.sh /some/where     # clone into a custom path
#
# Resolution order used by Rango afterwards (no env needed for the default):
#   $CHAMELEON_SOFTWARE/script → ../ChameleonUltra/software/script → ~/Workspace/chameleonUltra/software/script
#
# If github.com is unreachable from your network, the script falls back to a
# tarball from codeload.github.com (no git history, same content).
set -euo pipefail

REPO_URL="https://github.com/RfidResearchGroup/ChameleonUltra.git"
TARBALL_URL="https://codeload.github.com/RfidResearchGroup/ChameleonUltra/tar.gz/refs/heads/main"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RANGO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEST="${1:-$RANGO_ROOT/../ChameleonUltra}"
MARKER="software/script/chameleon_cli_main.py"

if [[ -n "${CHAMELEON_SOFTWARE:-}" && -f "$CHAMELEON_SOFTWARE/script/chameleon_cli_main.py" ]]; then
    echo "already configured: CHAMELEON_SOFTWARE=$CHAMELEON_SOFTWARE"
    exit 0
fi

if [[ -f "$DEST/$MARKER" ]]; then
    echo "already present: $DEST"
    exit 0
fi

if [[ -e "$DEST" && -n "$(ls -A "$DEST" 2>/dev/null)" ]]; then
    echo "error: $DEST exists and is not empty (and is not a ChameleonUltra checkout)" >&2
    exit 1
fi

echo "installing upstream Chameleon Ultra CLI into: $DEST"
if git clone --depth 1 "$REPO_URL" "$DEST" 2>/dev/null; then
    echo "cloned via git."
else
    echo "git clone failed (github.com unreachable?) — trying codeload tarball…"
    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT
    curl -fSL --max-time 240 -o "$TMP/cu.tar.gz" "$TARBALL_URL"
    mkdir -p "$DEST"
    tar xzf "$TMP/cu.tar.gz" -C "$DEST" --strip-components=1
    echo "extracted tarball (no git history)."
fi

if [[ ! -f "$DEST/$MARKER" ]]; then
    echo "error: install looks wrong — $DEST/$MARKER not found" >&2
    exit 1
fi

echo
echo "Done. Rango will find it automatically (side-by-side default)."
if [[ "$DEST" != "$RANGO_ROOT/../ChameleonUltra" ]]; then
    echo "Custom location — add this to your shell profile or the plugin manifest env:"
    echo "  export CHAMELEON_SOFTWARE=\"$DEST/software\""
fi
echo
echo "Optional — build the C attack tools (nested/darkside/hardnested need cmake):"
echo "  cd \"$DEST/software/src\" && cmake -B build && cmake --build build -j8"
