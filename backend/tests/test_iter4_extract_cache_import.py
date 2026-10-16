# Iteration 4: Pokemon Gen1/2/3 extraction, cache/entry, export->import patch flow
import os
import re
import pytest
import requests

BASE = "http://localhost:8001/api"  # localhost used for 16MB GBA uploads (ingress limits)
PUB = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

ROMS = [
    ("/tmp/yellow.gbc", "Pokemon Blue.gb", "pokemon_gen1"),
    ("/tmp/gold.gbc", "Pokemon Gold.gbc", "pokemon_gen2"),
    ("/tmp/emerald.gba", "Pokemon Emerald.gba", "pokemon_gen3"),
]
SPECIES = {"BULBASAUR", "IVYSAUR", "CHARMANDER", "PIKACHU", "SQUIRTLE", "CHIKORITA", "TORCHIC", "TREECKO"}
_cache = {}


def extract(path, name):
    if path in _cache:
        return _cache[path]
    with open(path, "rb") as f:
        r = requests.post(f"{BASE}/rom/extract", files={"file": (name, f, "application/octet-stream")},
                          data={"encoding": "auto"}, timeout=300)
    assert r.status_code == 200, r.text[:300]
    _cache[path] = r.json()
    return _cache[path]


# Extraction per generation
@pytest.mark.parametrize("path,name,enc", ROMS)
def test_extract_encoding_and_quality(path, name, enc):
    d = extract(path, name)
    assert d["encoding"] == enc
    assert d["excluded_names"] > 0
    assert len(d["strings"]) > 100
    texts = [s["text"] for s in d["strings"]]
    bare_species = [t for t in texts if t.strip() in SPECIES]
    assert not bare_species, bare_species[:5]
    # readable dialog: majority contain lowercase + spaces
    readable = sum(1 for t in texts if re.search(r"[a-z]{3,} [a-z]{2,}", t))
    print(enc, len(texts), "readable", readable, "names", d["excluded_names"])
    print("SAMPLE", texts[:3], texts[len(texts)//2:len(texts)//2+3])
    assert readable / len(texts) > 0.6
    # some messages contain control tokens
    assert any(re.search(r"\{(n|l|p|PLAYER|next|page)\}", t) for t in texts)


# Cache entry
class TestCacheEntry:
    def test_save_and_count(self):
        before = requests.get(f"{BASE}/cache/stats").json()
        r = requests.post(f"{BASE}/cache/entry", json={"source": "TEST_hello", "translated": "TEST_ahoj", "target_language": "zz"})
        assert r.status_code == 200 and r.json()["saved"] is True
        st = requests.get(f"{BASE}/cache/stats").json()
        zz = [x for x in st["per_language"] if x["lang"] == "zz"]
        assert zz and zz[0]["count"] >= 1
        assert st["total"] >= before["total"]

    def test_upsert_same_key(self):
        requests.post(f"{BASE}/cache/entry", json={"source": "TEST_hello", "translated": "TEST_ahoj2", "target_language": "zz"})
        st = requests.get(f"{BASE}/cache/stats").json()
        zz = [x for x in st["per_language"] if x["lang"] == "zz"][0]
        assert zz["count"] == 1

    def test_empty_translated_400(self):
        r = requests.post(f"{BASE}/cache/entry", json={"source": "TEST_x", "translated": "   ", "target_language": "zz"})
        assert r.status_code == 400

    def test_public_url_entry(self):
        r = requests.post(f"{PUB}/api/cache/entry", json={"source": "TEST_pub", "translated": "TEST_p", "target_language": "zz"})
        assert r.status_code == 200

    def test_zz_cleanup(self):
        total_before = requests.get(f"{BASE}/cache/stats").json()["total"]
        r = requests.post(f"{BASE}/cache/clear", params={"target_language": "zz"})
        assert r.status_code == 200 and r.json()["deleted"] >= 2
        st = requests.get(f"{BASE}/cache/stats").json()
        assert not [x for x in st["per_language"] if x["lang"] == "zz"]
        assert st["total"] == total_before - r.json()["deleted"]


# Export -> modify -> import
@pytest.mark.parametrize("path,name,enc", ROMS[:2] + [("/tmp/emerald.gba", "Pokemon Emerald.gba", "pokemon_gen3")])
def test_export_import_patch(path, name, enc):
    d = extract(path, name)
    sid = d["session_id"]
    strs = d["strings"][:20]
    tr = [{"id": s["id"], "original": s["text"], "translated": ""} for s in strs]
    r = requests.post(f"{BASE}/rom/export", json={"session_id": sid, "translations": tr, "target_language": "cs"})
    assert r.status_code == 200, r.text[:300]
    txt = r.text
    assert "{n}" in txt and "{PLAYER}" in txt and "Control tokens" in txt
    body = [l for l in txt.splitlines() if l and not l.startswith("#")]
    assert len(body) == 20
    # untranslated pre-filled with original
    assert all(l.split("\t")[0] == l.split("\t")[1] for l in body)
    # change 5 lines
    out = []
    for i, l in enumerate(body):
        o, t = l.split("\t")
        out.append(f"{o}\tTEST {i}" if i < 5 else l)
    content = "\n".join(out) + "\n"
    r = requests.post(f"{BASE}/rom/import", data={"session_id": sid},
                      files={"file": ("t.txt", content.encode("utf-8"), "text/plain")}, timeout=300)
    assert r.status_code == 200, r.text[:300]
    assert r.headers["X-Patched-Count"] == "5", r.headers
    assert len(r.content) == os.path.getsize(path)
    assert r.content != open(path, "rb").read()
