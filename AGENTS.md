# Rango workspace notes

Rango = the AI copilot layer for the Chameleon Ultra: `ai_shell/` (Python wrapper
library) + `plugin/` (Kimi Code plugin). The upstream Chameleon Ultra CLI is **not**
vendored — `scripts/install-cli.sh` fetches it (git clone, codeload tarball fallback);
at runtime it is located via `$CHAMELEON_SOFTWARE/script`,
`../ChameleonUltra/software/script`, then `~/Workspace/chameleonUltra/software/script`
(see `ai_shell/bridge.py`).

## Layout

- `ai_shell/` — bridge (in-process `exec_cmd` + stdout/stderr capture), `ops.py`
  (state snapshot, slot picking, verified card-load sequence), `library.py` (host card
  library), `dictionaries.py` (key dicts), `analyze.py` (offline dump analyzer,
  Flipper `.nfc` input, known-system key fingerprints, SAK/NTAG type ID), Kimi client,
  enhanced REPL, `selfcheck.py` + `test_analyze.py`.
- `plugin/` — Kimi Code plugin (manifest + MCP server + skill + `agents/card-analyst.md`).
  Install with `/plugins install <this repo>/plugin` then `/reload`; reinstall after
  edits (installs are copied to `~/.kimi-code/plugins/managed/`). The MCP server runs
  on this repo's `.venv` via `plugin/run-mcp.sh`, which locates the repo via
  `$RANGO_ROOT` → `plugin/.rango-root` (written by `scripts/setup-plugin.sh`) →
  in-place layout → `~/Workspace/rango`, `~/rango`.
- `scripts/` — `install-cli.sh` (upstream CLI fetcher), `setup-plugin.sh` (writes
  `plugin/.rango-root`; re-run it if the repo moves, then reinstall the plugin).
- `adapters/` — per-harness config/snippets for running the MCP server, skill, and
  card-analyst agent from Claude Code, Codex CLI, and OpenCode (the plugin manifest
  is Kimi-specific; the MCP server is not).
- `.github/workflows/ci.yml` — CI: ruff, tests, selfcheck (fetches the upstream CLI
  via `scripts/install-cli.sh` on the runner).

## Verify changes

```bash
uv run ruff check ai_shell/ plugin/mcp/
uv run python -m ai_shell.selfcheck     # cited commands exist upstream + gate semantics + slot-pick guards + simulated /plugins install boot
uv run python -m ai_shell.test_analyze  # dump-analyzer regression tests
echo -e "hw version\nexit" | uv run python -m ai_shell   # offline smoke test
```

## Run

```bash
uv run python -m ai_shell   # standalone AI shell; AI features need MOONSHOT_API_KEY
                            # (or another OpenAI-compatible endpoint in
                            #  ~/.chameleon_ai/config.toml); plain CLI works without it
```

## Environment notes

- If `github.com` is blocked on your network, `codeload.github.com` tarballs and
  `cdn.jsdelivr.net` usually work. If uv tries to download a Python interpreter from a
  blocked host, create a local `.python-version` pinning an installed interpreter
  (gitignored — do not commit it).
- Config/dictionaries/card library live in `~/.chameleon_ai/` (never commit API keys;
  config file is `~/.chameleon_ai/config.toml`).
- Known upstream quirk: `hf mf fchk --dic` may be a no-op stub (empty `load_dic_file`);
  pass keys positionally (`hf mf fchk --1k <KEY> <KEY> ...`), `dict_show` exists for this.
- Serial desync (frame-error floods, `CMD ... exec timeout`): a process holding the
  serial port was killed mid-connection. Recovery: unplug/replug. Prevention:
  `hw disconnect` before `/reload` or plugin reinstall.
- Emulation gotchas verified on-device: set `hw slot type` BEFORE `hf mf eload`;
  enable `--enable-block0` for the dump's UID; `hw slot enable --hf` or a formerly
  `(disabled)` slot won't emulate; `hw slot nick` needs `--hf`/`--lf`; pass the nick
  unquoted (`-n bike`) — the CLI splits on whitespace and would store the quote
  characters literally; `hw slot store` persists to flash.
