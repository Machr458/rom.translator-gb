"""Tests for translation cache: /api/cache/stats, /api/cache/clear, and cache reuse
across /api/rom/translate jobs."""
import os
import time
import io
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"


# ---------- helpers ----------
def _make_rom(strings, size=4096):
    """Build a small ROM-shaped bytes buffer with printable ASCII strings separated by NULs."""
    buf = bytearray(b"\x00" * size)
    off = 0x100
    for s in strings:
        b = s.encode("ascii") + b"\x00"
        buf[off:off + len(b)] = b
        off += len(b) + 4
    # Fake GB header magic-ish area just to be safe (not strictly needed by extractor).
    return bytes(buf)


def _clear_cache(lang=None):
    params = {"target_language": lang} if lang else {}
    r = requests.post(f"{API}/cache/clear", params=params, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _stats():
    r = requests.get(f"{API}/cache/stats", timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _extract(rom_bytes, filename="test.gb"):
    files = {"file": (filename, io.BytesIO(rom_bytes), "application/octet-stream")}
    data = {"encoding": "ascii", "max_strings": "50"}
    r = requests.post(f"{API}/rom/extract", files=files, data=data, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def _translate(session_id, target_lang, strings, provider="emergent"):
    payload = {
        "session_id": session_id,
        "target_language": target_lang,
        "strings": strings,
        "provider": provider,
    }
    r = requests.post(f"{API}/rom/translate", json=payload, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["job_id"]


def _poll(job_id, timeout=120):
    start = time.time()
    last = None
    while time.time() - start < timeout:
        r = requests.get(f"{API}/rom/translate/status/{job_id}", timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        last = j
        if j["status"] in ("done", "error"):
            return j, time.time() - start
        time.sleep(0.3)
    pytest.fail(f"Job {job_id} timed out. Last: {last}")


# ---------- tests ----------

class TestCacheStatsAndClear:
    def test_stats_after_full_clear(self):
        _clear_cache()
        s = _stats()
        assert s["total"] == 0
        assert s["per_language"] == []
        assert isinstance(s["total"], int)
        assert isinstance(s["per_language"], list)

    def test_clear_returns_deleted_count(self):
        _clear_cache()
        r = requests.post(f"{API}/cache/clear", timeout=15)
        assert r.status_code == 200
        assert "deleted" in r.json()


class TestTranslationCacheFlow:
    """End-to-end: extract → translate (fresh) → translate again (cached)."""

    @pytest.fixture(scope="class")
    def fresh_run(self):
        _clear_cache()
        rom = _make_rom(["HELLO WORLD", "GAME OVER", "PRESS START", "NEW GAME", "CONTINUE"])
        ext = _extract(rom)
        strings = ext["strings"]
        assert len(strings) >= 3, f"Expected at least 3 extracted strings, got {len(strings)}: {strings}"
        # Keep to a small subset to minimize cost.
        strings = strings[:5]
        job_id = _translate(ext["session_id"], "cs", strings)
        result, elapsed = _poll(job_id, timeout=180)
        return {"ext": ext, "strings": strings, "result": result, "elapsed": elapsed}

    def test_first_run_translates_and_populates_cache(self, fresh_run):
        r = fresh_run["result"]
        assert r["status"] == "done", f"Job failed: {r}"
        assert r["translated_count"] > 0
        assert r["cached_count"] == 0, "First run should have zero cached hits"
        # Cache should now contain entries
        s = _stats()
        assert s["total"] >= r["translated_count"], f"stats={s} translated={r['translated_count']}"
        langs = {e["lang"]: e["count"] for e in s["per_language"]}
        assert "cs" in langs
        assert langs["cs"] >= r["translated_count"]

    def test_second_run_hits_cache_and_is_fast(self, fresh_run):
        ext = fresh_run["ext"]
        strings = fresh_run["strings"]
        first_translations = {t["original"]: t["translated"] for t in fresh_run["result"]["translations"]}

        job_id = _translate(ext["session_id"], "cs", strings)
        result, elapsed = _poll(job_id, timeout=30)
        assert result["status"] == "done", f"Second job failed: {result}"
        assert result["cached_count"] == len(strings), (
            f"Expected all {len(strings)} strings from cache, got cached_count={result['cached_count']}, result={result}"
        )
        assert result["translated_count"] >= result["cached_count"]
        # Should be fast: no LLM call. Allow 5s network slack.
        assert elapsed < 5.0, f"Cached run took {elapsed:.2f}s — likely hit LLM"
        # Translations must match first run
        second_translations = {t["original"]: t["translated"] for t in result["translations"]}
        for orig, tr in first_translations.items():
            assert second_translations.get(orig) == tr, (
                f"Cached translation mismatch for '{orig}': first={tr!r} second={second_translations.get(orig)!r}"
            )


class TestStatusContract:
    def test_status_has_cached_count_field(self):
        """Even a minimal translate job status response must expose the new field."""
        _clear_cache()
        rom = _make_rom(["HELLO WORLD", "GAME OVER", "PRESS START"])
        ext = _extract(rom)
        strings = ext["strings"][:3]
        job_id = _translate(ext["session_id"], "cs", strings)
        result, _ = _poll(job_id, timeout=180)
        for field in ("status", "total", "done", "translated_count", "cached_count",
                      "failed_count", "translations", "error", "error_code", "errors"):
            assert field in result, f"Missing field '{field}' in status response: {result.keys()}"


class TestCacheKeySeparationByLanguage:
    def test_same_text_different_lang_creates_separate_entries(self):
        _clear_cache()
        rom = _make_rom(["HELLO WORLD", "GAME OVER", "PRESS START"])
        ext = _extract(rom)
        strings = ext["strings"][:3]

        # Translate to cs
        j1 = _translate(ext["session_id"], "cs", strings)
        r1, _ = _poll(j1, timeout=180)
        assert r1["status"] == "done"
        cs_count = r1["translated_count"]

        stats_after_cs = _stats()
        cs_stat = next((e for e in stats_after_cs["per_language"] if e["lang"] == "cs"), None)
        assert cs_stat is not None and cs_stat["count"] >= cs_count

        # Translate the same strings to en (new job, new lang)
        j2 = _translate(ext["session_id"], "en", strings)
        r2, _ = _poll(j2, timeout=180)
        assert r2["status"] == "done"
        assert r2["cached_count"] == 0, "en should not reuse cs cache entries"

        stats_after_both = _stats()
        by_lang = {e["lang"]: e["count"] for e in stats_after_both["per_language"]}
        assert "cs" in by_lang and "en" in by_lang, f"Expected both cs and en entries: {by_lang}"

        # Now clear only cs; en should remain
        _clear_cache("cs")
        stats_after_clear_cs = _stats()
        by_lang2 = {e["lang"]: e["count"] for e in stats_after_clear_cs["per_language"]}
        assert "cs" not in by_lang2, f"cs entries should be gone: {by_lang2}"
        assert "en" in by_lang2, f"en entries should remain: {by_lang2}"

        # Full clear
        _clear_cache()
        assert _stats()["total"] == 0
