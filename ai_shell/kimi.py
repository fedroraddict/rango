"""Kimi (Moonshot API) client with tool-calling loop."""

from openai import OpenAI

from .bridge import ChameleonBridge
from .config import Config
from .tools import TOOL_SCHEMAS, WEB_SEARCH_SCHEMA, ToolDispatcher

MAX_TOOL_ROUNDS = 8
MAX_TOOL_OUTPUT = 4000
# Cap on non-system messages kept between turns; older ones are dropped at a
# user-message boundary so tool_call/tool pairs are never orphaned.
MAX_HISTORY = 40

SYSTEM_TEMPLATE = """You are Kimi, an expert assistant embedded in an interactive shell for the
Chameleon Ultra RFID emulation device. You help the user operate the device:
reading, cracking, emulating and writing RFID/NFC cards (HF Mifare Classic,
Ultralight/NTAG, DESFire; LF EM410x, HID Prox, T5577, etc.).

You can act through tools:
- run_chameleon_command: execute CLI commands on the device (persistent connection)
- get_command_help: exact syntax of any CLI command — call it whenever unsure
- dict_* tools: manage Mifare key dictionaries (.dic files, one 12-hex key per line)
- $web_search: search the web (e.g. for known default keys of a specific system)

Rules:
- Only work on cards/devices the user owns or is authorized to test.
- Prefer read-only commands first (identify HF cards with 'hf 14a scan' / 'hf 14a info';
  LF cards with the per-family read commands like 'lf em 410x read' or 'lf hid prox read').
- Typical Mifare Classic cracking flow: identify -> dictionary attack with
  'hf mf fchk --1k <KEY1> <KEY2> ...' (keys as positional hex args from dict_show;
  NOTE: fchk's --dic flag is a broken stub in this CLI build, never use it)
  -> for remaining keys use 'hf mf autopwn', or the manual attacks:
  'hf mf darkside' (no known key), 'hf mf nested' / 'hf mf hardnested' (one known
  key), 'hf mf senested' (static-encrypted backdoor cards) — always check exact
  syntax with get_command_help first
  -> dump with 'hf mf dump -f <file> -d <keys.dic>' (dump's -d dic loading works fine).
- Write/flash/crack commands will ask the user for confirmation automatically;
  never try to bypass that, and explain what a command will do before running it.
  Exception: if the user explicitly enables "autopilot" for a workflow, run the
  whole pre-stated chain without stopping — but hw dfu, hw factory_reset and
  writing physical cards always get their own confirmation regardless.
- Host-side card library (~/.chameleon_ai/cards/) via card_* tools: after dumping
  a card, always ask the user for a name and card_add it; slots are working memory,
  the library is the permanent record.
- Keep answers concise and technical. Show the exact commands you run.

Device state: {device_state}

Available CLI commands (name :: description):
{catalog}
"""


class KimiClient:
    def __init__(self, cfg: Config, bridge: ChameleonBridge, dispatcher: ToolDispatcher):
        self.cfg = cfg
        self.bridge = bridge
        self.dispatcher = dispatcher
        self.client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url,
                             timeout=60.0, max_retries=2)
        self.messages: list[dict] = []

    def _system_message(self) -> dict:
        state = "connected over USB" if self.bridge.connected else "offline (not connected)"
        return {
            "role": "system",
            "content": SYSTEM_TEMPLATE.format(
                device_state=state, catalog=self.bridge.catalog()
            ),
        }

    def reset(self) -> None:
        self.messages = []

    def chat(self, user_text: str) -> str:
        """Send a user message, run the tool loop, return final assistant text."""
        # Rebuild the system message every turn: device_state (and possibly the
        # catalog) can change between calls.
        sysmsg = self._system_message()
        if self.messages and self.messages[0]["role"] == "system":
            self.messages[0] = sysmsg
        else:
            self.messages.insert(0, sysmsg)
        self.messages.append({"role": "user", "content": user_text})
        self._trim_history()

        for _ in range(MAX_TOOL_ROUNDS):
            resp = self.client.chat.completions.create(
                model=self.cfg.model,
                messages=self.messages,
                tools=[*TOOL_SCHEMAS, WEB_SEARCH_SCHEMA],
                temperature=0.3,
            )
            msg = resp.choices[0].message
            self.messages.append(msg.model_dump(exclude_none=True))

            if not msg.tool_calls:
                return msg.content or ""

            for call in msg.tool_calls:
                name = call.function.name
                arguments = call.function.arguments or ""
                if name == "$web_search":
                    # Executed server-side by Moonshot; echo the arguments back
                    # as the tool result, per the API contract.
                    self.dispatcher.activity_fn("web search")
                    result = arguments or "{}"
                else:
                    result = self.dispatcher.dispatch(name, arguments)
                if len(result) > MAX_TOOL_OUTPUT:
                    result = result[:MAX_TOOL_OUTPUT] + "\n... [truncated]"
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": name,
                    "content": result,
                })
        return "(stopped: too many tool rounds)"

    def _trim_history(self) -> None:
        """Drop oldest turns beyond MAX_HISTORY, keeping the system message and
        never cutting inside a tool_call/tool exchange."""
        excess = len(self.messages) - 1 - MAX_HISTORY
        if excess <= 0:
            return
        # Advance the cut to the next user message so no orphaned
        # assistant-with-tool_calls or tool messages remain at the boundary.
        cut = 1 + excess
        while cut < len(self.messages) and self.messages[cut]["role"] != "user":
            cut += 1
        if cut >= len(self.messages):
            # No user-message boundary ahead of the excess — keep the system
            # message plus the newest user message (always the tail here).
            cut = len(self.messages) - 1
        del self.messages[1:cut]
