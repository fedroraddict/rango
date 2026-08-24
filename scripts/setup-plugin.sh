#!/bin/bash
# Write the repo-root marker the MCP launcher (plugin/run-mcp.sh) uses after
# `/plugins install` copies plugin/ into the Kimi Code managed-plugins dir.
# Re-run this if you move the repo, then reinstall the plugin.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
printf '%s\n' "$ROOT" > "$ROOT/plugin/.rango-root"
echo "wrote $ROOT/plugin/.rango-root"
echo "now (re)install in Kimi Code: /plugins install $ROOT/plugin"
