"""Tests for Phase 6: real Windows validation, installer, public site and
distribution.

Covers: the release-metadata module (real SHA-256 / size, honest "not
published"), the public marketing site routes, the agent diagnostics
(PASS/WARNING/FAIL/NOT INSTALLED/NOT PERMITTED), the desktop config, the
first-run wizard and the headless agent runtime. Everything exercises real code
paths; nothing is mocked that we can run for real.
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp(prefix="openhud-p6-")
os.environ["OPENHUD_DATA_DIR"] = str(Path(_TMP) / "data")
os.environ["OPENHUD_WORKSPACE"] = str(Path(_TMP) / "workspace")
os.environ["OPENHUD_PASSWORD"] = "test-password"

from fastapi.testclient import TestClient  # noqa: E402

from openhud.web.app import app  # noqa: E402

client = TestClient(app)


# --------------------------------------------------------------------------
# public marketing site
# --------------------------------------------------------------------------
def test_public_site_pages_render_without_login():
    for path in ("/", "/features", "/how-it-works", "/pricing", "/help",
                 "/privacy", "/download", "/changelog"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "OpenHUD" in r.text
        assert "<html" in r.text.lower()


def test_site_is_public_but_app_is_protected():
    # The marketing site must be reachable without a session.
    assert client.get("/", follow_redirects=False).status_code == 200
    assert client.get("/download", follow_redirects=False).status_code == 200
    # The application itself must require a session.
    anon = TestClient(app)
    assert anon.get("/app", follow_redirects=False).status_code == 302
    assert anon.get("/settings", follow_redirects=False).status_code == 302


def test_version_and_release_api():
    v = client.get("/version").json()
    assert v["app"] == "openhud"
    assert v["version"] == "5.1.0"
    assert "download" in v
    rel = client.get("/api/site/release").json()
    assert rel["filename"] == "OpenHUD-AI-Setup.exe"
    assert rel["platform"].startswith("Windows")
    assert isinstance(rel["requirements"], list) and rel["requirements"]
    # Without a hosted URL or local artifact the page must be honest.
    assert rel["published"] is False


def test_changelog_api_has_entries():
    data = client.get("/api/site/changelog").json()
    assert data["entries"]
    assert all("version" in e and "items" in e for e in data["entries"])


def test_site_assets_exist():
    for path in ("/static/site/site.css", "/static/site/logo.svg",
                 "/static/site/favicon.svg", "/static/site/app-icon.png"):
        assert client.get(path).status_code == 200, path


# --------------------------------------------------------------------------
# release metadata: real file, real hash
# --------------------------------------------------------------------------
def test_release_metadata_computes_real_hash(tmp_path, monkeypatch):
    from openhud.core import release as rel

    artifact = tmp_path / "OpenHUD-AI-Setup.exe"
    artifact.write_bytes(b"openhud-installer-payload" * 100)
    monkeypatch.setenv("OPENHUD_RELEASE_DIR", str(tmp_path))
    monkeypatch.delenv("OPENHUD_DOWNLOAD_URL", raising=False)
    monkeypatch.delenv("OPENHUD_SERVE_INSTALLER", raising=False)

    r = rel.get_release()
    assert r.source == "artifact"
    assert r.size == artifact.stat().st_size
    assert r.sha256 == rel._sha256(artifact)
    assert r.published is False  # no hosting URL yet
    assert r.size_human.endswith(("B", "KB", "MB"))


def test_release_serving_local_implies_published(monkeypatch, tmp_path):
    from openhud.core import release as rel

    (tmp_path / "OpenHUD-AI-Setup.exe").write_bytes(b"payload")
    monkeypatch.setenv("OPENHUD_RELEASE_DIR", str(tmp_path))
    monkeypatch.delenv("OPENHUD_DOWNLOAD_URL", raising=False)
    monkeypatch.setenv("OPENHUD_SERVE_INSTALLER", "1")
    r = rel.get_release()
    assert r.serving is True
    assert r.published is True
    assert r.url == "/download/file"


def test_release_url_makes_it_published(monkeypatch, tmp_path):
    from openhud.core import release as rel

    monkeypatch.setenv("OPENHUD_RELEASE_DIR", str(tmp_path))  # empty dir
    monkeypatch.setenv("OPENHUD_DOWNLOAD_URL",
                       "https://github.com/openhud/releases/OpenHUD-AI-Setup.exe")
    r = rel.get_release()
    assert r.published is True
    assert r.url.endswith("OpenHUD-AI-Setup.exe")


def test_human_size():
    from openhud.core.release import human_size

    assert human_size(0) == "—"
    assert human_size(512) == "512 B"
    assert human_size(2048) == "2.0 KB"


# --------------------------------------------------------------------------
# agent diagnostics
# --------------------------------------------------------------------------
def test_selfcheck_runs_and_reports_statuses():
    from openhud.agent import selfcheck

    rep = selfcheck.run_checks(server=None, token=None, perms=None)
    assert rep.platform
    assert rep.checks
    names = {c.name for c in rep.checks}
    assert {"Sistema", "Arquitetura", "Python / runtime", "Conexão de rede",
            "WebSocket", "CPU", "RAM", "Armazenamento"} <= names
    valid = {selfcheck.PASS, selfcheck.WARNING, selfcheck.FAIL,
             selfcheck.NOT_INSTALLED, selfcheck.NOT_PERMITTED}
    assert all(c.status in valid for c in rep.checks)
    # Screen/control are off by default -> NOT PERMITTED, not a fake PASS.
    screen = next(c for c in rep.checks if c.name == "Captura de tela")
    assert screen.status == selfcheck.NOT_PERMITTED


def test_selfcheck_json_and_render():
    from openhud.agent import selfcheck

    rep = selfcheck.run_checks()
    data = rep.to_dict()
    assert set(data) >= {"platform", "ok", "summary", "checks"}
    assert sum(data["summary"].values()) == len(data["checks"])
    text = selfcheck.render(rep, color=False)
    assert "OpenHUD Agent Diagnostics" in text


def test_selfcheck_permission_gating():
    from openhud.agent import selfcheck

    rep = selfcheck.run_checks(perms={"screen": True, "control": True, "voice": True})
    screen = next(c for c in rep.checks if c.name == "Captura de tela")
    # With permission granted the status changes away from NOT PERMITTED
    # (either a real PASS, or NOT INSTALLED when the native lib is missing).
    assert screen.status in (selfcheck.PASS, selfcheck.NOT_INSTALLED, selfcheck.FAIL)


def test_selfcheck_cli_exit_code(capsys):
    from openhud.agent import selfcheck

    code = selfcheck.main(["--no-color"])
    out = capsys.readouterr().out
    assert "OpenHUD Agent Diagnostics" in out
    assert code in (0, 1)


# --------------------------------------------------------------------------
# desktop config
# --------------------------------------------------------------------------
def test_desktop_config_roundtrip(tmp_path):
    from openhud.desktop.config import DesktopConfig

    path = tmp_path / "desktop.json"
    cfg = DesktopConfig(server="https://x", token="tok", name="PC")
    cfg.groups["control"] = True
    cfg.save(path)
    loaded = DesktopConfig.load(path)
    assert loaded.server == "https://x"
    assert loaded.token == "tok"
    assert loaded.groups["control"] is True


def test_desktop_permissions_expand_from_groups(tmp_path):
    from openhud.desktop.config import DesktopConfig

    cfg = DesktopConfig()
    perms = cfg.permissions()
    # Basic on by default; control/screen/voice off.
    assert perms["system"] is True and perms["cpu"] is True
    assert perms["control"] is False and perms["screen"] is False and perms["voice"] is False
    cfg.groups["control"] = True
    assert cfg.permissions()["control"] is True
    assert "Controle" in cfg.summary()


def test_desktop_config_handles_corrupt_file(tmp_path):
    from openhud.desktop.config import DesktopConfig

    path = tmp_path / "desktop.json"
    path.write_text("{not valid json", encoding="utf-8")
    cfg = DesktopConfig.load(path)  # must not raise
    assert cfg.server == ""


# --------------------------------------------------------------------------
# first-run wizard
# --------------------------------------------------------------------------
class _FakeIO:
    def __init__(self, answers, confirms):
        self.answers = list(answers)
        self.confirms = list(confirms)
        self.said = []

    def say(self, message):
        self.said.append(message)

    def ask(self, prompt, default=""):
        return self.answers.pop(0) if self.answers else default

    def confirm(self, prompt, default=False):
        return self.confirms.pop(0) if self.confirms else default


def test_wizard_saves_config_and_respects_choices(tmp_path, monkeypatch):
    from openhud.desktop import wizard
    from openhud.desktop.config import DesktopConfig

    monkeypatch.setattr(wizard.DesktopConfig, "save",
                        lambda self, path=None: None)
    cfg = DesktopConfig()
    io = _FakeIO(
        answers=["https://meu-servidor.exemplo", ""],   # server, token
        confirms=[True, False, False, False, False, False],  # groups + autostart
    )
    out = wizard.run_wizard(cfg, io)
    assert out.server == "https://meu-servidor.exemplo"
    assert out.onboarded is True
    assert out.groups["basic"] is True
    assert out.groups["control"] is False
    assert out.autostart is False
    assert any("OpenHUD AI" in s for s in io.said)


def test_wizard_accepts_pair_code_argument(tmp_path, monkeypatch):
    from openhud.desktop import wizard
    from openhud.desktop.config import DesktopConfig

    monkeypatch.setattr(wizard.DesktopConfig, "save", lambda self, path=None: None)
    cfg = DesktopConfig()
    io = _FakeIO(answers=["https://s"], confirms=[True, False, False, False, False, False])
    out = wizard.run_wizard(cfg, io, pair_code="123456")
    assert out.extra["pair_code"] == "123456"


# --------------------------------------------------------------------------
# headless agent runtime
# --------------------------------------------------------------------------
def test_runtime_refuses_without_config():
    from openhud.desktop.config import DesktopConfig
    from openhud.desktop.runtime import AgentRuntime

    rt = AgentRuntime(DesktopConfig())
    assert rt.start() is False
    assert rt.state == "disconnected"
    assert "Servidor" in rt.last_error


def test_runtime_refuses_without_token():
    from openhud.desktop.config import DesktopConfig
    from openhud.desktop.runtime import AgentRuntime

    rt = AgentRuntime(DesktopConfig(server="https://x"))
    assert rt.start() is False
    assert "token" in rt.last_error.lower()


def test_runtime_state_callback():
    from openhud.desktop.config import DesktopConfig
    from openhud.desktop.runtime import AgentRuntime

    seen = []
    rt = AgentRuntime(DesktopConfig(), on_state=lambda s, d: seen.append(s))
    rt.start()
    assert "disconnected" in seen
    assert rt.status_label() == "OpenHUD desconectado"


# --------------------------------------------------------------------------
# installer + build scripts exist and are coherent
# --------------------------------------------------------------------------
def test_installer_script_present_and_clean():
    root = Path(__file__).resolve().parents[1]
    iss = (root / "installer" / "openhud.iss").read_text(encoding="utf-8")
    assert "OutputBaseFilename=OpenHUD-AI-Setup" in iss
    assert "openhud.ico" in iss
    # Optional shortcuts must be unchecked by default.
    assert iss.count("Flags: unchecked") >= 3
    # No Windows services or scheduled tasks are installed.
    assert "[Registry]" in iss
    assert "ScheduledTask" not in iss
    # Clean uninstall asks about user data.
    assert "RemoveData" in iss and "InitializeUninstall" in iss


def test_icon_asset_exists():
    root = Path(__file__).resolve().parents[1]
    ico = root / "installer" / "openhud.ico"
    assert ico.is_file() and ico.stat().st_size > 1000


def test_windows_smoke_test_script_present():
    root = Path(__file__).resolve().parents[1]
    ps = root / "installer" / "windows-smoke-test.ps1"
    assert ps.is_file()
    text = ps.read_text(encoding="utf-8")
    # Covers the real procedure and stays honest about the environment.
    for marker in ("selfcheck", "--json", "pytest", "Get-CimInstance Win32_VideoController",
                   "Run key", "Get-Service", "windows-test-report.json", "iscc"):
        assert marker in text, marker
    assert "IsWindows" in text
    assert "exit 1" in text


def test_version_consistency():
    from openhud import __version__
    from openhud.core import release as rel

    root = Path(__file__).resolve().parents[1]
    iss = (root / "installer" / "openhud.iss").read_text(encoding="utf-8")
    assert __version__ in iss
    assert rel.get_release().version == __version__


# --------------------------------------------------------------------------
# source ZIP metadata (honest: only when a real file exists)
# --------------------------------------------------------------------------
def test_source_zip_absent_is_honest(monkeypatch, tmp_path):
    from openhud.core import release as rel

    monkeypatch.setenv("OPENHUD_SOURCE_DIR", str(tmp_path))
    monkeypatch.delenv("OPENHUD_SOURCE_URL", raising=False)
    monkeypatch.delenv("OPENHUD_SERVE_SOURCE", raising=False)
    r = rel.get_release()
    assert r.source_zip_available is False
    assert r.source_zip_url is None


def test_source_zip_detected_with_real_hash(monkeypatch, tmp_path):
    from openhud.core import release as rel

    name = rel.SOURCE_ARTIFACT_NAME
    (tmp_path / name).write_bytes(b"source-zip-payload")
    monkeypatch.setenv("OPENHUD_SOURCE_DIR", str(tmp_path))
    monkeypatch.delenv("OPENHUD_SOURCE_URL", raising=False)
    monkeypatch.delenv("OPENHUD_SERVE_SOURCE", raising=False)
    r = rel.get_release()
    assert r.source_zip_available is True
    assert r.source_zip_name == name
    assert r.source_zip_size == len(b"source-zip-payload")
    assert r.source_zip_sha256 == hashlib.sha256(b"source-zip-payload").hexdigest()


def test_source_zip_served_when_opted_in(monkeypatch, tmp_path):
    from openhud.core import release as rel

    (tmp_path / rel.SOURCE_ARTIFACT_NAME).write_bytes(b"x")
    monkeypatch.setenv("OPENHUD_SOURCE_DIR", str(tmp_path))
    monkeypatch.setenv("OPENHUD_SERVE_SOURCE", "1")
    monkeypatch.delenv("OPENHUD_SOURCE_URL", raising=False)
    r = rel.get_release()
    assert r.source_zip_url == "/download/source"


def test_source_url_wins(monkeypatch, tmp_path):
    from openhud.core import release as rel

    monkeypatch.setenv("OPENHUD_SOURCE_DIR", str(tmp_path))
    monkeypatch.setenv("OPENHUD_SOURCE_URL",
                       "https://example.test/OpenHUD-AI-Complete-5.0.0.zip")
    r = rel.get_release()
    assert r.source_zip_available is True
    assert r.source_zip_url.endswith(".zip")
