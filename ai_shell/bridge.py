"""Bridge to the official Chameleon Ultra CLI.

Imports the upstream CLI modules and drives them in-process through
ChameleonCLI.exec_cmd, capturing printed output so it can be fed to the LLM.
Upstream files are never modified — the upstream CLI is NOT vendored into this
repo; its location is resolved from (first hit wins):
  1. $CHAMELEON_SOFTWARE/script  (CHAMELEON_SOFTWARE = <upstream>/software)
  2. ../ChameleonUltra/software/script relative to this repo (side-by-side clones)
  3. ~/Workspace/chameleonUltra/software/script (author's default)
"""

import io
import os
import re
import sys
import threading
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


def _resolve_script_dir() -> Path:
    candidates = []
    env = os.environ.get("CHAMELEON_SOFTWARE")
    if env:
        candidates.append(Path(env).expanduser() / "script")
    candidates.append(Path(__file__).resolve().parent.parent.parent / "ChameleonUltra" / "software" / "script")
    candidates.append(Path.home() / "Workspace" / "chameleonUltra" / "software" / "script")
    for cand in candidates:
        if (cand / "chameleon_cli_main.py").is_file():
            return cand
    searched = "\n  ".join(str(c) for c in candidates)
    raise FileNotFoundError(
        "upstream Chameleon Ultra CLI not found; clone it and set CHAMELEON_SOFTWARE. Searched:\n  " + searched
    )


SCRIPT_DIR = _resolve_script_dir()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

MAX_CAPTURE = 8000


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


class ChameleonBridge:
    """Owns one ChameleonCLI instance (and therefore one device connection)."""

    def __init__(self):
        import chameleon_cli_main
        import chameleon_cli_unit

        self._cli = chameleon_cli_main.ChameleonCLI()
        self.root = chameleon_cli_unit.root
        self._lock = threading.Lock()

    @property
    def connected(self) -> bool:
        return self._cli.device_com.isOpen()

    def run(self, cmd: str) -> str:
        """Execute a CLI command, return its printed output (ANSI stripped).

        Captures stdout AND stderr: several units print progress/results via
        tqdm, which writes to stderr. Both redirects are process-global, so
        concurrent calls would cross-capture without the lock.
        """
        with self._lock:
            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(buf):
                try:
                    self._cli.exec_cmd(cmd)
                except SystemExit:
                    # 'exit' calls sys.exit(); swallow it so the caller survives.
                    pass
                except Exception as e:  # defensive: exec_cmd already catches most
                    print(f"bridge error: {e}", file=buf)
            out = strip_ansi(buf.getvalue()).strip()
        if len(out) > MAX_CAPTURE:
            out = (out[:MAX_CAPTURE] + f"\n... [truncated, {len(out)} chars total — "
                   "for full card dumps use 'hf mf dump -f <file>' and read the file]")
        return out

    def exec_live(self, cmd: str) -> None:
        """Execute a command with live (uncaptured) output, for interactive use.

        Raises SystemExit when the command is 'exit'.
        """
        self._cli.exec_cmd(cmd)

    def catalog(self) -> str:
        """Serialize the CLITree into a compact command list for the LLM."""
        lines = []

        def walk(node):
            for child in node.children:
                if child.cls is not None:
                    help_text = (child.help_text or "").splitlines()[0] if child.help_text else ""
                    lines.append(f"{child.fullname} :: {help_text}")
                else:
                    lines.append(f"{child.fullname} :: [group] {child.help_text or ''}")
                    walk(child)

        walk(self.root)
        return "\n".join(lines)

    def command_help(self, cmd: str) -> str:
        """Return the argparse help for a command (e.g. 'hf mf fchk')."""
        return self.run(f"{cmd.strip()} -h")
