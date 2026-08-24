# Claude Code

1. Set up the repo once: `scripts/install-cli.sh` + `uv sync`.

2. Register the MCP server (user scope — available in every project). Run from the
   rango repo root so `$PWD` resolves, or substitute the absolute path yourself:

   ```bash
   claude mcp add --transport stdio --scope user chameleon -- bash "$PWD/plugin/run-mcp.sh"
   ```

   Project-scope alternative: copy [`mcp.json`](mcp.json) into the project root as
   `.mcp.json` (edit the path inside first).

3. Skill + subagent (directory symlink, the documented form, so repo edits stay
   live; copy the directory instead if your build doesn't follow symlinks):

   ```bash
   mkdir -p ~/.claude/skills ~/.claude/agents
   ln -sfn "$PWD/plugin/skills/chameleon-ultra" ~/.claude/skills/chameleon-ultra
   ln -sf "$PWD/plugin/agents/card-analyst.md" ~/.claude/agents/card-analyst.md
   ```

   The `whenToUse:` frontmatter key is not one Claude Code reads; local skill files
   aren't rejected for extra keys — no edit needed.

4. Restart Claude Code. Tools appear as `mcp__chameleon__<tool>` (e.g.
   `mcp__chameleon__chameleon_run`); the skill's confirmation gates and workflows
   apply unchanged.
