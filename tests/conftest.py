"""Test fixtures: every test runs against a throwaway database file."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def application(tmp_path, monkeypatch):
    """A freshly imported app bound to a temporary SQLite file.

    Re-importing rather than pointing the existing module at a new path keeps
    module-level state (the secret, the TTL) honest between tests.
    """
    monkeypatch.setenv("RTL_ADMIN_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("RTL_ADMIN_SECRET", "test-secret")
    import app as module

    module = importlib.reload(module)
    module.init_db()
    return module


@pytest.fixture()
def client(application):
    with TestClient(application.app) as test_client:
        yield test_client


@pytest.fixture()
def auth(client):
    """Headers for a logged-in admin."""
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["token"]}
