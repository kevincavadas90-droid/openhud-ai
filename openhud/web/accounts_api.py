"""User accounts API and pages.

Two surfaces share one :class:`AccountManager`:

  * ``/api/account/*`` — JSON endpoints used by the site pages, the logged-in
    app and the desktop client (register, login, reset, profile, devices).
  * ``/register``, ``/forgot-password``, ``/reset-password`` and ``/account`` —
    self-contained pages served from ``static/account``.

Session cookies are signed-free opaque tokens: the raw value only ever lives in
the user's cookie, while the database stores its SHA-256 hash. A separate,
non-HttpOnly CSRF cookie is paired with the session cookie and must be echoed
in the ``X-CSRF-Token`` header on every state-changing request.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from ..config import settings
from ..core.accounts import AccountManager, normalize_email, validate_email
from ..core.mail import Mailer, public_url, reset_email, verification_email
from .ratelimit import account_limiter, login_limiter, register_limiter, reset_limiter

log = logging.getLogger("openhud.accounts")

router = APIRouter()

USER_COOKIE = "openhud_user"
CSRF_COOKIE = "openhud_csrf"

# Paths that must be reachable without a session (login/register/reset flow).
ACCOUNT_PUBLIC_PATHS = {
    "/register", "/forgot-password", "/reset-password",
    "/api/account/register", "/api/account/login", "/api/account/logout",
    "/api/account/me", "/api/account/csrf",
    "/api/account/forgot-password", "/api/account/reset-password",
    "/api/account/verify-email",
}

_account_manager: AccountManager | None = None
_mailer: Mailer | None = None


def init_accounts(db) -> AccountManager:
    """Wire the account manager to the runtime database (called from app.py)."""
    global _account_manager, _mailer
    _account_manager = AccountManager(db)
    _mailer = Mailer(settings.data_dir)
    return _account_manager


def get_accounts() -> AccountManager:
    if _account_manager is None:
        raise RuntimeError("AccountManager não inicializado.")
    return _account_manager


def get_mailer() -> Mailer:
    if _mailer is None:
        raise RuntimeError("Mailer não inicializado.")
    return _mailer


def accounts_enabled() -> bool:
    return os.environ.get("OPENHUD_ACCOUNTS", "on").lower() not in {"off", "0", "false"}


# --------------------------------------------------------------------------
# request helpers
# --------------------------------------------------------------------------
def _is_https(request: Request) -> bool:
    return bool(request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https")


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _set_session_cookies(resp: JSONResponse, request: Request, token: str, csrf: str) -> None:
    secure = _is_https(request)
    max_age = 60 * 60 * 24 * 30
    resp.set_cookie(USER_COOKIE, token, max_age=max_age, httponly=True,
                    samesite="lax", secure=secure, path="/")
    # CSRF cookie is readable by JS on purpose; it is not a secret on its own.
    resp.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False,
                    samesite="lax", secure=secure, path="/")


def _clear_session_cookies(resp: JSONResponse) -> None:
    resp.delete_cookie(USER_COOKIE, path="/")
    resp.delete_cookie(CSRF_COOKIE, path="/")


def current_user(request: Request) -> dict[str, Any] | None:
    if not accounts_enabled():
        return None
    return get_accounts().user_for_session(request.cookies.get(USER_COOKIE))


def require_user(request: Request) -> dict[str, Any]:
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "Faça login para continuar.")
    return user


def require_csrf(request: Request, body_token: str | None = None) -> None:
    """Double-submit cookie check for state-changing requests."""
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get("x-csrf-token")
    token = header or body_token
    if not cookie or not token or cookie != token:
        raise HTTPException(403, "Token CSRF ausente ou inválido. Recarregue a página.")


# --------------------------------------------------------------------------
# payloads
# --------------------------------------------------------------------------
class RegisterPayload(BaseModel):
    email: str
    password: str
    name: str = ""
    csrf: str | None = None


class LoginPayload(BaseModel):
    email: str
    password: str
    csrf: str | None = None


class ForgotPayload(BaseModel):
    email: str
    csrf: str | None = None


class ResetPayload(BaseModel):
    token: str
    password: str
    csrf: str | None = None


class ChangePasswordPayload(BaseModel):
    current_password: str
    new_password: str
    csrf: str | None = None


class NamePayload(BaseModel):
    name: str
    csrf: str | None = None


class DeletePayload(BaseModel):
    password: str
    confirm: str = ""
    csrf: str | None = None


class DeviceLinkPayload(BaseModel):
    device_id: str
    name: str = ""
    csrf: str | None = None


class DeviceActionPayload(BaseModel):
    csrf: str | None = None


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
@router.get("/api/account/csrf")
def csrf_token(request: Request) -> JSONResponse:
    token = request.cookies.get(CSRF_COOKIE)
    if not token:
        import secrets

        token = secrets.token_urlsafe(24)
        resp = JSONResponse({"csrf": token})
        resp.set_cookie(CSRF_COOKIE, token, httponly=False, samesite="lax",
                        secure=_is_https(request), path="/", max_age=60 * 60 * 24 * 30)
        return resp
    return JSONResponse({"csrf": token})


@router.get("/api/account/me")
def me(request: Request) -> dict[str, Any]:
    if not accounts_enabled():
        return {"authenticated": False, "accounts_enabled": False}
    user = current_user(request)
    if user is None:
        return {"authenticated": False, "accounts_enabled": True}
    return {"authenticated": True, "accounts_enabled": True,
            "user": get_accounts().public_user(user)}


@router.post("/api/account/register")
def register(payload: RegisterPayload, request: Request) -> JSONResponse:
    if not accounts_enabled():
        raise HTTPException(404, "Cadastro de contas desativado.")
    require_csrf(request, payload.csrf)
    if not register_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "Muitos cadastros. Tente novamente mais tarde.")
    accounts = get_accounts()
    try:
        user = accounts.create_user(payload.email, payload.password, payload.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    # Best-effort verification e-mail; the account works immediately either way.
    verification_sent = False
    if validate_email(payload.email):
        raw = accounts.create_email_verification(user["id"])
        link = f"{public_url() or ''}/reset-password?verify={raw}"
        subject, body = verification_email(user.get("name", ""), link)
        result = get_mailer().send(user["email"], subject, body)
        verification_sent = result.delivered
    token, _ = accounts.create_session(user["id"], request.headers.get("user-agent", ""), _client_ip(request))
    import secrets

    csrf = secrets.token_urlsafe(24)
    resp = JSONResponse({
        "ok": True,
        "user": accounts.public_user(user),
        "email_sent": verification_sent,
    })
    _set_session_cookies(resp, request, token, csrf)
    return resp


@router.post("/api/account/login")
def login(payload: LoginPayload, request: Request) -> JSONResponse:
    if not accounts_enabled():
        raise HTTPException(404, "Login de contas desativado.")
    require_csrf(request, payload.csrf)
    ip = _client_ip(request)
    if not login_limiter.allow(ip):
        raise HTTPException(429, "Muitas tentativas. Tente novamente em alguns minutos.")
    accounts = get_accounts()
    user = accounts.verify_credentials(payload.email, payload.password)
    if user is None:
        raise HTTPException(401, "E-mail ou senha incorretos.")
    accounts.touch_login(user["id"])
    token, _ = accounts.create_session(user["id"], request.headers.get("user-agent", ""), ip)
    import secrets

    csrf = secrets.token_urlsafe(24)
    resp = JSONResponse({"ok": True, "user": accounts.public_user(user)})
    _set_session_cookies(resp, request, token, csrf)
    return resp


@router.post("/api/account/logout")
def logout(request: Request, payload: DeviceActionPayload | None = None) -> JSONResponse:
    token = request.cookies.get(USER_COOKIE)
    if accounts_enabled() and token:
        get_accounts().revoke_session(token)
    resp = JSONResponse({"ok": True})
    _clear_session_cookies(resp)
    return resp


@router.post("/api/account/forgot-password")
def forgot_password(payload: ForgotPayload, request: Request) -> dict[str, Any]:
    if not accounts_enabled():
        raise HTTPException(404, "Recuperação de senha desativada.")
    require_csrf(request, payload.csrf)
    if not reset_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "Muitos pedidos. Tente novamente mais tarde.")
    accounts = get_accounts()
    # Always return the same message so account existence is not leaked.
    generic = {"ok": True, "message": "Se o e-mail existir, enviamos um link de redefinição."}
    if not validate_email(payload.email):
        return generic
    user = accounts.get_user_by_email(payload.email)
    if user is None or user.get("status") != "active":
        return generic
    raw = accounts.create_reset(user["id"])
    link = f"{public_url() or ''}/reset-password?token={raw}"
    subject, body = reset_email(user.get("name", ""), link)
    result = get_mailer().send(user["email"], subject, body)
    # Only surface the link when mail could not be delivered AND we are not in
    # production (no SMTP). This keeps local testing usable without pretending
    # the e-mail was sent.
    out = dict(generic)
    out["email_sent"] = result.delivered
    if not result.delivered and os.environ.get("OPENHUD_EXPOSE_RESET_LINK", "").lower() in {"1", "true", "on"}:
        out["reset_link"] = link
    return out


@router.post("/api/account/reset-password")
def reset_password(payload: ResetPayload, request: Request) -> dict[str, Any]:
    if not accounts_enabled():
        raise HTTPException(404, "Redefinição de senha desativada.")
    require_csrf(request, payload.csrf)
    if not reset_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "Muitos pedidos. Tente novamente mais tarde.")
    try:
        user_id = get_accounts().consume_reset(payload.token, payload.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if user_id is None:
        raise HTTPException(400, "Link inválido ou expirado. Peça um novo.")
    return {"ok": True, "message": "Senha redefinida. Faça login novamente."}


@router.post("/api/account/verify-email")
def verify_email(payload: ResetPayload, request: Request) -> dict[str, Any]:
    require_csrf(request, payload.csrf)
    user_id = get_accounts().consume_email_verification(payload.token)
    if user_id is None:
        raise HTTPException(400, "Link inválido ou expirado.")
    return {"ok": True, "message": "E-mail confirmado."}


@router.post("/api/account/change-password")
def change_password(payload: ChangePasswordPayload, request: Request) -> dict[str, Any]:
    user = require_user(request)
    require_csrf(request, payload.csrf)
    if not account_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "Muitas alterações. Aguarde alguns minutos.")
    try:
        get_accounts().change_password(user["id"], payload.current_password, payload.new_password)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "message": "Senha alterada."}


@router.post("/api/account/name")
def set_name(payload: NamePayload, request: Request) -> dict[str, Any]:
    user = require_user(request)
    require_csrf(request, payload.csrf)
    accounts = get_accounts()
    accounts.set_name(user["id"], payload.name)
    return {"ok": True, "user": accounts.public_user(accounts.get_user(user["id"]))}


@router.post("/api/account/delete")
def delete_account(payload: DeletePayload, request: Request) -> JSONResponse:
    user = require_user(request)
    require_csrf(request, payload.csrf)
    if (payload.confirm or "").strip().upper() != "EXCLUIR":
        raise HTTPException(400, "Digite EXCLUIR para confirmar a exclusão.")
    from ..core.accounts import verify_password_hash

    if not verify_password_hash(payload.password, user["password_hash"]):
        raise HTTPException(403, "Senha incorreta.")
    get_accounts().delete_user(user["id"])
    resp = JSONResponse({"ok": True, "message": "Conta excluída."})
    _clear_session_cookies(resp)
    return resp


# -- devices ----------------------------------------------------------------
@router.get("/api/account/devices")
def list_devices(request: Request) -> dict[str, Any]:
    user = require_user(request)
    from ..core.agent_hub import get_hub

    accounts = get_accounts()
    linked = {d["device_id"]: d for d in accounts.list_user_devices(user["id"])}
    hub = get_hub()
    out = []
    for dev in hub.list_devices():
        if dev["id"] not in linked:
            continue
        row = linked[dev["id"]]
        out.append({
            "device_id": dev["id"],
            "name": dev.get("name") or row.get("name") or "Meu PC",
            "platform": dev.get("platform", "unknown"),
            "online": dev.get("online", False),
            "last_seen": dev.get("last_seen"),
            "linked_at": row.get("linked_at"),
            "version": (dev.get("info") or {}).get("app_version")
            or (dev.get("info") or {}).get("version") or "—",
            "permissions": dev.get("permissions", {}),
        })
    return {"devices": out}


@router.post("/api/account/devices/link")
def link_device(payload: DeviceLinkPayload, request: Request) -> dict[str, Any]:
    user = require_user(request)
    require_csrf(request, payload.csrf)
    from ..core.agent_hub import get_hub

    hub = get_hub()
    dev = hub.get_device(payload.device_id)
    if dev is None:
        raise HTTPException(404, "Dispositivo não encontrado.")
    get_accounts().link_device(user["id"], payload.device_id, payload.name or dev.name)
    return {"ok": True}


@router.post("/api/account/devices/{device_id}/unlink")
def unlink_device(device_id: str, request: Request, payload: DeviceActionPayload | None = None) -> dict[str, Any]:
    user = require_user(request)
    require_csrf(request, payload.csrf if payload else None)
    ok = get_accounts().unlink_device(user["id"], device_id)
    if not ok:
        raise HTTPException(404, "Dispositivo não vinculado a esta conta.")
    return {"ok": True}


@router.post("/api/account/devices/{device_id}/revoke")
def revoke_device(device_id: str, request: Request, payload: DeviceActionPayload | None = None) -> dict[str, Any]:
    """Unlink the device and revoke its agent token so it must re-pair."""
    user = require_user(request)
    require_csrf(request, payload.csrf if payload else None)
    from ..core.agent_hub import get_hub

    if not get_accounts().owns_device(user["id"], device_id):
        raise HTTPException(404, "Dispositivo não vinculado a esta conta.")
    get_accounts().unlink_device(user["id"], device_id)
    get_hub().revoke(device_id)
    return {"ok": True, "revoked": True}


# -- sessions ---------------------------------------------------------------
@router.get("/api/account/sessions")
def list_sessions(request: Request) -> dict[str, Any]:
    user = require_user(request)
    rows = get_accounts().list_sessions(user["id"])
    return {"sessions": [
        {"id": r["id"], "created_at": r["created_at"], "last_seen": r["last_seen"],
         "user_agent": r.get("user_agent", ""), "ip": r.get("ip", "")}
        for r in rows
    ]}


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------
def _account_page(name: str) -> FileResponse:
    return FileResponse(settings.static_dir / "account" / name,
                        headers={"Cache-Control": "no-cache"})


@router.get("/register", response_class=HTMLResponse)
def register_page() -> FileResponse:
    return _account_page("register.html")


@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_page() -> FileResponse:
    return _account_page("forgot-password.html")


@router.get("/reset-password", response_class=HTMLResponse)
def reset_page() -> FileResponse:
    return _account_page("reset-password.html")


@router.get("/account", response_class=HTMLResponse)
def account_page() -> FileResponse:
    return _account_page("account.html")
