from fastapi import FastAPI, APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import re
import json
import logging
import uuid
import base64
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime, timezone

from emergentintegrations.llm.chat import LlmChat, UserMessage
from google import genai as google_genai

from charmaps import (
    extract_pokemon_gen3_runs,
    encode_pokemon_gen3,
    detect_encoding,
    count_pokemon_gen3_runs,
)


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

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
        "label": "Emergent Universal Key (server default)",
        "keyHint": "No key needed — uses server-side credits",
        "models": [
            {"id": "gemini-3-flash-preview", "label": "Gemini 3 Flash (via Emergent)", "pricing": {"input": 0.10, "output": 0.40}},
            {"id": "gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro (via Emergent)", "pricing": {"input": 1.30, "output": 10.5}},
            {"id": "gpt-5.4-mini", "label": "GPT-5.4 Mini (via Emergent)", "pricing": {"input": 0.20, "output": 0.70}},
            {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6 (via Emergent)", "pricing": {"input": 3.10, "output": 15.5}},
        ],
        "default": "gemini-3-flash-preview",
    },
}

# In-memory job registry for async translation
JOBS: dict = {}


def _error_code(err: str) -> str:
    low = (err or "").lower()
    if "emergent_budget_exceeded" in low or "budget has been exceeded" in low:
        return "EMERGENT_BUDGET_EXCEEDED"
    if "resource_exhausted" in low or "429" in low or "quota" in low or "rate" in low:
        return "QUOTA_EXCEEDED"
    if "invalid api key" in low or "unauthorized" in low or "api key missing" in low:
        return "INVALID_KEY"
    if "timeout" in low:
        return "TIMEOUT"
    return "UPSTREAM_ERROR"


def _friendly_error(err: str) -> str:
    code = _error_code(err)
    if code == "EMERGENT_BUDGET_EXCEEDED":
        return ("Emergent Universal Key credit is exhausted. "
                "Add balance in Profile → Manage plan → Universal Key, "
                "or open Settings and switch to your own AI provider (Gemini / OpenAI / Anthropic).")
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
    strings: List[ExtractedString]

class TranslateRequest(BaseModel):
    session_id: str
    target_language: str  # ISO code label e.g. "cs", "en"
    strings: List[ExtractedString]
    provider: Optional[str] = "emergent"     # gemini | openai | anthropic | emergent
    model: Optional[str] = None              # provider-specific model id (falls back to provider default)
    api_key: Optional[str] = None            # user's own key (empty -> use server default when provider=emergent)
    batch_size: Optional[int] = None         # strings per single LLM call (defaults to DEFAULT_BATCH_SIZE)

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
DEFAULT_BATCH_SIZE = 60       # strings per single LLM call (bigger = fewer calls / cheaper / faster)
MAX_BATCH_SIZE = 300          # upper limit to protect against output token truncation
MAX_PARALLEL = 8              # parallel batch calls
PRINTABLE_RE = re.compile(rb"[\x20-\x7E]{%d,}" % MIN_STRING_LEN)


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


def extract_gen3_from_bytes(data: bytes, max_strings: int) -> List[ExtractedString]:
    # Lower min_length so we catch short dialogs like "Yes!", "OK.", names, menu items
    runs = extract_pokemon_gen3_runs(data, min_length=5, max_results=max_strings)
    return [
        ExtractedString(id=str(uuid.uuid4()), offset=off, length=length, text=text)
        for off, length, text in runs
    ]


def extract_strings_from_bytes(data: bytes, encoding: str = "ascii", max_strings: int = DEFAULT_MAX_STRINGS) -> List[ExtractedString]:
    # 0 or negative means "no user cap" -> use HARD_MAX_STRINGS
    if max_strings <= 0:
        max_strings = HARD_MAX_STRINGS
    else:
        max_strings = min(max(max_strings, 10), HARD_MAX_STRINGS)
    if encoding == "pokemon_gen3":
        return extract_gen3_from_bytes(data, max_strings)
    return extract_ascii_from_bytes(data, max_strings)


# ---------- Session storage (ROM binary) ----------
SESSION_DIR = ROOT_DIR / "rom_sessions"
SESSION_DIR.mkdir(exist_ok=True)


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
    return PROVIDERS


@api_router.get("/encodings")
async def get_encodings():
    return [
        {"id": "auto", "label": "Auto-detect (recommended)"},
        {"id": "ascii", "label": "ASCII (homebrew, dev ROMs)"},
        {"id": "pokemon_gen3", "label": "Pokemon Gen 3 (Emerald / Ruby / Sapphire / FRLG)"},
    ]


@api_router.post("/rom/extract", response_model=ExtractResponse)
async def extract_rom(
    file: UploadFile = File(...),
    encoding: str = Form("auto"),
    max_strings: int = Form(DEFAULT_MAX_STRINGS),
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
        enc = detect_encoding(data, fn)
    if enc not in {"ascii", "pokemon_gen3"}:
        raise HTTPException(status_code=400, detail=f"Unknown encoding '{enc}'")

    session_id = str(uuid.uuid4())
    rom_path(session_id).write_bytes(data)

    strings = extract_strings_from_bytes(data, encoding=enc, max_strings=max_strings)
    # If user asked for unlimited (max_strings<=0), we already have every string; skip the second pass
    if max_strings <= 0:
        found_total = len(strings)
    elif enc == "pokemon_gen3":
        found_total = count_pokemon_gen3_runs(data, min_length=5)
    else:
        found_total = len(extract_ascii_from_bytes(data, HARD_MAX_STRINGS))
    rom_type = detect_rom_type(fn, len(data))

    record = {
        "session_id": session_id,
        "filename": fn,
        "rom_size": len(data),
        "rom_type": rom_type,
        "encoding": enc,
        "string_count": len(strings),
        "found_total": found_total,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.rom_sessions.insert_one(record)

    return ExtractResponse(
        session_id=session_id,
        filename=fn,
        rom_size=len(data),
        rom_type=rom_type,
        encoding=enc,
        found_total=found_total,
        strings=strings,
    )


def _build_translation_prompt(target_lang_name: str, strings: List[ExtractedString]) -> str:
    lines = []
    for s in strings:
        lines.append(f'{{"id":"{s.id}","text":{json.dumps(s.text)}}}')
    joined = "\n".join(lines)
    return (
        f"You are a professional video game localizer. Translate the following in-game texts extracted from a Gameboy ROM "
        f"into {target_lang_name}.\n\n"
        f"IMPORTANT RULES:\n"
        f"1. Keep translations concise. Try to match the ORIGINAL LENGTH in characters — game text often has fixed buffers. "
        f"If the translation would be longer, abbreviate naturally to fit within the original length ({{'max_chars'}}).\n"
        f"2. Preserve punctuation and any leading/trailing spaces exactly.\n"
        f"3. Do NOT translate obvious code identifiers, file names, register names, or gibberish (return them unchanged).\n"
        f"4. Only use printable ASCII characters (a-z, A-Z, 0-9, punctuation, space). No accents, no unicode — Gameboy fonts can't render them.\n"
        f"5. Return STRICT JSON only — a single JSON array of objects with keys \"id\" and \"translated\". No prose, no code fences.\n\n"
        f"INPUT (one JSON object per line):\n{joined}\n\n"
        f"OUTPUT: JSON array only."
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
        client_ = google_genai.Client(api_key=key)
        try:
            resp = await asyncio.wait_for(
                asyncio.to_thread(client_.models.generate_content, model=model, contents=prompt),
                timeout=60,
            )
            return resp.text or ""
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Gemini error: {str(e)[:300]}")

    # --- OpenAI via official SDK ---
    if provider == "openai":
        key = api_key
        if not key:
            raise HTTPException(status_code=400, detail="OpenAI API key missing")
        from openai import AsyncOpenAI
        client_ = AsyncOpenAI(api_key=key)
        try:
            resp = await asyncio.wait_for(
                client_.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You are a precise game text translator that returns only JSON."},
                        {"role": "user", "content": prompt},
                    ],
                ),
                timeout=60,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"OpenAI error: {str(e)[:300]}")

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
                timeout=60,
            )
            # concatenate text blocks
            return "".join(getattr(b, "text", "") for b in msg.content) or ""
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Anthropic error: {str(e)[:300]}")

    # --- Emergent Universal Key via emergentintegrations ---
    if provider == "emergent":
        if not EMERGENT_LLM_KEY:
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
            api_key=EMERGENT_LLM_KEY,
            session_id=f"trans-{uuid.uuid4()}",
            system_message="You are a precise game text translator that returns only JSON.",
        ).with_model(e_provider, model)
        try:
            resp = await asyncio.wait_for(
                chat.send_message(UserMessage(text=prompt)),
                timeout=60,
            )
            return resp if isinstance(resp, str) else str(resp)
        except Exception as e:
            msg = str(e)
            # Detect the Emergent free-tier budget cap and surface a friendly message
            low = msg.lower()
            if "budget has been exceeded" in low or "max budget" in low:
                raise HTTPException(
                    status_code=402,
                    detail="EMERGENT_BUDGET_EXCEEDED: Emergent Universal Key credit was used up. Add balance in Profile → Manage plan → Universal Key, or switch to your own API key (Gemini / OpenAI / Anthropic) in Settings.",
                )
            raise HTTPException(status_code=502, detail=f"Emergent error: {msg[:300]}")

    raise HTTPException(status_code=400, detail=f"Provider '{provider}' not implemented")


async def _translate_batch(
    target_lang_name: str,
    batch: List[ExtractedString],
    provider: str,
    model: Optional[str],
    api_key: Optional[str],
) -> List[TranslatedString]:
    if not batch:
        return []

    prompt = _build_translation_prompt(target_lang_name, batch)

    # Try primary provider, auto-fallback to Emergent Universal Key on quota / upstream errors
    try:
        text = (await _call_llm(prompt, provider, model, api_key)).strip()
    except HTTPException as e:
        msg = str(e.detail).lower()
        is_quota = ("429" in msg or "resource_exhausted" in msg or "quota" in msg or "rate" in msg)
        is_upstream = e.status_code in (502, 503, 504)
        if provider != "emergent" and EMERGENT_LLM_KEY and (is_quota or is_upstream):
            logging.warning(f"Primary {provider} failed ({e.detail[:120]}), falling back to Emergent")
            text = (await _call_llm(prompt, "emergent", None, None)).strip()
        else:
            raise

    # Strip code fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except Exception:
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            raise HTTPException(status_code=502, detail="Translator returned invalid JSON")
        parsed = json.loads(m.group())

    by_id = {p.get("id"): p.get("translated", "") for p in parsed if isinstance(p, dict)}
    results = []
    for s in batch:
        tr = by_id.get(s.id, s.text)
        tr = "".join(ch if 0x20 <= ord(ch) <= 0x7E else "?" for ch in tr)
        results.append(TranslatedString(id=s.id, original=s.text, translated=tr))
    return results


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
        "translations": [],
        "error": None,
        "errors": [],
        "session_id": req.session_id,
        "target_language": req.target_language,
        "provider": provider,
        "model": req.model or PROVIDERS[provider]["default"],
    }

    async def worker():
        # Clamp user-requested batch_size into [10 .. MAX_BATCH_SIZE]
        bs = req.batch_size or DEFAULT_BATCH_SIZE
        bs = min(max(bs, 10), MAX_BATCH_SIZE)
        batches = [req.strings[i:i + bs] for i in range(0, len(req.strings), bs)]
        sem = asyncio.Semaphore(MAX_PARALLEL)
        abort_flag = {"stop": False, "reason": None}

        async def run(batch):
            async with sem:
                # Fail fast: if a prior batch hit a fatal error like budget exhaustion,
                # skip remaining batches instead of wasting time / retries.
                if abort_flag["stop"]:
                    out = [TranslatedString(id=s.id, original=s.text, translated=s.text) for s in batch]
                    JOBS[job_id]["failed_count"] += len(batch)
                    JOBS[job_id]["done"] += len(batch)
                    JOBS[job_id]["translations"].extend([t.model_dump() for t in out])
                    return out

                failed = False
                err_msg = None
                try:
                    out = await _translate_batch(lang_name, batch, provider, req.model, req.api_key)
                    real_translated = sum(1 for t, s in zip(out, batch) if t.translated != s.text)
                    JOBS[job_id]["translated_count"] += real_translated
                except Exception as e:
                    failed = True
                    err_msg = str(getattr(e, "detail", None) or e)[:250]
                    logging.warning(f"Batch failed: {err_msg}")
                    out = [TranslatedString(id=s.id, original=s.text, translated=s.text) for s in batch]
                    JOBS[job_id]["failed_count"] += len(batch)
                    # Detect fatal errors that will keep failing every batch -> abort
                    low = err_msg.lower()
                    if ("emergent_budget_exceeded" in low
                        or "budget has been exceeded" in low
                        or "invalid api key" in low
                        or "unauthorized" in low
                        or "api key missing" in low):
                        abort_flag["stop"] = True
                        abort_flag["reason"] = err_msg
                JOBS[job_id]["done"] += len(batch)
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
            await db.rom_sessions.update_one(
                {"session_id": req.session_id},
                {"$set": {"target_language": req.target_language,
                          "translated_at": datetime.now(timezone.utc).isoformat()}}
            )
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
        "failed_count": job.get("failed_count", 0),
        "translations": job["translations"],
        "error": job["error"],
        "error_code": job.get("error_code"),
        "errors": job.get("errors", []),
    }


@api_router.post("/rom/patch")
async def patch_rom(req: PatchRequest):
    p = rom_path(req.session_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="ROM session not found")

    sess = await db.rom_sessions.find_one({"session_id": req.session_id}, {"_id": 0})
    enc = (sess or {}).get("encoding", "ascii")

    data = bytearray(p.read_bytes())

    # Re-extract to get canonical offset mapping using the same encoding
    strings = extract_strings_from_bytes(bytes(data), encoding=enc)
    text_to_meta = {s.text: (s.offset, s.length) for s in strings}

    patched = 0
    for t in req.translations:
        meta = text_to_meta.get(t.original)
        if not meta:
            continue
        offset, length = meta
        if enc == "pokemon_gen3":
            payload = encode_pokemon_gen3(t.translated, length)
        else:
            raw = t.translated.encode("ascii", errors="replace")
            if len(raw) > length:
                payload = raw[:length]
            else:
                payload = raw + b" " * (length - len(raw))
        data[offset:offset + length] = payload
        patched += 1

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
    docs = await db.rom_sessions.find({}, {"_id": 0}).sort("created_at", -1).to_list(20)
    return docs


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


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
