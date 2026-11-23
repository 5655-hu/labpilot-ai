"""Pytest fixtures: isolated temp SQLite DB, temp uploads dir, seeded golden data, rate-limit reset."""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture(scope="session")
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp("labpilot")
    db_path = root / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    # Uploaded files are written next to the code by default. Redirect them
    # into the session temp dir so a test run leaves nothing behind in
    # backend/data/uploads and never collides with a previous run's {id}.csv.
    from app import store

    store.UPLOADS_DIR = root / "uploads"

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def gemini_helper(tmp_path, monkeypatch):
    """Stand-in for the private custom.gemini connector helper.

    The real helper lives outside this repository, so on a clean checkout
    `GeminiProvider.available()` is False and the AI path silently degrades
    to the rule-based text. Tests that exercise the AI path create their own
    placeholder and point the adapter at it; the subprocess itself is always
    mocked, so the file is never executed.
    """
    import app.ai_adapter as ai_adapter

    helper = tmp_path / "gemini.py"
    helper.write_text("# test stand-in for custom.gemini; never executed\n", encoding="utf-8")
    monkeypatch.setattr(ai_adapter, "GEMINI_HELPER", helper)
    return helper

@pytest.fixture(autouse=True)
def reset_rate_limit():
    """Every test starts and ends with an empty rate-limit window.

    The session-scoped TestClient always reports the same client IP
    ("testclient"), so without this the suite's 39 POSTs would pile into a
    single 30/min bucket and the later files would start getting 429.
    reset() also re-reads RATE_LIMIT_PER_MIN / TRUST_PROXY from the env.
    """
    from app import ratelimit

    ratelimit.reset()
    yield
    ratelimit.reset()
