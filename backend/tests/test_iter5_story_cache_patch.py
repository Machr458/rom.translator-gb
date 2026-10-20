# Iteration 5: story extraction gen1/2/3, export header/prefill, import patch count, /rom/patch decode, cache entry, LLM translate (small)
import os
import re
import time
import pytest
import requests

PUB = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
LOCAL = "http://localhost:8001"  # only for 16MB GBA upload
import sys
sys.path.insert(0, "/app/backend")
from text_extract import CODECS  # noqa: E402

ROMS = {
    "gen1": ("/tmp/yellow.gbc", "Pokemon Blue.gb", "pokemon_gen1", PUB),
    "gen2": ("/tmp/gold.gbc", "Pokemon Gold.gbc", "pokemon_gen2", PUB),
    "gen3": ("/tmp/emerald.gba", "Pokemon Emerald.gba", "pokemon_gen3", LOCAL),
}
NAMES = {"BULBASAUR", "POTION", "PIKACHU", "TACKLE", "CHIKORITA", "TORCHIC", "PALLET TOWN", "POKé BALL", "ANTIDOTE"}
_c = {}


def ex(key):
    if key in _c:
        return _c[key]
    path, name, enc, base = ROMS[key]
    with open(path, "rb") as f:
        r = requests.post(f"{base}/api/rom/extract", files={"file": (name, f)}, data={"encoding": "auto"}, timeout=300)
    assert r.status_code == 200, r.text[:300]
    _c[key] = r.json()
    return _c[key]


# Extraction + name filtering
@pytest.mark.parametrize("key", ["gen1", "gen2", "gen3"])
def test_extract(key):
    d = ex(key)
    assert d["encoding"] == ROMS[key][2]
    assert d["excluded_names"] > 0
    assert d["found_total"] == len(d["strings"]) > 100
    texts = {s["text"].strip() for s in d["strings"]}
    assert not (texts & NAMES), texts & NAMES
    allcaps = [t for t in texts if not re.search(r"[a-z]", re.sub(r"\{[^}]*\}|POKé", "", t))]
    print(key, len(texts), "names", d["excluded_names"], "allcaps-left", len(allcaps), sorted(allcaps)[:15])


# Export header + prefill
def test_export_header_prefill():
    d = ex("gen2")
    strs = d["strings"][:10]
    tr = [{"id": s["id"], "original": s["text"], "translated": ("PRELOZENO" if i == 0 else "")} for i, s in enumerate(strs)]
    r = requests.post(f"{PUB}/api/rom/export", json={"session_id": d["session_id"], "translations": tr})
    assert r.status_code == 200
    lines = r.text.splitlines()
    head = [l for l in lines if l.startswith("#")]
    for tok in ("{n}", "{l}", "{p}", "{PLAYER}"):
        assert any(tok in h for h in head), tok
    body = [l for l in lines if l and not l.startswith("#")]
    assert len(body) == 10
    assert body[0].split("\t")[1] == "PRELOZENO"
    assert all(l.split("\t")[0] == l.split("\t")[1] for l in body[1:])


# Import patch counts
@pytest.mark.parametrize("key", ["gen1", "gen2"])
def test_import(key):
    d = ex(key)
    strs = d["strings"][50:62]
    tr = [{"id": s["id"], "original": s["text"], "translated": ""} for s in strs]
    txt = requests.post(f"{PUB}/api/rom/export", json={"session_id": d["session_id"], "translations": tr}).text
    body = [l for l in txt.splitlines() if l and not l.startswith("#")]
    out = [f"{l.split(chr(9))[0]}\tAhoj {i}" if i < 3 else l for i, l in enumerate(body)]
    r = requests.post(f"{PUB}/api/rom/import", data={"session_id": d["session_id"]},
                      files={"file": ("t.txt", "\n".join(out).encode())}, timeout=120)
    assert r.status_code == 200, r.text[:200]
    assert r.headers["X-Patched-Count"] == "3", dict(r.headers)
    assert len(r.content) == os.path.getsize(ROMS[key][0])


# /rom/patch decodes at original offset
@pytest.mark.parametrize("key", ["gen1", "gen2"])
def test_patch_decode(key):
    d = ex(key)
    s = next(x for x in d["strings"] if "{n}" in x["text"] and x["length"] > 30)
    new = "Ahoj, jak se{n}mas?"
    r = requests.post(f"{PUB}/api/rom/patch", json={"session_id": d["session_id"],
                      "translations": [{"id": s["id"], "original": s["text"], "translated": new}]}, timeout=120)
    assert r.status_code == 200 and r.headers["X-Patched-Count"] == "1"
    dec = CODECS[ROMS[key][2]].decode(r.content, s["offset"])
    assert dec and dec[1] == new, dec
    assert len(r.content) == os.path.getsize(ROMS[key][0])


# Cache entry
def test_cache_entry():
    total0 = requests.get(f"{PUB}/api/cache/stats").json()["total"]
    r = requests.post(f"{PUB}/api/cache/entry", json={"source": "TEST_src", "translated": "TEST_dst", "target_language": "zz"})
    assert r.status_code == 200 and r.json() == {"saved": True}
    r = requests.post(f"{PUB}/api/cache/entry", json={"source": "TEST_src", "translated": "", "target_language": "zz"})
    assert r.status_code == 400
    c = requests.post(f"{PUB}/api/cache/clear", params={"target_language": "zz"}).json()
    assert c["deleted"] == 1
    assert requests.get(f"{PUB}/api/cache/stats").json()["total"] == total0


# LLM translate (small) gen2
def test_translate_llm():
    d = ex("gen2")
    cand = [s for s in d["strings"][3500:] if re.search(r"\{(PLAYER|n|p)\}", s["text"])][:30]
    payload = {"session_id": d["session_id"], "strings": cand, "target_language": "cs",
               "provider": "emergent", "model": "gemini-3-flash-preview"}
    r = requests.post(f"{PUB}/api/rom/translate", json=payload)
    assert r.status_code == 200, r.text
    jid = r.json()["job_id"]
    for _ in range(100):
        st = requests.get(f"{PUB}/api/rom/translate/status/{jid}").json()
        if st["status"] != "running":
            break
        time.sleep(3)
    print("STATUS", st["status"], st["translated_count"], st["cached_count"], st["failed_count"], st["errors"], st.get("error"))
    assert st["status"] == "done", st.get("error")
    tr = st["translations"]
    changed = [t for t in tr if t["translated"] != t["original"]]
    for t in tr[:10]:
        print("O:", t["original"]); print("T:", t["translated"])
    assert len(changed) >= len(tr) * 0.7
    for t in changed:
        for tok in ("{PLAYER}", "{RIVAL}"):
            assert t["translated"].count(tok) == t["original"].count(tok)
    keep = sum(1 for t in changed if "POKéMON" in t["translated"])
    print("POKéMON kept in", keep, "/", len(changed))
