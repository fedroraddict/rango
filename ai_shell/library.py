"""Host-side card library.

The Chameleon Ultra only has 8 slots — the library keeps unlimited card
dumps on the host, ready to be loaded into a slot on demand. Cards live in
~/.chameleon_ai/cards/ as <name>.bin plus a <name>.json metadata sidecar.
"""

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .config import CONFIG_DIR, ensure_dirs

CARD_DIR = CONFIG_DIR / "cards"

# No spaces: the CLI tokenizes command lines with str.split() (no quoting), so
# any path containing a space breaks commands like `hf mf eload -f <path>`.
NAME_RE = re.compile(r"^[\w.-]{1,64}$")


def _norm(name: str) -> str:
    return name.strip().replace(" ", "_")


def _card_paths(name: str) -> tuple[Path, Path]:
    name = _norm(name)
    if not NAME_RE.match(name):
        raise ValueError(f"invalid card name: {name!r}")
    base = CARD_DIR.resolve() / name
    if CARD_DIR.resolve() not in base.parents and base != CARD_DIR.resolve():
        raise ValueError(f"invalid card name: {name!r}")
    return base.with_suffix(".bin"), base.with_suffix(".json")


def card_add(name: str, dump_path: str, uid: str = "", note: str = "") -> dict:
    """Register a dump file in the library under a name (copies the file)."""
    ensure_dirs()
    CARD_DIR.mkdir(parents=True, exist_ok=True)
    src = Path(dump_path).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"dump file not found: {src}")
    bin_dst, json_dst = _card_paths(name)
    existed = json_dst.is_file()
    shutil.copyfile(src, bin_dst)
    meta = {
        "name": _norm(name),
        "file": str(bin_dst),
        "bytes": bin_dst.stat().st_size,
        "uid": uid.upper(),
        "note": note,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    json_dst.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    result = dict(meta)
    if existed:
        result["warning"] = f"overwrote existing library card {_norm(name)!r}"
    return result


def card_list() -> list[dict]:
    ensure_dirs()
    CARD_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for j in sorted(CARD_DIR.glob("*.json")):
        try:
            out.append(json.loads(j.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def card_show(name: str) -> dict:
    _, json_path = _card_paths(name)
    if not json_path.is_file():
        raise FileNotFoundError(f"card not in library: {name}")
    return json.loads(json_path.read_text(encoding="utf-8"))


def card_remove(name: str) -> str:
    bin_path, json_path = _card_paths(name)
    if not json_path.is_file():
        raise FileNotFoundError(f"card not in library: {name}")
    json_path.unlink()
    if bin_path.is_file():
        bin_path.unlink()
    return f"removed {name}"
