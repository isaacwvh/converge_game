import time

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.admin_auth import AdminIdentity, require_admin, require_confirmation, require_csrf, require_sensitive_admin
from app.config import settings


def request_with_session(session: dict) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "session": session})


def test_admin_api_requires_authentication(client):
    response = client.get("/api/v1/admin/state")
    assert response.status_code == 401
    status = client.get("/api/v1/admin/auth/status")
    assert status.status_code == 200
    assert status.json()["authenticated"] is False


def test_explicit_local_login_creates_a_normal_admin_session(client, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "local")
    monkeypatch.setattr(settings, "admin_local_login_enabled", True)
    login = client.post("/api/v1/admin/auth/local-login")
    assert login.status_code == 200

    status = client.get("/api/v1/admin/auth/status").json()
    assert status["authenticated"] is True
    assert status["admin"]["subject"] == "local-development-admin"
    assert status["csrf_token"]
    assert client.get("/api/v1/admin/state").status_code == 200

    audit = client.get("/api/v1/admin/audit").json()
    assert audit[0]["action"] == "admin.local-login"
    logout = client.post(
        "/api/v1/admin/auth/logout",
        headers={"X-CSRF-Token": status["csrf_token"]},
    )
    assert logout.status_code == 200
    assert client.get("/api/v1/admin/auth/status").json()["authenticated"] is False


def test_local_login_is_unavailable_unless_explicitly_enabled(client, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "local")
    monkeypatch.setattr(settings, "admin_local_login_enabled", False)
    assert client.post("/api/v1/admin/auth/local-login").status_code == 403

    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "admin_local_login_enabled", True)
    assert client.post("/api/v1/admin/auth/local-login").status_code == 403


def test_allowlist_and_csrf_are_both_enforced(monkeypatch):
    monkeypatch.setattr(settings, "admin_oidc_allowed_subjects", "allowed-subject")
    identity = require_admin(request_with_session({"admin": {"sub": "allowed-subject", "email": "admin@example.test"}}))
    assert identity.subject == "allowed-subject"
    with pytest.raises(HTTPException) as denied:
        require_admin(request_with_session({"admin": {"sub": "someone-else"}}))
    assert denied.value.status_code == 401

    request = request_with_session({"csrf": "expected"})
    assert require_csrf(request, "expected", identity) == identity
    with pytest.raises(HTTPException) as csrf_denied:
        require_csrf(request, "wrong", identity)
    assert csrf_denied.value.status_code == 403


def test_production_safety_and_confirmation_fail_closed(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "seed_demo", True)
    monkeypatch.setattr(settings, "admin_local_login_enabled", True)
    with pytest.raises(RuntimeError, match="SEED_DEMO") as safety:
        settings.validate_runtime()
    assert "ADMIN_LOCAL_LOGIN_ENABLED" in str(safety.value)
    with pytest.raises(HTTPException) as confirmation:
        require_confirmation("wrong", "PRODUCTION SCHEDULE 2026-10")
    assert confirmation.value.status_code == 409


def test_production_sensitive_actions_require_recent_oidc(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    identity = AdminIdentity("allowed-subject", None, None)
    with pytest.raises(HTTPException) as stale:
        require_sensitive_admin(request_with_session({"authenticated_at": 0}), identity)
    assert stale.value.status_code == 428
    recent = request_with_session({"authenticated_at": int(time.time())})
    assert require_sensitive_admin(recent, identity) == identity
