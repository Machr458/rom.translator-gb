"""Backend tests for ROM extract - focus on unlimited (max_strings=0) fix."""
import os
import time
import pytest
import requests

BASE_URL = os.environ['REACT_APP_BACKEND_URL'].rstrip('/') if os.environ.get('REACT_APP_BACKEND_URL') else None
if not BASE_URL:
    # fallback from frontend .env
    with open('/app/frontend/.env') as f:
        for line in f:
            if line.startswith('REACT_APP_BACKEND_URL='):
                BASE_URL = line.split('=', 1)[1].strip().rstrip('/')
                break

BIG_ROM = '/tmp/big.gba'
SMALL_ROM = '/tmp/small.gb'


@pytest.fixture(scope="module")
def big_rom_bytes():
    with open(BIG_ROM, 'rb') as f:
        return f.read()


@pytest.fixture(scope="module")
def small_rom_bytes():
    with open(SMALL_ROM, 'rb') as f:
        return f.read()


# ---------- Extract endpoint tests ----------

class TestExtractUnlimited:
    def test_extract_unlimited_pokemon_rom(self, big_rom_bytes):
        """max_strings=0 -> unlimited; found_total == len(strings) for Pokemon Gen3 ROM."""
        t0 = time.time()
        r = requests.post(
            f"{BASE_URL}/api/rom/extract",
            files={"file": ("big.gba", big_rom_bytes, "application/octet-stream")},
            data={"encoding": "auto", "max_strings": "0"},
            timeout=180,
        )
        elapsed = time.time() - t0
        print(f"Unlimited extract took {elapsed:.2f}s")

        assert r.status_code == 200, f"got {r.status_code}: {r.text[:300]}"
        assert r.headers.get("content-type", "").startswith("application/json")
        j = r.json()
        for k in ("session_id", "filename", "rom_size", "rom_type", "encoding", "found_total", "strings"):
            assert k in j, f"missing key {k}"
        assert j["rom_size"] == len(big_rom_bytes)
        assert j["encoding"] == "pokemon_gen3", f"expected pokemon_gen3, got {j['encoding']}"
        assert j["found_total"] == len(j["strings"]), (
            f"unlimited: found_total ({j['found_total']}) must equal len(strings) ({len(j['strings'])})"
        )
        assert j["found_total"] > 200, f"expected >200 strings, got {j['found_total']}"

    def test_extract_capped_250(self, big_rom_bytes):
        """max_strings=250 -> exactly 250 strings; found_total >= 250."""
        r = requests.post(
            f"{BASE_URL}/api/rom/extract",
            files={"file": ("big.gba", big_rom_bytes, "application/octet-stream")},
            data={"encoding": "auto", "max_strings": "250"},
            timeout=180,
        )
        assert r.status_code == 200, r.text[:300]
        j = r.json()
        assert len(j["strings"]) == 250, f"expected 250, got {len(j['strings'])}"
        assert j["found_total"] >= 250, f"found_total {j['found_total']} < 250"

    def test_extract_ascii_500(self, small_rom_bytes):
        """Regression: small ASCII gb with max_strings=500 still works."""
        r = requests.post(
            f"{BASE_URL}/api/rom/extract",
            files={"file": ("small.gb", small_rom_bytes, "application/octet-stream")},
            data={"encoding": "ascii", "max_strings": "500"},
            timeout=60,
        )
        assert r.status_code == 200, r.text[:300]
        j = r.json()
        assert j["encoding"] == "ascii"
        assert len(j["strings"]) >= 5, f"expected at least 5, got {len(j['strings'])}"
        # Ensure known text present
        texts = [s["text"] for s in j["strings"]]
        assert any("HELLO WORLD" in t for t in texts), f"HELLO WORLD not in {texts[:5]}"
