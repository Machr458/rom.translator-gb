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


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY')
GEMINI_MODEL = "gemini-3.1-pro-preview"

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
MAX_STRINGS = 300  # cap to keep translation cost reasonable
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


async def _translate_batch(target_lang_name: str, batch: List[ExtractedString]) -> List[TranslatedString]:
    if not batch:
        return []
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"trans-{uuid.uuid4()}",
        system_message="You are a precise game text translator that returns only JSON.",
    ).with_model("gemini", GEMINI_MODEL)

    prompt = _build_translation_prompt(target_lang_name, batch)
    resp = await chat.send_message(UserMessage(text=prompt))

    # Extract JSON
    text = resp if isinstance(resp, str) else str(resp)
    text = text.strip()
    # Strip code fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except Exception:
        # Try to find JSON array in text
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            raise HTTPException(status_code=502, detail="Translator returned invalid JSON")
        parsed = json.loads(m.group())

    by_id = {p.get("id"): p.get("translated", "") for p in parsed if isinstance(p, dict)}
    results = []
    for s in batch:
        tr = by_id.get(s.id, s.text)
        # sanitize to ASCII printable
        tr = "".join(ch if 0x20 <= ord(ch) <= 0x7E else "?" for ch in tr)
        results.append(TranslatedString(id=s.id, original=s.text, translated=tr))
    return results


@api_router.post("/rom/translate", response_model=TranslateResponse)
async def translate_rom(req: TranslateRequest):
    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=500, detail="LLM key not configured")
    lang_name = LANGUAGE_NAMES.get(req.target_language)
    if not lang_name:
        raise HTTPException(status_code=400, detail="Unsupported language")

    # Batch to keep prompts small; ~40 strings per call
    BATCH = 40
    all_out: List[TranslatedString] = []
    for i in range(0, len(req.strings), BATCH):
        batch = req.strings[i:i + BATCH]
        out = await _translate_batch(lang_name, batch)
        all_out.extend(out)

    await db.rom_sessions.update_one(
        {"session_id": req.session_id},
        {"$set": {"target_language": req.target_language, "translated_at": datetime.now(timezone.utc).isoformat()}}
    )

    return TranslateResponse(
        session_id=req.session_id,
        target_language=req.target_language,
        translations=all_out,
    )


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
