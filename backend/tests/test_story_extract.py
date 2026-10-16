# Iteration 4: story extraction (Gen1/Gen3), patch, export/import tokens, cache entry
import os
import sys
import pytest
import requests

sys.path.insert(0, "/app/backend")
from text_extract import GEN3, GEN1  # noqa: E402

# Large ROM uploads go to the internal backend (public ingress is slow for 16MB)
BASE = os.environ.get("BACKEND_INTERNAL_URL", "http://localhost:8001").rstrip("/")
PUBLIC = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
EMERALD, YELLOW = "/tmp/emerald.gba", "/tmp/yellow.gbc"
T = 300


def _extract(path, **form):
    with open(path, "rb") as f:
        r = requests.post(f"{BASE}/api/rom/extract", files={"file": (os.path.basename(path), f)},
                          data={"encoding": "auto", **form}, timeout=T)
    assert r.status_code == 200, r.text[:300]
    return r.json()


@pytest.fixture(scope="module")
def emerald():
    return _extract(EMERALD, scan_mode="bytewise")


@pytest.fixture(scope="module")
def yellow():
    return _extract(YELLOW)


# --- Gen3 extraction ---
class TestEmerald:
    def test_encoding_and_counts(self, emerald):
        print("emerald found", emerald["found_total"], "names", emerald["excluded_names"])
        assert emerald["encoding"] == "pokemon_gen3"
        assert emerald["found_total"] >= 10000
        assert len(emerald["strings"]) == emerald["found_total"]
        assert 3000 <= emerald["excluded_names"] <= 6000

    def test_dialog_tokens_present(self, emerald):
        texts = [s["text"] for s in emerald["strings"]]
        for tok in ("{n}", "{p}", "{PLAYER}"):
            assert any(tok in t for t in texts), tok

    def test_names_excluded(self, emerald):
        texts = {s["text"] for s in emerald["strings"]}
        for nm in ("BULBASAUR", "POUND", "PIKACHU", "POTION", "LITTLEROOT TOWN"):
            assert nm not in texts, nm

    def test_pointers_mode_fewer(self, emerald):
        p = _extract(EMERALD, scan_mode="pointers")
        print("pointers found", p["found_total"])
        assert p["encoding"] == "pokemon_gen3"
        assert 0 < p["found_total"] < emerald["found_total"]

    def test_max_strings_param_still_caps(self):
        p = _extract(YELLOW, max_strings="50")
        assert p["found_total"] == 50


# --- Gen1 extraction ---
class TestYellow:
    def test_gen1(self, yellow):
        texts = [s["text"] for s in yellow["strings"]]
        print("yellow found", yellow["found_total"], "names", yellow["excluded_names"])
        assert yellow["encoding"] == "pokemon_gen1"
        assert 1500 <= yellow["found_total"] <= 4000
        assert not any("{POKE}" in t for t in texts)
        assert any("POKéMON" in t for t in texts)
        assert "PIKACHU" not in texts
        assert yellow["excluded_names"] > 100


# --- Patch ---
class TestPatch:
    def _pick(self, strings, codec_tokens=("{n}",)):
        return [s for s in strings if any(t in s["text"] for t in codec_tokens) and s["length"] > 30][:2]

    def test_patch_gen3(self, emerald):
        picks = self._pick(emerald["strings"])
        empty = [s for s in emerald["strings"] if s not in picks][5]
        tr = [{"id": s["id"], "original": s["text"], "translated": "TEST PREKLAD{n}ahoj"} for s in picks]
        tr.append({"id": empty["id"], "original": empty["text"], "translated": ""})
        r = requests.post(f"{BASE}/api/rom/patch", json={"session_id": emerald["session_id"], "translations": tr}, timeout=T)
        assert r.status_code == 200
        assert r.headers.get("X-Patched-Count") == "2"
        out = r.content
        assert len(out) == os.path.getsize(EMERALD)
        for s in picks:
            dec = GEN3.decode(out, s["offset"])
            assert dec and dec[1] == "TEST PREKLAD{n}ahoj", dec
        dec = GEN3.decode(out, empty["offset"])
        assert dec and dec[1] == empty["text"]

    def test_patch_gen1(self, yellow):
        picks = self._pick(yellow["strings"])
        tr = [{"id": s["id"], "original": s["text"], "translated": "Ahoj POKéMON{n}svete!"} for s in picks]
        r = requests.post(f"{BASE}/api/rom/patch", json={"session_id": yellow["session_id"], "translations": tr}, timeout=T)
        assert r.status_code == 200 and int(r.headers["X-Patched-Count"]) == len(picks)
        assert len(r.content) == os.path.getsize(YELLOW)
        for s in picks:
            assert GEN1.decode(r.content, s["offset"])[1] == "Ahoj POKéMON{n}svete!"


# --- Export / Import ---
class TestExportImport:
    def test_export_legend(self, yellow):
        s = yellow["strings"][0]
        r = requests.post(f"{BASE}/api/rom/export", json={"session_id": yellow["session_id"], "translations": [
            {"id": s["id"], "original": s["text"], "translated": "x"}]}, timeout=T)
        assert r.status_code == 200
        head = [ln for ln in r.text.splitlines() if ln.startswith("#")]
        blob = "\n".join(head)
        for tok in ("{n}", "{l}", "{p}", "{PLAYER}"):
            assert tok in blob, tok
        assert f"{s['text']}\tx" in r.text

    def test_import_tab_double_space(self, yellow):
        dbl = [s for s in yellow["strings"] if "  " in s["text"]]
        normal = [s for s in yellow["strings"] if "{n}" in s["text"] and s["length"] > 20][:2]
        rows = normal + dbl[:1]
        print("double-space originals available:", len(dbl))
        txt = "# header\n" + "".join(f"{s['text']}\tPrelozeno {i}\n" for i, s in enumerate(rows))
        r = requests.post(f"{BASE}/api/rom/import", data={"session_id": yellow["session_id"]},
                          files={"file": ("t.txt", txt.encode())}, timeout=T)
        assert r.status_code == 200, r.text[:200]
        assert int(r.headers["X-Patched-Count"]) == len(rows)
        assert r.headers["X-Missed-Count"] == "0"
        for i, s in enumerate(rows):
            assert GEN1.decode(r.content, s["offset"])[1] == f"Prelozeno {i}"


# --- Cache entry (target_language zz only!) ---
class TestCacheEntry:
    def test_entry_and_cleanup(self):
        r = requests.post(f"{BASE}/api/cache/entry", json={"source": "TEST_src", "translated": "TEST_tr", "target_language": "zz"})
        assert r.status_code == 200 and r.json()["saved"] is True
        st = requests.get(f"{BASE}/api/cache/stats").json()
        assert any(p["lang"] == "zz" and p["count"] >= 1 for p in st["per_language"])
        r = requests.post(f"{BASE}/api/cache/entry", json={"source": "TEST_src", "translated": "  ", "target_language": "zz"})
        assert r.status_code == 400
        r = requests.post(f"{BASE}/api/cache/clear", params={"target_language": "zz"})
        assert r.status_code == 200 and r.json()["deleted"] >= 1

    def test_public_cache_stats(self):
        r = requests.get(f"{PUBLIC}/api/cache/stats", timeout=30)
        assert r.status_code == 200 and r.json()["total"] > 0
