"""Tests for lenient JSON parsing + recursive batch-split retry (iteration 4)."""
import os
import sys
import json
import asyncio
import pytest
import requests
from unittest.mock import patch, AsyncMock

# Ensure backend dir importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import server  # noqa: E402
from server import _lenient_json_parse, _translate_batch, ExtractedString  # noqa: E402


BASE_URL = os.environ.get("REACT_APP_BACKEND_URL")
if not BASE_URL:
    # fall back to frontend/.env
    fe_env = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", ".env")
    if os.path.exists(fe_env):
        for line in open(fe_env):
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip()
                break
BASE_URL = (BASE_URL or "").rstrip("/")


# ---------- _lenient_json_parse ----------
class TestLenientJsonParse:
    def test_valid_json(self):
        text = '[{"id":"s1","translated":"hola"},{"id":"s2","translated":"adios"}]'
        v = _lenient_json_parse(text)
        assert isinstance(v, list) and len(v) == 2
        assert v[0]["id"] == "s1" and v[0]["translated"] == "hola"

    def test_prose_prefix(self):
        text = 'Sure! Here is your JSON:\n[{"id":"a","translated":"X"},{"id":"b","translated":"Y"}]\nHope that helps.'
        v = _lenient_json_parse(text)
        assert isinstance(v, list) and len(v) == 2
        ids = {p["id"] for p in v}
        assert ids == {"a", "b"}

    def test_code_fence_and_prose(self):
        text = 'Here you go:\n```json\n[{"id":"x","translated":"Ok"}]\n```'
        v = _lenient_json_parse(text)
        assert isinstance(v, list) and v[0]["id"] == "x"

    def test_invalid_escape(self):
        # Backslash before non-escape char -> strict json.loads fails
        text = '[{"id":"s1","translated":"Path\\to\\file"},{"id":"s2","translated":"ok"}]'
        v = _lenient_json_parse(text)
        assert isinstance(v, list) and len(v) >= 1
        by_id = {p["id"]: p.get("translated", "") for p in v}
        assert "s1" in by_id
        assert "s2" in by_id

    def test_trailing_comma(self):
        text = '[{"id":"s1","translated":"hi"},{"id":"s2","translated":"bye"},]'
        v = _lenient_json_parse(text)
        assert isinstance(v, list) and len(v) == 2

    def test_missing_outer_brackets(self):
        # comma-separated objects without brackets — falls back to line-by-line regex
        text = '{"id":"s1","translated":"one"},\n{"id":"s2","translated":"two"},\n{"id":"s3","translated":"three"}'
        v = _lenient_json_parse(text)
        assert isinstance(v, list) and len(v) == 3
        ids = {p["id"] for p in v}
        assert ids == {"s1", "s2", "s3"}

    def test_completely_garbage(self):
        text = 'sorry, I cannot help with that'
        v = _lenient_json_parse(text)
        assert v is None


# ---------- _translate_batch recursive split ----------
class TestTranslateBatchRecursiveSplit:
    def _batch(self, n=8):
        return [ExtractedString(id=f"s{i}", text=f"text{i}", offset=i, length=10) for i in range(n)]

    def test_recursive_split_on_bad_json(self):
        """First call returns garbage; subsequent calls return valid JSON per sub-batch."""
        call_count = {"n": 0}

        async def fake_call_llm(prompt, provider, model, api_key):
            call_count["n"] += 1
            # First (top-level) call returns garbage -> forces split
            if call_count["n"] == 1:
                return "utter garbage no json here"
            # Subsequent calls: parse the prompt to find ids and return valid JSON
            ids = re.findall(r'"id":"([^"]+)"', prompt)
            arr = [{"id": i, "translated": f"T-{i}"} for i in ids]
            return json.dumps(arr)

        import re  # noqa: E402
        batch = self._batch(8)
        with patch.object(server, "_call_llm", side_effect=fake_call_llm):
            results = asyncio.get_event_loop().run_until_complete(
                _translate_batch("Spanish", batch, "emergent", "m", None)
            )
        assert len(results) == 8
        # After split, sub-batches translated successfully
        good = [r for r in results if r.translated.startswith("T-")]
        assert len(good) == 8, f"Expected all 8 translated via recursive split, got {len(good)}"

    def test_all_garbage_falls_back_to_original(self):
        """If every recursive call returns garbage, small enough batches (<=3 or depth>=3) should raise,
        but at top-level worker catches and marks failed. Here we just check it eventually raises HTTPException."""
        async def fake_call_llm(prompt, provider, model, api_key):
            return "nothing to parse"

        from fastapi import HTTPException
        batch = self._batch(4)
        with patch.object(server, "_call_llm", side_effect=fake_call_llm):
            with pytest.raises(HTTPException):
                asyncio.get_event_loop().run_until_complete(
                    _translate_batch("Spanish", batch, "emergent", "m", None)
                )


# ---------- Prompt inspection ----------
class TestPromptRules:
    def test_prompt_forbids_backslash(self):
        from server import _build_translation_prompt
        p = _build_translation_prompt("Spanish", [ExtractedString(id="s1", text="hi", offset=0, length=2)])
        low = p.lower()
        assert "backslash" in low
        assert "rfc 8259" in low or "well-formed" in low
        assert "escape" in low


# ---------- HTTP status endpoint shape ----------
@pytest.mark.skipif(not BASE_URL, reason="No REACT_APP_BACKEND_URL configured")
class TestStatusEndpointShape:
    def test_status_not_found_returns_404(self):
        r = requests.get(f"{BASE_URL}/api/rom/translate/status/does-not-exist-xyz")
        assert r.status_code == 404

    def test_status_shape_after_start(self):
        # Extract a tiny synthetic ROM (must be >=1024 bytes and .gb/.gbc/.gba)
        rom = b"ABCDEFGHIJ" * 200 + b"HELLO WORLD" + b"\x00" * 200
        files = {"file": ("t.gb", rom, "application/octet-stream")}
        r = requests.post(f"{BASE_URL}/api/rom/extract", files=files,
                          data={"encoding": "ascii", "max_strings": 10})
        assert r.status_code == 200, r.text
        ext = r.json()
        assert "session_id" in ext and "strings" in ext
        if not ext["strings"]:
            pytest.skip("No strings extracted from synthetic ROM")

        payload = {
            "session_id": ext["session_id"],
            "target_language": "es",
            "strings": ext["strings"][:3],
            "provider": "emergent",
            "batch_size": 10,
        }
        r2 = requests.post(f"{BASE_URL}/api/rom/translate", json=payload)
        assert r2.status_code == 200, r2.text
        job_id = r2.json()["job_id"]

        # Poll up to 60s
        import time
        final = None
        for _ in range(30):
            s = requests.get(f"{BASE_URL}/api/rom/translate/status/{job_id}")
            assert s.status_code == 200
            body = s.json()
            # verify shape on every poll
            for key in ["status", "translated_count", "failed_count", "translations", "error", "error_code", "errors"]:
                assert key in body, f"missing '{key}' in status response"
            if body["status"] in ("done", "error"):
                final = body
                break
            time.sleep(2)
        assert final is not None, "Job did not reach terminal state within 60s"
        # We don't assert translated_count > 0 (may hit external quota). Just structure.
        print(f"Final job status={final['status']} translated={final['translated_count']} failed={final['failed_count']} error_code={final.get('error_code')}")
