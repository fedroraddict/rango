# Adapters — use Rango from other agent harnesses

Rango's core is a standard MCP stdio server (`plugin/run-mcp.sh`) — any harness that
speaks MCP can drive the Chameleon Ultra through it. Only the manifest
(`plugin/kimi.plugin.json`) is Kimi Code–specific.

What transfers, per harness:

| Piece | Claude Code | Codex CLI | OpenCode |
|---|---|---|---|
| MCP server (16 tools) | `claude mcp add` / `.mcp.json` | `[mcp_servers.chameleon]` in `config.toml` | `mcp` in `opencode.json` |
| Workflow skill (`SKILL.md`) | `~/.claude/skills/` | `~/.agents/skills/` (strict installer frontmatter — see below) | `~/.config/opencode/skills/` (unknown frontmatter keys ignored) |
| `card-analyst` subagent | `~/.claude/agents/` (same file) | no md-agent equivalent — paste the body into a custom agent | `~/.config/opencode/agents/` (converted file included) |

Prerequisite for all: the repo is set up (`scripts/install-cli.sh`, `uv sync`).
`scripts/setup-plugin.sh` is **not** needed here — it exists for Kimi Code's
copy-on-install; other harnesses run `plugin/run-mcp.sh` in place and it finds
`ai_shell/` via its own location.

- [Claude Code](claude-code/README.md)
- [Codex CLI](codex/README.md)
- [OpenCode](opencode/README.md)

**Frontmatter caveat:** the canonical `plugin/skills/chameleon-ultra/SKILL.md` carries
a `whenToUse:` key (used by Kimi Code). Claude Code and OpenCode don't read it and
don't reject local skill files over extra keys; the Agent Skills spec allows only
`name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`, and
OpenAI's skill installer/validator enforces that (the Codex CLI runtime ignores
extras) — the Codex instructions strip it for you.

Formats verified 2026-08 against the official docs:
[Claude Code MCP](https://docs.anthropic.com/en/docs/claude-code/mcp),
[Codex config](https://github.com/openai/codex),
[OpenCode MCP](https://opencode.ai/docs/mcp-servers/) and
[OpenCode agents](https://opencode.ai/docs/agents/). Harness config schemas evolve —
if a snippet stops working, check the linked doc first.
