"""Story-focused text extraction for Pokemon Gen1/Gen2 (GB/GBC), Gen3 (GBA) and ASCII ROMs.

Whole messages are decoded up to their terminator; in-text control codes become {tokens}
so a single dialog stays one string. Names (fixed-stride tables, ALL-CAPS labels) are
split off into a glossary; junk is filtered by readability heuristics."""

import re
import unicodedata
from collections import defaultdict

TOKEN_RE = re.compile(r"\{[^{}]{1,16}\}")


class Codec:
    def __init__(self, chars, tokens, end, fill, letters, start_prev, special=None, token_bytes=None):
        self.chars = chars
        self.tokens = tokens
        self.end = end
        self.fill = fill
        self.letters = letters
        self.start_prev = start_prev
        self.special = special
        self.plain_bytes = {b for b, c in chars.items() if re.fullmatch(r"[A-Za-z0-9 .,!?:;'’‘“”…\-é]+", c)}
        multi = sorted(((c, b) for b, c in chars.items()), key=lambda x: -len(x[0]))
        self.enc_pairs = [(c, b) for c, b in multi if len(c) == 1 or c[0] == "'" or c == "POKé"]
        self.enc_single = {c: b for c, b in multi if len(c) == 1}
        self.token_bytes = {v: bytes([k]) for k, v in tokens.items()}
        self.token_bytes.update(token_bytes or {})
        self.space = self.enc_single[" "]

    def decode(self, data: bytes, start: int, max_len: int = 1200):
        n, out, i = len(data), [], start
        while i < n and i - start < max_len:
            b = data[i]
            if b in self.end:
                return (i - start, "".join(out)) if i > start else None
            if b in self.chars:
                out.append(self.chars[b])
                i += 1
            elif b in self.tokens:
                out.append("{" + self.tokens[b] + "}")
                i += 1
            else:
                r = self.special(data, i) if self.special else None
                if not r:
                    return None
                out.append(r[0])
                i += r[1]
        return None

    def _tok(self, tok: str):
        inner = tok[1:-1]
        if inner in self.token_bytes:
            return self.token_bytes[inner]
        try:
            return bytes(int(p, 16) for p in inner.split(":"))
        except ValueError:
            return None

    def encode(self, text: str) -> bytes:
        out, pos = bytearray(), 0
        for m in list(TOKEN_RE.finditer(text)) + [None]:
            chunk = text[pos:m.start()] if m else text[pos:]
            j = 0
            while j < len(chunk):
                for c, b in self.enc_pairs:
                    if len(c) > 1 and chunk.startswith(c, j):
                        out.append(b)
                        j += len(c)
                        break
                else:
                    ch = chunk[j]
                    b = self.enc_single.get(ch)
                    if b is None:
                        base = unicodedata.normalize("NFD", ch)[0]
                        b = self.enc_single.get(base, self.enc_single.get(ch.upper(), self.space))
                    out.append(b)
                    j += 1
            if m is None:
                break
            tb = self._tok(m.group())
            if tb:
                out += tb
            pos = m.end()
        return bytes(out)

    def units(self, text: str):
        """Encoded units (bytes per char/token) used for boundary-safe truncation."""
        res, pos = [], 0
        for m in list(TOKEN_RE.finditer(text)) + [None]:
            chunk = text[pos:m.start()] if m else text[pos:]
            if chunk:
                res.extend(self.encode(ch) for ch in chunk)
            if m is None:
                break
            res.append(self.encode(m.group()))
            pos = m.end()
        return res

    def patch_payload(self, text: str, length: int, terminator: int) -> bytes:
        """length = original message bytes (excl. terminator). Returns length+1 bytes."""
        out = bytearray()
        for u in self.units(text):
            if len(out) + len(u) > length:
                break
            out += u
        out.append(terminator)
        return bytes(out) + bytes([self.fill]) * (length + 1 - len(out))


# ---------- Gen3 (Ruby/Sapphire/Emerald/FRLG) ----------
_G3 = {0x00: " ", **{0xA1 + i: str(i) for i in range(10)},
       0xAB: "!", 0xAC: "?", 0xAD: ".", 0xAE: "-", 0xAF: "·", 0xB0: "…", 0xB1: "“", 0xB2: "”",
       0xB3: "‘", 0xB4: "’", 0xB7: "$", 0xB8: ",", 0xB9: "×", 0xBA: "/",
       **{0xBB + i: chr(65 + i) for i in range(26)}, **{0xD5 + i: chr(97 + i) for i in range(26)},
       0xF0: ":", 0xF1: "Ä", 0xF2: "Ö", 0xF3: "Ü", 0xF4: "ä", 0xF5: "ö", 0xF6: "ü",
       0x01: "À", 0x02: "Á", 0x03: "Â", 0x04: "Ç", 0x05: "È", 0x06: "É", 0x07: "Ê", 0x08: "Ë",
       0x09: "Ì", 0x0B: "Î", 0x0C: "Ï", 0x0D: "Ò", 0x0E: "Ó", 0x0F: "Ô", 0x11: "Ù", 0x12: "Ú",
       0x13: "Û", 0x14: "Ñ", 0x16: "à", 0x17: "á", 0x19: "ç", 0x1A: "è", 0x1B: "é", 0x1C: "ê",
       0x1D: "ë", 0x1E: "ì", 0x20: "î", 0x21: "ï", 0x22: "ò", 0x23: "ó", 0x24: "ô", 0x26: "ù",
       0x27: "ú", 0x28: "û", 0x29: "ñ", 0x2D: "&", 0x2E: "+", 0x35: "=", 0x36: ";", 0x5A: "Í",
       0x5B: "%", 0x5C: "(", 0x5D: ")", 0x68: "â", 0x6F: "í", 0x85: "<", 0x86: ">"}
_G3_TOK = {0xFE: "n", 0xFA: "l", 0xFB: "p", 0x34: "LV", 0x53: "PK", 0x54: "MN",
           0xB5: "MALE", 0xB6: "FEMALE", 0xEF: "ARROW"}
_G3_FD = {0x01: "PLAYER", 0x02: "STR1", 0x03: "STR2", 0x04: "STR3", 0x05: "KUN", 0x06: "RIVAL",
          0x07: "VERSION", 0x08: "AQUA", 0x09: "MAGMA", 0x0A: "ARCHIE", 0x0B: "MAXIE",
          0x0C: "KYOGRE", 0x0D: "GROUDON"}
_G3_FC = {0x01: 1, 0x02: 1, 0x03: 1, 0x04: 3, 0x05: 1, 0x06: 1, 0x07: 0, 0x08: 1, 0x09: 0, 0x0A: 0,
          0x0B: 2, 0x0C: 1, 0x0D: 1, 0x0E: 1, 0x0F: 0, 0x10: 2, 0x11: 1, 0x12: 1, 0x13: 1, 0x14: 1,
          0x15: 0, 0x16: 0, 0x17: 0, 0x18: 0}


def _g3_special(data, i):
    b, n = data[i], len(data)
    if i + 1 >= n:
        return None
    a = data[i + 1]
    if b == 0xFD and 0x01 <= a <= 0x40:
        return ("{" + _G3_FD.get(a, f"FD:{a:02X}") + "}", 2)
    if b == 0xFC and a in _G3_FC:
        k = _G3_FC[a]
        if i + 2 + k > n:
            return None
        return ("{FC:" + ":".join(f"{x:02X}" for x in data[i + 1:i + 2 + k]) + "}", 2 + k)
    if b in (0xF7, 0xF8, 0xF9):
        return (f"{{{b:02X}:{a:02X}}}", 2)
    return None


GEN3 = Codec(_G3, _G3_TOK, end={0xFF}, fill=0xFF, letters=set(range(0xBB, 0xEF)) | {0xFC, 0xFD},
             start_prev={0xFF, 0x00}, special=_g3_special,
             token_bytes={v: bytes([0xFD, k]) for k, v in _G3_FD.items()})

# ---------- Gen1 (Red/Blue/Yellow) & Gen2 (Gold/Silver/Crystal) ----------
_GB_BASE = {0x7F: " ", **{0x80 + i: chr(65 + i) for i in range(26)}, **{0xA0 + i: chr(97 + i) for i in range(26)},
            0x9A: "(", 0x9B: ")", 0x9C: ":", 0x9D: ";", 0x9E: "[", 0x9F: "]",
            0xE0: "'", 0xE3: "-", 0xE6: "?", 0xE7: "!", 0xE8: ".", 0xF1: "×", 0xF3: "/", 0xF4: ",",
            0x72: "“", 0x73: "”", 0x75: "…", **{0xF6 + i: str(i) for i in range(10)},
            0x4A: "PKMN", 0x54: "POKé", 0x5B: "PC", 0x5C: "TM", 0x5D: "TRAINER", 0x5E: "ROCKET"}
_GB_TOK = {0x4E: "next", 0x4F: "n", 0x51: "p", 0x55: "l", 0x4C: "scroll", 0x4B: "_cont",
           0x52: "PLAYER", 0x53: "RIVAL", 0x56: "DOTS", 0x59: "TARGET", 0x5A: "USER", 0x5F: "DEXEND",
           0xE1: "PK", 0xE2: "MN", 0xEF: "MALE", 0xF5: "FEMALE", 0xF0: "YEN", 0xF2: "DOT",
           0xEC: "ARROW2", 0xED: "ARROW", 0xEE: "DOWN"}
GEN1 = Codec({**_GB_BASE, 0x70: "‘", 0x71: "’", 0xBA: "é", 0xBB: "'d", 0xBC: "'l", 0xBD: "'s",
              0xBE: "'t", 0xBF: "'v", 0xE4: "'r", 0xE5: "'m"},
             {**_GB_TOK, 0x49: "page"}, end={0x50, 0x57, 0x58}, fill=0x50,
             letters=set(range(0x80, 0x9A)) | set(range(0xA0, 0xBA)) | {0x52, 0x53, 0x54, 0x72},
             start_prev={0x00, 0x50, 0x57, 0x58})
GEN2 = Codec({**_GB_BASE, 0xC0: "Ä", 0xC1: "Ö", 0xC2: "Ü", 0xC3: "ä", 0xC4: "ö", 0xC5: "ü",
              0xD0: "'d", 0xD1: "'l", 0xD2: "'m", 0xD3: "'r", 0xD4: "'s", 0xD5: "'t", 0xD6: "'v",
              0xE9: "&", 0xEA: "é"},
             {**_GB_TOK, 0x49: "MOM", 0x14: "PLAY_G", 0x38: "RED", 0x39: "GREEN", 0x1F: "BSP",
              0x22: "LF", 0x25: "WBR", 0x24: "POKE2"},
             end={0x50, 0x57, 0x58}, fill=0x50,
             letters=set(range(0x80, 0x9A)) | set(range(0xA0, 0xBA)) | {0x52, 0x53, 0x54, 0x72, 0x14},
             start_prev={0x00, 0x50, 0x57, 0x58})

GEN3.enc_single.update({"'": 0xB4, '"': 0xB1, "`": 0xB3})
for _c in (GEN1, GEN2):
    _c.enc_single.update({"’": 0xE0, "‘": 0xE0, '"': 0x72})

CODECS = {"pokemon_gen3": GEN3, "pokemon_gen1": GEN1, "pokemon_gen2": GEN2}
BREAK_TOKENS = ("{n}", "{p}", "{l}", "{next}", "{page}", "{scroll}", "{LF}")
PLAIN_CHARS = re.compile(r"[A-Za-z0-9 .,!?:;'’‘“”…\-]")


# ---------- Scanning ----------
def _starts_ok(c: Codec, data: bytes, i: int) -> bool:
    if i == 0:
        return True
    p = data[i - 1]
    return p in c.start_prev or p not in c.plain_bytes


def _head_clean(text: str) -> bool:
    return all(PLAIN_CHARS.match(ch) for ch in TOKEN_RE.sub("", text)[:3])


def scan_bytewise(c: Codec, data: bytes):
    res, i, n = [], 0, len(data)
    while i < n:
        if data[i] in c.letters and _starts_ok(c, data, i):
            r = c.decode(data, i)
            if r and _head_clean(r[1]):
                res.append((i, r[0], r[1]))
                i += r[0] + 1
                continue
        i += 1
    return res


def scan_gba_pointers(c: Codec, data: bytes):
    res, n = {}, len(data)
    for i in range(0xC0, n - 3, 4):
        b3 = data[i + 3]
        if b3 not in (0x08, 0x09):
            continue
        off = data[i] | (data[i + 1] << 8) | (data[i + 2] << 16) | ((b3 - 0x08) << 24)
        if off >= n or off in res:
            continue
        if data[off] in c.letters and _starts_ok(c, data, off):
            r = c.decode(data, off)
            if r and _head_clean(r[1]):
                res[off] = (off, r[0], r[1])
    return sorted(res.values())


PRINTABLE_RE = re.compile(rb"[\x20-\x7E]{4,}")


def scan_ascii(data: bytes):
    return [(m.start(), len(m.group()), m.group().decode("ascii").strip()) for m in PRINTABLE_RE.finditer(data)]


# ---------- Classification ----------
VOWELS = set("aeiouAEIOUéÉ")
RARE = set("qxzjQXZJ")
COMMON_STORY_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "can", "did", "do", "for", "from",
    "got", "has", "have", "he", "her", "here", "i", "in", "is", "it", "me", "my", "of",
    "on", "or", "our", "she", "so", "the", "they", "this", "to", "was", "we", "were",
    "will", "with", "won", "you", "your", "win", "lose", "lost",
}


TOKEN_LEGEND = [
    ("{n}", "new line inside the text box"),
    ("{l}", "scroll: continue on the next line (text box scrolls up)"),
    ("{p}", "new text box (waits for the A button)"),
    ("{next}", "next line (Pokedex / menus)"),
    ("{page}", "next Pokedex page"),
    ("{PLAYER} / {RIVAL}", "player's / rival's name inserted by the game"),
    ("{STR1} {STR2} {STR3}", "variable text inserted by the game (item, Pokemon, number...)"),
    ("{KUN}", "honorific after the player's name (empty in English)"),
    ("{TARGET} / {USER}", "battle: target / attacking Pokemon name"),
    ("{FC:..} {FD:..} {F7:..} {F8:..} {F9:..}", "game commands (colors, pauses, sounds, button icons, variables)"),
    ("{PK} {MN} {LV} {MALE} {FEMALE} {ARROW} {DOTS}", "special symbols"),
]
BREAK_SET = {"{n}", "{l}", "{p}", "{next}", "{page}", "{scroll}", "{_cont}", "{LF}", "{BSP}", "{WBR}"}


def required_tokens(text: str):
    """Non-layout tokens (variables/commands) that a translation must keep."""
    return sorted(t for t in TOKEN_RE.findall(text) if t not in BREAK_SET)


def plain_text(text: str) -> str:
    return TOKEN_RE.sub(" ", text).strip()


def _is_readable(text: str) -> bool:
    p = plain_text(text)
    letters = [ch for ch in p if ch.isalpha()]
    if len(letters) < 3 or len(letters) < len(p.replace(" ", "")) * 0.6:
        return False
    if re.search(r"(.)\1{3,}", p):
        return False
    v = sum(1 for ch in letters if ch in VOWELS) / len(letters)
    if not 0.15 <= v <= 0.7:
        return False
    if sum(1 for ch in letters if ch in RARE) > max(1, len(letters) * 0.08):
        return False
    if sum(1 for ch in letters if not ch.isascii()) > len(letters) * 0.3 or re.search(r"[^\x00-\x7F’‘“”…·×]{3,}", p):
        return False
    if len(TOKEN_RE.findall(text)) * 3 >= len(letters):
        return False
    if re.search(r"[b-df-hj-np-tv-xzB-DF-HJ-NP-TV-XZ]{6,}", p):
        return False
    words = [w for w in re.split(r"[\s\-/]+", p) if w]
    if any(sum(ch.isalpha() for ch in w) > 18 for w in words):
        return False
    mixed = sum(1 for w in words if re.search(r"[a-z][A-Z]", w.replace("é", "")))
    if mixed > max(1, len(words) // 4):
        return False
    if len(letters) < 6 and any(ch in RARE for ch in letters):
        return False
    if len(words) == 1 and p.islower() and len(letters) < 5 and not re.search(r"[.!?…]$", p):
        return False
    if all(sum(ch.isalpha() for ch in w) <= 2 for w in words):
        return False
    lower_words = [w for w in words if any(ch.islower() for ch in w) and sum(ch.isalpha() for ch in w) >= 3]
    no_vowel = sum(1 for w in lower_words if not any(ch in VOWELS or ch in "yY" for ch in w))
    if no_vowel > len(lower_words) // 5:
        return False
    if sum(1 for w in words if sum(ch.isalpha() for ch in w) <= 1) * 2 > len(words):
        return False
    if len(words) <= 2 and mixed:
        return False
    if len(words) == 1 and lower_words and len(letters) < 6 and not re.search(r"[.!?…]$", p):
        return False
    return True


def _table_offsets(cands, min_run: int = 6):
    """Offsets of strings sitting in fixed-stride tables (species/move/item names...)."""
    flagged, stride = set(), None
    run = [cands[0]] if cands else []
    for prev, cur in zip(cands, cands[1:]):
        d = cur[0] - prev[0]
        if d == stride and prev[1] < d:
            run.append(cur)
        else:
            if len(run) >= min_run:
                flagged.update(x[0] for x in run)
            stride = d if 3 <= d <= 48 and prev[1] < d else None
            run = [prev, cur] if stride else [cur]
    if len(run) >= min_run:
        flagged.update(x[0] for x in run)
    return flagged


def _is_name(text: str, in_table: bool) -> bool:
    p = plain_text(text)
    if any(t in text for t in BREAK_TOKENS) or len(p) > 30:
        return False
    if {word.lower() for word in re.findall(r"[A-Za-z]+", p)} & COMMON_STORY_WORDS:
        return False
    return in_table


def classify(cands):
    """cands: [(offset, length, text)] sorted. Returns (story, names, occurrences)."""
    cands = [x for x in cands if _is_readable(x[2])]
    table = _table_offsets(cands)
    story, names, seen = [], set(), set()
    occurrences = defaultdict(list)
    for off, length, text in cands:
        if _is_name(text, off in table):
            names.add(plain_text(text))
            continue
        occurrences[text].append((off, length))
        if text not in seen:
            seen.add(text)
            story.append((off, length, text))
    return story, names, occurrences


def extract_texts(data: bytes, encoding: str, scan_mode: str):
    """Returns (story, names, occurrences). Names always come from a full bytewise scan."""
    c = CODECS.get(encoding)
    if c is None:
        byte_cands = cands = scan_ascii(data)
    else:
        byte_cands = scan_bytewise(c, data)
        cands = scan_gba_pointers(c, data) if (scan_mode == "pointers" and c is GEN3) else byte_cands
    story, names, occ = classify(cands)
    if cands is not byte_cands:
        names |= classify(byte_cands)[1]
    return story, names, occ


def patch_payload(encoding: str, text: str, length: int, terminator: int) -> bytes:
    c = CODECS.get(encoding)
    if c is None:
        raw = text.encode("ascii", errors="replace")[:length]
        return raw + b" " * (length - len(raw))
    return c.patch_payload(text, length, terminator)


def glossary_for(texts, names, limit: int = 80):
    """Names (len>=3) that literally appear inside the given texts."""
    if not names:
        return []
    blob = "\n".join(plain_text(t) for t in texts)
    hits = {nm for nm in names if len(nm) >= 3
            and re.search(r"(?<![A-Za-z])" + re.escape(nm) + r"(?![A-Za-z])", blob, re.IGNORECASE)}
    return sorted(hits, key=len, reverse=True)[:limit]


def protect_glossary_terms(text: str, names):
    """Replace detected game names with unique markers, preserving their exact spelling."""
    replacements = {}
    protected = text
    token_index = 0
    for name in glossary_for([text], names):
        pattern = re.compile(r"(?<![A-Za-z])" + re.escape(name) + r"(?![A-Za-z])", re.IGNORECASE)

        def replace(match):
            nonlocal token_index
            token = f"{{KEEP{token_index:04d}}}"
            while token in text or token in replacements:
                token_index += 1
                token = f"{{KEEP{token_index:04d}}}"
            token_index += 1
            replacements[token] = match.group(0)
            return token

        protected = pattern.sub(replace, protected)
    return protected, replacements


def restore_glossary_terms(text: str, replacements):
    for token, original in replacements.items():
        text = text.replace(token, original)
    return text


def detect_gb_encoding(data: bytes, filename: str):
    title = bytes(data[0x134:0x144]).decode("ascii", errors="ignore").upper() if len(data) > 0x144 else ""
    fn = filename.lower()
    if any(t in title for t in ("POKEMON RED", "POKEMON BLUE", "POKEMON GREEN", "POKEMON YELLOW")):
        return "pokemon_gen1"
    if any(t in title for t in ("POKEMON_GLD", "POKEMON_SLV", "PM_CRYSTAL", "POKEMON GOLD", "POKEMON SILVER")):
        return "pokemon_gen2"
    if fn.endswith((".gb", ".gbc")) and "pokemon" in fn.replace("é", "e").replace(" ", ""):
        if any(w in fn for w in ("red", "blue", "yellow", "green")):
            return "pokemon_gen1"
        if any(w in fn for w in ("gold", "silver", "crystal")):
            return "pokemon_gen2"
    return None
