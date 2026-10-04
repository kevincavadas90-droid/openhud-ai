"""Tests for Phase 5: computer assistant, accessibility, autonomy gating,
scam guard, screen analysis, updates, maintenance/backup and the new REST API.

Everything exercises real code paths. Screen capture and control depend on a
connected PC agent and optional native libraries, so those tests assert the
graceful-degradation contract instead of the network.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp(prefix="openhud-p5-")
os.environ["OPENHUD_DATA_DIR"] = str(Path(_TMP) / "data")
os.environ["OPENHUD_WORKSPACE"] = str(Path(_TMP) / "workspace")
os.environ["OPENHUD_PASSWORD"] = "test-password"

from fastapi.testclient import TestClient  # noqa: E402

from openhud.core.runtime import runtime  # noqa: E402
from openhud.web.app import app  # noqa: E402

client = TestClient(app)
assert client.post("/api/login", json={"password": "test-password"}).status_code == 200


# --------------------------------------------------------------------------
# profiles / autonomy / gating
# --------------------------------------------------------------------------
def test_profiles_and_autonomy_shape():
    from openhud.core.assist import AUTONOMY_LEVELS, PROFILES

    assert "standard" in PROFILES and "beginner" in PROFILES
    assert set(AUTONOMY_LEVELS) == {"observe", "guide", "assisted", "automatic"}
    for key, lvl in AUTONOMY_LEVELS.items():
        assert {"level", "label", "description", "can_control"} <= set(lvl)
    assert AUTONOMY_LEVELS["assisted"]["always_confirm"] is True
    assert AUTONOMY_LEVELS["automatic"]["always_confirm"] is False


def test_gate_blocks_control_in_guide_mode():
    from openhud.core.assist import gate

    res = gate("pc_mouse_click", {"x": 1, "y": 2}, {"autonomy_level": "guide"},
               tool_requires_confirmation=True, tool_is_control=True, legacy_autonomy="supervised")
    assert res["decision"] == "block"


def test_gate_auto_in_automatic_mode():
    from openhud.core.assist import gate

    res = gate("pc_mouse_click", {"x": 1, "y": 2}, {"autonomy_level": "automatic"},
               tool_requires_confirmation=True, tool_is_control=True, legacy_autonomy="autonomous")
    assert res["decision"] == "auto"


def test_gate_confirm_sensitive_payment_even_automatic():
    from openhud.core.assist import gate

    res = gate("pc_keyboard_type", {"text": "pagar o boleto agora"}, {"autonomy_level": "automatic"},
               tool_requires_confirmation=True, tool_is_control=True, legacy_autonomy="autonomous")
    assert res["decision"] == "confirm"
    assert res["sensitive"] is True
    assert res["classification"]["category"] == "payment"


def test_ordinary_tools_keep_confirmation_semantics():
    from openhud.core.assist import gate

    # run_python is not a control tool and is not always-sensitive; autonomous
    # legacy autonomy must still let it run without a new gate.
    auto = gate("run_python", {"code": "print('pagar')"}, {"autonomy_level": "automatic"},
                tool_requires_confirmation=True, tool_is_control=False, legacy_autonomy="autonomous")
    assert auto["decision"] == "auto"
    supervised = gate("run_python", {"code": "print(1)"}, {"autonomy_level": "assisted"},
                      tool_requires_confirmation=True, tool_is_control=False, legacy_autonomy="supervised")
    assert supervised["decision"] == "confirm"
    assert supervised["reason"]


def test_classify_always_sensitive_tools():
    from openhud.core.assist import classify_action

    assert classify_action("trading_execute_order", {}).sensitive
    assert classify_action("delete_file", {"path": "x"}).sensitive
    assert not classify_action("run_python", {"code": "senha = 1"}, text_scan=False).sensitive


def test_task_states_and_controller():
    from openhud.core.assist import TASK_STATES, task_controller

    assert "observing" in TASK_STATES and "waiting_confirmation" in TASK_STATES
    task_controller.begin("conv-x")
    task_controller.set_state("conv-x", "executing", "Fazendo algo")
    assert any(t["conversation_id"] == "conv-x" for t in task_controller.list())
    task_controller.request_cancel("conv-x")
    assert task_controller.is_cancelled("conv-x")
    task_controller.clear("conv-x")
    assert not task_controller.is_cancelled("conv-x")


def test_detect_control_phrase():
    from openhud.core.assist import detect_control_phrase

    assert detect_control_phrase("pare agora") == "cancel"
    assert detect_control_phrase("pause") == "pause"
    assert detect_control_phrase("continue") == "resume"
    assert detect_control_phrase("qual a capital da França?") is None


# --------------------------------------------------------------------------
# scam guard
# --------------------------------------------------------------------------
def test_scam_guard_detects_and_abstains():
    from openhud.core.scam_guard import analyze_text

    high = analyze_text("Urgente! Informe sua senha e o código do token agora.", "http://itau-seguranca.xyz/login")
    assert high.risk == "high"
    assert high.findings

    clean = analyze_text("Olá, o relatório está anexado. Abraços.", "https://empresa.com.br")
    assert clean.risk == "low"


# --------------------------------------------------------------------------
# screen analysis (pure functions; no capture needed)
# --------------------------------------------------------------------------
def test_screen_analysis_pure_functions():
    from openhud.agent.screen import detect_elements, find_matches, summarize_screen

    raw = [{"text": "Entrar", "x": 10, "y": 10, "w": 60, "h": 20},
           {"text": "Digite sua senha", "x": 5, "y": 50, "w": 120, "h": 18},
           {"text": "Senha", "x": 5, "y": 50, "w": 40, "h": 18}]
    els = detect_elements(raw, 1000, 800)
    summary = summarize_screen(els, 1000, 800)
    assert summary["summary"]
    matches = find_matches(els, "botão entrar")
    assert any(m.text == "Entrar" for m in matches)
    assert find_matches(els, "algo que não existe") == []


def test_screen_capabilities_reports_availability():
    from openhud.agent.screen import capabilities

    caps = capabilities()
    assert "capture" in caps and "ocr" in caps and "control" in caps


# --------------------------------------------------------------------------
# assistant REST API
# --------------------------------------------------------------------------
def test_api_profiles_autonomy_accessibility():
    r = client.get("/api/assistant/profiles")
    assert r.status_code == 200 and r.json()["profiles"]

    r = client.put("/api/assistant/profile", json={"profile": "beginner"})
    assert r.status_code == 200
    assert r.json()["profile"] == "beginner"

    r = client.put("/api/assistant/autonomy", json={"level": "assisted"})
    assert r.status_code == 200
    assert runtime.get_settings()["autonomy_level"] == "assisted"

    r = client.put("/api/assistant/accessibility", json={"large_text": True, "high_contrast": True})
    assert r.status_code == 200
    assert r.json()["preferences"]["large_text"] is True
    assert client.get("/api/assistant/accessibility").json()["preferences"]["high_contrast"] is True


def test_api_rejects_unknown_profile_and_level():
    assert client.put("/api/assistant/profile", json={"profile": "nope"}).status_code == 400
    assert client.put("/api/assistant/autonomy", json={"level": "nope"}).status_code == 400


def test_api_scam_check():
    r = client.post("/api/assistant/scam-check",
                    json={"text": "informe sua senha urgente", "url": "http://banco-falso.xyz"})
    assert r.status_code == 200
    assert r.json()["risk"] == "high"


def test_api_control_center_and_diagnose():
    r = client.get("/api/assistant/control-center")
    assert r.status_code == 200
    body = r.json()
    assert {"devices", "tasks", "security", "health"} <= set(body)
    assert "summary" in body["health"]

    d = client.get("/api/assistant/diagnose").json()
    assert "problems" in d and "suggested_fixes" in d


def test_api_screen_endpoints_degrade_gracefully():
    # No PC agent connected in tests: the endpoints must return a clear state.
    r = client.post("/api/assistant/screen/analyze", json={})
    assert r.status_code in (200, 409, 503)
    caps = client.get("/api/assistant/screen/capabilities")
    assert caps.status_code == 200


def test_api_task_action_unknown_conversation():
    r = client.post("/api/assistant/tasks/does-not-exist/action", json={"action": "cancel"})
    assert r.status_code in (200, 404)


# --------------------------------------------------------------------------
# updates (safe, check-only)
# --------------------------------------------------------------------------
def test_updates_rejects_http_and_missing_url():
    from openhud.core.updates import check_for_update

    assert check_for_update("5.0.0", "").available is False
    assert check_for_update("5.0.0", "http://evil.example/m.json").error
    info = check_for_update("5.0.0", "https://localhost/m.json")
    # Unreachable in tests, but never raises and reports the reason honestly.
    assert info.available is False


def test_updates_version_compare():
    from openhud.core.updates import UpdateInfo, _version_tuple

    assert _version_tuple("5.10.0") > _version_tuple("5.9.0")
    assert _version_tuple("v5.0.0") == (5, 0, 0)
    assert UpdateInfo().to_dict()["available"] is False


def test_update_api_version_and_check():
    r = client.get("/api/assistant/update/version")
    assert r.status_code == 200
    assert r.json()["version"] == app.version
    r = client.post("/api/assistant/update/check", json={})
    assert r.status_code == 200
    assert "available" in r.json()


# --------------------------------------------------------------------------
# maintenance: backup / restore / schema
# --------------------------------------------------------------------------
def test_maintenance_backup_restore_sqlite():
    from openhud.core.maintenance import SCHEMA_VERSION

    r = client.get("/api/assistant/maintenance/schema")
    assert r.status_code == 200
    assert r.json()["current"] == SCHEMA_VERSION

    created = client.post("/api/assistant/maintenance/backup")
    assert created.status_code == 200
    info = created.json()
    assert info["ok"] and info["integrity"] == "ok"

    listing = client.get("/api/assistant/maintenance/backups").json()
    assert any(b["name"] == Path(info["path"]).name for b in listing)

    restored = client.post("/api/assistant/maintenance/restore",
                           json={"command": "restore", "args": {"name": Path(info["path"]).name}})
    assert restored.status_code == 200
    assert restored.json()["ok"] is True


def test_maintenance_restore_missing_backup():
    r = client.post("/api/assistant/maintenance/restore",
                    json={"command": "restore", "args": {"name": "nao-existe.db"}})
    assert r.status_code == 400


# --------------------------------------------------------------------------
# desktop launcher
# --------------------------------------------------------------------------
def test_desktop_password_and_port():
    from openhud.desktop.app import ensure_password, free_port

    pw = ensure_password()
    assert pw and len(pw) >= 8
    port = free_port()
    assert 1 <= port <= 65535
