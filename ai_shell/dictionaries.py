"""Mifare key dictionary (.dic) management.

.dic format: one hex key per line (12 hex chars = 6 bytes), as used by
`hf mf fchk --dic <file>` and friends. Files live in ~/.chameleon_ai/dicts/.
"""

import re
import shutil
from pathlib import Path

from .config import DICT_DIR, ensure_dirs

KEY_RE = re.compile(r"^[0-9a-fA-F]{12}$")

# Well-known public default/factory Mifare Classic keys (widely published,
# e.g. in the Proxmark3 default key list). Used to seed a starter dictionary.
DEFAULT_KEYS = [
    "FFFFFFFFFFFF",  # factory default
    "000000000000",
    "A0A1A2A3A4A5",  # MAD key A
    "D3F7D3F7D3F7",  # NDEF/public sector
    "B0B1B2B3B4B5",
    "AABBCCDDEEFF",
    "4D3A99C351DD",
    "1A982C7E459A",
    "714C5C886E97",
    "587EE5F9350F",
    "A0478CC39091",
    "533CB6C723F6",
    "8FD0A4F256E9",
    "000000000001",
    "000000000002",
    "A64598A77478",
    "26940B21FF5D",
    "FC00018778F7",
    "E00000000000",
    "A0B0C0D0E0F0",
    "A1B1C1D1E1F1",
    "C0C1C2C3C4C5",
    "B5FF67CBA951",
    "66A6BCBF8BB4",
]


def _clean_keys(keys) -> list[str]:
    """Normalize and validate keys; returns sorted unique uppercase hex keys."""
    out = set()
    for k in keys:
        k = k.strip()
        if KEY_RE.match(k):
            out.add(k.upper())
    return sorted(out)


def _dict_path(name: str) -> Path:
    name = name.strip()
    if not name:
        raise ValueError("dictionary name must not be empty")
    if not name.endswith(".dic"):
        name += ".dic"
    path = (DICT_DIR / name).resolve()
    if DICT_DIR.resolve() not in path.parents:
        raise ValueError(f"invalid dictionary name: {name}")
    return path


def list_dicts() -> list[dict]:
    ensure_dirs()
    result = []
    for p in sorted(DICT_DIR.glob("*.dic")):
        keys = _clean_keys(p.read_text(encoding="utf-8", errors="replace").splitlines())
        result.append({"name": p.name, "path": str(p), "keys": len(keys)})
    return result


def read_keys(name: str) -> list[str]:
    path = _dict_path(name)
    if not path.is_file():
        raise FileNotFoundError(f"dictionary not found: {path}")
    return _clean_keys(path.read_text(encoding="utf-8", errors="replace").splitlines())


def create(name: str, keys) -> dict:
    ensure_dirs()
    clean = _clean_keys(keys)
    if not clean:
        raise ValueError("no valid keys (need 12 hex chars each)")
    path = _dict_path(name)
    path.write_text("\n".join(clean) + "\n", encoding="utf-8")
    return {"name": path.name, "path": str(path), "keys": len(clean)}


def merge(names, out_name: str) -> dict:
    keys: list[str] = []
    for n in names:
        keys.extend(read_keys(n))
    return create(out_name, keys)


def import_file(path: str, name: str | None = None) -> dict:
    src = Path(path).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"file not found: {src}")
    keys = _clean_keys(src.read_text(encoding="utf-8", errors="replace").splitlines())
    if not keys:
        # not a plain hex list — copy raw so the user can inspect it
        ensure_dirs()
        dst = _dict_path(name or src.name)
        shutil.copyfile(src, dst)
        return {"name": dst.name, "path": str(dst), "keys": 0,
                "note": "copied raw; no valid 12-hex keys detected"}
    return create(name or src.name, keys)


def seed_default(name: str = "default_keys") -> dict:
    return create(name, DEFAULT_KEYS)
