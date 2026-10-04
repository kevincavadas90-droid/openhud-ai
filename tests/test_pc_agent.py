"""Tests for the PC-agent layer: hub, telemetry, diagnostics and REST API."""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENHUD_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENHUD_PASSWORD", "test-pass")
    monkeypatch.setenv("OPENHUD_WORKSPACE", str(tmp_path / "ws"))
    # Import fresh so the runtime picks up the temp data dir.
    import importlib

    import openhud.web.app as app_module

    importlib.reload(app_module)
    c = TestClient(app_module.app)
    c.post("/api/login", json={"password": "test-pass"})
    return c


def test_telemetry_collect_shape():
    from openhud.agent.telemetry import TelemetryCollector

    col = TelemetryCollector()
    info = col.system_info()
    assert "os" in info and "hostname" in info
    m = col.collect()
    assert m["available"] is True
    assert "cpu" in m and "ram" in m
    assert isinstance(m["gpu"], list)
    # A second sample yields non-null network rates keys.
    m2 = col.collect()
    assert "down_kbps" in m2["network"]


def test_diagnostics_high_cpu_bottleneck():
    from openhud.agent.diagnostics import diagnose

    metrics = {
        "available": True,
        "ts": 1.0,
        "cpu": {"percent": 97.0, "temp_c": 60.0, "cores_logical": 8},
        "ram": {"percent": 40.0, "used_mb": 4000, "total_mb": 16000},
        "gpu": [{"name": "RTX", "util_percent": 45.0, "mem_percent": 50.0, "temp_c": 55.0}],
        "disk": [],
        "processes": [{"name": "chrome", "cpu_percent": 30.0}],
    }
    d = diagnose(metrics)
    assert d["ok"] is True
    assert d["bottleneck"]["type"] == "cpu"
    assert any("CPU" in f["title"] for f in d["findings"])


def test_diagnostics_gpu_vram_bottleneck():
    from openhud.agent.diagnostics import diagnose

    metrics = {
        "available": True,
        "ts": 1.0,
        "cpu": {"percent": 55.0},
        "ram": {"percent": 60.0, "used_mb": 8000, "total_mb": 16000},
        "gpu": [{"name": "RTX", "util_percent": 98.0, "mem_percent": 99.0, "temp_c": 80.0}],
        "disk": [],
        "processes": [],
    }
    d = diagnose(metrics)
    assert d["bottleneck"]["type"] == "gpu_vram"


def test_diagnostics_no_data_is_honest():
    from openhud.agent.diagnostics import diagnose

    d = diagnose({"available": False})
    assert d["ok"] is False
    assert "Agent" in d["error"]


def test_hub_pairing_and_token(monkeypatch):
    from openhud.core.agent_hub import AgentHub

    class FakeDB:
        def __init__(self):
            self.store = {}

        def get_setting(self, key, default=None):
            return self.store.get(key, default)

        def set_setting(self, key, value):
            self.store[key] = value

    hub = AgentHub(FakeDB())
    code = hub.create_pairing_code()["code"]
    result = hub.redeem_pairing_code(code, "PC", "Windows", {})
    assert result["device_id"]
    assert hub.verify_token(result["token"]) is not None
    # single use
    with pytest.raises(ValueError):
        hub.redeem_pairing_code(code, "PC2", "Windows", {})
    # revoke invalidates token
    assert hub.revoke(result["device_id"]) is True
    assert hub.verify_token(result["token"]) is None


def test_api_agents_local_and_permissions(client):
    r = client.post("/api/agents/local")
    assert r.status_code == 200
    dev = r.json()
    assert dev["id"] == "local"
    assert dev["metrics"].get("ts")

    listing = client.get("/api/agents").json()
    assert listing["local_id"] == "local"
    assert any(d["id"] == "local" for d in listing["devices"])

    # permission update
    r = client.post("/api/agents/local/permissions", json={"permissions": {"processes": True}})
    assert r.status_code == 200
    assert r.json()["permissions"]["processes"] is True


def test_api_pairing_requires_auth():
    # A fresh client without login must not mint pairing codes.
    import importlib

    import openhud.web.app as app_module

    app_module.auth.enabled = True
    from fastapi.testclient import TestClient

    c = TestClient(app_module.app)
    r = c.post("/api/agents/pairing")
    assert r.status_code == 401


def test_api_diagnose_local(client):
    client.post("/api/agents/local")
    r = client.post("/api/agents/local/diagnose")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True


def test_api_command_offline_device(client):
    # Unknown device -> 404 (honest error, not a fake success).
    r = client.post("/api/agents/nope/command", json={"command": "get_metrics", "args": {}})
    assert r.status_code == 404


def test_pc_tools_registered():
    from openhud.tools import build_default_registry

    names = {t.name for t in build_default_registry().all()}
    assert {"pc_metrics", "pc_diagnose", "pc_game_profile"} <= names
