# OpenCode

1. Set up the repo once: `scripts/install-cli.sh` + `uv sync`.

2. Merge [`opencode.json`](opencode.json) into your global
   `~/.config/opencode/opencode.json` or a project `opencode.json` (edit the path
   inside first).

3. Card-analyst subagent (frontmatter already converted to OpenCode's format —
   `mode: subagent` + a `permission` map; upstream `tools:` is deprecated):

   ```bash
   mkdir -p ~/.config/opencode/agents
   cp adapters/opencode/card-analyst.md ~/.config/opencode/agents/card-analyst.md
   ```

4. Workflow skill — OpenCode has first-class skill support, and the canonical
   SKILL.md works unmodified (unknown frontmatter fields like `whenToUse:` are
   ignored per the docs):

   ```bash
   mkdir -p ~/.config/opencode/skills/chameleon-ultra
   cp plugin/skills/chameleon-ultra/SKILL.md ~/.config/opencode/skills/chameleon-ultra/SKILL.md
   ```

   OpenCode also reads `~/.claude/skills/` — if you already did the Claude Code
   step, there is nothing to do here. The `instructions: [...]` config field is a
   fallback, not an equivalent: `instructions` files are always-on system-prompt
   content and lose the skill's load-on-demand behavior.

5. Restart OpenCode. MCP tools are named `chameleon_<tool>` (e.g.
   `chameleon_chameleon_run`, per the docs' glob examples); the `card_load` /
   `chameleon_run` confirmation gates described in the skill apply unchanged.
