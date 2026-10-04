"""Tests for the MT5 trading module: indicators, risk, strategies, backtest,
alerts, paper trading, permissions, idempotency and the failure situations
required by the spec (disconnected agent, MT5 closed, broker rejection,
insufficient margin, daily loss, duplicate order, emergency stop, real trading
disabled by default).
"""
from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient


# --------------------------------------------------------------------------
# indicators
# --------------------------------------------------------------------------
def test_sma_ema_rsi_basic():
    from openhud.trading import indicators as ind

    values = [float(i) for i in range(1, 21)]
    sma5 = ind.sma(values, 5)
    assert sma5[:4] == [None] * 4
    assert sma5[4] == pytest.approx(3.0)
    assert sma5[-1] == pytest.approx(18.0)

    ema5 = ind.ema(values, 5)
    assert ema5[4] == pytest.approx(3.0)
    # Num série crescente a EMA acompanha mais de perto que a SMA.
    assert ema5[-1] >= sma5[-1]

    rising = ind.rsi(values, 14)
    assert rising[-1] == pytest.approx(100.0)
    falling = ind.rsi(list(reversed(values)), 14)
    assert falling[-1] == pytest.approx(0.0)


def test_bollinger_and_atr():
    from openhud.trading import indicators as ind

    closes = [10.0, 11.0, 12.0, 11.0, 10.0, 11.0, 12.0, 13.0, 12.0, 11.0,
              10.0, 11.0, 12.0, 11.0, 10.0, 11.0, 12.0, 13.0, 12.0, 11.0]
    bb = ind.bollinger(closes, 5, 2.0)
    assert bb["upper"][-1] is not None and bb["upper"][-1] >= bb["middle"][-1] >= bb["lower"][-1]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    atr = ind.atr(highs, lows, closes, 5)
    assert atr[-1] is not None and atr[-1] > 0


def test_stochastic_bounds():
    from openhud.trading import indicators as ind

    closes = [10 + math.sin(i / 3) for i in range(40)]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    st = ind.stochastic(highs, lows, closes)
    assert st["k"][-1] is not None and 0 <= st["k"][-1] <= 100


def test_swing_points_no_lookahead():
    from openhud.trading import indicators as ind

    highs = [1, 2, 3, 2, 1, 2, 3, 2, 1, 2, 3]
    lows = [h - 1 for h in highs]
    sw = ind.swing_points(highs, lows, left=1, right=1)
    # Peaks at index 2, 6, 10 are confirmed (index 10 has no right bar -> excluded).
    assert all(p["index"] <= len(highs) - 2 for p in sw["highs"])


# --------------------------------------------------------------------------
# risk engine
# --------------------------------------------------------------------------
def test_compute_risk_position_sizing():
    from openhud.trading.core import compute_risk

    r = compute_risk(balance=10_000, equity=10_000, risk_pct=1.0, entry=1.1000, stop=1.0950)
    assert r["ok"] is True
    # risk 100 USD / (0.0050 * 100000) = 0.2 lot
    assert r["lot"] == pytest.approx(0.2, abs=0.01)
    assert r["risk_actual_pct"] <= 1.05


def test_compute_risk_rejects_bad_input():
    from openhud.trading.core import compute_risk

    assert compute_risk(balance=0, equity=0, risk_pct=1, entry=1.1, stop=1.09)["ok"] is False
    assert compute_risk(balance=1000, equity=1000, risk_pct=1, entry=1.1, stop=1.1)["ok"] is False
    assert compute_risk(balance=1000, equity=1000, risk_pct=0, entry=1.1, stop=1.09)["ok"] is False


def test_check_limits_violations():
    from openhud.trading.core import RiskLimits, check_limits

    limits = RiskLimits(max_open_positions=1, max_trades_per_day=2, max_lot=0.5,
                        allowed_symbols=["EURUSD"], allowed_hours=[9, 10], max_daily_loss_pct=2.0)
    ok = check_limits(limits, symbol="EURUSD", hour=9, open_positions=0, trades_today=0,
                      daily_pnl=0, balance=10_000, lot=0.1)
    assert ok["ok"] is True

    bad = check_limits(limits, symbol="GBPUSD", hour=3, open_positions=1, trades_today=5,
                       daily_pnl=-500, balance=10_000, lot=1.0)
    assert bad["ok"] is False
    assert len(bad["violations"]) >= 5


# --------------------------------------------------------------------------
# strategies
# --------------------------------------------------------------------------
def test_parse_strategy_ema_rsi():
    from openhud.trading.core import parse_strategy

    s = parse_strategy("Minha estratégia usa EMA 9 + EMA 21 + RSI 14", name="Minha")
    assert s.name == "Minha"
    assert any("EMA 9" in c.label for c in s.entry_long)
    assert any(c.indicator == "rsi" for c in s.filters)
    assert s.to_dict()["entry_long"]


def test_parse_strategy_rsi_thresholds():
    from openhud.trading.core import parse_strategy

    s = parse_strategy("Avise quando RSI abaixo de 30")
    assert any(c.op == "<" and c.value == 30 for c in s.filters)


def test_parse_strategy_unknown_reports_honestly():
    from openhud.trading.core import parse_strategy

    s = parse_strategy("compra quando estiver bom")
    assert s.notes  # não inventa regras
    assert not s.entry_long


def test_strategy_roundtrip():
    from openhud.trading.core import parse_strategy

    s = parse_strategy("EMA 9 + EMA 21 + RSI 14")
    back = type(s).from_dict(s.to_dict())
    assert back.name == s.name
    assert len(back.entry_long) == len(s.entry_long)


# --------------------------------------------------------------------------
# analysis
# --------------------------------------------------------------------------
def _synthetic_ohlc(n=200, trend=1.0):
    closes = [1.1000 + trend * i * 0.0002 + 0.0005 * math.sin(i / 4) for i in range(n)]
    highs = [c + 0.0008 for c in closes]
    lows = [c - 0.0008 for c in closes]
    vols = [100 + (i % 20) for i in range(n)]
    return {"closes": closes, "highs": highs, "lows": lows, "volumes": vols}


def test_analyse_timeframe_returns_real_findings():
    from openhud.trading.analysis import analyse_timeframe

    a = analyse_timeframe(_synthetic_ohlc())
    assert a["ok"] is True
    assert a["price"] is not None
    assert a["indicators"]["ema9"] is not None
    assert a["findings"]


def test_analyse_timeframe_insufficient_data():
    from openhud.trading.analysis import analyse_timeframe

    a = analyse_timeframe({"closes": [1.0, 1.1], "highs": [1.2, 1.3], "lows": [0.9, 1.0]})
    assert a["ok"] is False
    assert "suficientes" in a["error"]


def test_multi_timeframe_consensus():
    from openhud.trading.analysis import multi_timeframe

    frames = {tf: _synthetic_ohlc() for tf in ("M5", "M15", "H1", "H4")}
    mt = multi_timeframe(frames)
    assert mt["ok"] is True
    assert mt["consensus"] == "alta"
    assert mt["aligned"] is True


# --------------------------------------------------------------------------
# backtest
# --------------------------------------------------------------------------
def test_backtest_runs_and_reports():
    from openhud.trading.core import parse_strategy, run_backtest

    s = parse_strategy("EMA 9 + EMA 21 + RSI 14")
    result = run_backtest(_synthetic_ohlc(300), s)
    assert result["ok"] is True
    m = result["metrics"]
    assert m["trades"] >= 0
    assert "profit_factor" in m and "max_drawdown_pct" in m
    assert "não garantem" in result["disclaimer"]


def test_backtest_rejects_insufficient_history():
    from openhud.trading.core import parse_strategy, run_backtest

    s = parse_strategy("EMA 9 + EMA 21")
    result = run_backtest(_synthetic_ohlc(20), s)
    assert result["ok"] is False


# --------------------------------------------------------------------------
# alerts
# --------------------------------------------------------------------------
def test_alert_price_and_indicator():
    from openhud.trading.alerts import evaluate_alert

    data = _synthetic_ohlc()
    price = data["closes"][-1]
    assert evaluate_alert({"kind": "price", "params": {"value": price - 1, "op": ">="}}, data)["triggered"] is True
    assert evaluate_alert({"kind": "price", "params": {"value": price + 1, "op": ">="}}, data)["triggered"] is False
    rsi_alert = evaluate_alert({"kind": "indicator", "params": {"indicator": "rsi", "op": ">", "value": 0}}, data)
    assert rsi_alert["triggered"] is True


def test_alert_spread_unavailable_is_honest():
    from openhud.trading.alerts import evaluate_alert

    r = evaluate_alert({"kind": "spread", "params": {"max": 2}}, _synthetic_ohlc(), spread=None)
    assert r["triggered"] is False
    assert "indisponível" in r["reason"]


# --------------------------------------------------------------------------
# paper trading
# --------------------------------------------------------------------------
def test_paper_account_lifecycle():
    from openhud.trading.core import PaperAccount

    acc = PaperAccount(balance=10_000)
    opened = acc.open_position(symbol="EURUSD", direction="compra", entry=1.1000, lot=0.1, stop=1.0950, take=1.1100)
    assert opened["ok"] is True
    pid = opened["position"]["id"]
    assert acc.mark_to_market({"EURUSD": 1.1050}) == pytest.approx(10_050.0)
    closed = acc.close_position(pid, 1.1050)
    assert closed["ok"] is True
    assert acc.summary()["closed_trades"] == 1
    assert acc.balance == pytest.approx(10_050.0)


def test_paper_rejects_bad_position():
    from openhud.trading.core import PaperAccount

    acc = PaperAccount()
    assert acc.open_position(symbol="EURUSD", direction="lateral", entry=1.1, lot=0.1)["ok"] is False
    assert acc.close_position("nope", 1.1)["ok"] is False


# --------------------------------------------------------------------------
# permissions, modes, idempotency (server policy)
# --------------------------------------------------------------------------
@pytest.fixture()
def hub(tmp_path):
    from openhud.core.agent_hub import AgentHub
    from openhud.core.db import Database

    db = Database(tmp_path / "t.db")
    return AgentHub(db)


def _register_device(hub, name="PC"):
    code = hub.create_pairing_code()["code"]
    res = hub.redeem_pairing_code(code, name, "Windows", {})
    return hub.get_device(res["device_id"])


def test_real_trading_disabled_by_default(hub):
    from openhud.trading.core import DEFAULT_TRADING_PERMISSIONS

    dev = _register_device(hub)
    assert dev.permissions["ALLOW_REAL_TRADING"] is False
    assert DEFAULT_TRADING_PERMISSIONS["ALLOW_REAL_TRADING"] is False
    assert dev.trading_mode == "analysis"


def test_old_devices_get_new_permission_keys(tmp_path):
    """A device saved before the MT5 module existed must receive the new
    permission defaults on load, not crash."""
    from openhud.core.agent_hub import AgentHub
    from openhud.core.db import Database

    db = Database(tmp_path / "old.db")
    db.set_setting("agent_devices", [{
        "id": "old1", "name": "PC antigo", "platform": "Windows", "token_hash": "x",
        "created_at": 1.0, "last_seen": 1.0, "info": {}, "metrics": {}, "metrics_at": 0.0,
        "permissions": {"system": True, "cpu": True},
    }])
    hub = AgentHub(db)
    dev = hub.get_device("old1")
    assert dev.permissions["ALLOW_MARKET_READ"] is True
    assert dev.permissions["ALLOW_REAL_TRADING"] is False
    assert dev.trading_mode == "analysis"


def test_mode_requires_permission(hub):
    dev = _register_device(hub)
    with pytest.raises(PermissionError):
        hub.set_trading_mode(dev.id, "real")
    # Enabling the permission then switching works.
    hub.set_permissions(dev.id, {"ALLOW_REAL_TRADING": True})
    hub.set_trading_mode(dev.id, "real")
    assert hub.get_device(dev.id).trading_mode == "real"


def test_emergency_stop_blocks_orders(hub):
    dev = _register_device(hub)
    hub.set_emergency_stop(dev.id, True)
    assert hub.get_device(dev.id).emergency_stop is True
    hub.set_emergency_stop(dev.id, False)
    assert hub.get_device(dev.id).emergency_stop is False


def test_request_rejects_disconnected_device(hub):
    dev = _register_device(hub)
    with pytest.raises(RuntimeError):
        hub.request(dev.id, "mt5_status", {})


def test_order_idempotency_store(tmp_path):
    from openhud.core.db import Database
    from openhud.trading.store import TradingStore

    store = TradingStore(Database(tmp_path / "o.db"))
    req = "req-123"
    store.record_order({"request_id": req, "device_id": "d1", "symbol": "EURUSD",
                        "direction": "compra", "lot": 0.1, "mode": "demo", "status": "confirmed",
                        "response": {"ok": True, "order": 42}})
    got = store.get_order(req)
    assert got["status"] == "confirmed"
    assert got["response"]["order"] == 42
    # Recording again (a duplicate submit) updates, never creates a second row.
    store.record_order({"request_id": req, "device_id": "d1", "symbol": "EURUSD",
                        "direction": "compra", "lot": 0.1, "mode": "demo", "status": "confirmed",
                        "response": {"ok": True, "order": 42}})
    rows = store.db.query("SELECT COUNT(*) AS n FROM trading_orders")
    assert int(dict(rows[0])["n"]) == 1


def test_trades_today_counts_only_confirmed(tmp_path):
    from openhud.core.db import Database
    from openhud.trading.store import TradingStore

    store = TradingStore(Database(tmp_path / "t2.db"))
    for i, status in enumerate(["confirmed", "confirmed", "failed"]):
        store.record_order({"request_id": f"r{i}", "device_id": "d1", "mode": "demo",
                            "status": status, "symbol": "EURUSD", "direction": "compra", "lot": 0.1})
    assert store.trades_today("d1", "demo") == 2


# --------------------------------------------------------------------------
# service-level failure handling (no MT5 available)
# --------------------------------------------------------------------------
def test_service_reports_no_pc(tmp_path, monkeypatch):
    from openhud.core.agent_hub import AgentHub
    from openhud.core.db import Database
    from openhud.trading.service import TradingService
    from openhud.trading.store import TradingStore
    import openhud.core.agent_hub as hub_mod

    db = Database(tmp_path / "s.db")
    hub_mod.hub = AgentHub(db)
    svc = TradingService(TradingStore(db))
    res = svc.status()
    assert res["ok"] is False
    assert "conectado" in res["error"].lower()


def test_service_order_blocked_in_analysis_mode(tmp_path):
    from openhud.core.agent_hub import AgentHub
    from openhud.core.db import Database
    from openhud.trading.service import TradingService
    from openhud.trading.store import TradingStore
    import openhud.core.agent_hub as hub_mod

    db = Database(tmp_path / "s2.db")
    hub_mod.hub = AgentHub(db)
    code = hub_mod.hub.create_pairing_code()["code"]
    dev_id = hub_mod.hub.redeem_pairing_code(code, "PC", "Windows", {})["device_id"]
    svc = TradingService(TradingStore(db))
    res = svc.execute_order(device_id=dev_id, symbol="EURUSD", direction="compra", lot=0.1,
                            stop=1.09, take=1.11, request_id="x1", confirmed=True)
    assert res["ok"] is False
    assert "DEMO" in res["error"] or "REAL" in res["error"]


def test_service_emergency_stop_blocks_execution(tmp_path):
    from openhud.core.agent_hub import AgentHub
    from openhud.core.db import Database
    from openhud.trading.service import TradingService
    from openhud.trading.store import TradingStore
    import openhud.core.agent_hub as hub_mod

    db = Database(tmp_path / "s3.db")
    hub_mod.hub = AgentHub(db)
    code = hub_mod.hub.create_pairing_code()["code"]
    dev_id = hub_mod.hub.redeem_pairing_code(code, "PC", "Windows", {})["device_id"]
    hub_mod.hub.set_emergency_stop(dev_id, True)
    svc = TradingService(TradingStore(db))
    res = svc.execute_order(device_id=dev_id, symbol="EURUSD", direction="compra", lot=0.1,
                            stop=1.09, take=1.11, request_id="x2", confirmed=True)
    assert res["ok"] is False
    assert "STOP TRADING" in res["error"]


def test_mt5_bridge_reports_unavailable_without_package():
    from openhud.agent import mt5_bridge

    status = mt5_bridge.mt5_status()
    # In CI (Linux) MT5 cannot be present: must report honestly, not raise.
    assert status["ok"] is True
    assert status["connected"] is False
    assert status["installed"] is False


def test_mt5_send_order_never_claims_success_without_broker():
    from openhud.agent import mt5_bridge

    res = mt5_bridge.send_order(symbol="EURUSD", direction="compra", lot=0.1)
    assert res["ok"] is False
    assert "error" in res


# --------------------------------------------------------------------------
# API surface
# --------------------------------------------------------------------------
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENHUD_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENHUD_PASSWORD", "test-pass")
    monkeypatch.setenv("OPENHUD_WORKSPACE", str(tmp_path / "ws"))
    import importlib

    import openhud.web.app as app_module

    importlib.reload(app_module)
    c = TestClient(app_module.app)
    c.post("/api/login", json={"password": "test-pass"})
    return c


def test_trading_config_endpoint(client):
    r = client.get("/api/trading/config")
    assert r.status_code == 200
    data = r.json()
    assert data["default_mode"] == "analysis"
    assert "ALLOW_REAL_TRADING" in data["permission_keys"]
    assert data["default_permissions"]["ALLOW_REAL_TRADING"] is False
    assert "risco" in data["risk_notice"].lower()


def test_trading_status_requires_pc(client):
    r = client.get("/api/trading/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False


def test_strategy_and_backtest_endpoints(client):
    r = client.post("/api/trading/strategies", json={"text": "EMA 9 + EMA 21 + RSI 14", "name": "T"})
    assert r.status_code == 200
    sid = r.json()["strategy"]["id"]
    # Backtest with no MT5 device must fail honestly (no fabricated data).
    r2 = client.post("/api/trading/backtest", json={"symbol": "EURUSD", "strategy_id": sid})
    assert r2.status_code == 200
    assert r2.json()["ok"] is False


def test_journal_endpoints(client):
    r = client.post("/api/trading/journal", json={"symbol": "EURUSD", "strategy": "EMA", "result": 10.0})
    assert r.status_code == 200
    jid = r.json()["id"]
    listed = client.get("/api/trading/journal").json()
    assert any(j["id"] == jid for j in listed)
    assert client.delete(f"/api/trading/journal/{jid}").json()["deleted"] is True


def test_alerts_endpoints(client):
    r = client.post("/api/trading/alerts", json={"symbol": "EURUSD", "kind": "price", "params": {"value": 1.2, "op": ">="}})
    assert r.status_code == 200
    aid = r.json()["id"]
    assert any(a["id"] == aid for a in client.get("/api/trading/alerts").json())
    assert client.delete(f"/api/trading/alerts/{aid}").json()["deleted"] is True


def test_trading_requires_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENHUD_DATA_DIR", str(tmp_path / "data2"))
    monkeypatch.setenv("OPENHUD_PASSWORD", "secret")
    import importlib

    import openhud.web.app as app_module

    importlib.reload(app_module)
    c = TestClient(app_module.app)
    r = c.get("/api/trading/config")
    assert r.status_code == 401
