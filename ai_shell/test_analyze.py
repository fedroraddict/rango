"""Permanent regression tests for ai_shell.analyze.

Run: uv run python -m ai_shell.test_analyze   (also pytest-compatible)

Born from a code review that caught a 4K crash and wrong access tables —
the size matrix and the datasheet tables are asserted here for good.
Expected access-condition values follow NXP MF1S50YYX datasheet Tables 7/8.
"""

from .analyze import (
    _DATA_ACCESS,
    _TRAILER_ACCESS,
    _access_bits,
    _triplet_index,
    analyze_dump,
    format_report,
)

DEFAULT_TRAILER = bytes.fromhex("FFFFFFFFFFFF" "FF078069" "FFFFFFFFFFFF")


def make_classic(nblocks: int, trailer: bytes = DEFAULT_TRAILER) -> bytearray:
    d = bytearray(nblocks * 16)
    d[0:4] = bytes.fromhex("DEADBEEF")
    d[4] = 0xDE ^ 0xAD ^ 0xBE ^ 0xEF
    d[5] = 0x08
    d[6:8] = bytes.fromhex("0400")
    layouts = [4] * 32 + [16] * ((nblocks - 128) // 16 if nblocks > 128 else 0)
    blk = 0
    for n in layouts[: len(layouts) if nblocks > 128 else nblocks // 4]:
        d[(blk + n - 1) * 16:(blk + n) * 16] = trailer
        blk += n
    return d


def test_size_matrix():
    for size, nsectors in ((320, 5), (1024, 16), (2048, 32), (4096, 40)):
        r = analyze_dump(bytes(make_classic(size // 16)))
        assert "error" not in r, (size, r)
        assert len(r["sectors"]) == nsectors, (size, len(r["sectors"]))
        assert r["sectors"][-1]["access_consistent"]
    r4k = analyze_dump(bytes(make_classic(256)))
    assert len(r4k["sectors"][39]["blocks"]) == 16
    assert len(r4k["sectors"][39]["data_access"]) == 15
    for bad in (46, 51, 62):  # too small or not a multiple of 4
        assert "error" in analyze_dump(bytes(bad)), bad


def test_ntag_sizes():
    for size in (48, 144, 180, 540, 924):
        r = analyze_dump(bytes(size))
        assert "error" not in r and "sectors" not in r, size
        assert f"{size // 4} pages" in r["type"]


def test_ff0780_decode():
    acc = _access_bits(bytes.fromhex("000000000000" "FF0780" "69" "000000000000"))
    assert acc["consistent"] and acc["raw"] == "FF0780"
    assert acc["blocks"][:3] == [(0, 0, 0)] * 3 and acc["blocks"][3] == (0, 0, 1)


def test_trailer_table_matches_datasheet():
    # NXP MF1S50YYX Table 8: (keyA r/w, access-bits r/w, keyB r/w)
    expected = {
        (0, 0, 0): ("-/A", "A/-", "A/A"),
        (0, 1, 0): ("-/-", "A/-", "A/-"),
        (1, 0, 0): ("-/B", "A|B/-", "-/B"),
        (1, 1, 0): ("-/-", "A|B/-", "-/-"),
        (0, 0, 1): ("-/A", "A/A", "A/A"),
        (0, 1, 1): ("-/B", "A|B/B", "-/B"),
        (1, 0, 1): ("-/-", "A|B/B", "-/-"),
        (1, 1, 1): ("-/-", "A|B/-", "-/-"),
    }
    assert expected == _TRAILER_ACCESS


def test_data_table_matches_datasheet():
    assert _DATA_ACCESS[(1, 1, 0)] == ("A|B", "B", "B", "A|B")  # value-block config
    assert _DATA_ACCESS[(0, 0, 0)] == ("A|B", "A|B", "A|B", "A|B")  # transport


def test_4k_triplet_mapping():
    assert [_triplet_index(i, 16) for i in range(16)] == [0] * 5 + [1] * 5 + [2] * 5 + [3]
    assert [_triplet_index(i, 4) for i in range(4)] == [0, 1, 2, 3]


def test_value_block_and_content():
    d = make_classic(64)
    v = (1337).to_bytes(4, "little", signed=True)
    d[64:80] = v + bytes(b ^ 0xFF for b in v) + v + bytes([1, 0xFE, 1, 0xFE])
    d[128:144] = b"HELLO WORLD CARD"[:16]
    r = analyze_dump(bytes(d))
    assert r["value_blocks"] == [{"block": 4, "value": 1337}]
    assert any(c["kind"] == "value-block" for c in r["sectors"][1]["content"])
    assert r["sectors"][0]["content"][0]["kind"] == "manufacturer"
    assert any("HELLO WORLD CARD" in t for h in r["ascii"] for t in h["text"])


def test_custom_keys_masked_everywhere():
    d = make_classic(64)
    custom = bytes.fromhex("112233445566")
    d[14 * 64 + 58:14 * 64 + 64] = custom
    d[15 * 64 + 58:15 * 64 + 64] = custom
    r = analyze_dump(bytes(d))
    report = format_report(r)
    assert "112233445566" not in report
    assert "1122••••••••" in report and "sectors [14, 15]" in report


def test_7byte_uid_labeled():
    d = make_classic(64)
    d[0:8] = bytes.fromhex("88AABBCC" "11" "0804" "00")
    d[4] = 0x88 ^ 0xAA ^ 0xBB ^ 0xCC
    r = analyze_dump(bytes(d))
    assert r["uid_7byte"] and r["uid"] == "AABBCC"
    assert "7-byte UID" in format_report(r)


def test_inconsistent_access_bits_flagged():
    d = make_classic(64)
    d[54:58] = bytes.fromhex("FFFFFF69")  # broken inverted copies
    r = analyze_dump(bytes(d))
    assert not r["sectors"][0]["access_consistent"]
    assert "permissions moot" in format_report(r)


def test_ndef_scan_ignores_trailers():
    d = make_classic(64)
    # 03 05 D1 looks like an NDEF TLV but sits inside a (random) key in a trailer
    d[3 * 16 + 10:3 * 16 + 13] = bytes([0x03, 0x05, 0xD1])
    r = analyze_dump(bytes(d))
    assert r["ndef_hint"] is None
    # ...and a real one in a data block is found
    d[5 * 16:5 * 16 + 3] = bytes([0x03, 0x05, 0xD1])
    r = analyze_dump(bytes(d))
    assert r["ndef_hint"] and "block 5" in r["ndef_hint"]


def test_ndef_long_form_tlv():
    d = make_classic(64)
    d[5 * 16:5 * 16 + 5] = bytes([0x03, 0xFF, 0x01, 0x00, 0xD1])  # 256-byte message
    r = analyze_dump(bytes(d))
    assert r["ndef_hint"] and "256 bytes" in r["ndef_hint"]


def test_flipper_nfc_input(tmp_path=None):
    import tempfile
    from pathlib import Path

    from .analyze import analyze_path

    d = make_classic(64)
    lines = ["Filetype: Flipper NFC device", "Version: 4", "Device type: Mifare Classic",
             "UID: DE AD BE EF", "ATQA: 00 04", "SAK: 08", "Mifare Classic type: 1K"]
    for b in range(64):
        hexbytes = " ".join(f"{x:02X}" for x in d[b * 16:(b + 1) * 16])
        if b == 10:  # an unread block
            hexbytes = " ".join(["??"] * 16)
        lines.append(f"Block {b}: {hexbytes}")
    with tempfile.NamedTemporaryFile("w", suffix=".nfc", delete=False, encoding="utf-8") as f:
        f.write("\n".join(lines))
        path = Path(f.name)
    try:
        report = analyze_path(path)
    finally:
        path.unlink()
    assert "Source: Flipper .nfc v4" in report
    assert "incomplete dump" in report
    assert "UID: DEADBEEF" in report
    assert "Mifare Classic 1K" in report


def test_key_fingerprint_saflok():
    d = make_classic(64)
    d[1 * 64 + 48:1 * 64 + 54] = bytes.fromhex("2A2C13CC242A")  # sector 1 keyA
    r = analyze_dump(bytes(d))
    assert any("Saflok" in f for f in r["fingerprints"])
    assert "identified: Saflok" in format_report(r)


def test_sak_size_mismatch():
    d = make_classic(64)
    d[5] = 0x18  # SAK says 4K, file is 1K
    r = analyze_dump(bytes(d))
    assert r["size_mismatch"] and r["sak_type"] == "Mifare Classic 4K"
    assert "ANOMALY" in format_report(r)
    d2 = make_classic(64)
    r2 = analyze_dump(bytes(d2))
    assert not r2["size_mismatch"] and r2["sak_type"] == "Mifare Classic 1K"


def test_ntag_possible_types():
    assert analyze_dump(bytes(180))["possible_types"] == "NTAG213"
    assert analyze_dump(bytes(924))["possible_types"] == "NTAG216"
    assert "or" in analyze_dump(bytes(80))["possible_types"]  # ambiguous 20-page
    assert "Possible types" in format_report(analyze_dump(bytes(180)))


def test_named_acl_in_report():
    r = analyze_dump(bytes(make_classic(64)))
    assert "transport configuration" in format_report(r)


def test_mad_gpb_da_bit():
    d = make_classic(64)
    d[48:54] = bytes.fromhex("A0A1A2A3A4A5")  # sector 0 keyA = MAD key
    d[57] = 0x69  # GPB: DA bit clear -> no confirmation
    r = analyze_dump(bytes(d))
    assert r["mad"].startswith("MAD1") and "GPB confirms" not in r["mad"]
    d[57] = 0xC1  # DA bit set, version 01 -> confirms MAD1
    r = analyze_dump(bytes(d))
    assert "GPB confirms MAD1" in r["mad"]


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok {t.__name__}")
    print(f"all {len(tests)} analyze tests passed")


if __name__ == "__main__":
    main()
