---
name: chameleon-ultra
description: Use when the user mentions Chameleon Ultra/Lite, RFID or NFC card reading/cloning/emulation, Mifare Classic key recovery (fchk, nested, darkside, hardnested, autopwn), LF cards (EM410x, HID Prox, T5577...), or the MCP tools mcp__plugin-chameleon-ultra_chameleon__*. Provides device-operation workflows and mandatory safety rules.
whenToUse: When the user wants to operate a Chameleon Ultra/Lite device — read, identify, crack, dump, emulate, or clone RFID/NFC cards, manage device slots or the card library, or troubleshoot the device connection.
---

# Chameleon Ultra device operation

This plugin exposes the device's official CLI through an MCP server named `chameleon`. Tools below are cited by their bare MCP names — your host prefixes them (Kimi Code: `mcp__plugin-chameleon-ultra_chameleon__chameleon_run`, Claude Code: `mcp__chameleon__chameleon_run`, other hosts similar). Always use these MCP tools for device access — never drive the CLI through Bash, because the MCP server process holds the single persistent serial connection.

## Tools

- `chameleon_state()` — one-call device snapshot (firmware, battery, active slot, slot summaries). Start every workflow with this instead of separate version/battery/slot calls.
- `chameleon_run(command, confirm_dangerous)` — run any CLI command, returns output + connection state.
- `chameleon_help(command)` — exact syntax of one command, e.g. `hf mf nested`. Call it whenever unsure of flags.
- `chameleon_catalog()` — full command list.
- `card_analyze(name_or_path)` — offline dump analysis without touching the device (library name or absolute path).
- `dict_list / dict_seed_default / dict_create / dict_merge / dict_import / dict_show` — manage Mifare key dictionaries (`.dic` = one 12-hex key per line) in `~/.chameleon_ai/dicts/`.
- `card_list / card_add / card_show / card_remove` — host-side card library in `~/.chameleon_ai/cards/` (unlimited saved dumps, independent of the 8 device slots).
- `card_load(name, slot, nick, confirm_dangerous)` — load a library card into a device slot with the verified command order (type → eload → block0 → nick); auto-picks the first free slot when slot=0.

## Collaboration modes

- **Copilot (default)**: explain each gated command in one sentence and get user approval before running it. Chain read-only steps freely.
- **Autopilot**: only when the user explicitly asks for it ("autopilot", "do the whole flow"). Then you may pre-plan the full workflow, state it once up front, and run the chain — including gated steps with `confirm_dangerous=true` — without stopping at each step. Autopilot lasts for the stated workflow only, not the whole session.
- Even in autopilot: `hw dfu`, `hw factory_reset`, and writing to a *physical* card (`hf mf clone`, `hf mf wrbl`, LF write commands) always get their own explicit confirmation.

## Safety rules (mandatory)

- Only operate on cards/devices the user owns or is explicitly authorized to test.
- **Stay card-agnostic**: cards already in the library or slots (names, UIDs, keys) are reference examples only. Never assume the type, keys, or identity of the card currently on the reader — always identify it fresh with scans, and never reuse a previous card's data as a default for a new one.
- Read-only commands (connect, scan, info, read, dump, view) run directly.
- Anything that writes a card, flashes firmware, changes device settings, or runs a key-recovery attack (fchk, autopwn, nested, darkside, hardnested, senested): first tell the user in one or two sentences what the command will do and ask for approval, then re-call `chameleon_run` with `confirm_dangerous=true` only after they agree. The server refuses otherwise.
- Never run `hw dfu` / `hw factory_reset` without an explicit user request.

## Card-type coverage map

Route every card through identify first, then its family row:

| Family | Identify / read | Key recovery | Dump / save | Emulate |
|---|---|---|---|---|
| Mifare Classic | `hf 14a scan` / `hf 14a info` (SAK 08/18/09/10/11/19) | workflow 3 decision tree | `hf mf dump -f … -d …` → `card_add` | `card_load` (or manual seq.) |
| Ultralight / NTAG | SAK 00/20 → `hf mfu version`, `hf mfu signature` | `hf mfu ulcg` (Giantec/USCUID backdoor), `hf mfu authnonce` (UL-C) | `hf mfu dump -f …` → `card_add` | `hw slot type -t NTAG_*` + `hf mfu eload` |
| DESFire | `hf des info` | `hf des chk` (dictionary/pattern) | info only at this CLI build | `hw slot type -t HF14A_4` (partial) |
| SEOS | `hf 14a info` | — | — | `hw slot type -t SEOS` + `hf seos eload` |
| EMV payment | `emv scan` | — | `emv scan -f <json>` | `emv scan -s N` / `emv load` |
| LF known family | `lf em 410x read` / `lf em 4x05 read` / `lf hid prox read` / `lf ioprox read` / `lf pac read` / `lf viking read` / `lf jablotron read` | — | record the printed ID in the library note | family `econfig` (e.g. `lf em 410x econfig`) or `hw slot type` |
| LF unknown | `lf sniff --timeout 5000 --out <file>` → `data modulation` / `data manrawdecode` | — | capture file | after family identified |
| LF families the CLI doesn't expose (FDX-B, Paradox, Keri…) | raw capture above | — | capture file | not exposed in this CLI build — say so honestly |

## Standard workflows

Command syntax below was verified against this CLI build; still call `chameleon_help` before any command you haven't run in this session.

### 1. Connect and health-check
```
chameleon_state()                  # if offline: chameleon_run("hw connect") first
```
If connect fails: check the USB-C cable (must be data-capable), unplug/replug, press a device button to wake it. After connecting, report firmware + battery + active slot from the state snapshot so the user knows the device's condition.

### 2. Identify an unknown card (universal flow)
```
chameleon_run("hf 14a scan")       # HF tag present? type, UID, SAK
chameleon_run("hf 14a info")       # HF details (SAK-guessed type; PRNG if Classic)
```
Then route by the coverage map: Mifare Classic → workflow 3; Ultralight/NTAG → `hf mfu version` + `hf mfu dump`; DESFire → `hf des info`; payment card → `emv scan`; anything unclear → `hf 14a info` again and reason from SAK/ATS.

There is no generic LF search command: try the per-family reads — `lf em 410x read`, `lf em 4x05 read`, `lf hid prox read`, `lf ioprox read`, `lf pac read`, `lf viking read`, `lf jablotron read`; if all miss, go raw: `lf sniff` + `data modulation`.

**When scans find nothing, coach the user — do not silently retry-loop.** After 2 failed attempts: card flat on the device body center, out of the wallet, away from metal/other cards, held still for the whole ~1s scan window. Then alternate HF/LF attempts. Still nothing → suggest cross-checking with the phone app to isolate placement vs card vs device.

### 3. Crack a Mifare Classic card — decision tree
Work down this list; stop at the first success. Always state expected duration before asking approval for an attack.

1. **Default dictionary** (seconds): `dict_seed_default()` once; `dict_show` → positional fchk:
   `chameleon_run("hf mf fchk --1k FFFFFFFFFFFF A0A1A2A3A4A5 ...", confirm_dangerous=true)` (`--mini/--1k/--2k/--4k` matching card size). **Never use `fchk --dic`** — broken stub in this CLI build.
2. **Targeted dictionary**: ask the user what system the card belongs to (transit, hotel, gym, office...), then web-search that system's known default/known keys (WebSearch/FetchURL; if a page is unreachable from this network, open it in the ego lite browser). Add finds with `dict_create`/`dict_merge` and rerun fchk.
3. **autopwn** (seconds–minutes): `hf mf autopwn` — chains dictionary + PRNG attacks automatically.
4. **Manual attacks by PRNG** (from `hf 14a info`; syntax via `chameleon_help`):
   - no known key → `hf mf darkside` (minutes)
   - weak PRNG, one known key → `hf mf nested --blk <dec> -a -k <hex> --tblk <dec>`
   - static-encrypted backdoor cards (FM11RF08S) → `hf mf senested`
   - hard PRNG → `hf mf hardnested --blk ... -k ... --tblk ...` (can run long — warn the user)
5. **Last resort — reader-side key recovery (mfkey32v2)**: if the card itself resists everything, harvest keys from the *reader*: pick a slot with `hw slot list`, `hf mf econfig -s N --enable-log` (confirm_dangerous), user holds the Chameleon against the real reader for one auth attempt, then `hf mf elog --decrypt` (may need several reader presentations; rerun until keys appear).
6. When all keys are known: `hf mf dump -f <dump.bin> -d <keys.dic>` (dump's `-d` dic loading works fine), then **save to the library**: ask the user for a name → `card_add(name, dump_path, uid)` → then offer slot loading (workflow 4).

### 4. Emulate a card from the device
Slot selection and naming rules (always follow):
- Run `chameleon_state()` first. Prefer a completely free slot (both HF and LF `undef`); otherwise a slot whose relevant side is unused. Never overwrite a configured slot without asking.
- If no slot is free, show the user the slot list and ask which one to replace.
- Always ask the user for a name for the card and set it after loading.

**Mifare Classic library cards: use the `card_load` tool** (handles the order correctly and auto-picks a free slot). For non-Mifare or manual control, the verified sequence is below — order matters, set the type BEFORE loading (setting the type resets emulator memory):
```
chameleon_run("hw slot type -s N -t MIFARE_1024", confirm_dangerous=true)  # 1K card; MIFARE_2048/4096 for bigger
chameleon_run("hf mf eload -f <dump.bin> [-s N]", confirm_dangerous=true)  # load dump into slot memory
chameleon_run("hf mf econfig -s N --enable-block0", confirm_dangerous=true) # present UID/ATQA/SAK from the dump's block 0
chameleon_run("hw slot enable -s N --hf", confirm_dangerous=true)           # a slot that started as "(disabled)undef" stays disabled and will NOT emulate until enabled
chameleon_run("hw slot nick -s N --hf -n <name_from_user>", confirm_dangerous=true)     # name the slot (--hf/--lf mandatory; NO quotes — the CLI stores them literally, spaces become _)
chameleon_run("hw slot change -s N", confirm_dangerous=true)                # select active slot
chameleon_run("hw slot store", confirm_dangerous=true)                      # persist to flash (survives power cycle)
```
`hw slot list` shows the settings-UID (placeholder) even when block0 mode is on — verify the real emulated data with `hf mf eview -s N` instead. The device emulates the active slot when presented to a reader. If the reader writes to the card (counters/value blocks), set the write mode first: `hf mf econfig -s N --write NORMAL|DENIED|DECEIVE|SHADOW` (DENIED = read-only emulation, SHADOW = accept writes then discard). Detection logs from readers: `hf mf elog`.

**Non-Classic emulation** (same slot rules apply):
- Ultralight/NTAG: `hw slot type -s N -t NTAG_213` (or 210/212/215/216, matching the dump), then `hf mfu eload -f <dump> -s N`; verify with `hf mfu eview`.
- LF cards: set the emulated ID with the family's `econfig` (e.g. `lf em 410x econfig --id …`, check `chameleon_help` per family) and the slot type via `hw slot type`.
- SEOS / generic ISO14443-4: `hw slot type -t SEOS` + `hf seos eload`, or `emv load` for EMV APDU responses.

### 5. Recon and special workflows
- **Understand an unknown reader** before emulating: `hf 14a sniff` (hold device near reader; logs the reader's frames; `--timeout` up to 30000 ms). Deep auth debug against a real card: `hf 14a auth-trace`.
- **Payment card**: `emv scan` — add `-s N` to also load it into a slot for emulation in one step (that form writes the slot, so it needs `confirm_dangerous=true`).
- **Unknown LF card**: `lf sniff --timeout 5000 --out <file>` then `data modulation`, `data manrawdecode`, `data plot --ascii` to identify the encoding before picking a per-family write.

### 6. Write / clone to a physical card
- Mifare: `hf mf clone -f <dump.bin> -d <keys.dic>` — warn the user: adding `-a` also writes access bits and **can brick the tag**. Single block: `hf mf wrbl --blk N -a -k <hex> -d <hex>`.
- LF (onto a T5577 blank): `lf em 410x write`, `lf hid prox write`, or the generic `lf clone`.

## Troubleshooting

- **Serial desync** (flood of `Data frame no sof byte`, `Chameleon Connect fail: CMD ... exec timeout`): the device's USB state is wedged, usually because a process holding the port was killed mid-connection (e.g. `/reload` or plugin reinstall while connected). Fix: unplug and replug the USB-C cable, then `hw connect` again. Prevention: run `hw disconnect` before reloading Kimi Code or reinstalling the plugin.
- **Command returns "(no output)" unexpectedly**: check whether it's a known upstream stub (fchk `--dic`) before assuming capture failure.
- **Slot list shows a placeholder UID after loading a dump**: normal when block0 mode is on — verify with `hf mf eview -s N`, not the slot list.
- **A T5577 blank isn't detectable until it's been written once** (vendor FAQ) — write a first ID, then it reads normally.
- **LF never works on some units** (vendor FAQ: antenna issue on some black RRG units) — if every LF read/write fails with correct technique, suspect hardware, not commands.

## Reporting results
Summarize in a small table: card type, UID, which sectors/keys were recovered (and how), what remains locked. Never paste full card dumps into chat unless the user asks — save them to files and give the path.
