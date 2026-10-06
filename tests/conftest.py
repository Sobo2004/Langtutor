"""Shared test setup.

Tests run against a temporary SQLite database (never the real app.db) and never
call OpenAI: anything that would reach the AI is replaced with a fake.
"""
import importlib
import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_tmp_dir = tempfile.mkdtemp(prefix="langtutor-tests-")
os.environ["LANGTUTOR_DB"] = str(Path(_tmp_dir) / "test.db")
os.environ["ADMIN_PASSWORD"] = "test-admin-password"
os.environ["LLM_PROVIDER"] = "openai"

main = importlib.import_module("main")


@pytest.fixture
def app_module():
    return main


@pytest.fixture(autouse=True)
def reset_rate_limits():
    main._rate_hits.clear()
    yield
    main._rate_hits.clear()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(main.app)


@pytest.fixture
def user(client):
    """A fresh signed-up and logged-in user. Returns (client, username, user_id)."""
    username = "test_" + uuid.uuid4().hex[:8]
    assert client.post("/auth/signup", json={"username": username, "password": "secret123"}).status_code == 200
    assert client.post("/auth/login", json={"username": username, "password": "secret123"}).status_code == 200
    con = main.db()
    user_id = con.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    con.close()
    main._rate_hits.clear()
    return client, username, user_id
