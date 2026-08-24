"""Entry point: uv run python -m ai_shell

Enhanced REPL: stock Chameleon CLI commands pass through unchanged;
prefix '?' talks to the Kimi assistant.
"""

import sys

import colorama
import prompt_toolkit
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import FileHistory

from . import dictionaries
from .bridge import (
    ChameleonBridge,  # importing bridge resolves the upstream CLI onto sys.path
)
from .config import CONFIG_FILE, ensure_dirs, load_config
from .kimi import KimiClient
from .tools import ToolDispatcher

AI_HELP = """\
AI shell commands:
  ? <question>   ask Kimi (can run device commands, manage key dicts, web search)
  ?auto on|off   toggle auto-approval of write/crack commands (default off)
  ?reset         clear the AI conversation
  ?dicts         list local key dictionaries
  ?help          show this help
Everything else is passed to the stock Chameleon CLI (try 'help' / Tab-completion).
"""


def main() -> None:
    # Lazy: chameleon_utils is importable only after the bridge import above
    # has resolved the upstream CLI onto sys.path. Bound as globals for the
    # module-level helpers below.
    global CC, CG, CR, CY, CustomNestedCompleter, color_string
    import chameleon_cli_main
    import chameleon_cli_unit
    from chameleon_utils import CC, CG, CR, CY, CustomNestedCompleter, color_string

    colorama.init(autoreset=True)
    chameleon_cli_unit.check_tools()

    bridge = ChameleonBridge()
    cfg = load_config()
    ensure_dirs()

    dispatcher = ToolDispatcher(bridge, confirm_fn=_make_confirm(), activity_fn=_activity)
    kimi = None
    if cfg.api_key:
        kimi = KimiClient(cfg, bridge, dispatcher)

    chameleon_cli_main.ChameleonCLI.print_banner()
    print(color_string((CG, "AI shell enabled. ")) + AI_HELP if kimi else
          color_string((CR, "AI disabled: no API key. ")) +
          f"Set MOONSHOT_API_KEY or add api_key to {CONFIG_FILE}\n" + AI_HELP)

    completer = CustomNestedCompleter.from_clitree(bridge.root)
    session = prompt_toolkit.PromptSession(
        completer=completer,
        history=FileHistory(str(dictionaries.DICT_DIR.parent / "history")),
    )

    while True:
        try:
            cmd = session.prompt(_prompt_text(bridge)).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not cmd:
            continue
        if cmd.startswith("?"):
            if not _handle_ai(cmd[1:].strip(), kimi, dispatcher):
                break
            continue
        try:
            bridge.exec_live(cmd)
        except SystemExit:
            return  # 'exit' unit already printed its farewell
        except Exception as e:
            print(f"error: {e}")

    print("Bye, thank you.  ^.^ ")


def _prompt_text(bridge):
    if bridge.connected:
        status = color_string((CG, "USB"))
    else:
        status = color_string((CR, "Offline"))
    return ANSI(f"[{status}] chameleon --> ")


def _activity(msg: str) -> None:
    print(color_string((CC, f"[ai] {msg}")))


def _make_confirm():
    def confirm(command: str) -> bool:
        if not sys.stdin.isatty():
            print(color_string((CR, f"[ai] declined (non-interactive): {command}")))
            return False
        try:
            ans = prompt_toolkit.prompt(
                ANSI(color_string((CY, f"[ai] run '{command}'? [y/N] ")))).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return ans in ("y", "yes")
    return confirm


def _handle_ai(text: str, kimi, dispatcher) -> bool:
    """Handle '?...' input. Returns False only when the shell should exit."""
    if text in ("", "help"):
        print(AI_HELP)
        return True
    if text == "auto on":
        dispatcher.auto = True
        print("auto-approval ON: write/crack commands run without asking")
        return True
    if text == "auto off":
        dispatcher.auto = False
        print("auto-approval OFF")
        return True
    if text == "reset":
        if kimi:
            kimi.reset()
        print("conversation cleared")
        return True
    if text == "dicts":
        dicts = dictionaries.list_dicts()
        if not dicts:
            print("no dictionaries; ask the AI to seed one (? seed a default key dictionary)")
        for d in dicts:
            print(f"  {d['name']:30} {d['keys']:5} keys  {d['path']}")
        return True
    if kimi is None:
        print("AI disabled: set MOONSHOT_API_KEY or api_key in the config file.")
        return True
    try:
        answer = kimi.chat(text)
    except KeyboardInterrupt:
        print("AI request aborted.")
        return True
    except Exception as e:
        print(f"AI error: {type(e).__name__}: {e}")
        return True
    if answer:
        print(answer)
    return True


if __name__ == "__main__":
    main()
