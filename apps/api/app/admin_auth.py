import secrets
import time
from dataclasses import dataclass
from urllib.parse import urljoin

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import AdminAuditLog

router = APIRouter(prefix="/api/v1/admin/auth", tags=["admin-auth"])
oauth = OAuth()
LOCAL_ADMIN_SUBJECT = "local-development-admin"



@dataclass(frozen=True)
class AdminIdentity:
    subject: str
    email: str | None
    name: str | None

    def public(self) -> dict:
        return {"subject": self.subject, "email": self.email, "name": self.name}


def _client():
    if not settings.oidc_configured:
        raise HTTPException(503, "Administrator OIDC is not configured")
    client = oauth.create_client("admin_oidc")
    if client is None:
        oauth.register(
            name="admin_oidc",
            server_metadata_url=settings.admin_oidc_discovery_url,
            client_id=settings.admin_oidc_client_id,
            client_secret=settings.admin_oidc_client_secret,
            client_kwargs={"scope": "openid email profile"},
        )
        client = oauth.create_client("admin_oidc")
    return client


def _identity(request: Request) -> AdminIdentity | None:
    stored = request.session.get("admin")
    if not isinstance(stored, dict):
        return None
    subject = stored.get("sub")
    if stored.get("auth_method") == "local":
        if (
            settings.app_env != "local"
            or not settings.admin_local_login_enabled
            or subject != LOCAL_ADMIN_SUBJECT
        ):
            return None
    elif subject not in settings.allowed_admin_subjects:
        return None
    return AdminIdentity(subject, stored.get("email"), stored.get("name"))


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


def require_sensitive_admin(
    request: Request,
    admin: AdminIdentity = Depends(require_csrf),
) -> AdminIdentity:
    authenticated_at = request.session.get("authenticated_at", 0)
    if settings.app_env == "production" and time.time() - authenticated_at > 300:
        raise HTTPException(428, "Recent OIDC reauthentication is required")
    return admin


def require_confirmation(value: str | None, expected: str) -> None:
    if settings.app_env == "production" and value != expected:
        raise HTTPException(409, f"Production confirmation must exactly match: {expected}")


def _safe_admin_path(value: str | None) -> str:
    if value and value.startswith("/admin") and not value.startswith("//"):
        return value
    return "/admin"


@router.get("/status")
def auth_status(request: Request):
    identity = _identity(request)
    return {
        "configured": settings.oidc_configured,
        "local_login_enabled": settings.app_env == "local" and settings.admin_local_login_enabled,
        "local_login_url": "/api/v1/admin/auth/local-login",
        "authenticated": identity is not None,
        "admin": identity.public() if identity else None,
        "csrf_token": request.session.get("csrf") if identity else None,
        "recent_authentication": bool(
            identity and time.time() - request.session.get("authenticated_at", 0) <= 300
        ),
        "login_url": "/api/v1/admin/auth/login",
    }


@router.post("/local-login")
def local_login(request: Request, db: Session = Depends(get_db)):
    if settings.app_env != "local" or not settings.admin_local_login_enabled:
        raise HTTPException(403, "Local administrator login is disabled")
    request.session.clear()
    request.session["authenticated_at"] = int(time.time())
    request.session["admin"] = {
        "sub": LOCAL_ADMIN_SUBJECT,
        "name": "Local administrator",
        "auth_method": "local",
    }
    request.session["csrf"] = secrets.token_urlsafe(32)
    db.add(AdminAuditLog(admin_subject=LOCAL_ADMIN_SUBJECT, action="admin.local-login", details={}))
    db.commit()
    return {"ok": True}


@router.get("/login")
async def login(request: Request, next: str | None = None, reauth: bool = False):
    request.session["admin_next"] = _safe_admin_path(next)
    redirect_uri = urljoin(settings.public_base_url.rstrip("/") + "/", "api/v1/admin/auth/callback")
    extra = {"prompt": "login", "max_age": 0} if reauth else {}
    return await _client().authorize_redirect(request, redirect_uri, **extra)


@router.get("/callback")
async def callback(request: Request, db: Session = Depends(get_db)):
    token = await _client().authorize_access_token(request)
    userinfo = token.get("userinfo")
    if not isinstance(userinfo, dict) or not userinfo.get("sub"):
        raise HTTPException(401, "OIDC provider did not return a valid subject")
    subject = str(userinfo["sub"])
    if subject not in settings.allowed_admin_subjects:
        request.session.clear()
        raise HTTPException(403, "Authenticated identity is not an administrator")
    request.session["authenticated_at"] = int(time.time())
    request.session["admin"] = {
        "sub": subject,
        "email": userinfo.get("email"),
        "name": userinfo.get("name"),
        "auth_method": "oidc",
    }
    request.session["csrf"] = secrets.token_urlsafe(32)
    next_path = _safe_admin_path(request.session.pop("admin_next", None))
    db.add(AdminAuditLog(admin_subject=subject, action="admin.login", details={"email": userinfo.get("email")}))
    db.commit()
    return RedirectResponse(next_path, status_code=303)


@router.post("/logout")
def logout(request: Request, admin: AdminIdentity = Depends(require_csrf), db: Session = Depends(get_db)):
    db.add(AdminAuditLog(admin_subject=admin.subject, action="admin.logout", details={}))
    db.commit()
    request.session.clear()
    return {"ok": True}
