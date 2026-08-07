"""Verify the bug fix: Export can be called with empty translated placeholders
right after SCAN & EXTRACT (no AI translation needed). Then Insert (import)
patches the ROM with the edited TXT."""
import os
import io
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://retro-localize.preview.emergentagent.com').rstrip('/')
API = f"{BASE_URL}/api"


def _make_mini_rom():
    data = bytearray(4096)
    strings = [b'HELLO WORLD', b'GAME OVER MAN', b'PRESS START BUTTON']
    for i, s in enumerate(strings):
        off = 0x100 + i * 32
        data[off:off + len(s)] = s
    return bytes(data), strings


def _extract():
    rom, strings = _make_mini_rom()
    files = {"file": ("mini.gb", rom, "application/octet-stream")}
    data = {"encoding": "ascii", "max_strings": "500"}
    r = requests.post(f"{API}/rom/extract", files=files, data=data, timeout=60)
    assert r.status_code == 200, f"extract failed {r.status_code}: {r.text[:400]}"
    payload = r.json()
    assert payload["session_id"]
    assert len(payload["strings"]) >= 3, f"expected >=3 strings, got {payload['strings']}"
    return payload, rom, strings


def test_extract_returns_session_and_strings():
    payload, _, _ = _extract()
    assert payload["encoding"] == "ascii"
    texts = [s["text"] for s in payload["strings"]]
    for expected in ["HELLO WORLD", "GAME OVER MAN", "PRESS START BUTTON"]:
        assert any(expected in t for t in texts), f"missing {expected} in {texts}"


def test_export_with_empty_placeholders_returns_text_plain():
    """BUG FIX: Export must work with translated='' placeholders (no AI run)."""
    payload, _, _ = _extract()
    items = [{"id": s["id"], "original": s["text"], "translated": ""} for s in payload["strings"]]
    body = {"session_id": payload["session_id"], "translations": items}
    r = requests.post(f"{API}/rom/export", json=body, timeout=30)
    assert r.status_code == 200, f"export failed {r.status_code}: {r.text[:400]}"
    ctype = r.headers.get("content-type", "")
    assert "text/plain" in ctype, f"expected text/plain got {ctype}"
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd and ".txt" in cd, cd
    body_text = r.text
    # Header lines starting with #
    assert body_text.startswith("#"), body_text[:200]
    assert "# ROM Translator" in body_text
    # Each original present with a TAB delimiter and empty translated
    for s in payload["strings"]:
        line = f"{s['text']}\t"
        assert line in body_text, f"missing line for {s['text']!r}"


def test_import_patches_rom_after_extract_only():
    """BUG FIX: Insert Translation should work right after SCAN, without TRANSLATE."""
    payload, original_rom, _ = _extract()
    # Build a TXT file with real translations
    lines = [
        "# comment line",
        "",
        "HELLO WORLD\tAHOJ SVETE",
        "GAME OVER MAN\tKONEC HRY BRO",
        "PRESS START BUTTON\tSTISKNI STARTUJ",
    ]
    txt = ("\n".join(lines) + "\n").encode("utf-8")
    files = {"file": ("edited.txt", txt, "text/plain")}
    data = {"session_id": payload["session_id"]}
    r = requests.post(f"{API}/rom/import", files=files, data=data, timeout=30)
    assert r.status_code == 200, f"import failed {r.status_code}: {r.text[:400]}"
    assert r.headers.get("content-type", "").startswith("application/octet-stream")
    patched = int(r.headers.get("x-patched-count", "0"))
    assert patched == 3, f"expected 3 patched, got {patched}"
    binary = r.content
    assert len(binary) == len(original_rom)
    # Verify patched bytes at correct offsets
    assert b"AHOJ SVETE" in binary
    assert b"KONEC HRY BRO" in binary
    assert b"STISKNI STARTUJ"[:len("PRESS START BUTTON")] in binary or b"STISKNI STARTUJ" in binary
    # Original strings should be overwritten (at the exact offsets from extract)
    for s in payload["strings"]:
        if s["text"] == "HELLO WORLD":
            off = s["offset"]
            length = s["length"]
            patched_bytes = binary[off:off + length]
            # AHOJ SVETE padded with spaces to length
            assert patched_bytes.startswith(b"AHOJ SVETE"), patched_bytes


def test_import_no_lines_returns_400():
    payload, _, _ = _extract()
    files = {"file": ("empty.txt", b"# only comments\n\n", "text/plain")}
    data = {"session_id": payload["session_id"]}
    r = requests.post(f"{API}/rom/import", files=files, data=data, timeout=30)
    assert r.status_code == 400


def test_export_unknown_session_returns_404():
    body = {"session_id": "does-not-exist-xxx", "translations": []}
    r = requests.post(f"{API}/rom/export", json=body, timeout=15)
    assert r.status_code == 404
