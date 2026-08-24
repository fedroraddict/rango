#!/bin/bash
# Entry point for the Rango (chameleon-ultra) plugin MCP server.
#
# `/plugins install` COPIES this directory into the Kimi Code managed-plugins
# dir, so the repo root cannot be derived from this script's own location.
# Resolution order: $RANGO_ROOT env → plugin/.rango-root marker (written by
# scripts/setup-plugin.sh and copied along on install) → in-place dev layout
# → well-known clone locations.
#
# CHAMELEON_SOFTWARE (optional) points at the upstream CLI's software/ dir;
# the MCP server resolves the CLI itself via ai_shell.bridge.
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

find_rango_root() {
    if [[ -n "${RANGO_ROOT:-}" && -d "$RANGO_ROOT/ai_shell" ]]; then
        echo "$RANGO_ROOT"; return 0
    fi
    if [[ -f "$PLUGIN_ROOT/.rango-root" ]]; then
        local p
        p="$(head -n1 "$PLUGIN_ROOT/.rango-root" | tr -d '[:space:]')"
        if [[ -n "$p" && -d "$p/ai_shell" ]]; then
            echo "$p"; return 0
        fi
    fi
    if [[ -d "$PLUGIN_ROOT/../ai_shell" ]]; then  # running in-place inside the repo
        (cd "$PLUGIN_ROOT/.." && pwd); return 0
    fi
    local c
    for c in "$HOME/Workspace/rango" "$HOME/rango"; do
        if [[ -d "$c/ai_shell" ]]; then
            echo "$c"; return 0
        fi
    done
    return 1
}

if ! RANGO_ROOT="$(find_rango_root)"; then
    echo "rango MCP: cannot locate the rango repo (no ai_shell/ found)." >&2
    echo "Fix: run scripts/setup-plugin.sh in the rango repo, or set RANGO_ROOT." >&2
    exit 1
fi

PYTHON="$RANGO_ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    echo "rango MCP: venv not found at $PYTHON" >&2
    echo "Run: cd $RANGO_ROOT && uv sync" >&2
    exit 1
fi

export RANGO_ROOT
exec "$PYTHON" "$PLUGIN_ROOT/mcp/chameleon_mcp.py"
