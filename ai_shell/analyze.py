"""Offline Mifare dump analysis (no device needed).

Deterministic decoder for Mifare Classic and Ultralight/NTAG-family dumps:
identity, access-bits decode, key audit (defaults + ~/.chameleon_ai/dicts/),
value blocks, ASCII content, MAD/NDEF heuristics, known-system key
fingerprints, and Flipper Zero .nfc file input.

Key insight this module is built on: a complete Classic dump is already
plaintext *and* carries the sector keys in its trailers — there is nothing to
crack offline, only things to decode.

Access-condition tables follow NXP MF1S50YYX datasheet Tables 7/8; card-type
identification follows Proxmark3's detect_nxp_card tree (dump-applicable
subset: SAK/ATQA only — no ATS/GetVersion available offline).
"""

import json
import re
import string
from pathlib import Path

from .config import DICT_DIR
from .dictionaries import DEFAULT_KEYS

CLASSIC_SIZES = {320: "Mifare Mini", 1024: "Mifare Classic 1K", 2048: "Mifare Classic 2K", 4096: "Mifare Classic 4K"}
# Ultralight/NTAG dumps are 4-byte pages; anything else page-sized (>= 48, % 4 == 0) is treated as page-based.

# SAK -> card type (Proxmark3 cmdhf14a.c detect_nxp_card, offline subset)
SAK_TYPES = {
    0x01: "TNP3xxx (Infineon)",
    0x08: "Mifare Classic 1K",
    0x09: "Mifare Mini",
    0x10: "Mifare Plus 2K (SL2)",
    0x11: "Mifare Plus 4K (SL2)",
    0x18: "Mifare Classic 4K",
    0x19: "Mifare Classic 2K",
    0x20: "Mifare DESFire / Plus SL3 family",
    0x28: "SmartMX with Classic 1K emulation",
    0x38: "SmartMX with Classic 4K emulation",
}
# Expected dump size per Classic SAK (for magic-card/misread cross-check)
SAK_SIZE = {0x09: 320, 0x08: 1024, 0x19: 2048, 0x18: 4096}

# Ultralight/NTAG identification by page count (Proxmark3 cmdhfmfu.c sizes).
# Ambiguous counts list all candidates; the CC byte (page 3) can disambiguate.
UL_PAGE_TYPES = {
    16: "Mifare Ultralight",
    20: "Ultralight EV1 (MF0UL11) or NTAG210",
    41: "Ultralight EV1 (MF0UL21) or NTAG212",
    42: "NTAG203",
    45: "NTAG213",
    48: "Ultralight C",
    135: "NTAG215",
    231: "NTAG216",
}

# Named well-known access-bit configurations (Proxmark3 `hf mf acl`)
NAMED_ACLS = {
    "FF0780": "transport configuration",
    "7F0788": "key B enabler",
    "787788": "no value-commands",
}

# Known-system key fingerprints (Flipper Zero supported_cards/hotels.c):
# (sector, "A"|"B", key, system name) — a single matching trailer key identifies the system.
KEY_FINGERPRINTS = [
    (1, "A", "2A2C13CC242A", "Saflok hotel key"),
    (1, "A", "8A19D40CF2B5", "Onity hotel key"),
    (2, "B", "0000014B5C31", "VingCard hotel key"),
]

# MAD administrative AIDs (Proxmark3 mad.c hardcoded table)
MAD_ADMIN_AIDS = {
    0x0000: "free",
    0x0001: "defect",
    0x0002: "reserved",
    0x0003: "additional directory info",
    0x0004: "card holder info",
    0x0005: "not applicable",
}

FLIPPER_NFC_HEADER = "Filetype: Flipper NFC device"

_PRINTABLE = set(bytes(string.printable, "ascii")) - set(b"\x0b\x0c")

# (C1, C2, C3) -> (read, write, increment, decrement/transfer/restore) for data blocks
_DATA_ACCESS = {
    (0, 0, 0): ("A|B", "A|B", "A|B", "A|B"),
    (0, 1, 0): ("A|B", "-", "-", "-"),
    (1, 0, 0): ("A|B", "B", "-", "-"),
    (1, 1, 0): ("A|B", "B", "B", "A|B"),
    (0, 0, 1): ("A|B", "-", "-", "A|B"),
    (0, 1, 1): ("B", "B", "-", "-"),
    (1, 0, 1): ("B", "-", "-", "-"),
    (1, 1, 1): ("-", "-", "-", "-"),
}

# (C1, C2, C3) -> (keyA read/write, access-bits read/write, keyB read/write) for trailers
_TRAILER_ACCESS = {
    (0, 0, 0): ("-/A", "A/-", "A/A"),
    (0, 1, 0): ("-/-", "A/-", "A/-"),
    (1, 0, 0): ("-/B", "A|B/-", "-/B"),
    (1, 1, 0): ("-/-", "A|B/-", "-/-"),
    (0, 0, 1): ("-/A", "A/A", "A/A"),
    (0, 1, 1): ("-/B", "A|B/B", "-/B"),
    (1, 0, 1): ("-/-", "A|B/B", "-/-"),
    (1, 1, 1): ("-/-", "A|B/-", "-/-"),
}

MAD_KEY_A = "A0A1A2A3A4A5"


def parse_flipper_nfc(text: str) -> tuple[bytes, list[str]]:
    """Convert a Flipper Zero .nfc text dump to raw dump bytes + report notes.

    Format: `Block N: XX XX ...` (Classic, 16 B) or `Page N: XX XX XX XX`
    (Ultralight/NTAG). Unread bytes are literal `??` — zero-filled here and
    counted. Note: .nfc v3+ stores the header ATQA MSB-first while block 0
    keeps the on-card LSB-first order; we analyze block 0, so no conversion.
    """
    blocks: dict[int, bytes] = {}
    device_type, version, unread = "", "", 0
    for line in text.splitlines():
        if line.startswith("Version:"):
            version = line.split(":", 1)[1].strip()
        elif line.startswith("Device type:"):
            device_type = line.split(":", 1)[1].strip()
        m = re.match(r"^(?:Block|Page) (\d+):\s*(.*)$", line)
        if m:
            parts = m.group(2).split()
            unread += parts.count("??")
            blocks[int(m.group(1))] = bytes(0 if p == "??" else int(p, 16) for p in parts)
    if not blocks:
        raise ValueError("no Block/Page lines found in .nfc file")
    unit = 16 if "Classic" in device_type else 4
    n = max(blocks) + 1
    missing = [i for i in range(n) if i not in blocks]
    data = b"".join(blocks.get(i, bytes(unit))[:unit].ljust(unit, b"\x00") for i in range(n))
    notes = [f"Source: Flipper .nfc v{version or '?'} ({device_type or 'unknown type'})"]
    if unread or missing:
        notes.append(f"incomplete dump: {unread} unread (??) bytes"
                     + (f", {len(missing)} missing blocks" if missing else "")
                     + " — zero-filled")
    return data, notes


def _ascii_runs(block: bytes, min_len: int = 4) -> list[str]:
    runs, cur = [], []
    for b in block:
        if b in _PRINTABLE and b not in b"\r\n\t":
            cur.append(chr(b))
        else:
            if len(cur) >= min_len:
                runs.append("".join(cur))
            cur = []
    if len(cur) >= min_len:
        runs.append("".join(cur))
    return runs


def _is_value_block(block: bytes) -> int | None:
    """Return the decoded value if `block` has value-block encoding, else None."""
    v, inv, v2 = block[0:4], block[4:8], block[8:12]
    a, ai, a2, ai2 = block[12], block[13], block[14], block[15]
    if v != v2 or v != bytes(b ^ 0xFF for b in inv):
        return None
    if a != a2 or ai != ai2 or a != ai ^ 0xFF:
        return None
    return int.from_bytes(v, "little", signed=True)


def _access_bits(trailer: bytes) -> dict:
    """Decode the 3 access bytes of a sector trailer."""
    b6, b7, b8, gpb = trailer[6], trailer[7], trailer[8], trailer[9]
    consistent = (
        (b6 & 0x0F) ^ 0x0F == (b7 >> 4) & 0x0F
        and (b6 >> 4) ^ 0x0F == b8 & 0x0F
        and (b7 & 0x0F) ^ 0x0F == (b8 >> 4) & 0x0F
    )
    blocks = []
    for i in range(4):
        c = ((b7 >> (4 + i)) & 1, (b8 >> i) & 1, (b8 >> (4 + i)) & 1)
        blocks.append(c)
    return {"gpb": gpb, "consistent": consistent, "raw": trailer[6:9].hex().upper(), "blocks": blocks}


def _triplet_index(block_in_sector: int, nblocks: int) -> int:
    """Access-bit triplet index for a block within its sector.

    4-block sectors use one triplet per block; in 16-block sectors (4K,
    sectors 32-39) blocks 0-4/5-9/10-14 share triplets 0-2 and the trailer
    (block 15) uses triplet 3 (datasheet Table 6 note).
    """
    if nblocks == 16:
        return min(block_in_sector // 5, 3)
    return block_in_sector


def _load_dictionary_keys() -> dict[str, str]:
    """All keys from ~/.chameleon_ai/dicts/*.dic mapped to their dict name."""
    keys: dict[str, str] = {}
    if DICT_DIR.is_dir():
        for p in sorted(DICT_DIR.glob("*.dic")):
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                k = line.strip().upper()
                if len(k) == 12 and all(c in "0123456789ABCDEF" for c in k):
                    keys.setdefault(k, p.name)
    return keys


def _load_mad_names() -> dict[int, str]:
    """MAD AID -> application name. Admin AIDs always; optionally Proxmark3's
    mad.json (list of {"mad": "xxxx", "application": ...}) from the dicts dir."""
    names: dict[int, str] = dict(MAD_ADMIN_AIDS)
    p = DICT_DIR / "mad.json"
    if p.is_file():
        try:
            for e in json.loads(p.read_text(encoding="utf-8")):
                names.setdefault(int(e["mad"], 16), e.get("application", ""))
        except (json.JSONDecodeError, KeyError, ValueError, OSError):
            pass
    return names


def _classify_key(key_hex: str, dict_keys: dict[str, str]) -> str:
    if key_hex == "0" * 12:
        return "zeros (unreadable by the dumping reader, or a genuine zero default key)"
    if key_hex in DEFAULT_KEYS:
        return "default"
    if key_hex in dict_keys:
        return f"in-dictionary ({dict_keys[key_hex]})"
    return "custom"


def _mask(key_hex: str) -> str:
    return key_hex if len(key_hex) != 12 else key_hex[:4] + "••••••••"


def _classic_layout(nblocks: int) -> list[int]:
    """Blocks per sector for a Classic card of `nblocks` blocks."""
    sectors = [4] * 32
    extra = nblocks - 32 * 4
    if extra > 0:  # 4K: sectors 32..39 have 16 blocks
        sectors += [16] * (extra // 16)
    return sectors[: nblocks // 4] if extra < 0 else sectors


def _mad_aids(data: bytes, layouts: list[int], mad_version: str) -> list[dict]:
    """Decode MAD application IDs: MAD1 directory = sector 0 blocks 1-2
    (sectors 1-15); MAD2 adds sector 16 blocks 0-2 (sectors 17+).
    AIDs are 2 bytes each as stored (some dumps are byte-swapped — pm3 has a
    swapmad flag for that; names resolve against both orders)."""
    names = _load_mad_names()
    blocks_per_sector = []
    blk = 0
    for n in layouts:
        blocks_per_sector.append(blk)
        blk += n
    out = []
    spans = [(0, [1, 2], 1)]  # MAD1: sector 0, its blocks 1-2, AIDs from sector 1
    if mad_version == "MAD2" and len(blocks_per_sector) > 16:
        spans.append((16, [0, 1, 2], 17))
    for sector, idxs, first_aid_sector in spans:
        base = blocks_per_sector[sector]
        aid_sector = first_aid_sector
        for i in idxs:
            block = data[(base + i) * 16:(base + i + 1) * 16]
            for j in range(0, 16, 2):
                aid = block[j] | block[j + 1] << 8
                if aid == 0x0000 or (aid > 0x0005 and aid not in names):
                    aid_sector += 1
                    continue  # free / unknown / unregistered — skip noise
                out.append({"sector": aid_sector, "aid": f"{aid:04X}",
                            "name": names.get(aid, "")})
                aid_sector += 1
    return out


def analyze_dump(data: bytes) -> dict:
    """Analyze a raw dump; returns a structured result dict (see format_report)."""
    size = len(data)
    if size in CLASSIC_SIZES:
        return _analyze_classic(data)
    if size >= 48 and size % 4 == 0:
        return _analyze_ultralight(data)
    return {"error": f"unrecognized dump size: {size} bytes "
            f"(Classic: 320/1024/2048/4096; Ultralight/NTAG: 48+, multiple of 4)"}


def _analyze_classic(data: bytes) -> dict:
    dict_keys = _load_dictionary_keys()
    uid = data[1:4].hex().upper() if data[0] == 0x88 else data[0:4].hex().upper()
    bcc_ok = (data[0] ^ data[1] ^ data[2] ^ data[3]) == data[4]
    sak = data[5]
    result = {
        "type": CLASSIC_SIZES[len(data)],
        "size": len(data),
        "uid": uid,
        "uid_7byte": data[0] == 0x88,  # 0x88 = cascade tag; rest of UID is not in block 0
        "bcc_ok": bcc_ok,
        "sak": f"{sak:02X}",
        "atqa": data[6:8].hex().upper(),
        "sak_type": SAK_TYPES.get(sak, "unknown"),
        "sectors": [],
    }
    expected = SAK_SIZE.get(sak)
    result["size_mismatch"] = bool(expected and expected != len(data))
    layouts = _classic_layout(len(data) // 16)
    blk = 0
    seen_keys: dict[str, list[int]] = {}
    value_blocks, ascii_hits, fingerprints, mad = [], [], [], None
    for s, nblocks in enumerate(layouts):
        blocks = [data[(blk + i) * 16:(blk + i + 1) * 16] for i in range(nblocks)]
        trailer = blocks[-1]
        acc = _access_bits(trailer)
        key_a, key_b = trailer[0:6].hex().upper(), trailer[10:16].hex().upper()
        for label, k in (("A", key_a), ("B", key_b)):
            cls = _classify_key(k, dict_keys)
            if cls == "custom":
                seen_keys.setdefault(f"{label}:{k}", []).append(s)
        for f_sector, f_ab, f_key, f_name in KEY_FINGERPRINTS:
            if s == f_sector and (key_a if f_ab == "A" else key_b) == f_key:
                fingerprints.append(f"{f_name} (sector {s} key{f_ab})")
        sector = {
            "sector": s,
            "blocks": list(range(blk, blk + nblocks)),
            "access_raw": acc["raw"],
            "access_name": NAMED_ACLS.get(acc["raw"], ""),
            "access_consistent": acc["consistent"],
            "gpb": acc["gpb"],
            "key_a": key_a, "key_a_class": _classify_key(key_a, dict_keys),
            "key_b": key_b, "key_b_class": _classify_key(key_b, dict_keys),
            "data_access": [],
            "trailer_access": _TRAILER_ACCESS.get(acc["blocks"][_triplet_index(nblocks - 1, nblocks)], ("?",) * 3),
        }
        for i in range(nblocks - 1):
            if blk + i == 0:
                sector.setdefault("content", []).append({"block": 0, "kind": "manufacturer"})
                continue
            perm = _DATA_ACCESS.get(acc["blocks"][_triplet_index(i, nblocks)], ("?",) * 4)
            sector["data_access"].append(perm)
            b = blocks[i]
            val = _is_value_block(b)
            if val is not None:
                value_blocks.append({"block": blk + i, "value": val})
                sector.setdefault("content", []).append({"block": blk + i, "kind": "value-block"})
                continue
            if b == b"\x00" * 16:
                kind = "zero"
            elif b == b"\xff" * 16:
                kind = "0xFF-filled"
            else:
                runs = _ascii_runs(b)
                kind = "random-looking"
                if runs:
                    kind = "ascii"
                    ascii_hits.append({"block": blk + i, "text": runs})
            sector.setdefault("content", []).append({"block": blk + i, "kind": kind})
        # pm3 MADCheck: DA bit (GPB bit 7) set + MAD version bits 01/10
        gpb_mad1 = acc["gpb"] & 0x83 == 0x81
        gpb_mad2 = acc["gpb"] & 0x83 == 0x82
        if s == 0 and key_a == MAD_KEY_A:
            mad = "MAD1 (sector 0 keyed with A0A1A2A3A4A5"
            mad += ", GPB confirms MAD1)" if gpb_mad1 else ")"
        if s == 16 and key_a == MAD_KEY_A:
            mad = "MAD2 (sector 16 keyed with A0A1A2A3A4A5"
            mad += ", GPB confirms MAD2)" if gpb_mad2 else ")"
        blk += nblocks
        result["sectors"].append(sector)
    result["value_blocks"] = value_blocks
    result["ascii"] = ascii_hits
    result["fingerprints"] = fingerprints
    result["mad"] = mad
    if mad:
        mad_version = "MAD2" if mad.startswith("MAD2") else "MAD1"
        result["mad_aids"] = _mad_aids(data, layouts, mad_version)
    else:
        result["mad_aids"] = []
    result["key_reuse"] = {k: v for k, v in seen_keys.items() if len(v) > 1}
    result["ndef_hint"] = _find_ndef_classic(data, layouts)
    result["summary"] = _classic_summary(result)
    return result


def _find_ndef_tlv(buf: bytes) -> int | None:
    """Return the NDEF message length if `buf` holds a plausible NDEF TLV.

    Heuristic: 0x03 TLV, short-form (<len>) or long-form (0xFF <len16>)
    length, record header 0xD0-0xD2.
    """
    idx = buf.find(b"\x03")
    while idx != -1:
        if idx + 2 < len(buf):
            if buf[idx + 1] == 0xFF and idx + 5 <= len(buf):  # long-form length
                # no bounds check on ln — real long-form messages exceed the
                # per-block scan window anyway; the record header is the guard
                ln = int.from_bytes(buf[idx + 2:idx + 4], "big")
                if ln >= 4 and buf[idx + 4] in (0xD0, 0xD1, 0xD2):
                    return ln
            else:
                ln = buf[idx + 1]
                if 4 <= ln <= 254 and idx + 2 + ln <= len(buf) and buf[idx + 2] in (0xD0, 0xD1, 0xD2):
                    return ln
        idx = buf.find(b"\x03", idx + 1)
    return None


def _find_ndef_classic(data: bytes, layouts: list[int]) -> str | None:
    """Scan data blocks only (trailers hold keys — random bytes false-positive)."""
    blk = 0
    for nblocks in layouts:
        for i in range(nblocks - 1):
            if blk + i == 0:
                continue
            ln = _find_ndef_tlv(data[(blk + i) * 16:(blk + i + 1) * 16])
            if ln is not None:
                return f"possible NDEF message TLV in block {blk + i}, {ln} bytes"
        blk += nblocks
    return None


def _classic_summary(result: dict) -> str:
    sectors = result["sectors"]
    data_kinds = [c["kind"] for s in sectors for c in s.get("content", []) if c["kind"] != "manufacturer"]
    keys_default = all(
        s["key_a_class"] == "default" and s["key_b_class"] == "default" for s in sectors
    )
    if result["fingerprints"]:
        return "identified: " + "; ".join(result["fingerprints"])
    if result["value_blocks"]:
        return "stored-value card (value blocks present — credit/purse application)"
    if result["ndef_hint"] or result["mad"]:
        return "application card with MAD/NDEF structure (e.g. transit or NFC tag application)"
    if data_kinds and all(k in ("zero", "0xFF-filled") for k in data_kinds) and keys_default:
        return "blank/factory card — UID-only badge with default keys"
    if keys_default:
        return "card uses only default keys — fully cloneable, treat as insecure"
    return "provisioned application card (custom keys; random-looking data is proprietary/encrypted content)"


def _analyze_ultralight(data: bytes) -> dict:
    npages = len(data) // 4
    uid = (data[0:3] + data[4:8]).hex().upper()
    bcc0_ok = data[3] == (0x88 ^ data[0] ^ data[1] ^ data[2])
    bcc1_ok = data[8] == (data[4] ^ data[5] ^ data[6] ^ data[7])
    ascii_hits = []
    for p in range(4, npages):
        for run in _ascii_runs(data[p * 4:(p + 1) * 4]):
            ascii_hits.append({"page": p, "text": [run]})
    ndef = None
    if npages > 5:
        ln = _find_ndef_tlv(data[16:32])
        if ln is not None:
            ndef = f"possible NDEF message TLV at page 4, {ln} bytes"
    return {
        "type": f"Ultralight/NTAG-family ({npages} pages)",
        "possible_types": UL_PAGE_TYPES.get(npages, ""),
        "size": len(data),
        "uid": uid,
        "bcc_ok": bcc0_ok and bcc1_ok,
        "lock_bytes": data[10:12].hex().upper(),
        "otp_cc": data[12:16].hex().upper(),  # OTP on Ultralight, Capability Container on NTAG21x
        "ascii": ascii_hits,
        "ndef_hint": ndef,
        "summary": "Ultralight/NTAG tag" + (" with NDEF content" if ndef else ""),
    }


def format_report(result: dict) -> str:
    """Render analyze_dump's result as a compact human-readable report."""
    if "error" in result:
        return f"ERROR: {result['error']}"
    uid_note = " (7-byte UID — block 0 holds only the first 3 bytes)" if result.get("uid_7byte") else ""
    lines = [f"Type: {result['type']}  ({result['size']} bytes)",
             f"UID: {result['uid']}{uid_note}  BCC: {'ok' if result['bcc_ok'] else 'INVALID'}"]
    if "sectors" not in result:  # Ultralight-family
        if result.get("possible_types"):
            lines.append(f"Possible types: {result['possible_types']} (by page count)")
        lines.append(f"Lock bytes: {result['lock_bytes']}  OTP/CC: {result['otp_cc']}")
        if result["ndef_hint"]:
            lines.append(result["ndef_hint"])
        for hit in result["ascii"]:
            lines.append(f"page {hit['page']}: ascii {hit['text']}")
        lines.append(f"Summary: {result['summary']}")
        return "\n".join(lines)

    lines.append(f"SAK: {result['sak']} ({result['sak_type']})  ATQA: {result['atqa']} (as stored, LSB first)")
    if result.get("size_mismatch"):
        lines.append("ANOMALY: SAK/type does not match dump size — magic card or misread")
    if result.get("mad"):
        lines.append(f"MAD: {result['mad']}")
    for aid in result.get("mad_aids", []):
        name = f" ({aid['name']})" if aid["name"] else ""
        lines.append(f"  MAD AID sector {aid['sector']}: 0x{aid['aid']}{name}")
    if result.get("ndef_hint"):
        lines.append(result["ndef_hint"])
    for s in result["sectors"]:
        ka = s["key_a"] if s["key_a_class"] == "default" else _mask(s["key_a"])
        kb = s["key_b"] if s["key_b_class"] == "default" else _mask(s["key_b"])
        flag = "" if s["access_consistent"] else "  [access-bits INCONSISTENT]"
        acl = f" ({s['access_name']})" if s.get("access_name") else ""
        lines.append(
            f"S{s['sector']:02d} blk {s['blocks'][0]}-{s['blocks'][-1]} "
            f"AC {s['access_raw']}{acl}{flag} keyA {ka} ({s['key_a_class']}) keyB {kb} ({s['key_b_class']})"
        )
        if not s["access_consistent"]:
            lines.append("    sector blocked on real cards (inconsistent access bits) — permissions moot")
        perms = "/".join(f"r{p[0]} w{p[1]}" for p in s["data_access"])
        t = s["trailer_access"]
        lines.append(f"    data: {perms}  trailer: keyA {t[0]}  AC {t[1]}  keyB {t[2]}")
        for c in s.get("content", []):
            if c["kind"] not in ("zero", "manufacturer"):
                lines.append(f"    blk {c['block']}: {c['kind']}")
    for vb in result["value_blocks"]:
        lines.append(f"value block @ blk {vb['block']}: {vb['value']}")
    for hit in result["ascii"]:
        lines.append(f"blk {hit['block']}: ascii {hit['text']}")
    for key, sectors in result["key_reuse"].items():
        label, k = key.split(":", 1)
        lines.append(f"key reuse: key{label} {_mask(k)} in sectors {sectors}")
    lines.append(f"Summary: {result['summary']}")
    return "\n".join(lines)


def analyze_path(path: str | Path) -> str:
    """Read a dump file (raw .bin or Flipper .nfc) and return the report."""
    p = Path(path).expanduser()
    if not p.is_file():
        return f"ERROR: file not found: {p}"
    raw = p.read_bytes()
    if raw.startswith(FLIPPER_NFC_HEADER.encode()):
        try:
            data, notes = parse_flipper_nfc(raw.decode("utf-8", errors="replace"))
        except ValueError as e:
            return f"ERROR: {e}"
        return "\n".join(notes) + "\n" + format_report(analyze_dump(data))
    return format_report(analyze_dump(raw))
