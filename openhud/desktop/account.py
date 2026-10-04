"""Account login for the OpenHUD desktop app.

The Windows program must let the user sign in with the same e-mail and password
they use on the website, then register this computer on the account. This module
does exactly that using only the standard library (``urllib``), so it adds no
new dependency to the single-file PyInstaller build.

Design notes:
  * credentials are sent once over HTTPS/WSS to ``/api/account/login``; the
    returned session cookie is used only to call ``/api/agent/register-device``
    and is not persisted — the desktop app keeps the *device token* instead,
    which the server can revoke at any time;
  * the password is never written to disk;
  * every failure returns a clear, translated message instead of a stack trace.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class AccountResult:
    ok: bool
    message: str
    device_id: str = ""
    token: str = ""
    user: dict[str, Any] | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "message": self.message, "device_id": self.device_id,
            "token": self.token, "user": self.user or {}, "detail": self.detail,
        }


def _opener() -> urllib.request.OpenerDirector:
    ctx = ssl.create_default_context()
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


def _post(server: str, path: str, payload: dict[str, Any],
          cookies: str | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict, str]:
    """POST JSON and return (status, body, set_cookie_header). Raises URLError."""
    url = server.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "OpenHUD-Desktop/1.0")
    if cookies:
        req.add_header("Cookie", cookies)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with _opener().open(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(body) if body else {}), _set_cookie(resp.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"detail": raw}
        return exc.code, parsed, _set_cookie(exc.headers) if exc.headers else ""


def _set_cookie(headers) -> str:
    """Join every Set-Cookie header; ``get('Set-Cookie')`` returns only the first."""
    if headers is None:
        return ""
    getter = getattr(headers, "get_all", None)
    values = getter("Set-Cookie") if getter else None
    if not values:
        single = headers.get("Set-Cookie")
        values = [single] if single else []
    return ", ".join(values)


def _cookie_pair(set_cookie: str) -> str:
    """Extract the ``name=value`` pairs we need from a Set-Cookie header."""
    if not set_cookie:
        return ""
    parts = []
    for chunk in set_cookie.split(","):
        first = chunk.strip().split(";")[0].strip()
        if first and "=" in first:
            parts.append(first)
    return "; ".join(parts)


def _cookie_value(cookies: str, name: str) -> str:
    for pair in (cookies or "").split(";"):
        key, _, value = pair.strip().partition("=")
        if key == name:
            return value
    return ""


def login_and_register(server: str, email: str, password: str, device_name: str,
                       platform: str = "windows") -> AccountResult:
    """Sign in with the account and register this computer.

    Returns an :class:`AccountResult`; on success ``token`` is the device token
    to store in the desktop config.
    """
    server = (server or "").rstrip("/")
    if not server:
        return AccountResult(False, "Informe o endereço do servidor.", detail="missing_server")
    if not email or not password:
        return AccountResult(False, "Informe e-mail e senha.", detail="missing_credentials")

    # 1) CSRF token (non-HttpOnly cookie the server sets).
    csrf = ""
    try:
        req = urllib.request.Request(server + "/api/account/csrf")
        req.add_header("User-Agent", "OpenHUD-Desktop/1.0")
        with _opener().open(req, timeout=20) as resp:
            csrf = (json.loads(resp.read().decode("utf-8")) or {}).get("csrf", "")
            csrf_cookie = _cookie_pair(resp.headers.get("Set-Cookie", ""))
    except urllib.error.HTTPError as exc:
        return AccountResult(False, "Servidor não respondeu ao pedido de login.",
                             detail=f"http_{exc.code}")
    except Exception as exc:  # noqa: BLE001
        return AccountResult(False, f"Não consegui falar com o servidor: {exc}",
                             detail=type(exc).__name__)

    # 2) Login.
    try:
        status, body, set_cookie = _post(
            server, "/api/account/login",
            {"email": email, "password": password, "csrf": csrf},
            cookies=csrf_cookie,
            headers={"X-CSRF-Token": csrf},
        )
    except Exception as exc:  # noqa: BLE001
        return AccountResult(False, f"Falha de conexão: {exc}", detail=type(exc).__name__)

    if status == 401:
        return AccountResult(False, "E-mail ou senha incorretos.", detail="bad_credentials")
    if status == 429:
        return AccountResult(False, "Muitas tentativas. Aguarde alguns minutos.", detail="rate_limited")
    if status != 200:
        return AccountResult(False, body.get("detail", "Não foi possível entrar."),
                             detail=f"http_{status}")

    cookies = _cookie_pair(set_cookie) or csrf_cookie
    user = body.get("user") or {}
    # The server rotates the CSRF token when a session starts, so use the new
    # value from the login response for the next call.
    csrf = _cookie_value(cookies, "openhud_csrf") or csrf

    # 3) Register this device on the account.
    try:
        status, body, _ = _post(
            server, "/api/agent/register-device",
            {"name": device_name, "platform": platform, "csrf": csrf},
            cookies=cookies,
            headers={"X-CSRF-Token": csrf},
        )
    except Exception as exc:  # noqa: BLE001
        return AccountResult(False, f"Login ok, mas não consegui registrar o dispositivo: {exc}",
                             detail=type(exc).__name__)
    if status != 200:
        return AccountResult(False, body.get("detail", "Não foi possível registrar este computador."),
                             detail=f"http_{status}")

    return AccountResult(True, "Conectado.", device_id=body.get("device_id", ""),
                         token=body.get("token", ""), user=user)
