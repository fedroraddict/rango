"""Tool definitions and dispatch for the AI assistant.

The assistant can:
- run Chameleon CLI commands (confirmation gate for anything not read-only)
- fetch per-command help
- manage .dic key dictionaries
- web search (handled server-side by Moonshot's builtin $web_search)
"""

import json
from collections.abc import Callable

from . import dictionaries, library
from .bridge import ChameleonBridge

# Commands that never modify device or card state — safe to run without asking.
# Verified against `ChameleonBridge().catalog()` (see selfcheck.py).
# Note: get/set commands that mutate with an argument (hw slot nick, hw mode,
# hw slot prng) are deliberately excluded.
READONLY_PREFIXES = (
    "rem", "clear", "dump_help",
    "hw connect", "hw disconnect",
    "hw version", "hw chipid", "hw address", "hw battery",
    "hw slot list",
    "hf 14a scan", "hf 14a info", "hf 14a sniff", "hf 14a auth-trace",
    "hf mf rdbl", "hf mf view", "hf mf elog", "hf mf eview",
    "hf mfu rdpg", "hf mfu dump", "hf mfu version", "hf mfu signature",
    "hf mfu authnonce", "hf mfu rcnt", "hf mfu ercnt",
    "hf mfu eview", "hf mfu edetect",
    "hf des info",
    "hf seos eview",
    "lf em 4x05 read", "lf em 410x read", "lf hid prox read",
    "lf ioprox read", "lf pac read", "lf viking read", "lf jablotron read",
    "lf generic adcread", "lf sniff",
    "emv scan", "emv debug",
    "data hexsamples", "data plot", "data manrawdecode", "data modulation",
)

# Flags that write to a local file. The CLI opens output files during argparse
# (before the device check), so even a read-only-on-card command can truncate
# an arbitrary local file — any command carrying one of these is gated.
OUTPUT_FILE_FLAGS = frozenset({
    "-f", "--file", "--out", "--dump-file", "--export-key", "--export-dic",
})

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "run_chameleon_command",
            "description": (
                "Execute a Chameleon Ultra CLI command on the device and return its output. "
                "Use exact CLI syntax; call get_command_help first if unsure. Write, flash and "
                "cracking commands require user confirmation, which is handled automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Full CLI command, e.g. 'hf mf fchk --1k FFFFFFFFFFFF A0A1A2A3A4A5'"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_command_help",
            "description": "Get the exact usage/parameters of a Chameleon CLI command, e.g. 'hf mf nested'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command name without flags, e.g. 'hf mf fchk'"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dict_list",
            "description": "List local Mifare key dictionaries (.dic files) with key counts and paths.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dict_create",
            "description": "Create a .dic key dictionary from a list of 12-hex-char Mifare keys.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "keys": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "keys"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dict_merge",
            "description": "Merge several dictionaries into a new one (deduplicated).",
            "parameters": {
                "type": "object",
                "properties": {
                    "names": {"type": "array", "items": {"type": "string"}},
                    "out_name": {"type": "string"},
                },
                "required": ["names", "out_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dict_import",
            "description": "Import an existing key file from an arbitrary path into the dictionary store.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "name": {"type": "string"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dict_show",
            "description": (
                "Return the keys of a dictionary as a list of 12-hex strings. Use to build "
                "'hf mf fchk' commands with positional keys — on this CLI build fchk's --dic "
                "flag is a broken upstream stub, keys must be passed positionally."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dict_seed_default",
            "description": (
                "Create the starter dictionary of well-known public default Mifare keys "
                "(factory defaults, MAD key, etc.). Good first step before dictionary attacks."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "card_list",
            "description": "List the host-side card library (saved dumps, independent of the 8 device slots).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "card_add",
            "description": "Save a card dump file into the host library under a user-chosen name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "dump_path": {"type": "string"},
                    "uid": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["name", "dump_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "card_show",
            "description": "Show metadata + dump path of a library card (use the path with 'hf mf eload -f').",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "card_remove",
            "description": "Remove a card from the host library.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
]

# Moonshot server-side web search; declared so the model can use it.
WEB_SEARCH_SCHEMA = {
    "type": "builtin_function",
    "function": {"name": "$web_search"},
}


# `emv scan -s N` also loads the scanned card into a device slot — a device
# write, so that form of the command must leave the read-only set.
EMV_SLOT_FLAGS = frozenset({"-s", "--slot"})


def _has_flag(tokens: list[str], flags: frozenset) -> bool:
    """True if any token names one of `flags`, in every argparse spelling:
    exact (`--file x`), `=`-joined (`--file=x`), concatenated short (`-fx`)."""
    for t in tokens:
        if t in flags:
            return True
        if t.startswith("--") and "=" in t and t.split("=", 1)[0] in flags:
            return True
        if not t.startswith("--") and t.startswith("-") and len(t) > 2 and t[:2] in flags:
            return True
    return False


def is_readonly(command: str) -> bool:
    tokens = command.lower().split()
    if _has_flag(tokens, OUTPUT_FILE_FLAGS):
        return False
    cmd = " ".join(tokens)
    if not any(cmd == p or cmd.startswith(p + " ") for p in READONLY_PREFIXES):
        return False
    return not (cmd.startswith("emv scan") and _has_flag(tokens[2:], EMV_SLOT_FLAGS))


class ToolDispatcher:
    def __init__(self, bridge: ChameleonBridge, confirm_fn: Callable[[str], bool],
                 activity_fn: Callable[[str], None] | None = None):
        self.bridge = bridge
        self.confirm_fn = confirm_fn
        self.activity_fn = activity_fn or (lambda msg: None)
        self.auto = False  # when True, skip confirmations (session-scoped)

    def dispatch(self, name: str, arguments_json: str) -> str:
        try:
            args = json.loads(arguments_json) if arguments_json else {}
        except json.JSONDecodeError:
            return f"error: invalid tool arguments: {arguments_json!r}"
        try:
            return self._dispatch(name, args)
        except Exception as e:
            return f"error: {type(e).__name__}: {e}"

    def _dispatch(self, name: str, args: dict) -> str:
        if name == "run_chameleon_command":
            return self._run_command(args["command"])
        if name == "get_command_help":
            return self.bridge.command_help(args["command"])
        if name == "dict_list":
            dicts = dictionaries.list_dicts()
            if not dicts:
                return "no dictionaries yet (use dict_seed_default to create the starter one)"
            return json.dumps(dicts, indent=2)
        if name == "dict_create":
            return json.dumps(dictionaries.create(args["name"], args["keys"]))
        if name == "dict_merge":
            return json.dumps(dictionaries.merge(args["names"], args["out_name"]))
        if name == "dict_import":
            return json.dumps(dictionaries.import_file(args["path"], args.get("name")))
        if name == "dict_show":
            return json.dumps(dictionaries.read_keys(args["name"]))
        if name == "dict_seed_default":
            return json.dumps(dictionaries.seed_default())
        if name == "card_list":
            cards = library.card_list()
            if not cards:
                return "card library is empty (dump a card, then card_add it under a name)"
            return json.dumps(cards, indent=2)
        if name == "card_add":
            return json.dumps(library.card_add(args["name"], args["dump_path"],
                                               args.get("uid", ""), args.get("note", "")))
        if name == "card_show":
            return json.dumps(library.card_show(args["name"]))
        if name == "card_remove":
            return library.card_remove(args["name"])
        return f"error: unknown tool {name!r}"

    def _run_command(self, command: str) -> str:
        command = command.strip()
        if not command:
            return "error: empty command"
        if not self.auto and not is_readonly(command):
            if not self.confirm_fn(command):
                return f"command declined by user: {command}"
        self.activity_fn(f"$ {command}")
        out = self.bridge.run(command)
        return out or "(no output)"
