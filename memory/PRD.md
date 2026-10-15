# ROM.TRANSLATE — PRD
## Problem
Jednoduchá aplikace na překládání her na Gameboy: nahraje se ROM, vybere jazyk, AI přeloží všechny nalezené texty. (User communicates in Czech.)

## Architecture
React + FastAPI + MongoDB. backend/server.py (API, async translation jobs, cache), backend/charmaps.py (Pokemon Gen3 charmap, pointer scan). Frontend: pages/RomTranslator.jsx, components/rom/*.

## Implemented
- ROM upload, bytewise/pointer-table text extraction, Gen3 charmap
- Multi-provider AI translation (Emergent/Gemini/OpenAI/Claude), batching, json_repair, cost estimate
- Translation cache in Mongo (translation_cache), TXT export/import, patched ROM download
- 2026-06: "Smazat cache" button in header with confirmation dialog (ClearCacheButton.jsx)

## Backlog
- P1: LZ77 decompression for GBA compressed texts; React error boundaries
- P2: Diff preview on TXT import; hardcoded Emerald pointer tables; inline editable cells; reduce bytewise false positives
- P3: Live chunk progress in table; cache savings stats in header
