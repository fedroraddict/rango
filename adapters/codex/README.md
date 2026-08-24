# Codex CLI

1. Set up the repo once: `scripts/install-cli.sh` + `uv sync`.

2. Register the MCP server — either via the CLI (run from the rango repo root):

   ```bash
   codex mcp add chameleon -- bash "$PWD/plugin/run-mcp.sh"
   ```

   or merge [`config.toml`](config.toml) into `~/.codex/config.toml` (edit the path
   inside first).

3. Workflow skill (user scope; the documented location is `~/.agents/skills/`):

   ```bash
   mkdir -p ~/.agents/skills/chameleon-ultra
   sed '/^whenToUse:/d' plugin/skills/chameleon-ultra/SKILL.md > ~/.agents/skills/chameleon-ultra/SKILL.md
   ```

   The Agent Skills spec allows only `name`, `description`, `license`, `compatibility`,
   `metadata`, `allowed-tools` frontmatter keys; OpenAI's skill installer/validator
   rejects other keys such as Kimi's `whenToUse` (the Codex CLI runtime itself just
   ignores them), so we strip it. Codex detects skill changes automatically — restart
   only if the skill doesn't appear. `~/.codex/skills/` is a deprecated legacy location
   older builds still read; prefer `~/.agents/skills/`.

4. The `card-analyst` subagent has no direct markdown-agent equivalent in Codex;
   paste the body of `plugin/agents/card-analyst.md` into a custom agent/prompt if
   you want it.

5. If you skip the skill, at least copy the "Safety rules (mandatory)" section of
   `SKILL.md` into your project's `AGENTS.md` — they are what stands between a
   helpful agent and a wiped slot.
