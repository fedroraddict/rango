# Rango — chameleon-ultra (Kimi Code plugin)

Operate a Chameleon Ultra RFID device from Kimi Code: read, crack, emulate and write
cards through the official CLI, with a host-side card library and key-dictionary
management. The device is driven over one persistent serial connection owned by the
MCP server process.

This directory is the installable plugin; the core logic (`ai_shell/`) lives at the
repo root.

## Install / refresh

One-time setup, from the repo root: `scripts/install-cli.sh` (fetch the upstream CLI),
`uv sync` (create `.venv`), `scripts/setup-plugin.sh` (write `plugin/.rango-root` so
the MCP launcher can find this repo after install copies this directory). Then, in
Kimi Code:

```
/plugins install <path to the rango repo>/plugin
/reload
```

Disconnect the device first (`hw disconnect` via the agent, or close anything holding
the serial port) — reinstalling while connected can wedge the device's USB state
(recovery: unplug/replug the cable).

Re-run the same two lines after editing anything here. If the repo itself moves,
re-run `scripts/setup-plugin.sh` and reinstall.

## Tools (MCP server `plugin-chameleon-ultra_chameleon`)

| Tool | Purpose |
|---|---|
| `chameleon_state` | One-call snapshot: firmware, battery, active slot, slot summaries |
| `chameleon_run` | Run any official CLI command (gate: non-read-only needs `confirm_dangerous=true`) |
| `chameleon_help` / `chameleon_catalog` | Exact syntax of one command / full command list |
| `card_list / card_add / card_show / card_remove` | Host card library (`~/.chameleon_ai/cards/`) |
| `card_analyze` | Offline dump analysis (raw .bin or Flipper .nfc): access bits, key audit + system fingerprints, value blocks, MAD AIDs/NDEF, card-type ID |
| `card_load` | Load a library card into a device slot (verified order, auto free-slot pick) |
| `dict_list / dict_seed_default / dict_create / dict_merge / dict_import / dict_show` | Mifare key dictionaries (`~/.chameleon_ai/dicts/`) |

## Mental model (mirrors the CU GUI app)

- **Library** = permanent record (unlimited, host-side). Every dump gets a name and lives here.
- **Slots** = the 8 working memories on the device; load cards from the library when needed.
- The agent pre-checks state, coaches card placement when scans fail, and follows a
  key-recovery decision tree (default dict → targeted/web-sourced dict → autopwn →
  manual PRNG attacks → mfkey32v2 reader-side recovery).

## Collaboration modes

- **Copilot** (default): every gated command is explained and confirmed by you.
- **Autopilot**: say "autopilot: <workflow>" and the agent states the plan once, then
  runs the whole chain. `hw dfu`, `hw factory_reset`, and writing physical cards always
  require their own confirmation even in autopilot.

## Layout

```
plugin/
├── kimi.plugin.json          # manifest (MCP server + skills + agents)
├── run-mcp.sh                # MCP entry — resolves the repo root ($RANGO_ROOT →
│                             #   plugin/.rango-root marker → in-place → known paths),
│                             #   then runs the repo's .venv
├── mcp/chameleon_mcp.py      # 16 MCP tools over ai_shell/
├── skills/chameleon-ultra/   # workflows, safety rules, troubleshooting
└── agents/card-analyst.md    # offline dump-analysis subagent
```

Core logic lives in `ai_shell/` at the repo root (`bridge.py`, `ops.py`, `library.py`,
`dictionaries.py`, `analyze.py`) — shared with the standalone AI shell
(`uv run python -m ai_shell` from the repo root). `analyze.py` is the deterministic
offline dump analyzer behind `card_analyze` and the `agents/card-analyst.md`
subagent.
