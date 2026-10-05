"""Integration tests for the PC-agent device lifecycle.

These exercise the real FastAPI app, the real AgentHub registry and the real
SQLite database (no mocks). They cover the flow the Windows app performs:

    login (account) -> register device -> list devices -> link to account
    -> permissions -> revoke -> token invalid -> account deletion cleans up

Plus pairing-code expiry, rate limiting and the frozen-build pipeline files.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp(prefix="openhud-device-")
os.environ["OPENHUD_DATA_DIR"] = str(Path(_TMP) / "data")
os.environ["OPENHUD_WORKSPACE"] = str(Path(_TMP) / "workspace")
os.environ["OPENHUD_PASSWORD"] = "test-password"
os.environ["OPENHUD_ACCOUNTS"] = "on"

from openhud.web.app import app  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_hub():
    """Remove devices created during a test so the global hub singleton does
    not leak state into other test modules."""
    from openhud.core.agent_hub import get_hub

    hub = get_hub()
    before = {d["id"] for d in hub.list_devices()}
    yield
    for did in {d["id"] for d in hub.list_devices()} - before:
        hub.revoke(did)


def _csrf(c: TestClient) -> str:
    return c.get("/api/account/csrf").json()["csrf"]


def _register(c: TestClient, email: str, password: str = "SenhaSegura123") -> None:
    csrf = _csrf(c)
    r = c.post("/api/account/register",
               json={"email": email, "password": password, "name": "Dono", "csrf": csrf})
    assert r.status_code == 200, r.text


# -- account registration + device registration -----------------------------
def test_register_device_with_account_session():
    email = f"dev-{int(time.time()*1000)}@example.com"
    _register(client, email)
    csrf = _csrf(client)
    r = client.post("/api/agent/register-device",
                    json={"name": "Meu PC", "platform": "windows", "csrf": csrf})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["device_id"] and body["token"]
    assert len(body["token"]) >= 20

    # The device is owned by the account and shows in /api/account/devices.
    devices = client.get("/api/account/devices").json()["devices"]
    assert any(d["device_id"] == body["device_id"] for d in devices)

    # The token authenticates the hub and can be revoked.
    from openhud.core.agent_hub import get_hub

    assert get_hub().verify_token(body["token"]) is not None
    rev = client.post(f"/api/account/devices/{body['device_id']}/revoke", json={"csrf": csrf})
    assert rev.status_code == 200 and rev.json()["revoked"] is True
    assert get_hub().verify_token(body["token"]) is None


def test_register_device_requires_csrf():
    email = f"dev-{int(time.time()*1000)}-2@example.com"
    _register(client, email)
    r = client.post("/api/agent/register-device",
                    json={"name": "PC", "platform": "windows", "csrf": "wrong"})
    assert r.status_code == 403


def test_account_without_devices_lists_none():
    c = TestClient(app)
    email = f"nodev-{int(time.time()*1000)}@example.com"
    _register(c, email)
    assert c.get("/api/account/devices").json()["devices"] == []


def test_devices_endpoint_requires_login():
    c = TestClient(app)
    assert c.get("/api/account/devices").status_code == 401


def test_unlink_unknown_device_is_404():
    c = TestClient(app)
    email = f"unlink-{int(time.time()*1000)}@example.com"
    _register(c, email)
    csrf = _csrf(c)
    r = c.post("/api/account/devices/does-not-exist/unlink", json={"csrf": csrf})
    assert r.status_code == 404


def test_account_deletion_removes_device_links():
    c = TestClient(app)
    email = f"del-{int(time.time()*1000)}@example.com"
    _register(c, email)
    csrf = _csrf(c)
    dev = c.post("/api/agent/register-device",
                 json={"name": "PC", "platform": "windows", "csrf": csrf}).json()
    # Delete the account.
    r = c.post("/api/account/delete",
               json={"password": "SenhaSegura123", "confirm": "EXCLUIR", "csrf": csrf})
    assert r.status_code == 200, r.text
    from openhud.core.runtime import runtime

    rows = runtime.db.query(
        "SELECT COUNT(*) AS n FROM user_devices WHERE device_id=?", (dev["device_id"],)
    )
    assert rows[0]["n"] == 0


# -- hub-level lifecycle (no HTTP) ------------------------------------------
def _fake_hub():
    from openhud.core.agent_hub import AgentHub

    class FakeDB:
        def __init__(self):
            self.store = {}

        def get_setting(self, key, default=None):
            return self.store.get(key, default)

        def set_setting(self, key, value):
            self.store[key] = value

    return AgentHub(FakeDB())


def test_pairing_code_expires():
    hub = _fake_hub()
    code = hub.create_pairing_code()["code"]
    hub._pairing[code]["created_at"] = time.time() - 10_000  # older than TTL
    with pytest.raises(ValueError):
        hub.redeem_pairing_code(code, "PC", "Windows", {})


def test_invalid_token_rejected():
    hub = _fake_hub()
    assert hub.verify_token("not-a-real-token") is None
    assert hub.verify_token("") is None


def test_register_device_returns_unique_tokens():
    hub = _fake_hub()
    a = hub.register_device("PC A", "windows", {})
    b = hub.register_device("PC B", "windows", {})
    assert a["device_id"] != b["device_id"]
    assert a["token"] != b["token"]
    assert hub.verify_token(a["token"]).id == a["device_id"]


def test_device_permission_update_and_unknown_key_ignored():
    hub = _fake_hub()
    d = hub.register_device("PC", "windows", {})
    hub.set_permissions(d["device_id"], {"processes": True, "bogus_key": True})
    dev = hub.get_device(d["device_id"])
    assert dev.permissions["processes"] is True
    assert "bogus_key" not in dev.permissions


def test_command_to_offline_device_is_honest_error():
    hub = _fake_hub()
    d = hub.register_device("PC", "windows", {})
    with pytest.raises(RuntimeError):
        hub.request(d["device_id"], "get_metrics", {}, timeout=0.1)


def test_command_blocked_without_permission():
    hub = _fake_hub()
    d = hub.register_device("PC", "windows", {})
    # Fake a live connection so we reach the permission check.
    hub._connections[d["device_id"]] = object()
    hub.loop = None  # send() would fail, but permission check happens first
    with pytest.raises(PermissionError):
        hub.request(d["device_id"], "shell", {"command": "echo hi"}, timeout=0.1)


def test_revoke_removes_device_from_listing():
    hub = _fake_hub()
    d = hub.register_device("PC", "windows", {})
    assert any(x["id"] == d["device_id"] for x in hub.list_devices())
    hub.revoke(d["device_id"])
    assert not any(x["id"] == d["device_id"] for x in hub.list_devices())


# -- packaging pipeline files ----------------------------------------------
def test_windows_build_workflow_template_is_valid():
    wf = Path(__file__).resolve().parents[1] / "installer/github-actions/windows-build.yml"
    assert wf.is_file(), "o template do workflow de build do Windows deve existir"
    text = wf.read_text(encoding="utf-8")
    assert "windows-latest" in text
    assert "openhud.desktop.build" in text
    assert "openhud.agent.build_exe" in text
    assert "OpenHUD-AI-Setup.exe" in text
    assert "iscc" in text.lower()
    assert "softprops/action-gh-release" in text


def test_enable_github_build_installs_workflow(tmp_path, monkeypatch):
    """The installer copies the template into .github/workflows/ and is idempotent."""
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "enable_github_build", root / "installer/enable-github-build.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    dst = tmp_path / ".github" / "workflows" / "windows-build.yml"
    monkeypatch.setattr(mod, "DST", dst)
    assert mod.main() == 0
    assert dst.is_file()
    assert dst.read_bytes() == mod.SRC.read_bytes()
    # Idempotent second run.
    assert mod.main() == 0


def test_installer_script_present():
    iss = Path(__file__).resolve().parents[1] / "installer/openhud.iss"
    text = iss.read_text(encoding="utf-8")
    assert "OpenHUD-AI-Setup" in text
    assert "MyAppVersion" in text
    assert "PrivilegesRequired=lowest" in text


def test_build_scripts_import_cleanly():
    import importlib

    for mod in ("openhud.desktop.build", "openhud.agent.build_exe"):
        m = importlib.import_module(mod)
        assert hasattr(m, "main")


# -- download link resolution (never fabricated) ----------------------------
def test_release_url_published_when_configured(monkeypatch):
    from openhud.core import release as rel

    monkeypatch.setenv("OPENHUD_DOWNLOAD_URL",
                       "https://github.com/kevincavadas90-droid/openhud-ai/"
                       "releases/download/v5.2.0/OpenHUD-AI-Setup.exe")
    monkeypatch.setenv("OPENHUD_SOURCE_URL",
                       "https://github.com/kevincavadas90-droid/openhud-ai/"
                       "releases/download/v5.2.0/OpenHUD-AI-Complete-5.2.0.zip")
    r = rel.get_release()
    assert r.published is True
    assert r.url.endswith("OpenHUD-AI-Setup.exe")
    assert r.filename == "OpenHUD-AI-Setup.exe"
    assert r.source_zip_available is True
    assert r.source_zip_url.endswith("OpenHUD-AI-Complete-5.2.0.zip")


def test_release_not_published_without_url_or_artifact(monkeypatch):
    from openhud.core import release as rel

    monkeypatch.delenv("OPENHUD_DOWNLOAD_URL", raising=False)
    monkeypatch.delenv("OPENHUD_SERVE_INSTALLER", raising=False)
    monkeypatch.setenv("OPENHUD_RELEASE_DIR", "/nonexistent-dir")
    # No local artifact exists in that dir -> must stay unpublished (honest).
    r = rel.get_release()
    assert r.published is False
    assert r.url is None
