"""MCP server exposing the Chameleon Ultra CLI as tools.

Wraps the ai_shell package (bridge + ops + library + dictionaries + analyze)
in an MCP stdio server. One long-lived process = one persistent owner of the
device's serial port.

ai_shell lives in this repo (sibling of plugin/). The upstream Chameleon Ultra
CLI is NOT vendored — ai_shell.bridge resolves its location (see there);
set CHAMELEON_SOFTWARE=<upstream>/software if it isn't in a default location.
"""

import os
import sys
from pathlib import Path

# `/plugins install` copies plugin/ into the Kimi Code managed-plugins dir,
# where the repo root cannot be derived from __file__ — run-mcp.sh resolves it
# and exports RANGO_ROOT. In-place dev runs fall back to the parent chain
# (plugin/mcp/ -> repo root).
_env_root = os.environ.get("RANGO_ROOT")
RANGO_ROOT = Path(_env_root) if _env_root else Path(__file__).resolve().parent.parent.parent

if not (RANGO_ROOT / "ai_shell").is_dir():
    sys.exit(
        f"rango MCP: ai_shell/ not found under {RANGO_ROOT} — set RANGO_ROOT to "
        "the rango repo path, or run scripts/setup-plugin.sh in the repo"
    )

if str(RANGO_ROOT) not in sys.path:
    sys.path.insert(0, str(RANGO_ROOT))

from mcp.server import MCPServer

from ai_shell import analyze, dictionaries, library, ops
from ai_shell.bridge import ChameleonBridge
from ai_shell.tools import is_readonly

mcp = MCPServer("chameleon")
_bridge = ChameleonBridge()

REFUSAL = (
    "Refused: '{command}' modifies device/card state or runs an attack. "
    "Describe to the user exactly what the command does, ask for confirmation, "
    "and only then call chameleon_run again with confirm_dangerous=true."
)


@mcp.tool()
def chameleon_run(command: str, confirm_dangerous: bool = False) -> str:
    """Execute a Chameleon Ultra CLI command and return its output.

    Read-only commands (connect, scan, info, read, dump...) run directly.
    Anything that writes, flashes, changes settings or runs a key attack
    requires confirm_dangerous=true — ask the user before setting it.
    """
    command = command.strip()
    if not command:
        return "error: empty command"
    if not is_readonly(command) and not confirm_dangerous:
        return REFUSAL.format(command=command)
    out = _bridge.run(command)
    state = "connected" if _bridge.connected else "offline"
    return f"[device: {state}]\n{out or '(no output)'}"


@mcp.tool()
def chameleon_help(command: str) -> str:
    """Get exact usage and parameters of a CLI command, e.g. 'hf mf nested'."""
    return _bridge.command_help(command)


@mcp.tool()
def chameleon_catalog() -> str:
    """List all available CLI commands with one-line descriptions."""
    return _bridge.catalog()


@mcp.tool()
def dict_list() -> str:
    """List local Mifare key dictionaries (.dic files) with key counts and paths."""
    dicts = dictionaries.list_dicts()
    if not dicts:
        return "no dictionaries yet (use dict_seed_default to create the starter one)"
    return "\n".join(f"{d['name']}\t{d['keys']} keys\t{d['path']}" for d in dicts)


@mcp.tool()
def dict_seed_default() -> str:
    """Create the starter dictionary of well-known public default Mifare keys."""
    return str(dictionaries.seed_default())


@mcp.tool()
def dict_create(name: str, keys: list[str]) -> str:
    """Create a .dic dictionary from 12-hex-char Mifare keys."""
    return str(dictionaries.create(name, keys))


@mcp.tool()
def dict_merge(names: list[str], out_name: str) -> str:
    """Merge several dictionaries into a new deduplicated one."""
    return str(dictionaries.merge(names, out_name))


@mcp.tool()
def dict_import(path: str, name: str = "") -> str:
    """Import an existing key file from an arbitrary path into the dictionary store."""
    return str(dictionaries.import_file(path, name or None))


@mcp.tool()
def dict_show(name: str) -> str:
    """Return the keys of a dictionary (12-hex strings, space-separated).

    Use these as positional arguments to 'hf mf fchk' — on this CLI build
    fchk's --dic flag is a broken upstream stub, keys must go on the command line.
    """
    return " ".join(dictionaries.read_keys(name))


@mcp.tool()
def card_list() -> str:
    """List the host-side card library (saved dumps, unlimited — independent of the 8 device slots)."""
    cards = library.card_list()
    if not cards:
        return "card library is empty (dump a card, then card_add it under a name)"
    lines = [f"{c['name']}\tUID {c.get('uid') or '?'}\t{c['bytes']} bytes\t{c['file']}" for c in cards]
    return "\n".join(lines)


@mcp.tool()
def card_add(name: str, dump_path: str, uid: str = "", note: str = "") -> str:
    """Save a card dump file into the host library under a user-chosen name."""
    return str(library.card_add(name, dump_path, uid, note))


@mcp.tool()
def card_show(name: str) -> str:
    """Show metadata + dump path of a library card (use the path with 'hf mf eload -f')."""
    return str(library.card_show(name))


@mcp.tool()
def card_remove(name: str) -> str:
    """Remove a card from the host library."""
    return library.card_remove(name)


@mcp.tool()
def card_analyze(name_or_path: str) -> str:
    """Analyze a card dump offline (no device needed): identity, access-bits
    decode, key audit (defaults + dictionaries, custom keys masked), value
    blocks, ASCII content, MAD/NDEF heuristics. Accepts a library card name
    or an absolute dump file path."""
    try:
        path = library.card_show(name_or_path)["file"]
    except Exception:  # not a library card (unknown name, corrupt sidecar) — treat as a path
        path = name_or_path
    return analyze.analyze_path(path)


@mcp.tool()
def chameleon_state() -> str:
    """One-call device snapshot: connection, firmware, battery, active slot, and a
    one-line summary per slot. Use for pre-flight checks before any workflow."""
    return ops.device_state(_bridge)


@mcp.tool()
def card_load(name: str, slot: int = 0, nick: str = "", confirm_dangerous: bool = False) -> str:
    """Load a library card into a device slot (writes device emulator memory).

    Runs the verified sequence — set slot type BEFORE eload, then enable block0
    anticollision — and auto-picks the first fully free slot when slot=0. Ask the
    user which slot to use (or confirm auto-pick) before calling; the tool never
    persists to flash, so offer 'hw slot store' afterwards.
    """
    if not confirm_dangerous:
        return REFUSAL.format(command=f"card_load {name} -> slot {slot or 'auto'}")
    return ops.load_card_to_slot(_bridge, name, slot, nick)


if __name__ == "__main__":
    mcp.run()  # stdio transport
