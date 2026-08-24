"""Composite device operations built on the bridge: state snapshots and
slot-aware card loading with the verified command order."""

import os
import re
from dataclasses import dataclass

from .bridge import ChameleonBridge
from .library import card_show

# Dump byte size -> slot tag type (Mifare Classic family)
SLOT_TYPE_BY_SIZE = {
    320: "MIFARE_Mini",
    1024: "MIFARE_1024",
    2048: "MIFARE_2048",
    4096: "MIFARE_4096",
}


@dataclass
class SlotInfo:
    number: int
    active: bool
    hf: str  # condensed, e.g. '"bike" Mifare Classic 1k UID 9119DACE' or 'undef'
    lf: str

    @property
    def free(self) -> bool:
        return "undef" in self.hf and "undef" in self.lf


def parse_slots(slot_list_output: str) -> list[SlotInfo]:
    """Parse `hw slot list` output into SlotInfo records."""
    slots: list[SlotInfo] = []
    current = None
    for line in slot_list_output.splitlines():
        # note: device indents "- Slot N:" for slots 2+ with a leading space
        m = re.match(r"\s*- Slot (\d):\s*(\(active\))?", line)
        if m:
            current = SlotInfo(number=int(m.group(1)), active=bool(m.group(2)), hf="", lf="")
            slots.append(current)
            continue
        if current is None:
            continue
        m = re.match(r"\s+HF:\s+(.*)", line)
        if m:
            current.hf = " ".join(m.group(1).split())
            continue
        m = re.match(r"\s+LF:\s+(.*)", line)
        if m:
            current.lf = " ".join(m.group(1).split())
            continue
        m = re.match(r"\s+UID:\s+([0-9A-Fa-f]+)", line)
        if m and current.hf and "undef" not in current.hf:
            current.hf += f" UID {m.group(1).upper()}"
    return slots


def device_state(bridge: ChameleonBridge) -> str:
    """One-call snapshot: connection, firmware, battery, slots."""
    if not bridge.connected:
        return "offline — run chameleon_run('hw connect') first"
    version = bridge.run("hw version").replace("\n", " ").strip()
    battery_raw = bridge.run("hw battery")
    pct = re.search(r"percentage ->\s*(\d+%)", battery_raw)
    battery = pct.group(1) if pct else "?"
    lines = [f"connected | {version} | battery {battery}", "slots:"]
    for s in parse_slots(bridge.run("hw slot list")):
        marker = "*" if s.active else " "
        lines.append(f"  {s.number}{marker} HF: {s.hf or '?'} | LF: {s.lf or '?'}")
    lines.append("(* = active slot)")
    return "\n".join(lines)


def pick_slot(slots: list[SlotInfo], requested: int = 0) -> tuple[int | None, str | None]:
    """Choose a slot: the requested one, else the first fully free one.
    Returns (slot_number, None) or (None, error_message_for_user)."""
    if requested:
        if not 1 <= requested <= 8:
            return None, f"slot must be 1-8, got {requested}"
        return requested, None
    for s in slots:
        if s.free:
            return s.number, None
    summary = "; ".join(f"{s.number}: HF {s.hf or '?'} / LF {s.lf or '?'}" for s in slots)
    return None, ("no free slot — ask the user which slot to replace. Current slots: " + summary)


def load_card_to_slot(bridge: ChameleonBridge, name: str, slot: int = 0, nick: str = "") -> str:
    """Load a library card into a device slot with the verified order:
    type BEFORE eload (type change wipes emulator memory), then block0 so the
    emulated UID comes from the dump. Does not run 'hw slot store' — the caller
    (agent) should offer persistence to the user.
    """
    if not bridge.connected:
        return "error: offline — run hw connect first"
    meta = card_show(name)  # raises FileNotFoundError if missing
    path = meta["file"]
    size = os.path.getsize(path)
    tag_type = SLOT_TYPE_BY_SIZE.get(size)
    if tag_type is None:
        return (f"error: dump is {size} bytes — not a recognized Mifare Classic size. "
                "card_load is Mifare-Classic-only; for NTAG/Ultralight use "
                "'hw slot type -t NTAG_*' + 'hf mfu eload', for LF use the family's "
                "econfig command (see the coverage map in the skill)")

    slots = parse_slots(bridge.run("hw slot list"))
    slot_no, err = pick_slot(slots, slot)
    if err:
        return "error: " + err

    steps = [
        f"hw slot type -s {slot_no} -t {tag_type}",
        # path stays unquoted (CLI splits on whitespace, no quoting): library
        # names forbid spaces, so this only breaks if $HOME itself contains one
        f"hf mf eload -f {path} -s {slot_no}",
        f"hf mf econfig -s {slot_no} --enable-block0",
        # slots that start as "(disabled)undef" stay disabled after loading —
        # a disabled side does not emulate
        f"hw slot enable -s {slot_no} --hf",
    ]
    if nick:
        # CLI splits on whitespace (no quoting) — spaces must not survive.
        safe_nick = nick.replace('"', "").strip().replace(" ", "_")
        if safe_nick:
            # no quotes: the naive split would store them as part of the nick
            steps.append(f"hw slot nick -s {slot_no} --hf -n {safe_nick}")

    log = []
    for cmd in steps:
        out = bridge.run(cmd)
        log.append(f"$ {cmd}\n{out}")
        if "error" in out.lower() or "fail" in out.lower():
            return "ABORTED mid-sequence:\n" + "\n".join(log)

    state = parse_slots(bridge.run("hw slot list"))
    active = next((s for s in state if s.active), None)
    active_note = (f"active slot is {active.number}" if active else "no active slot")
    return (
        f"loaded '{name}' ({meta.get('uid') or 'UID from dump'}) into slot {slot_no} "
        f"[{tag_type}, block0 anticollision]. {active_note}. "
        f"Slot {slot_no} is NOT necessarily active — offer: 'hw slot change -s {slot_no}' "
        f"to activate, 'hw slot store' to persist across reboots.\n\n" + "\n".join(log)
    )
