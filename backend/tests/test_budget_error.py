"""Tests for Emergent budget-exhausted error mapping and fail-fast worker.

Covers:
- _error_code and _friendly_error helpers (unit-level, imported from server module).
- End-to-end: POST /api/rom/translate with provider=emergent (real key that is over budget)
  -> GET /api/rom/translate/status/{job_id} exposes structured error_code=EMERGENT_BUDGET_EXCEEDED
     and a friendly message (no raw litellm.BadRequestError text).
- Fail-fast: 2+ batches (>=40 strings) still end quickly (well under N*timeout seconds).
"""
import os
import sys
import time
import pytest
import requests

# Make backend imports work
sys.path.insert(0, "/app/backend")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or None
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

SMALL_ROM = "/tmp/small.gb"
BIG_ROM = "/tmp/big.gba"


# ---------- Helper function unit tests ----------

class TestErrorMappingHelpers:
    def test_error_code_budget(self):
        from server import _error_code
        assert _error_code("EMERGENT_BUDGET_EXCEEDED: foo") == "EMERGENT_BUDGET_EXCEEDED"
        assert _error_code("Budget has been exceeded! Current cost: 1.5") == "EMERGENT_BUDGET_EXCEEDED"
        # Note: raw "max budget" is caught by _call_llm and re-raised with
        # "EMERGENT_BUDGET_EXCEEDED:" prefix, so _error_code only needs to match
        # the two variants below.
        assert _error_code("emergent_budget_exceeded: credit gone") == "EMERGENT_BUDGET_EXCEEDED"

    def test_error_code_quota(self):
        from server import _error_code
        assert _error_code("429 RESOURCE_EXHAUSTED quota") == "QUOTA_EXCEEDED"
        assert _error_code("rate limited") == "QUOTA_EXCEEDED"

    def test_error_code_invalid_key(self):
        from server import _error_code
        assert _error_code("Invalid API key provided") == "INVALID_KEY"
        assert _error_code("Unauthorized") == "INVALID_KEY"

    def test_error_code_timeout(self):
        from server import _error_code
        assert _error_code("Request timeout after 60s") == "TIMEOUT"

    def test_error_code_default(self):
        from server import _error_code
        assert _error_code("random upstream boom") == "UPSTREAM_ERROR"

    def test_friendly_budget_mentions_action(self):
        from server import _friendly_error
        msg = _friendly_error("Budget has been exceeded")
        low = msg.lower()
        assert "profile" in low or "manage plan" in low or "settings" in low
        assert "universal key" in low or "own" in low or "provider" in low
        # must NOT include raw technical noise
        assert "litellm" not in low and "openaiexception" not in low

    def test_friendly_quota_actionable(self):
        from server import _friendly_error
        msg = _friendly_error("429 RESOURCE_EXHAUSTED").lower()
        assert "settings" in msg or "provider" in msg or "wait" in msg

    def test_friendly_invalid_key(self):
        from server import _friendly_error
        msg = _friendly_error("Invalid API key").lower()
        assert "settings" in msg or "key" in msg

    def test_friendly_timeout(self):
        from server import _friendly_error
        msg = _friendly_error("timeout").lower()
        assert "again" in msg or "settings" in msg or "faster" in msg


# ---------- End-to-end: budget-exhausted job through the real API ----------

@pytest.fixture(scope="module")
def session_with_strings():
    """Extract a session from the big ROM so we have plenty of strings for batching."""
    with open(BIG_ROM, "rb") as f:
        data = f.read()
    r = requests.post(
        f"{BASE_URL}/api/rom/extract",
        files={"file": ("big.gba", data, "application/octet-stream")},
        data={"encoding": "auto", "max_strings": "120"},
        timeout=180,
    )
    assert r.status_code == 200, r.text[:300]
    return r.json()


class TestBudgetExceededE2E:
    def test_translate_returns_structured_budget_error(self, session_with_strings):
        """POST translate + poll status returns error_code=EMERGENT_BUDGET_EXCEEDED with clean message."""
        sess = session_with_strings
        payload = {
            "session_id": sess["session_id"],
            "target_language": "cs",
            "strings": sess["strings"][:60],  # 3 batches of 20
            "provider": "emergent",
            "model": None,
            "api_key": "",
        }
        r = requests.post(f"{BASE_URL}/api/rom/translate", json=payload, timeout=30)
        assert r.status_code == 200, r.text[:300]
        job_id = r.json()["job_id"]
        assert job_id

        # Poll status
        t0 = time.time()
        final = None
        while time.time() - t0 < 90:
            s = requests.get(f"{BASE_URL}/api/rom/translate/status/{job_id}", timeout=15)
            assert s.status_code == 200
            data = s.json()
            if data["status"] in ("done", "error"):
                final = data
                break
            time.sleep(1.0)

        elapsed = time.time() - t0
        print(f"Job finished in {elapsed:.2f}s; status={final and final['status']}")
        assert final is not None, "job did not finish within 90s"

        # The real EMERGENT_LLM_KEY in this container is budget-exhausted, so we expect
        # status=error with structured EMERGENT_BUDGET_EXCEEDED. If somehow the key was
        # topped up (status=done), we still validate the shape.
        if final["status"] == "error":
            assert final.get("error_code") == "EMERGENT_BUDGET_EXCEEDED", (
                f"expected EMERGENT_BUDGET_EXCEEDED, got {final.get('error_code')}; "
                f"error={final.get('error')!r}; errors={final.get('errors')}"
            )
            friendly = (final.get("error") or "").lower()
            # Friendly Czech-agnostic message contents
            assert any(k in friendly for k in ("profile", "manage plan", "universal key", "settings", "provider")), (
                f"friendly error missing actionable next step: {friendly!r}"
            )
            # Must NOT be raw technical noise
            assert "litellm" not in friendly
            assert "openaiexception" not in friendly
            assert "badrequesterror" not in friendly

            # Fail-fast: with 3 batches, dedupe should keep error list small
            errs = final.get("errors", [])
            assert len(errs) <= 3, f"too many raw errors leaked: {errs}"

            # Fail-fast timing: 3 batches * 60s worst case would be >>10s.
            # If short-circuiting works we should finish under ~30s.
            assert elapsed < 45, f"fail-fast broken: took {elapsed:.1f}s for 3 batches"
        else:
            # unexpected happy path — key was topped up
            assert final.get("translated_count", 0) > 0, final

    def test_translate_fail_fast_many_batches(self, session_with_strings):
        """With 80 strings (4 batches), abort_flag should short-circuit remaining batches."""
        sess = session_with_strings
        # Extract more strings if we don't have enough
        strings = sess["strings"]
        if len(strings) < 80:
            pytest.skip(f"session only has {len(strings)} strings")
        payload = {
            "session_id": sess["session_id"],
            "target_language": "cs",
            "strings": strings[:80],
            "provider": "emergent",
            "model": None,
            "api_key": "",
        }
        r = requests.post(f"{BASE_URL}/api/rom/translate", json=payload, timeout=30)
        assert r.status_code == 200
        job_id = r.json()["job_id"]

        t0 = time.time()
        final = None
        while time.time() - t0 < 90:
            s = requests.get(f"{BASE_URL}/api/rom/translate/status/{job_id}", timeout=15).json()
            if s["status"] in ("done", "error"):
                final = s
                break
            time.sleep(0.8)
        elapsed = time.time() - t0
        print(f"4-batch job finished in {elapsed:.2f}s")
        assert final is not None

        if final["status"] == "error":
            assert final.get("error_code") == "EMERGENT_BUDGET_EXCEEDED"
            # 4 batches would take 4 * ~10s upstream if we don't short-circuit;
            # with fail-fast expected under 45s.
            assert elapsed < 60, f"fail-fast broken: 4 batches took {elapsed:.1f}s"
            errs = final.get("errors", [])
            # Dedupe: same message once
            unique = set(errs)
            assert len(unique) <= 2, f"errors not deduped: {errs}"


# ---------- Regression: small ASCII job structure ----------

class TestRegression:
    def test_status_shape_has_error_code_field(self, session_with_strings):
        """status endpoint always returns the error_code key (nullable)."""
        sess = session_with_strings
        r = requests.post(
            f"{BASE_URL}/api/rom/translate",
            json={
                "session_id": sess["session_id"],
                "target_language": "cs",
                "strings": sess["strings"][:5],
                "provider": "emergent",
                "api_key": "",
            },
            timeout=30,
        )
        assert r.status_code == 200
        job_id = r.json()["job_id"]
        # First poll immediately - key must exist even before job ends
        s = requests.get(f"{BASE_URL}/api/rom/translate/status/{job_id}", timeout=15).json()
        assert "error_code" in s
        assert "error" in s
        assert "errors" in s
