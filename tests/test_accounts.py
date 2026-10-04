"""Tests for the multi-user account system.

Two layers:
  * unit tests of :class:`AccountManager` against a real SQLite database
    (password hashing, sessions, resets, e-mail verification, devices);
  * end-to-end API tests through the FastAPI app (register/login/logout,
    CSRF enforcement, password reset, account deletion, device linking).

Everything uses real code paths and a real database file — no mocks.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp(prefix="openhud-acct-")
os.environ["OPENHUD_DATA_DIR"] = str(Path(_TMP) / "data")
os.environ["OPENHUD_WORKSPACE"] = str(Path(_TMP) / "workspace")
os.environ["OPENHUD_PASSWORD"] = "test-password"
os.environ["OPENHUD_EXPOSE_RESET_LINK"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from openhud.core.accounts import (  # noqa: E402
    AccountManager,
    hash_password,
    normalize_email,
    validate_email,
    validate_password,
    verify_password_hash,
)
from openhud.core.db import Database  # noqa: E402
from openhud.web.app import app  # noqa: E402

client = TestClient(app)


def _db() -> Database:
    return Database(Path(tempfile.mkdtemp(prefix="openhud-acct-db-")) / "a.db")


# --------------------------------------------------------------------------
# password hashing
# --------------------------------------------------------------------------
def test_hash_is_salted_and_verifies():
    h1 = hash_password("Senha12345")
    h2 = hash_password("Senha12345")
    assert h1 != h2  # random salt
    assert h1.startswith("pbkdf2_sha256$")
    assert verify_password_hash("Senha12345", h1)
    assert not verify_password_hash("outra", h1)


def test_verify_rejects_malformed_hash():
    assert not verify_password_hash("x", "not-a-hash")
    assert not verify_password_hash("x", "pbkdf2_sha256$abc$def")


def test_password_policy():
    assert validate_password("curta")[0] is False
    assert validate_password("12345678")[0] is False        # common
    assert validate_password("somenteletras")[0] is False   # letters only
    assert validate_password("123456789")[0] is False       # digits only
    assert validate_password("Senha12345")[0] is True


def test_email_normalisation_and_validation():
    assert normalize_email("  User@Example.COM ") == "user@example.com"
    assert validate_email("a@b.com")
    assert not validate_email("sem-arroba")
    assert not validate_email("a@b")


# --------------------------------------------------------------------------
# AccountManager
# --------------------------------------------------------------------------
def test_create_and_authenticate_user():
    am = AccountManager(_db())
    user = am.create_user("User@Example.com", "Senha12345", "Ana")
    assert user["email"] == "user@example.com"
    assert am.get_user_by_email("USER@example.com")["id"] == user["id"]
    assert am.verify_credentials("user@example.com", "Senha12345") is not None
    assert am.verify_credentials("user@example.com", "errada") is None
    # The stored row never contains the clear password.
    assert "Senha12345" not in user["password_hash"]


def test_duplicate_email_rejected():
    am = AccountManager(_db())
    am.create_user("a@b.com", "Senha12345")
    try:
        am.create_user("a@b.com", "OutraSenha1")
    except ValueError as exc:
        assert "Já existe" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_invalid_email_and_password_rejected():
    am = AccountManager(_db())
    for email, password in [("bad", "Senha12345"), ("a@b.com", "curta")]:
        try:
            am.create_user(email, password)
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError(f"expected ValueError for {email}/{password}")


def test_session_lifecycle_and_expiry():
    am = AccountManager(_db())
    user = am.create_user("a@b.com", "Senha12345")
    token, _ = am.create_session(user["id"], "pytest", "127.0.0.1")
    assert am.user_for_session(token)["id"] == user["id"]
    # token is stored only as a hash
    assert am.db.query_one("SELECT * FROM user_sessions")["token_hash"] != token
    am.revoke_session(token)
    assert am.user_for_session(token) is None
    assert am.user_for_session("nonsense") is None


def test_expired_session_is_rejected():
    import time

    am = AccountManager(_db())
    user = am.create_user("a@b.com", "Senha12345")
    token, _ = am.create_session(user["id"])
    am.db.execute("UPDATE user_sessions SET expires_at=?", (time.time() - 10,))
    assert am.user_for_session(token) is None


def test_password_reset_flow():
    am = AccountManager(_db())
    user = am.create_user("a@b.com", "Senha12345")
    raw = am.create_reset(user["id"])
    assert am.consume_reset(raw, "NovaSenha123") == user["id"]
    # one-time use
    assert am.consume_reset(raw, "OutraSenha12") is None
    assert am.verify_credentials("a@b.com", "NovaSenha123") is not None
    assert am.consume_reset("invalido", "OutraSenha12") is None


def test_email_verification_flow():
    am = AccountManager(_db())
    user = am.create_user("a@b.com", "Senha12345")
    assert am.get_user(user["id"])["email_verified"] == 0
    raw = am.create_email_verification(user["id"])
    assert am.consume_email_verification(raw) == user["id"]
    assert am.get_user(user["id"])["email_verified"] == 1
    assert am.consume_email_verification(raw) is None


def test_device_linking_and_unlinking():
    am = AccountManager(_db())
    user = am.create_user("a@b.com", "Senha12345")
    am.link_device(user["id"], "dev1", "PC da Ana")
    assert am.owns_device(user["id"], "dev1")
    assert am.user_for_device("dev1")["id"] == user["id"]
    assert len(am.list_user_devices(user["id"])) == 1
    # relink updates the name instead of duplicating
    am.link_device(user["id"], "dev1", "PC novo")
    assert am.list_user_devices(user["id"])[0]["name"] == "PC novo"
    assert am.unlink_device(user["id"], "dev1") is True
    assert am.unlink_device(user["id"], "dev1") is False
    assert am.owns_device(user["id"], "dev1") is False


def test_delete_user_removes_related_rows():
    am = AccountManager(_db())
    user = am.create_user("a@b.com", "Senha12345")
    am.create_session(user["id"])
    am.create_reset(user["id"])
    am.link_device(user["id"], "dev1")
    am.delete_user(user["id"])
    assert am.get_user(user["id"]) is None
    assert am.db.query_one("SELECT * FROM user_sessions WHERE user_id=?", (user["id"],)) is None
    assert am.db.query_one("SELECT * FROM user_devices WHERE user_id=?", (user["id"],)) is None


def test_public_user_hides_hash():
    am = AccountManager(_db())
    user = am.create_user("a@b.com", "Senha12345", "Ana")
    pub = am.public_user(user)
    assert "password_hash" not in pub
    assert pub["email"] == "a@b.com"


# --------------------------------------------------------------------------
# API: end-to-end
# --------------------------------------------------------------------------
def _csrf() -> str:
    client.get("/api/account/csrf")
    return client.cookies.get("openhud_csrf")


def _post(path: str, **body):
    body["csrf"] = _csrf()
    return client.post(path, json=body)


def _fresh_email(prefix: str = "u") -> str:
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def test_api_register_login_logout_me():
    email = _fresh_email()
    r = _post("/api/account/register", email=email, password="Senha12345", name="Ana")
    assert r.status_code == 200, r.text
    assert r.json()["user"]["email"] == email
    assert client.get("/api/account/me").json()["authenticated"] is True

    assert _post("/api/account/logout").status_code == 200
    assert client.get("/api/account/me").json()["authenticated"] is False

    r = _post("/api/account/login", email=email, password="Senha12345")
    assert r.status_code == 200
    assert r.json()["user"]["email"] == email


def test_api_login_wrong_password():
    email = _fresh_email()
    _post("/api/account/register", email=email, password="Senha12345")
    r = _post("/api/account/login", email=email, password="errada123")
    assert r.status_code == 401


def test_api_register_requires_csrf():
    r = client.post("/api/account/register",
                    json={"email": _fresh_email(), "password": "Senha12345"})
    assert r.status_code == 403


def test_api_register_duplicate_email():
    email = _fresh_email()
    assert _post("/api/account/register", email=email, password="Senha12345").status_code == 200
    r = _post("/api/account/register", email=email, password="Senha12345")
    assert r.status_code == 400


def test_api_password_reset_roundtrip():
    email = _fresh_email()
    _post("/api/account/register", email=email, password="Senha12345")
    _post("/api/account/logout")
    d = _post("/api/account/forgot-password", email=email).json()
    assert d["ok"] is True
    assert d.get("reset_link")  # exposed in tests via OPENHUD_EXPOSE_RESET_LINK
    token = d["reset_link"].split("token=")[-1]
    assert _post("/api/account/reset-password", token=token, password="NovaSenha123").status_code == 200
    assert _post("/api/account/login", email=email, password="NovaSenha123").status_code == 200


def test_api_forgot_password_does_not_leak_existence():
    d = _post("/api/account/forgot-password", email=_fresh_email("naoexiste")).json()
    assert d["ok"] is True
    assert "reset_link" not in d  # unknown e-mail yields no link


def test_api_change_password_and_name():
    email = _fresh_email()
    _post("/api/account/register", email=email, password="Senha12345", name="Ana")
    assert _post("/api/account/name", name="Ana Silva").json()["user"]["name"] == "Ana Silva"
    assert _post("/api/account/change-password",
                 current_password="Senha12345", new_password="OutraSenha99").status_code == 200
    assert _post("/api/account/change-password",
                 current_password="errada", new_password="MaisUmaSenha1").status_code == 400
    assert _post("/api/account/login", email=email, password="OutraSenha99").status_code == 200


def test_api_delete_account():
    email = _fresh_email()
    _post("/api/account/register", email=email, password="Senha12345")
    assert _post("/api/account/delete", password="Senha12345", confirm="errado").status_code == 400
    assert _post("/api/account/delete", password="Senha12345", confirm="EXCLUIR").status_code == 200
    assert _post("/api/account/login", email=email, password="Senha12345").status_code == 401


def test_api_sessions_listing():
    email = _fresh_email()
    _post("/api/account/register", email=email, password="Senha12345")
    sessions = client.get("/api/account/sessions").json()["sessions"]
    assert len(sessions) >= 1
    assert "token_hash" not in sessions[0]


def test_api_device_registration_links_to_account():
    email = _fresh_email()
    _post("/api/account/register", email=email, password="Senha12345")
    r = _post("/api/agent/register-device", name="PC Teste", platform="windows")
    assert r.status_code == 200, r.text
    device_id = r.json()["device_id"]
    assert r.json()["token"]
    devices = client.get("/api/account/devices").json()["devices"]
    assert any(d["device_id"] == device_id for d in devices)
    # revoke removes it from the hub entirely (so it does not leak into other
    # tests that look for a connected device)
    assert _post(f"/api/account/devices/{device_id}/revoke").status_code == 200
    # unlink removes the (now revoked) device from the account view
    assert _post(f"/api/account/devices/{device_id}/unlink").status_code in (200, 404)
    assert client.get("/api/account/devices").json()["devices"] == []


def test_api_account_pages_render():
    for path in ("/register", "/login", "/forgot-password", "/reset-password", "/account"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "OpenHUD" in r.text


def test_account_js_exposes_get_for_read_only_endpoints():
    """The account page must use GET for devices/sessions (they are GET routes).

    Regression: ``api()`` always POSTs, so calling it against ``GET
    /api/account/devices`` returned 405 "Method Not Allowed" in the browser.
    """
    js = client.get("/static/account/account.js").text
    assert "async function get(" in js
    assert "get," in js  # exported on window.OpenHUD

    html = client.get("/account").text
    assert 'get("/api/account/devices")' in html
    assert 'get("/api/account/sessions")' in html
    assert 'api("/api/account/devices")' not in html
    assert 'api("/api/account/sessions")' not in html


def test_public_pages_reference_cache_busted_assets():
    """Asset URLs carry a version query so browsers don't serve stale JS/CSS."""
    for path in ("/", "/features", "/login", "/register", "/account"):
        html = client.get(path).text
        assert "site.css?v=" in html, path
        assert "site.js?v=" in html, path


def test_api_me_unauthenticated():
    client.cookies.clear()
    d = client.get("/api/account/me").json()
    assert d["authenticated"] is False
    assert d["accounts_enabled"] is True


def test_site_config_endpoint():
    d = client.get("/api/site/config").json()
    assert "donation_url" in d
    assert d["accounts_enabled"] in (True, False)


def test_sitemap_and_robots():
    assert client.get("/sitemap.xml").status_code == 200
    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert "Disallow: /api/" in robots.text


# --------------------------------------------------------------------------
# desktop account login + wizard
# --------------------------------------------------------------------------
def test_desktop_login_validates_inputs():
    from openhud.desktop.account import login_and_register

    r = login_and_register("", "a@b.com", "Senha12345", "PC")
    assert r.ok is False and r.detail == "missing_server"
    r = login_and_register("https://x", "", "", "PC")
    assert r.ok is False and r.detail == "missing_credentials"


def test_desktop_login_against_live_server():
    """Start a real uvicorn server and log in with the desktop client.

    This exercises the exact HTTP contract the Windows app uses (CSRF cookie,
    login, device registration) end to end — no mocks.
    """
    import socket
    import threading
    import time

    import uvicorn

    from openhud.desktop.account import login_and_register

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                import urllib.request

                urllib.request.urlopen(base + "/health", timeout=1)
                break
            except Exception:
                time.sleep(0.2)

        email = _fresh_email("desk")
        # Register through the API client first.
        _post("/api/account/register", email=email, password="Senha12345", name="Desktop")
        client.cookies.clear()

        result = login_and_register(base, email, "Senha12345", "PC do Teste", "windows")
        assert result.ok is True, result.message
        assert result.token
        assert result.user["email"] == email

        bad = login_and_register(base, email, "senha-errada", "PC", "windows")
        assert bad.ok is False
        assert bad.detail == "bad_credentials"
    finally:
        # Do not leave a registered device behind in the shared hub.
        try:
            from openhud.core.agent_hub import get_hub

            if result.device_id:
                get_hub().revoke(result.device_id)
        except Exception:
            pass
        server.should_exit = True
        thread.join(timeout=10)


def test_wizard_account_login_path(tmp_path, monkeypatch):
    from openhud.desktop import wizard
    from openhud.desktop.account import AccountResult
    from openhud.desktop.config import DesktopConfig

    monkeypatch.setattr(wizard.DesktopConfig, "save", lambda self, path=None: None)

    def fake_login(server, email, password, name, platform):
        assert password == "Senha12345"  # used once, never stored
        return AccountResult(True, "ok", device_id="dev-1", token="tok-1",
                             user={"email": email, "name": "Ana"})

    cfg = DesktopConfig()
    io = _WizardIO(
        answers=["https://s", "ana@b.com", "Senha12345", "PC da Ana"],
        confirms=[True, True, False, False, False, False],  # use account + groups + autostart
    )
    out = wizard.run_wizard(cfg, io, login=fake_login)
    assert out.token == "tok-1"
    assert out.device_id == "dev-1"
    assert out.account_email == "ana@b.com"
    assert out.onboarded is True


class _WizardIO:
    def __init__(self, answers=None, confirms=None):
        self.answers = list(answers or [])
        self.confirms = list(confirms or [])

    def say(self, message):
        pass

    def ask(self, prompt, default=""):
        return self.answers.pop(0) if self.answers else default

    def confirm(self, prompt, default=False):
        return self.confirms.pop(0) if self.confirms else default
