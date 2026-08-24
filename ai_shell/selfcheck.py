"""Offline regression guard: every CLI command cited in the plugin skill,
the read-only allowlist, or tool schema examples must exist in the real
command tree; the confirmation gate must catch every argparse flag spelling;
and the MCP plugin must boot after a simulated `/plugins install`.
Run: uv run python -m ai_shell.selfcheck
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .bridge import ChameleonBridge
from .tools import OUTPUT_FILE_FLAGS, READONLY_PREFIXES, is_readonly

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = REPO_ROOT / "plugin" / "skills" / "chameleon-ultra" / "SKILL.md"
TOOLS_PY = Path(__file__).resolve().parent / "tools.py"
KIMI_PY = Path(__file__).resolve().parent / "kimi.py"
MCP_PY = REPO_ROOT / "plugin" / "mcp" / "chameleon_mcp.py"

# Commands referenced as chameleon_run("...") or as `backticked` text.
SKILL_CMD_RE = re.compile(r'chameleon_run\("([^"]+)"|`((?:hw|hf|lf|emv|data|clear|dump_help)\b[^`\n]*)`')
SCHEMA_EXAMPLE_RE = re.compile(r"e\.g\. '([^']+)'")
# Single-quoted citations in prose, e.g. the kimi.py system prompt.
QUOTED_CMD_RE = re.compile(r"'((?:hw|hf|lf|emv|data)\s[^']*)'")

COMMAND_ROOTS = {"hw", "hf", "lf", "emv", "data", "clear", "dump_help", "rem", "exit"}


def command_exists(root, cmd: str) -> bool:
    """Walk the CLITree; True if the tokens resolve to a runnable leaf command."""
    node = leaf_node(root, cmd)
    return node is not None and node.cls is not None


def leaf_node(root, cmd: str):
    """Walk the CLITree; return the deepest matched node, or None if the
    very first token matches nothing."""
    node = root
    matched = 0
    for token in cmd.split():
        child = next((c for c in node.children if c.name == token), None)
        if child is None:
            break
        node = child
        matched += 1
    return node if matched else None


def skill_commands(text: str) -> set[str]:
    cmds = set()
    for m in SKILL_CMD_RE.finditer(text):
        cmd = (m.group(1) or m.group(2)).strip()
        if cmd.split()[0] in COMMAND_ROOTS:
            cmds.add(cmd)
    return cmds


def check_gate(failures: list[str]) -> None:
    """Confirmation-gate semantics: write side effects (local output files,
    device-slot loads) must stay gated in every argparse flag spelling."""
    gated = [
        "hf mfu dump --file=/tmp/x.bin",  # =-joined long flag
        "lf sniff --out=/tmp/x.raw",
        "hf mf rdbl -f/tmp/x.bin",  # concatenated short flag
        "emv scan -s 3",  # loads the scanned card into a device slot
        "emv scan --slot=3",
    ]
    for cmd in gated:
        if is_readonly(cmd):
            failures.append(f"is_readonly({cmd!r}) must be False (write side effect)")
    for cmd in ["hf 14a scan", "emv scan", "hw slot list", "hf mfu dump"]:
        if not is_readonly(cmd):
            failures.append(f"is_readonly({cmd!r}) must be True")


def check_simulated_install(failures: list[str]) -> None:
    """Simulate `/plugins install`: copy plugin/ into an unrelated dir (Kimi
    Code copies it into the managed-plugins dir), hand the copy a .rango-root
    marker like scripts/setup-plugin.sh writes, and require the launcher to
    boot and answer tools/list with every @mcp.tool()."""
    expected = MCP_PY.read_text(encoding="utf-8").count("@mcp.tool()")
    rpc = (
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":'
        '{"protocolVersion":"2024-11-05","capabilities":{},'
        '"clientInfo":{"name":"selfcheck","version":"0"}}}\n'
        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}\n'
    )
    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / "managed" / "chameleon-ultra"
        shutil.copytree(REPO_ROOT / "plugin", dst,
                        ignore=shutil.ignore_patterns("__pycache__", ".rango-root"))
        (dst / ".rango-root").write_text(str(REPO_ROOT) + "\n", encoding="utf-8")
        # Paced writes: dumping everything then closing stdin can race the
        # server (EOF discards a pending tools/list response).
        proc = subprocess.Popen(["bash", str(dst / "run-mcp.sh")],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        assert proc.stdin is not None
        first, rest = rpc.splitlines(keepends=True)[0], rpc.splitlines(keepends=True)[1:]
        proc.stdin.write(first)
        proc.stdin.flush()
        time.sleep(0.5)
        proc.stdin.writelines(rest)
        proc.stdin.flush()
        time.sleep(2)
        proc.stdin.close()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            failures.append("simulated install: MCP server did not answer in time")
            return
        out, err_out = proc.stdout.read(), proc.stderr.read()
    tools = None
    for line in out.splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == 2:
            tools = msg.get("result", {}).get("tools", [])
    if tools is None:
        failures.append(f"simulated install: no tools/list response "
                        f"(exit {proc.returncode}); stderr: {err_out.strip()[:200]!r} "
                        f"stdout: {out.strip()[:200]!r}")
    elif len(tools) != expected:
        failures.append(f"simulated install: {len(tools)} tools listed, expected {expected}")


def main() -> int:
    bridge = ChameleonBridge()
    failures = []

    for prefix in READONLY_PREFIXES:
        if not command_exists(bridge.root, prefix):
            failures.append(f"READONLY_PREFIXES entry not a real command: {prefix!r}")

    for cmd in sorted(skill_commands(SKILL_MD.read_text(encoding="utf-8"))):
        if not command_exists(bridge.root, cmd):
            failures.append(f"SKILL.md cites unknown command: {cmd!r}")

    for example in SCHEMA_EXAMPLE_RE.findall(TOOLS_PY.read_text(encoding="utf-8")):
        if not command_exists(bridge.root, example):
            failures.append(f"tools.py schema example cites unknown command: {example!r}")

    for cited in QUOTED_CMD_RE.findall(KIMI_PY.read_text(encoding="utf-8")):
        if not command_exists(bridge.root, cited):
            failures.append(f"kimi.py cites unknown command: {cited!r}")

    # Semantic tripwire: an allowlisted "read-only" command must not *require*
    # an output-file flag or a write-mode FileType argument — that combination
    # would truncate a local file without confirmation (argparse opens output
    # files before the device check runs).
    for prefix in READONLY_PREFIXES:
        node = leaf_node(bridge.root, prefix)
        if node is None or node.cls is None:
            continue  # already reported above
        parser = node.cls().args_parser()
        for action in parser._actions:
            has_out_flag = any(opt in OUTPUT_FILE_FLAGS for opt in action.option_strings)
            ftype = getattr(action, "type", None)
            writes_file = (isinstance(ftype, argparse.FileType)
                           and any(m in getattr(ftype, "_mode", "") for m in "wax"))
            if action.required and (has_out_flag or writes_file):
                failures.append(
                    f"read-only command {prefix!r} requires an output-file argument "
                    f"({action.option_strings or action.dest}) — remove it from "
                    "READONLY_PREFIXES or make the flag optional"
                )

    check_gate(failures)

    # Slot-picking regression guard (a bad pick once wiped a used slot):
    # fixture with slot 1 used and slot 5 free must auto-pick 5, never 1.
    from .ops import parse_slots, pick_slot

    # fixture uses the device's real formatting: slots 2+ have a leading space
    fixture = (
        "- Slot 1:\n   HF: door Mifare Classic 1k\n      UID: D37A831A\n   LF: EM410X\n"
        " - Slot 4: (active)\n   HF: bike Mifare Classic 1k\n   LF: undef\n"
        " - Slot 5:\n   HF: (disabled)undef\n   LF: (disabled)undef\n"
    )
    picked, err = pick_slot(parse_slots(fixture))
    if err or picked != 5:
        failures.append(f"pick_slot fixture: expected slot 5, got {picked!r} (err={err!r})")
    _, err_full = pick_slot([s for s in parse_slots(fixture) if not s.free])
    if err_full is None or "no free slot" not in err_full:
        failures.append("pick_slot must refuse when no slot is free")

    check_simulated_install(failures)

    if failures:
        print("selfcheck FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("selfcheck OK: cited commands exist, gate semantics hold, simulated install boots")
    return 0


if __name__ == "__main__":
    sys.exit(main())
