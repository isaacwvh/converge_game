import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.admin_auth import (
    PASSWORD_ADMIN_SUBJECT,
    AdminIdentity,
    require_admin,
    require_confirmation,
    require_csrf,
)
from app.config import settings


def request_with_session(session: dict) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "session": session})


def test_admin_api_requires_authentication(client):
    response = client.get("/api/v1/admin/state")
    assert response.status_code == 401
    assert client.get("/api/v1/admin/auth/status").json() == {
        "authenticated": False,
        "admin": None,
        "csrf_token": None,
    }


def test_password_login_creates_and_clears_admin_session(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "correct horse battery staple")

    denied = client.post("/api/v1/admin/auth/login", json={"password": "wrong"})
    assert denied.status_code == 401
    assert denied.json()["detail"] == "Invalid administrator credentials"
    assert client.get("/api/v1/admin/auth/status").json()["authenticated"] is False

    login = client.post(
        "/api/v1/admin/auth/login",
        json={"password": "correct horse battery staple"},
    )
    assert login.status_code == 200

    status = client.get("/api/v1/admin/auth/status").json()
    assert status["authenticated"] is True
    assert status["admin"] == {"subject": PASSWORD_ADMIN_SUBJECT}
    assert status["csrf_token"]
    assert client.get("/api/v1/admin/state").status_code == 200

    audit = client.get("/api/v1/admin/audit").json()
    assert audit[0]["action"] == "admin.login"
    assert audit[0]["admin_subject"] == PASSWORD_ADMIN_SUBJECT
    assert audit[0]["details"] == {}

    logout = client.post(
        "/api/v1/admin/auth/logout",
        headers={"X-CSRF-Token": status["csrf_token"]},
    )
    assert logout.status_code == 200
    assert client.get("/api/v1/admin/auth/status").json()["authenticated"] is False


def test_only_password_sessions_are_accepted():
    valid = require_admin(
        request_with_session(
            {"admin": {"sub": PASSWORD_ADMIN_SUBJECT, "auth_method": "password"}}
        )
    )
    assert valid.subject == PASSWORD_ADMIN_SUBJECT

    for session in (
        {"admin": {"sub": "legacy-provider-user", "auth_method": "provider"}},
        {"admin": {"sub": "legacy-development-user", "auth_method": "development"}},
        {"admin": {"sub": "someone-else", "auth_method": "password"}},
    ):
        with pytest.raises(HTTPException) as denied:
            require_admin(request_with_session(session))
        assert denied.value.status_code == 401


def test_csrf_is_enforced():
    identity = AdminIdentity(PASSWORD_ADMIN_SUBJECT)
    request = request_with_session({"csrf": "expected"})
    assert require_csrf(request, "expected", identity) == identity
    with pytest.raises(HTTPException) as denied:
        require_csrf(request, "wrong", identity)
    assert denied.value.status_code == 403


def test_production_safety_and_confirmation_fail_closed(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "seed_demo", True)
    monkeypatch.setattr(settings, "admin_password", "replace-with-a-long-random-password")
    with pytest.raises(RuntimeError, match="SEED_DEMO") as safety:
        settings.validate_runtime()
    assert "ADMIN_PASSWORD" in str(safety.value)

    with pytest.raises(HTTPException) as confirmation:
        require_confirmation("wrong", "PRODUCTION SCHEDULE 2026-10")
    assert confirmation.value.status_code == 409
