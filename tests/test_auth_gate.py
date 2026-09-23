"""The gate tests.

The point of a locked-by-default gate is that *forgetting* is impossible. These
two tests are what make that true: the first calls every route the app exposes
with no token and demands a 401, and the second freezes the list of public paths
so opening a new one has to be a deliberate edit in two places.
"""
from __future__ import annotations

from fastapi.routing import APIRoute

import app as application


def test_every_route_is_closed_without_a_token(client):
    """Call every non-public route unauthenticated. All must answer 401."""
    leaked = []
    for route in application.app.routes:
        if not isinstance(route, APIRoute) or route.path in application.PUBLIC_PATHS:
            continue
        path = route.path.replace("{item_id}", "1")
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            response = client.request(method, path, json={})
            if response.status_code != 401:
                leaked.append(f"{method} {path} -> {response.status_code}")
    assert not leaked, "these routes answered without authentication: " + ", ".join(leaked)


def test_public_paths_are_the_expected_three():
    """A second, independent copy of the list.

    If someone adds a path to PUBLIC_PATHS, this test fails until they add it
    here too — which puts the decision in the diff instead of leaving it silent.
    """
    assert application.PUBLIC_PATHS == {"/", "/health", "/api/auth/login"}


def test_token_signature_cannot_be_forged():
    token = application.issue_token("admin")
    assert application.read_token(token) == "admin"
    assert application.read_token(token[:-1] + "0") is None
    assert application.read_token("admin:99999999999:deadbeef") is None


def test_expired_token_is_rejected(monkeypatch):
    monkeypatch.setattr(application, "TOKEN_TTL_SECONDS", -1)
    assert application.read_token(application.issue_token("admin")) is None


def test_login_rejects_a_wrong_password(client):
    response = client.post("/api/auth/login", json={"username": "admin", "password": "nope"})
    assert response.status_code == 401
