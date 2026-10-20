from fastapi import FastAPI, APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import re
import json
import logging
import uuid
import base64
from contextlib import contextmanager
import sqlite3
import unicodedata
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime, timezone

from json_repair import repair_json as _repair_json

from charmaps import (
    extract_pokemon_gen3_runs,
    extract_pokemon_gen3_via_pointers,
    encode_pokemon_gen3,
    detect_encoding,
    count_pokemon_gen3_runs,
    analyze_pokemon_gen3,
)
from text_extract import (extract_texts, patch_payload, protect_glossary_terms,
                          restore_glossary_terms, detect_gb_encoding, CODECS, TOKEN_LEGEND, required_tokens)


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

DATA_DIR = Path(os.environ.get("APP_DATA_DIR", ROOT_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "rom_translator.sqlite3"


@contextmanager
def _db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _init_db():
    with _db_connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS rom_sessions (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                record_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rom_glossaries (
                session_id TEXT PRIMARY KEY,
                names_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS translation_cache (
                key TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                translated TEXT NOT NULL,
                target_lang TEXT NOT NULL,
                manual INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_translation_cache_lang
                ON translation_cache(target_lang);
        """)


def _get_session(session_id: str) -> Optional[dict]:
    with _db_connect() as conn:
        row = conn.execute(
            "SELECT record_json FROM rom_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    return json.loads(row["record_json"]) if row else None


def _insert_session(record: dict):
    with _db_connect() as conn:
        conn.execute(
            "INSERT INTO rom_sessions (session_id, created_at, record_json) VALUES (?, ?, ?)",
            (record["session_id"], record["created_at"], json.dumps(record)),
        )


def _update_session(session_id: str, fields: dict):
    with _db_connect() as conn:
        row = conn.execute(
            "SELECT record_json FROM rom_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row:
            record = json.loads(row["record_json"])
            record.update(fields)
            conn.execute(
                "UPDATE rom_sessions SET record_json = ? WHERE session_id = ?",
                (json.dumps(record), session_id),
            )


def _list_sessions(limit: int = 20) -> list:
    with _db_connect() as conn:
        rows = conn.execute(
            "SELECT record_json FROM rom_sessions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [json.loads(row["record_json"]) for row in rows]


def _upsert_glossary(session_id: str, names: list):
    with _db_connect() as conn:
        conn.execute(
            "INSERT INTO rom_glossaries (session_id, names_json) VALUES (?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET names_json = excluded.names_json",
            (session_id, json.dumps(names)),
        )


def _get_glossary(session_id: str) -> list:
    with _db_connect() as conn:
        row = conn.execute(
            "SELECT names_json FROM rom_glossaries WHERE session_id = ?", (session_id,)
        ).fetchone()
    return json.loads(row["names_json"]) if row else []


_init_db()

EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

# Provider catalog with recommended models
# pricing = {"input": USD per 1M input tokens, "output": USD per 1M output tokens}
PROVIDERS = {
    "gemini": {
        "label": "Google Gemini",
        "keyHint": "AIza... (Google AI Studio) or your project key",
        "models": [
            {"id": "gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro (best quality)", "pricing": {"input": 1.25, "output": 10.0}},
            {"id": "gemini-3-flash-preview", "label": "Gemini 3 Flash (fast, cheap)", "pricing": {"input": 0.075, "output": 0.30}},
            {"id": "gemini-2.5-pro", "label": "Gemini 2.5 Pro", "pricing": {"input": 1.25, "output": 10.0}},
            {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash", "pricing": {"input": 0.075, "output": 0.30}},
        ],
        "default": "gemini-3-flash-preview",
    },
    "openai": {
        "label": "OpenAI",
        "keyHint": "sk-... from platform.openai.com",
        "models": [
            {"id": "gpt-5.4", "label": "GPT-5.4 (recommended)", "pricing": {"input": 1.25, "output": 10.0}},
            {"id": "gpt-5.4-mini", "label": "GPT-5.4 Mini (fast)", "pricing": {"input": 0.15, "output": 0.60}},
            {"id": "gpt-5", "label": "GPT-5", "pricing": {"input": 1.25, "output": 10.0}},
            {"id": "gpt-4o", "label": "GPT-4o", "pricing": {"input": 2.50, "output": 10.0}},
        ],
        "default": "gpt-5.4-mini",
    },
    "groq": {
        "label": "Groq",
        "keyHint": "gsk_... from console.groq.com/keys",
        "models": [
            {"id": "llama-3.3-70b-versatile", "label": "Llama 3.3 70B (recommended)"},
            {"id": "llama-3.1-8b-instant", "label": "Llama 3.1 8B (fast)"},
            {"id": "openai/gpt-oss-120b", "label": "GPT OSS 120B"},
        ],
        "default": "llama-3.3-70b-versatile",
    },
    "freetheai": {
        "label": "FreeTheAI",
        "keyHint": "Create an API key at freetheai.org",
        "models": [
            {"id": "fta/ocz/glm-5.3-flash-free", "label": "GLM 5.3 Flash (free)"},
            {"id": "fta/ocz/deepseek-v4.1-flash-free", "label": "DeepSeek V4.1 Flash (free)"},
            {"id": "fta/ocz/nemotron-3.5-lightning-free", "label": "Nemotron 3.5 Lightning (free)"},
            {"id": "fta/ocz/nemotron-3-ultra-free", "label": "Nemotron 3 Ultra (free)"},
            {"id": "fta/ocz/mimo-v2.6-flash-free", "label": "MiMo V2.6 Flash (free)"},
            {"id": "fta/ocz/longcat-2.5-preview-free", "label": "LongCat 2.5 Preview (free)"},
            {"id": "fta/ocz/nemotron-3.5-super-vl-free", "label": "Nemotron 3.5 Super VL (free)"},
            {"id": "fta/ocz/beam-free", "label": "Beam (free)"},
            {"id": "fta/ocz/big-pickle", "label": "Big Pickle (free)"},
        ],
        "default": "fta/ocz/glm-5.3-flash-free",
    },
    "anthropic": {
        "label": "Anthropic Claude",
        "keyHint": "sk-ant-... from console.anthropic.com",
        "models": [
            {"id": "claude-sonnet-5", "label": "Claude Sonnet 5 (best)", "pricing": {"input": 3.0, "output": 15.0}},
            {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6 (recommended)", "pricing": {"input": 3.0, "output": 15.0}},
            {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5 (fast)", "pricing": {"input": 0.80, "output": 4.0}},
        ],
        "default": "claude-sonnet-4-6",
    },
    "emergent": {
        "label": "Emergent Universal Key",
        "keyHint": "sk-emergent-... from Profile → Manage plan → Universal Key. Leave EMPTY to use the app's default key (free tier, limited).",
        "models": [
            {"id": "gemini-3-flash-preview", "label": "Gemini 3 Flash (via Emergent)", "pricing": {"input": 0.10, "output": 0.40}},
            {"id": "gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro (via Emergent)", "pricing": {"input": 1.30, "output": 10.5}},
            {"id": "gpt-5.4-mini", "label": "GPT-5.4 Mini (via Emergent)", "pricing": {"input": 0.20, "output": 0.70}},
            {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6 (via Emergent)", "pricing": {"input": 3.10, "output": 15.5}},
        ],
        "default": "gemini-3-flash-preview",
    },
}
OPENAI_COMPATIBLE_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "freetheai": "https://api.freetheai.org/v1",
}

import hashlib

# In-memory job registry for async translation
JOBS: dict = {}


def _cache_key(text: str, target_lang: str) -> str:
    """Deterministic cache key: hash of (text, target lang). Provider/model intentionally
    excluded so a translation done once is reused for the same language regardless of AI."""
    h = hashlib.sha256(f"{target_lang}\x1f{text}".encode("utf-8")).hexdigest()
    return h[:32]


async def _cache_lookup(texts_by_lang: dict) -> dict:
    """Look up cached translations. texts_by_lang: {lang: set(texts)}.
    Returns {(lang, text): translated} for hits."""
    hits = {}
    all_keys = []
    key_meta = {}
    for lang, texts in texts_by_lang.items():
        for t in texts:
            k = _cache_key(t, lang)
            all_keys.append(k)
            key_meta[k] = (lang, t)
    if not all_keys:
        return hits
    with _db_connect() as conn:
        for start in range(0, len(all_keys), 900):
            keys = all_keys[start:start + 900]
            placeholders = ",".join("?" for _ in keys)
            rows = conn.execute(
                f"SELECT key, translated FROM translation_cache WHERE key IN ({placeholders})",
                keys,
            ).fetchall()
            for row in rows:
                meta = key_meta.get(row["key"])
                if meta:
                    hits[meta] = row["translated"]
    return hits


async def _cache_store_many(items: list):
    """items: list of {key, source, translated, target_lang}. Bulk upsert."""
    if not items:
        return
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _db_connect() as conn:
            conn.executemany("""
                INSERT INTO translation_cache
                    (key, source, translated, target_lang, manual, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    source = excluded.source,
                    translated = excluded.translated,
                    target_lang = excluded.target_lang,
                    manual = excluded.manual,
                    updated_at = excluded.updated_at
            """, [
                (
                    item["key"], item["source"], item["translated"], item["target_lang"],
                    int(bool(item.get("manual", False))), now, now,
                )
                for item in items
            ])
    except Exception as e:
        logging.warning(f"Cache bulk_write failed: {e}")


def _error_code(err: str) -> str:
    low = (err or "").lower()
    if "emergent_budget_exceeded" in low or "budget has been exceeded" in low or "max budget" in low:
        return "EMERGENT_BUDGET_EXCEEDED"
    # Check INVALID_KEY before QUOTA to avoid false 'rate' match inside 'gene-rate'
    if ("invalid api key" in low or "unauthorized" in low or "api key missing" in low
            or "authenticationerror" in low or "invalid_api_key" in low):
        return "INVALID_KEY"
    if ("resource_exhausted" in low or " 429" in low or "quota" in low
            or "rate limit" in low or "ratelimit" in low or "too many requests" in low):
        return "QUOTA_EXCEEDED"
    if "timeout" in low:
        return "TIMEOUT"
    return "UPSTREAM_ERROR"


def _friendly_error(err: str) -> str:
    code = _error_code(err)
    if code == "EMERGENT_BUDGET_EXCEEDED":
        return ("Emergent Universal Key credit is exhausted. "
                "Add balance in Profile → Manage plan → Universal Key, "
                "or open Settings and switch to your own AI provider (Gemini / OpenAI / Anthropic / Groq / FreeTheAI).")
    if code == "QUOTA_EXCEEDED":
        return ("The selected provider's free-tier quota is used up for today. "
                "Open Settings and try a different provider or wait until the quota resets.")
    if code == "INVALID_KEY":
        return ("The API key was rejected. Open Settings and re-enter a valid key, "
                "or switch to the Emergent Universal Key.")
    if code == "TIMEOUT":
        return "The AI provider timed out. Try again, or switch to a faster model in Settings."
    return f"Translation failed: {err[:200]}"

app = FastAPI()
api_router = APIRouter(prefix="/api")

# ---------- Models ----------
class ExtractedString(BaseModel):
    id: str
    offset: int
    length: int
    text: str

class ExtractResponse(BaseModel):
    session_id: str
    filename: str
    rom_size: int
    rom_type: str
    encoding: str
    found_total: int
    excluded_names: int = 0
    strings: List[ExtractedString]

class TranslateRequest(BaseModel):
    session_id: str
    target_language: str  # ISO code label e.g. "cs", "en"
    strings: List[ExtractedString]
    provider: Optional[str] = "emergent"     # gemini | openai | anthropic | emergent
    model: Optional[str] = None              # provider-specific model id (falls back to provider default)
    api_key: Optional[str] = None            # user's own key (empty -> use server default when provider=emergent)

class TranslatedString(BaseModel):
    id: str
    original: str
    translated: str

class TranslateResponse(BaseModel):
    session_id: str
    target_language: str
    translations: List[TranslatedString]

class PatchRequest(BaseModel):
    session_id: str
    translations: List[TranslatedString]

class SessionRecord(BaseModel):
    session_id: str
    filename: str
    rom_size: int
    rom_type: str
    target_language: Optional[str] = None
    string_count: int
    created_at: str

# ---------- ROM string extraction ----------
LANGUAGE_NAMES = {
    "cs": "Czech (Čeština)",
    "en": "English",
    "de": "German (Deutsch)",
    "es": "Spanish (Español)",
    "fr": "French (Français)",
    "pl": "Polish (Polski)",
    "sk": "Slovak (Slovenčina)",
    "it": "Italian (Italiano)",
    "ja": "Japanese (日本語)",
    "pt": "Portuguese (Português)",
    "ru": "Russian (Русский)",
}

MIN_STRING_LEN = 4
DEFAULT_MAX_STRINGS = 500     # sensible default per extract
HARD_MAX_STRINGS = 100000     # hard cap regardless of user choice (protects RAM)
UNLIMITED_SENTINEL = 0        # 0 or negative == "no user cap; use HARD_MAX_STRINGS"
MAX_BATCH_STRINGS = 60
MAX_BATCH_CHARS = 6000
MAX_PARALLEL = max(1, int(os.environ.get("MAX_PARALLEL", "8")))
LLM_TIMEOUT = 150             # seconds per LLM call (thinking models answer slowly on big batches)
PRINTABLE_RE = re.compile(rb"[\x20-\x7E]{%d,}" % MIN_STRING_LEN)


def _group_strings_by_text(strings: List[ExtractedString]) -> dict:
    groups = {}
    for item in strings:
        groups.setdefault(item.text, []).append(item)
    return groups


def _build_translation_batches(groups: List[List[ExtractedString]]) -> List[List[ExtractedString]]:
    batches = []
    batch = []
    batch_chars = 0
    for group in groups:
        if not group:
            continue
        item = group[0]
        if batch and (len(batch) >= MAX_BATCH_STRINGS or batch_chars + len(item.text) > MAX_BATCH_CHARS):
            batches.append(batch)
            batch = []
            batch_chars = 0
        batch.append(item)
        batch_chars += len(item.text)
    if batch:
        batches.append(batch)
    return batches


def detect_rom_type(filename: str, size: int) -> str:
    fn = filename.lower()
    if fn.endswith(".gba"):
        return "Game Boy Advance"
    if fn.endswith(".gbc"):
        return "Game Boy Color"
    if fn.endswith(".gb"):
        return "Game Boy"
    if size > 4 * 1024 * 1024:
        return "Game Boy Advance"
    return "Game Boy"


def extract_ascii_from_bytes(data: bytes, max_strings: int) -> List[ExtractedString]:
    results: List[ExtractedString] = []
    seen_texts = set()
    for m in PRINTABLE_RE.finditer(data):
        text = m.group().decode("ascii", errors="ignore").strip()
        if len(text) < MIN_STRING_LEN:
            continue
        letters = sum(1 for c in text if c.isalpha())
        if letters < 3:
            continue
        key = text.lower()
        if key in seen_texts:
            continue
        seen_texts.add(key)
        results.append(ExtractedString(
            id=str(uuid.uuid4()),
            offset=m.start(),
            length=len(m.group()),
            text=text,
        ))
        if len(results) >= max_strings:
            break
    return results


def extract_gen3_from_bytes(data: bytes, max_strings: int, scan_mode: str = "bytewise") -> List[ExtractedString]:
    # Lower min_length so we catch short dialogs like "Yes!", "OK.", names, menu items
    if scan_mode == "pointers":
        runs = extract_pokemon_gen3_via_pointers(data, min_length=4, max_results=max_strings)
    else:
        runs = extract_pokemon_gen3_runs(data, min_length=5, max_results=max_strings)
    return [
        ExtractedString(id=str(uuid.uuid4()), offset=off, length=length, text=text)
        for off, length, text in runs
    ]


def extract_story(data: bytes, encoding: str, scan_mode: str = "bytewise"):
    """Story/dialog strings (names filtered out) + names glossary + all occurrences."""
    story, names, occ = extract_texts(data, encoding, scan_mode)
    strings = [ExtractedString(id=str(uuid.uuid4()), offset=o, length=l, text=t) for o, l, t in story[:HARD_MAX_STRINGS]]
    return strings, names, occ


def apply_translations(data: bytearray, encoding: str, occ: dict, pairs) -> int:
    """Write (original, translated) pairs into every occurrence of the original text."""
    patched = 0
    for orig, tran in pairs:
        if not tran or tran.strip() == orig.strip() or orig not in occ:
            continue
        for off, length in occ[orig]:
            term = data[off + length] if off + length < len(data) else 0
            payload = patch_payload(encoding, tran, length, term)
            data[off:off + len(payload)] = payload
        patched += 1
    return patched


def extract_strings_from_bytes(data: bytes, encoding: str = "ascii", max_strings: int = DEFAULT_MAX_STRINGS, scan_mode: str = "bytewise") -> List[ExtractedString]:
    # 0 or negative means "no user cap" -> use HARD_MAX_STRINGS
    if max_strings <= 0:
        max_strings = HARD_MAX_STRINGS
    else:
        max_strings = min(max(max_strings, 10), HARD_MAX_STRINGS)
    if encoding == "pokemon_gen3":
        return extract_gen3_from_bytes(data, max_strings, scan_mode)
    return extract_ascii_from_bytes(data, max_strings)


# ---------- Session storage (ROM binary) ----------
SESSION_DIR = DATA_DIR / "rom_sessions"
SESSION_DIR.mkdir(parents=True, exist_ok=True)


def rom_path(session_id: str) -> Path:
    return SESSION_DIR / f"{session_id}.bin"


# ---------- Endpoints ----------
@api_router.get("/")
async def root():
    return {"message": "Gameboy ROM Translator API"}


@api_router.get("/languages")
async def get_languages():
    return [{"code": k, "name": v} for k, v in LANGUAGE_NAMES.items()]


@api_router.get("/providers")
async def get_providers():
    providers = dict(PROVIDERS)
    if os.environ.get("DISABLE_EMERGENT_PROVIDER") == "1":
        providers.pop("emergent", None)
    return providers


class TestKeyRequest(BaseModel):
    provider: str
    model: Optional[str] = None
    api_key: Optional[str] = None


@api_router.post("/ai/test")
async def test_ai_key(req: TestKeyRequest):
    """Send a tiny prompt to validate the provider+key combination.
    Returns which key was actually used (masked) and the outcome.
    """
    key_used = req.api_key or (EMERGENT_LLM_KEY if req.provider == "emergent" else None)
    masked = f"{key_used[:8]}...{key_used[-4:]}" if key_used and len(key_used) > 12 else "(none)"
    key_source = "user" if req.api_key else ("server" if req.provider == "emergent" else "user")

    logging.info(f"[test_ai_key] provider={req.provider} model={req.model} key_source={key_source} key={masked}")

    try:
        resp = await _call_llm("Reply with exactly one word: PONG", req.provider, req.model, req.api_key)
        return {
            "ok": True,
            "reply": (resp or "").strip()[:100],
            "provider": req.provider,
            "model": req.model or PROVIDERS.get(req.provider, {}).get("default"),
            "key_source": key_source,
            "key_masked": masked,
        }
    except HTTPException as e:
        return {
            "ok": False,
            "error": str(e.detail)[:400],
            "error_code": _error_code(str(e.detail)),
            "friendly": _friendly_error(str(e.detail)),
            "provider": req.provider,
            "model": req.model or PROVIDERS.get(req.provider, {}).get("default"),
            "key_source": key_source,
            "key_masked": masked,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e)[:400],
            "error_code": _error_code(str(e)),
            "friendly": _friendly_error(str(e)),
            "provider": req.provider,
            "model": req.model or PROVIDERS.get(req.provider, {}).get("default"),
            "key_source": key_source,
            "key_masked": masked,
        }


@api_router.get("/rom/{session_id}/analyze")
async def analyze_rom(session_id: str):
    """Diagnostic info: how many Gen3-encoded strings the ROM contains, by length bucket,
    plus how much of the ROM matches Gen3 patterns. Helps user judge extraction coverage."""
    p = rom_path(session_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Session not found")
    sess = _get_session(session_id)
    enc = (sess or {}).get("encoding", "ascii")
    data = p.read_bytes()
    if enc == "pokemon_gen3":
        stats = analyze_pokemon_gen3(data)
        stats["encoding"] = enc
        return stats
    else:
        # ASCII scan: just report total unique printable strings
        n = len(extract_ascii_from_bytes(data, HARD_MAX_STRINGS))
        return {
            "encoding": enc,
            "total_unique": n,
            "rom_size": len(data),
        }


@api_router.get("/encodings")
async def get_encodings():
    return [
        {"id": "auto", "label": "Auto-detect (recommended)"},
        {"id": "ascii", "label": "ASCII (homebrew, dev ROMs)"},
        {"id": "pokemon_gen1", "label": "Pokemon Gen 1 (Red / Blue / Yellow)"},
        {"id": "pokemon_gen2", "label": "Pokemon Gen 2 (Gold / Silver / Crystal)"},
        {"id": "pokemon_gen3", "label": "Pokemon Gen 3 (Emerald / Ruby / Sapphire / FRLG)"},
    ]


@api_router.post("/rom/extract", response_model=ExtractResponse)
async def extract_rom(
    file: UploadFile = File(...),
    encoding: str = Form("auto"),
    max_strings: int = Form(0),
    scan_mode: str = Form("bytewise"),  # bytewise | pointers (Pokemon Gen 3 only)
):
    fn = file.filename or "rom.gb"
    if not fn.lower().endswith((".gb", ".gbc", ".gba")):
        raise HTTPException(status_code=400, detail="Unsupported file type. Use .gb, .gbc or .gba")

    data = await file.read()
    if len(data) < 1024:
        raise HTTPException(status_code=400, detail="ROM too small")
    if len(data) > 40 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="ROM too large (max 40MB)")

    # Resolve encoding: auto-detect if requested
    enc = encoding
    if enc == "auto":
        enc = detect_gb_encoding(data, fn) or detect_encoding(data, fn)
    if enc not in {"ascii", "pokemon_gen1", "pokemon_gen2", "pokemon_gen3"}:
        raise HTTPException(status_code=400, detail=f"Unknown encoding '{enc}'")

    session_id = str(uuid.uuid4())
    rom_path(session_id).write_bytes(data)

    import asyncio
    strings, names, _ = await asyncio.to_thread(extract_story, data, enc, scan_mode)
    if max_strings > 0:
        strings = strings[:max_strings]
    found_total = len(strings)
    _upsert_glossary(session_id, sorted(names))
    rom_type = detect_rom_type(fn, len(data))

    record = {
        "session_id": session_id,
        "filename": fn,
        "rom_size": len(data),
        "rom_type": rom_type,
        "encoding": enc,
        "scan_mode": scan_mode,
        "string_count": len(strings),
        "found_total": found_total,
        "excluded_names": len(names),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _insert_session(record)

    return ExtractResponse(
        session_id=session_id,
        filename=fn,
        rom_size=len(data),
        rom_type=rom_type,
        encoding=enc,
        found_total=found_total,
        excluded_names=len(names),
        strings=strings,
    )


EXTRA_CHARS = {
    "pokemon_gen3": "á é í ó ú à è ì ò ù â ê î ô û ä ö ü ñ ç (and their uppercase forms)",
    "pokemon_gen2": "é ä ö ü Ä Ö Ü",
    "pokemon_gen1": "é",
}


def _allowed_chars(encoding: str) -> set:
    c = CODECS.get(encoding)
    return set(c.enc_single) if c else set()


def _sanitize_translation(text: str, encoding: str) -> str:
    allowed = _allowed_chars(encoding)
    punctuation = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "−": "-", "…": "...", "·": ".", "×": "x"}
    result = []
    for char in text:
        if 0x20 <= ord(char) <= 0x7E or char in allowed:
            result.append(char)
        elif char in punctuation:
            result.append(punctuation[char])
        else:
            base = "".join(c for c in unicodedata.normalize("NFKD", char) if c.isascii() and c.isalnum())
            if base:
                result.append(base)
            elif char.isspace():
                result.append(" ")
    return "".join(result)


def _build_translation_prompt(target_lang_name: str, strings: List[ExtractedString], encoding: str = "ascii", glossary: Optional[list] = None) -> str:
    extra = EXTRA_CHARS.get(encoding)
    charset_rule = (
        f"4. Only use printable ASCII characters plus these accented letters the game font supports: {extra}. "
        f"Any other letter with diacritics must be written without it (e.g. č->c, ř->r, š->s, ž->z, ě->e, ů->u, ý->y).\n"
        if extra else
        "4. Only use printable ASCII characters (a-z, A-Z, 0-9, punctuation, space). No accents, no unicode — Gameboy fonts can't render them.\n"
    )
    gloss_rule = (
        "8. These are proper names from the game (Pokemon, moves, items, places, characters). "
        f"Keep them EXACTLY unchanged wherever they appear: {', '.join(glossary)}\n"
        if glossary else ""
    )
    lines = []
    for s in strings:
        lines.append(f'{{"id":"{s.id}","text":{json.dumps(s.text)}}}')
    joined = "\n".join(lines)
    return (
        f"You are a professional video game localizer. Translate the following in-game texts extracted from a Gameboy ROM "
        f"into {target_lang_name}.\n\n"
        f"IMPORTANT RULES:\n"
        f"1. Keep translations concise. Try to match the ORIGINAL LENGTH in characters — game text often has fixed buffers. "
        f"If the translation would be longer, abbreviate naturally to fit within the original length.\n"
        f"2. Preserve punctuation and any leading/trailing spaces exactly.\n"
        f"3. Do NOT translate obvious code identifiers, file names, register names, or gibberish (return them unchanged).\n"
        f"{charset_rule}"
        f'5. Do NOT include backslash (\\) in the translated text. If original has a backslash, replace it with "/". '
        f"Do NOT use any escape sequences.\n"
        f'6. Return STRICT RFC 8259 JSON only — a single JSON array of objects with exactly two keys: "id" and "translated". '
        f"No prose, no code fences, no markdown. Each object on its own line for readability is OK.\n"
        f"7. Texts contain game control tokens in curly braces, e.g. {{n}} new line, {{l}} scroll line, {{p}} new text box, "
        f"{{PLAYER}}, {{RIVAL}}, {{STR1}}, {{FC:01:02}}. They are NOT words: never translate, rename, remove or add them. "
        f"Every variable/command token (anything other than {{n}} {{l}} {{p}}) must appear in the translation exactly as many times as in the original. "
        f"You may move line-break tokens to re-wrap a sentence, but keep each line no longer than the longest line of the original. "
        f"Words in ALL CAPS are game terms/names — keep them unchanged. Protected name markers like {{KEEP0000}} must also remain exactly unchanged.\n"
        f"{gloss_rule}\n"
        f"INPUT (one JSON object per line):\n{joined}\n\n"
        f"OUTPUT: JSON array only, well-formed."
    )


async def _call_llm(prompt: str, provider: str, model: Optional[str], api_key: Optional[str]) -> str:
    """Dispatch to the requested LLM provider with the user's key.
    Provider 'emergent' uses the server-side EMERGENT_LLM_KEY via emergentintegrations.
    """
    import asyncio

    provider = (provider or "emergent").lower()
    if provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'")

    model = model or PROVIDERS[provider]["default"]

    # --- Google Gemini via google-genai SDK ---
    if provider == "gemini":
        key = api_key or GEMINI_API_KEY
        if not key:
            raise HTTPException(status_code=400, detail="Gemini API key missing")
        from google import genai as google_genai
        client_ = google_genai.Client(api_key=key)
        try:
            resp = await asyncio.wait_for(
                asyncio.to_thread(client_.models.generate_content, model=model, contents=prompt),
                timeout=LLM_TIMEOUT,
            )
            return resp.text or ""
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Gemini error: {(str(e) or type(e).__name__)[:300]}")

    # --- OpenAI-compatible APIs via official SDK ---
    if provider in {"openai", *OPENAI_COMPATIBLE_BASE_URLS}:
        key = api_key
        if not key:
            raise HTTPException(status_code=400, detail=f"{PROVIDERS[provider]['label']} API key missing")
        from openai import AsyncOpenAI
        client_args = {"api_key": key}
        if provider in OPENAI_COMPATIBLE_BASE_URLS:
            client_args["base_url"] = OPENAI_COMPATIBLE_BASE_URLS[provider]
        client_ = AsyncOpenAI(**client_args)
        try:
            resp = await asyncio.wait_for(
                client_.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You are a precise game text translator that returns only JSON."},
                        {"role": "user", "content": prompt},
                    ],
                ),
                timeout=LLM_TIMEOUT,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            label = PROVIDERS[provider]["label"]
            raise HTTPException(status_code=502, detail=f"{label} error: {(str(e) or type(e).__name__)[:300]}")

    # --- Anthropic Claude via official SDK ---
    if provider == "anthropic":
        key = api_key
        if not key:
            raise HTTPException(status_code=400, detail="Anthropic API key missing")
        from anthropic import AsyncAnthropic
        client_ = AsyncAnthropic(api_key=key)
        try:
            msg = await asyncio.wait_for(
                client_.messages.create(
                    model=model,
                    max_tokens=4096,
                    system="You are a precise game text translator that returns only JSON.",
                    messages=[{"role": "user", "content": prompt}],
                ),
                timeout=LLM_TIMEOUT,
            )
            # concatenate text blocks
            return "".join(getattr(b, "text", "") for b in msg.content) or ""
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Anthropic error: {(str(e) or type(e).__name__)[:300]}")

    # --- Emergent Universal Key via emergentintegrations ---
    if provider == "emergent":
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
        except ImportError as e:
            raise HTTPException(
                status_code=501,
                detail="Emergent provider is unavailable in this installation; choose another provider.",
            ) from e
        # Allow the user to bring their OWN emergent key (from Profile → Manage plan → Universal Key)
        # to bypass the server-side pod-scoped key that has a $1 free-tier cap.
        key = api_key or EMERGENT_LLM_KEY
        if not key:
            raise HTTPException(status_code=400, detail="Emergent LLM key not configured")
        # Determine underlying provider from model id
        if model.startswith("gemini"):
            e_provider = "gemini"
        elif model.startswith("gpt") or model.startswith("o"):
            e_provider = "openai"
        elif model.startswith("claude"):
            e_provider = "anthropic"
        else:
            e_provider = "gemini"
        chat = LlmChat(
            api_key=key,
            session_id=f"trans-{uuid.uuid4()}",
            system_message="You are a precise game text translator that returns only JSON.",
        ).with_model(e_provider, model)
        try:
            resp = await asyncio.wait_for(
                chat.send_message(UserMessage(text=prompt)),
                timeout=LLM_TIMEOUT,
            )
            return resp if isinstance(resp, str) else str(resp)
        except Exception as e:
            msg = str(e) or type(e).__name__
            # Detect the Emergent free-tier budget cap and surface a friendly message
            low = msg.lower()
            if "budget has been exceeded" in low or "max budget" in low:
                raise HTTPException(
                    status_code=402,
                    detail="EMERGENT_BUDGET_EXCEEDED: Emergent Universal Key credit was used up. Add balance in Profile → Manage plan → Universal Key, or switch to your own API key (Gemini / OpenAI / Anthropic / Groq / FreeTheAI) in Settings.",
                )
            raise HTTPException(status_code=502, detail=f"Emergent error: {msg[:300]}")

    raise HTTPException(status_code=400, detail=f"Provider '{provider}' not implemented")


async def _translate_batch(
    target_lang_name: str,
    batch: List[ExtractedString],
    provider: str,
    model: Optional[str],
    api_key: Optional[str],
    _depth: int = 0,
    encoding: str = "ascii",
    names: Optional[set] = None,
) -> List[TranslatedString]:
    if not batch:
        return []

    protected_batch = []
    protected_terms = {}
    for item in batch:
        protected_text, replacements = protect_glossary_terms(item.text, names or set())
        protected_batch.append(item.model_copy(update={"text": protected_text}))
        protected_terms[item.id] = replacements
    prompt = _build_translation_prompt(target_lang_name, protected_batch, encoding)

    # Honor the selected provider; never spend the app's Emergent balance as an implicit fallback.
    try:
        text = (await _call_llm(prompt, provider, model, api_key)).strip()
    except HTTPException as e:
        msg = str(e.detail).lower()
        if "timeout" in msg and len(batch) > 3 and _depth < 3:
            mid = len(batch) // 2
            logging.warning(f"LLM timeout at depth={_depth}, splitting batch of {len(batch)}")
            left = await _translate_batch(target_lang_name, batch[:mid], provider, model, api_key, _depth + 1, encoding, names)
            right = await _translate_batch(target_lang_name, batch[mid:], provider, model, api_key, _depth + 1, encoding, names)
            return left + right
        raise

    # Strip code fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    parsed = _lenient_json_parse(text)
    if parsed is None:
        # Split batch in half and retry each half separately — smaller output has less
        # chance of hitting the malformed-JSON case. Recurse up to 3 levels deep.
        if len(batch) > 3 and _depth < 3:
            mid = len(batch) // 2
            logging.warning(f"Invalid JSON at depth={_depth}, splitting batch of {len(batch)} into {mid}+{len(batch)-mid}")
            left = await _translate_batch(target_lang_name, batch[:mid], provider, model, api_key, _depth + 1, encoding, names)
            right = await _translate_batch(target_lang_name, batch[mid:], provider, model, api_key, _depth + 1, encoding, names)
            return left + right
        raise HTTPException(status_code=502, detail="Translator returned invalid JSON")

    by_id = {p.get("id"): p.get("translated", "") for p in parsed if isinstance(p, dict)}
    results = []
    protected_by_id = {item.id: item for item in protected_batch}
    for s in batch:
        protected_source = protected_by_id[s.id].text
        tr = by_id.get(s.id, protected_source)
        tr = _sanitize_translation(tr, encoding)
        if required_tokens(tr) != required_tokens(protected_source):
            logging.warning(f"Token mismatch, keeping original: {s.text[:60]!r}")
            tr = s.text
        else:
            tr = restore_glossary_terms(tr, protected_terms[s.id])
        results.append(TranslatedString(id=s.id, original=s.text, translated=tr))
    return results


def _lenient_json_parse(text: str):
    """Try progressively more forgiving JSON parsers. Returns list or None."""
    # 1. Strict json.loads
    try:
        v = json.loads(text)
        if isinstance(v, list):
            return v
    except Exception:
        pass
    # 2. Find array in text
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            v = json.loads(m.group())
            if isinstance(v, list):
                return v
        except Exception:
            pass
        # 3. json_repair (lenient)
        try:
            repaired = _repair_json(m.group())
            if isinstance(repaired, str):
                v = json.loads(repaired)
            else:
                v = repaired
            if isinstance(v, list):
                return v
        except Exception:
            pass
    # 4. Full-text json_repair
    try:
        repaired = _repair_json(text)
        if isinstance(repaired, str):
            v = json.loads(repaired)
        else:
            v = repaired
        if isinstance(v, list):
            return v
    except Exception:
        pass
    # 5. Line-by-line JSON objects fallback: {"id":"...","translated":"..."}
    objs = []
    for m in re.finditer(r'\{[^{}]*"id"\s*:\s*"([^"]+)"[^{}]*"translated"\s*:\s*"((?:[^"\\]|\\.)*)"[^{}]*\}', text):
        try:
            obj = json.loads(m.group(0))
            objs.append(obj)
        except Exception:
            try:
                obj = json.loads(_repair_json(m.group(0)))
                objs.append(obj)
            except Exception:
                continue
    if objs:
        return objs
    return None


@api_router.post("/rom/translate")
async def translate_rom_start(req: TranslateRequest):
    """Start an async translation job. Returns job_id immediately.
    Client polls GET /api/rom/translate/status/{job_id}.
    """
    lang_name = LANGUAGE_NAMES.get(req.target_language)
    if not lang_name:
        raise HTTPException(status_code=400, detail="Unsupported language")

    provider = (req.provider or "emergent").lower()
    if provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail="Unknown provider")
    # For non-emergent providers a user key is mandatory.
    # For emergent, an optional user key overrides the server key (to bypass the pod-scoped free-tier cap).
    if provider != "emergent" and not req.api_key:
        raise HTTPException(status_code=400, detail=f"API key required for provider '{provider}'")

    import asyncio

    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "status": "running",
        "total": len(req.strings),
        "done": 0,
        "translated_count": 0,
        "failed_count": 0,
        "cached_count": 0,
        "translations": [],
        "error": None,
        "errors": [],
        "session_id": req.session_id,
        "target_language": req.target_language,
        "provider": provider,
        "model": req.model or PROVIDERS[provider]["default"],
    }

    sess_doc = _get_session(req.session_id)
    job_encoding = (sess_doc or {}).get("encoding", "ascii")
    job_names = set(_get_glossary(req.session_id))

    async def worker():
        # === CACHE LOOKUP: skip strings we've already translated ===
        cache_hits = await _cache_lookup({req.target_language: {s.text for s in req.strings}})
        cached_out = []
        remaining = []
        for s in req.strings:
            key = (req.target_language, s.text)
            if key in cache_hits:
                cached_out.append(TranslatedString(id=s.id, original=s.text, translated=cache_hits[key]))
            else:
                remaining.append(s)
        if cached_out:
            JOBS[job_id]["cached_count"] = len(cached_out)
            JOBS[job_id]["translated_count"] += len(cached_out)
            JOBS[job_id]["done"] += len(cached_out)
            JOBS[job_id]["translations"].extend([t.model_dump() for t in cached_out])
            logging.info(f"Cache hits: {len(cached_out)}/{len(req.strings)}")

        remaining_groups = _group_strings_by_text(remaining)
        batches = _build_translation_batches(list(remaining_groups.values()))
        sem = asyncio.Semaphore(MAX_PARALLEL)
        abort_flag = {"stop": False, "reason": None}

        async def run(batch):
            async with sem:
                # Fail fast: if a prior batch hit a fatal error like budget exhaustion,
                # skip remaining batches instead of wasting time / retries.
                if abort_flag["stop"]:
                    out = [
                        TranslatedString(id=item.id, original=item.text, translated=item.text)
                        for representative in batch
                        for item in remaining_groups[representative.text]
                    ]
                    JOBS[job_id]["failed_count"] += len(out)
                    JOBS[job_id]["done"] += len(out)
                    JOBS[job_id]["translations"].extend([t.model_dump() for t in out])
                    return out

                failed = False
                err_msg = None
                try:
                    unique_out = await _translate_batch(lang_name, batch, provider, req.model, req.api_key, 0, job_encoding, job_names)
                    translated_by_text = {t.original: t.translated for t in unique_out}
                    out = [
                        TranslatedString(
                            id=item.id,
                            original=item.text,
                            translated=translated_by_text.get(representative.text, item.text),
                        )
                        for representative in batch
                        for item in remaining_groups[representative.text]
                    ]
                    real_translated = sum(1 for t in out if t.translated != t.original)
                    JOBS[job_id]["translated_count"] += real_translated
                    # === CACHE STORE: persist successful translations ===
                    to_store = [
                        {
                            "key": _cache_key(s.text, req.target_language),
                            "source": s.text,
                            "translated": t.translated,
                            "target_lang": req.target_language,
                        }
                        for t, s in zip(unique_out, batch)
                        if t.translated and t.translated != s.text
                    ]
                    if to_store:
                        await _cache_store_many(to_store)
                except Exception as e:
                    failed = True
                    err_msg = str(getattr(e, "detail", None) or e)[:250]
                    logging.warning(f"Batch failed: {err_msg}")
                    out = [
                        TranslatedString(id=item.id, original=item.text, translated=item.text)
                        for representative in batch
                        for item in remaining_groups[representative.text]
                    ]
                    JOBS[job_id]["failed_count"] += len(out)
                    low = err_msg.lower()
                    if ("emergent_budget_exceeded" in low
                        or "budget has been exceeded" in low
                        or "invalid api key" in low
                        or "unauthorized" in low
                        or "api key missing" in low):
                        abort_flag["stop"] = True
                        abort_flag["reason"] = err_msg
                JOBS[job_id]["done"] += len(out)
                JOBS[job_id]["translations"].extend([t.model_dump() for t in out])
                if failed and err_msg and err_msg not in JOBS[job_id]["errors"]:
                    JOBS[job_id]["errors"].append(err_msg)
                return out

        try:
            await asyncio.gather(*[run(b) for b in batches])
            if JOBS[job_id]["translated_count"] == 0 and JOBS[job_id]["failed_count"] > 0:
                JOBS[job_id]["status"] = "error"
                # Prefer the fatal reason if we aborted
                first_err = abort_flag.get("reason") or (JOBS[job_id]["errors"][0] if JOBS[job_id]["errors"] else "unknown")
                JOBS[job_id]["error"] = _friendly_error(first_err)
                JOBS[job_id]["error_code"] = _error_code(first_err)
            else:
                JOBS[job_id]["status"] = "done"
                if abort_flag["stop"]:
                    JOBS[job_id]["error_code"] = _error_code(abort_flag.get("reason") or "")
            _update_session(req.session_id, {
                "target_language": req.target_language,
                "translated_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(e)

    asyncio.create_task(worker())
    return {"job_id": job_id, "total": len(req.strings)}


@api_router.get("/rom/translate/status/{job_id}")
async def translate_rom_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job_id,
        "status": job["status"],
        "total": job["total"],
        "done": job["done"],
        "translated_count": job.get("translated_count", 0),
        "cached_count": job.get("cached_count", 0),
        "failed_count": job.get("failed_count", 0),
        "translations": job["translations"],
        "error": job["error"],
        "error_code": job.get("error_code"),
        "errors": job.get("errors", []),
    }


@api_router.get("/cache/stats")
async def cache_stats():
    with _db_connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM translation_cache").fetchone()[0]
        per_lang = [
            {"lang": row["target_lang"], "count": row["count"]}
            for row in conn.execute(
                "SELECT target_lang, COUNT(*) AS count FROM translation_cache "
                "GROUP BY target_lang ORDER BY count DESC"
            ).fetchall()
        ]
    return {"total": total, "per_language": per_lang}


class CacheEntryRequest(BaseModel):
    source: str
    translated: str
    target_language: str


@api_router.post("/cache/entry")
async def cache_entry(req: CacheEntryRequest):
    if not req.source or not req.translated.strip():
        raise HTTPException(status_code=400, detail="source and translated are required")
    await _cache_store_many([{
        "key": _cache_key(req.source, req.target_language),
        "source": req.source,
        "translated": req.translated,
        "target_lang": req.target_language,
        "manual": True,
    }])
    return {"saved": True}


@api_router.post("/cache/clear")
async def cache_clear(target_language: Optional[str] = None):
    with _db_connect() as conn:
        if target_language:
            result = conn.execute(
                "DELETE FROM translation_cache WHERE target_lang = ?", (target_language,)
            )
        else:
            result = conn.execute("DELETE FROM translation_cache")
    return {"deleted": result.rowcount}


@api_router.post("/rom/export")
async def export_translations(req: PatchRequest):
    """Export translations to a human-editable plain text file.
    Format: `original<TAB>translated` per line, with a small header.
    The user can edit the file freely and later re-upload via /api/rom/import
    to patch the ROM with their edits.
    """
    sess = _get_session(req.session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    lines = [
        "# ROM Translator :: translation export",
        f"# ROM: {sess.get('filename', 'unknown')}",
        f"# Encoding: {sess.get('encoding', 'ascii')}",
        f"# Target language: {sess.get('target_language', '?')}",
        "# Format: <original>\\t<translated>   (edit the RIGHT column freely, keep the LEFT column exactly)",
        "# Untranslated lines are pre-filled with the original text; lines left unchanged are skipped on import.",
        "# Lines starting with # are ignored on import.",
        "#",
        "# Control tokens in {curly braces} are game codes, NOT text. Keep them in your translation:",
        *[f"#   {tok:<44} {desc}" for tok, desc in TOKEN_LEGEND],
        "# You may move {n} {l} {p} to re-wrap a sentence; keep lines about as long as in the original.",
        "",
    ]
    for t in req.translations:
        # Sanitize tabs and newlines in each field
        orig = t.original.replace("\t", " ").replace("\r", " ").replace("\n", " ")
        tran = (t.translated or t.original).replace("\t", " ").replace("\r", " ").replace("\n", " ")
        lines.append(f"{orig}\t{tran}")

    content = "\n".join(lines) + "\n"
    fn = sess.get("filename", "rom.gb")
    base = os.path.splitext(fn)[0]
    out_name = f"{base}_translations.txt"
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{out_name}"'},
    )


@api_router.post("/rom/import")
async def import_translations(
    session_id: str = Form(...),
    file: UploadFile = File(...),
):
    """Upload a TXT file with edited translations and patch the ROM in place.
    Returns the patched ROM binary as a download.

    Accepts multiple encodings (UTF-8, UTF-16 with BOM, Windows-1250) and
    multiple field separators: TAB, `->`, `=`, or a run of 2+ spaces.
    """
    p = rom_path(session_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Session not found — the ROM must first be scanned via /api/rom/extract")

    raw_bytes = await file.read()

    # Decode: try UTF-16 BOM first (Notepad "Save As Unicode"), then UTF-8, then Windows-1250
    if raw_bytes.startswith(b"\xff\xfe") or raw_bytes.startswith(b"\xfe\xff"):
        raw = raw_bytes.decode("utf-16", errors="replace")
    else:
        try:
            raw = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                raw = raw_bytes.decode("windows-1250")
            except UnicodeDecodeError:
                raw = raw_bytes.decode("latin-1", errors="replace")
    # Strip UTF-8 BOM if present
    raw = raw.lstrip("\ufeff")

    # Parse: skip comments (#) and empty lines
    # Try separators in order: TAB, then ' -> ', ' = ', or run of 2+ spaces
    _sep_re = re.compile(r"\t| -> | = |  +")
    pairs = []
    unparseable = []
    for line in raw.splitlines():
        s = line.rstrip("\r\n")
        if not s.strip() or s.lstrip().startswith("#"):
            continue
        if "\t" in s:
            orig, tran = s.split("\t", 1)
            pairs.append((orig, tran.strip()))
            continue
        m = _sep_re.search(s)
        if not m:
            unparseable.append(s[:80])
            continue
        orig = s[:m.start()].rstrip()
        tran = s[m.end():].lstrip()
        pairs.append((orig, tran))

    if not pairs:
        sample = " | ".join(unparseable[:3]) if unparseable else "no non-comment lines"
        raise HTTPException(
            status_code=400,
            detail=(f"No translation lines found. Expected format: <original><TAB><translated> "
                    f"(or original -> translated / original = translated). Sample of ignored lines: {sample}"),
        )

    # Load ROM & encoding
    sess = _get_session(session_id)
    enc = (sess or {}).get("encoding", "ascii")
    data = bytearray(p.read_bytes())

    import asyncio
    _, _, occ = await asyncio.to_thread(extract_story, bytes(data), enc, (sess or {}).get("scan_mode", "bytewise"))
    filled = [(o, t) for o, t in pairs if t]
    missed = sum(1 for o, _ in filled if o not in occ)
    patched = apply_translations(data, enc, occ, filled)

    fn = (sess or {}).get("filename", "rom.gb")
    base, ext = os.path.splitext(fn)
    out_name = f"{base}_translated{ext}"

    return Response(
        content=bytes(data),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{out_name}"',
            "X-Patched-Count": str(patched),
            "X-Missed-Count": str(missed),
            "X-Total-Lines": str(len(pairs)),
        },
    )


@api_router.post("/rom/patch")
async def patch_rom(req: PatchRequest):
    p = rom_path(req.session_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="ROM session not found")

    sess = _get_session(req.session_id)
    enc = (sess or {}).get("encoding", "ascii")

    data = bytearray(p.read_bytes())

    import asyncio
    _, _, occ = await asyncio.to_thread(extract_story, bytes(data), enc, (sess or {}).get("scan_mode", "bytewise"))
    patched = apply_translations(data, enc, occ, [(t.original, t.translated) for t in req.translations])

    fn = (sess or {}).get("filename", "rom.gb")
    base, ext = os.path.splitext(fn)
    out_name = f"{base}_translated{ext}"

    return Response(
        content=bytes(data),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{out_name}"',
            "X-Patched-Count": str(patched),
        },
    )


@api_router.get("/history")
async def get_history():
    return _list_sessions()


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


