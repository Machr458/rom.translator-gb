"""Character map encodings for various retro game ROMs.

Currently supported:
- ascii: standard printable ASCII (default for homebrew and many GBA tools)
- pokemon_gen3: Pokemon Ruby/Sapphire/Emerald/FireRed/LeafGreen custom encoding
"""

# ---------- Pokemon Gen 3 (Emerald/Ruby/Sapphire/FRLG) ----------
# Reference: https://bulbapedia.bulbagarden.net/wiki/Character_encoding_in_Generation_III

POKEMON_GEN3_CHARMAP: dict[int, str] = {
    0x00: " ",
    # Digits 0-9 at 0xA1-0xAA
    **{0xA1 + i: str(i) for i in range(10)},
    0xAB: "!",
    0xAC: "?",
    0xAD: ".",
    0xAE: "-",
    0xAF: "\xB7",   # middle dot
    0xB0: "\u2026", # ellipsis
    0xB1: '"',
    0xB2: '"',
    0xB3: "'",
    0xB4: "'",
    0xB5: "M",  # male symbol -> M (ASCII fallback)
    0xB6: "F",  # female symbol -> F
    0xB7: "$",
    0xB8: ",",
    0xB9: "x",
    0xBA: "/",
    # A-Z at 0xBB-0xD4
    **{0xBB + i: chr(ord("A") + i) for i in range(26)},
    # a-z at 0xD5-0xEE
    **{0xD5 + i: chr(ord("a") + i) for i in range(26)},
    0xEF: ":",
    0xF0: "\xC4",   # A umlaut fallback
    0xF1: "\xD6",   # O umlaut fallback
    0xF2: "\xDC",   # U umlaut
    0xF3: "\xE4",
    0xF4: "\xF6",
    0xF5: "\xFC",
}

# Reverse map (single-char strings only) for encoding text -> bytes.
POKEMON_GEN3_ENCODE: dict[str, int] = {v: k for k, v in POKEMON_GEN3_CHARMAP.items() if len(v) == 1}
# Prefer 0x00 for ASCII space (padding is 0x00)
POKEMON_GEN3_ENCODE[" "] = 0x00

# Control bytes that terminate a text run
GEN3_CONTROL_BYTES = {0xFF, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE}


def _is_gen3_letter(b: int) -> bool:
    return 0xBB <= b <= 0xD4 or 0xD5 <= b <= 0xEE


def _is_gen3_char(b: int) -> bool:
    return b in POKEMON_GEN3_CHARMAP


def extract_pokemon_gen3_runs(data: bytes, min_length: int = 8, max_results: int = 200):
    """Return list of (offset, length, decoded_text) tuples for Pokemon Gen 3 text runs.

    A "run" starts at a letter byte and continues while consecutive bytes are
    valid Gen3 characters (letters, digits, punctuation, space=0x00). The run
    ends at any Gen3 control byte (0xFA/0xFB/0xFC/0xFD/0xFE/0xFF) or an invalid
    byte. The length reported is bytes (== characters in Gen3).
    """
    results = []
    seen = set()
    i = 0
    n = len(data)
    while i < n:
        if _is_gen3_letter(data[i]):
            start = i
            chars = []
            while i < n and _is_gen3_char(data[i]):
                chars.append(POKEMON_GEN3_CHARMAP[data[i]])
                i += 1
            length = i - start
            # Must be terminated by a control byte
            if i < n and data[i] in GEN3_CONTROL_BYTES and length >= min_length:
                text = "".join(chars).rstrip()
                if len(text) < min_length:
                    i += 1
                    continue
                letters = sum(1 for c in text if c.isalpha())
                spaces = sum(1 for c in text if c == " ")
                # Reject padding-heavy runs (mostly 0x00 with just one letter)
                if letters < 3 or spaces > len(text) * 0.7:
                    i += 1
                    continue
                key = text.lower()
                if key not in seen:
                    seen.add(key)
                    results.append((start, length, text))
                    if len(results) >= max_results:
                        break
            else:
                # not a valid run; move past first byte only to allow re-scan
                i = start + 1
        else:
            i += 1
    return results


def count_pokemon_gen3_runs(data: bytes, min_length: int = 5) -> int:
    """Count total unique Gen3 text runs (for user info)."""
    seen = set()
    i = 0
    n = len(data)
    while i < n:
        if _is_gen3_letter(data[i]):
            start = i
            chars = []
            while i < n and _is_gen3_char(data[i]):
                chars.append(POKEMON_GEN3_CHARMAP[data[i]])
                i += 1
            length = i - start
            if i < n and data[i] in GEN3_CONTROL_BYTES and length >= min_length:
                text = "".join(chars).rstrip()
                letters = sum(1 for c in text if c.isalpha())
                spaces = sum(1 for c in text if c == " ")
                if len(text) >= min_length and letters >= 3 and spaces <= len(text) * 0.7:
                    seen.add(text.lower())
            else:
                i = start + 1
        else:
            i += 1
    return len(seen)


def encode_pokemon_gen3(text: str, target_length: int) -> bytes:
    """Encode ASCII text into Pokemon Gen 3 bytes, padded/truncated to target_length.

    Unknown characters fall back to space (0x00).
    """
    out = bytearray()
    for ch in text:
        b = POKEMON_GEN3_ENCODE.get(ch)
        if b is None:
            # Try common substitutions
            b = POKEMON_GEN3_ENCODE.get(ch.upper()) or POKEMON_GEN3_ENCODE.get(ch.lower()) or 0x00
        out.append(b)
    if len(out) > target_length:
        return bytes(out[:target_length])
    return bytes(out) + b"\x00" * (target_length - len(out))


def detect_encoding(data: bytes, filename: str) -> str:
    """Auto-detect ROM encoding. Returns 'pokemon_gen3' or 'ascii'."""
    fn = filename.lower()
    # GBA header: game code at 0xAC (4 bytes), title at 0xA0 (12 bytes)
    if len(data) >= 0xB0:
        title = bytes(data[0xA0:0xAC]).decode("ascii", errors="ignore").upper()
        code = bytes(data[0xAC:0xB0]).decode("ascii", errors="ignore").upper()
        pokemon_indicators = ("POKEMON", "POKEM")
        pokemon_codes = ("BPE", "BPR", "BPG", "AXV", "AXP")  # Emerald, FireRed, LeafGreen, Ruby, Sapphire
        if any(t in title for t in pokemon_indicators) or any(code.startswith(c) for c in pokemon_codes):
            return "pokemon_gen3"
    # Filename hint
    if any(word in fn for word in ("pokemon", "emerald", "ruby", "sapphire", "firered", "leafgreen")):
        return "pokemon_gen3"
    return "ascii"
