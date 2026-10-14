import secrets
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import AdminAuditLog

router = APIRouter(prefix="/api/v1/admin/auth", tags=["admin-auth"])
PASSWORD_ADMIN_SUBJECT = "password-admin"


@dataclass(frozen=True)
class AdminIdentity:
    subject: str

    def public(self) -> dict:
        return {"subject": self.subject}


class LoginIn(BaseModel):
    password: str


def _identity(request: Request) -> AdminIdentity | None:
    stored = request.session.get("admin")
    if (
        not isinstance(stored, dict)
        or stored.get("auth_method") != "password"
        or stored.get("sub") != PASSWORD_ADMIN_SUBJECT
    ):
        return None
    return AdminIdentity(PASSWORD_ADMIN_SUBJECT)


def require_admin(request: Request) -> AdminIdentity:
    identity = _identity(request)
    if identity is None:
        raise HTTPException(401, "Administrator authentication required")
    return identity


def require_csrf(
    request: Request,
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    admin: AdminIdentity = Depends(require_admin),
) -> AdminIdentity:
    expected = request.session.get("csrf")
    if not csrf_token or not expected or not secrets.compare_digest(csrf_token, expected):
        raise HTTPException(403, "Invalid CSRF token")
    return admin


def require_confirmation(value: str | None, expected: str) -> None:
    if settings.app_env == "production" and value != expected:
        raise HTTPException(409, f"Production confirmation must exactly match: {expected}")


@router.get("/status")
def auth_status(request: Request):
    identity = _identity(request)
    return {
        "authenticated": identity is not None,
        "admin": identity.public() if identity else None,
        "csrf_token": request.session.get("csrf") if identity else None,
    }


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    request.session.clear()
    if not settings.admin_password or not secrets.compare_digest(
        body.password.encode(), settings.admin_password.encode()
    ):
        raise HTTPException(401, "Invalid administrator credentials")
    request.session["admin"] = {
        "sub": PASSWORD_ADMIN_SUBJECT,
        "auth_method": "password",
    }
    request.session["csrf"] = secrets.token_urlsafe(32)
    db.add(AdminAuditLog(admin_subject=PASSWORD_ADMIN_SUBJECT, action="admin.login", details={}))
    db.commit()
    return {"ok": True}


@router.post("/logout")
def logout(request: Request, admin: AdminIdentity = Depends(require_csrf), db: Session = Depends(get_db)):
    db.add(AdminAuditLog(admin_subject=admin.subject, action="admin.logout", details={}))
    db.commit()
    request.session.clear()
    return {"ok": True}
