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


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

# Provider catalog with recommended models
PROVIDERS = {
    "gemini": {
        "label": "Google Gemini",
        "keyHint": "AIza... (Google AI Studio) or your project key",
        "models": [
            {"id": "gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro (best quality)"},
            {"id": "gemini-3-flash-preview", "label": "Gemini 3 Flash (fast, cheap)"},
            {"id": "gemini-2.5-pro", "label": "Gemini 2.5 Pro"},
            {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
        ],
        "default": "gemini-3-flash-preview",
    },
    "openai": {
        "label": "OpenAI",
        "keyHint": "sk-... from platform.openai.com",
        "models": [
            {"id": "gpt-5.4", "label": "GPT-5.4 (recommended)"},
            {"id": "gpt-5.4-mini", "label": "GPT-5.4 Mini (fast)"},
            {"id": "gpt-5", "label": "GPT-5"},
            {"id": "gpt-4o", "label": "GPT-4o"},
        ],
        "default": "gpt-5.4-mini",
    },
    "anthropic": {
        "label": "Anthropic Claude",
        "keyHint": "sk-ant-... from console.anthropic.com",
        "models": [
            {"id": "claude-sonnet-5", "label": "Claude Sonnet 5 (best)"},
            {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6 (recommended)"},
            {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5 (fast)"},
        ],
        "default": "claude-sonnet-4-6",
    },
    "emergent": {
        "label": "Emergent Universal Key (server default)",
        "keyHint": "No key needed — uses server-side credits",
        "models": [
            {"id": "gemini-3-flash-preview", "label": "Gemini 3 Flash (via Emergent)"},
            {"id": "gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro (via Emergent)"},
            {"id": "gpt-5.4-mini", "label": "GPT-5.4 Mini (via Emergent)"},
            {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6 (via Emergent)"},
        ],
        "default": "gemini-3-flash-preview",
    },
}

# In-memory job registry for async translation
JOBS: dict = {}

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
MAX_STRINGS = 150  # cap to keep translation cost reasonable
BATCH_SIZE = 15     # smaller batches -> faster individual Gemini calls
MAX_PARALLEL = 8    # parallel batch calls
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


def extract_strings_from_bytes(data: bytes) -> List[ExtractedString]:
    results: List[ExtractedString] = []
    seen_texts = set()
    for m in PRINTABLE_RE.finditer(data):
        text = m.group().decode("ascii", errors="ignore").strip()
        if len(text) < MIN_STRING_LEN:
            continue
        # Filter noise: require at least one letter and >=2 vowels-ish OR contains spaces
        letters = sum(1 for c in text if c.isalpha())
        if letters < 3:
            continue
        # dedupe by lowercased text (translate once) but keep first offset info
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
        if len(results) >= MAX_STRINGS:
            break
    return results


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


@api_router.post("/rom/extract", response_model=ExtractResponse)
async def extract_rom(file: UploadFile = File(...)):
    fn = file.filename or "rom.gb"
    if not fn.lower().endswith((".gb", ".gbc", ".gba")):
        raise HTTPException(status_code=400, detail="Unsupported file type. Use .gb, .gbc or .gba")

    data = await file.read()
    if len(data) < 1024:
        raise HTTPException(status_code=400, detail="ROM too small")
    if len(data) > 40 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="ROM too large (max 40MB)")

    session_id = str(uuid.uuid4())
    rom_path(session_id).write_bytes(data)

    strings = extract_strings_from_bytes(data)
    rom_type = detect_rom_type(fn, len(data))

    record = {
        "session_id": session_id,
        "filename": fn,
        "rom_size": len(data),
        "rom_type": rom_type,
        "string_count": len(strings),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.rom_sessions.insert_one(record)

    return ExtractResponse(
        session_id=session_id,
        filename=fn,
        rom_size=len(data),
        rom_type=rom_type,
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
            raise HTTPException(status_code=502, detail=f"Emergent error: {str(e)[:300]}")

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
    text = (await _call_llm(prompt, provider, model, api_key)).strip()

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
        "translations": [],
        "error": None,
        "session_id": req.session_id,
        "target_language": req.target_language,
        "provider": provider,
        "model": req.model or PROVIDERS[provider]["default"],
    }

    async def worker():
        batches = [req.strings[i:i + BATCH_SIZE] for i in range(0, len(req.strings), BATCH_SIZE)]
        sem = asyncio.Semaphore(MAX_PARALLEL)

        async def run(batch):
            async with sem:
                try:
                    out = await _translate_batch(lang_name, batch, provider, req.model, req.api_key)
                except Exception as e:
                    logging.warning(f"Batch failed, keeping originals: {e}")
                    out = [TranslatedString(id=s.id, original=s.text, translated=s.text) for s in batch]
                JOBS[job_id]["done"] += len(batch)
                JOBS[job_id]["translations"].extend([t.model_dump() for t in out])
                return out

        try:
            await asyncio.gather(*[run(b) for b in batches])
            JOBS[job_id]["status"] = "done"
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
        "translations": job["translations"],
        "error": job["error"],
    }


@api_router.post("/rom/patch")
async def patch_rom(req: PatchRequest):
    p = rom_path(req.session_id)
    if not p.exists():
        raise HTTPException(status_code=404, detail="ROM session not found")

    data = bytearray(p.read_bytes())

    # We need offsets — load them from the extraction (re-extract to get canonical mapping)
    strings = extract_strings_from_bytes(bytes(data))
    text_to_meta = {s.text: (s.offset, s.length) for s in strings}

    patched = 0
    for t in req.translations:
        meta = text_to_meta.get(t.original)
        if not meta:
            continue
        offset, length = meta
        payload = t.translated.encode("ascii", errors="replace")
        if len(payload) > length:
            payload = payload[:length]
        else:
            # pad with spaces to preserve length
            payload = payload + b" " * (length - len(payload))
        data[offset:offset + length] = payload
        patched += 1

    sess = await db.rom_sessions.find_one({"session_id": req.session_id}, {"_id": 0})
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
