"""Trading persistence: strategies, alerts, journal, audit, order idempotency.

Uses the generic ``execute``/``query`` helpers of the active database backend
(SQLite or Postgres), so the schema below works on both. Trading data is kept
strictly separate from general memory: it never mixes with the user's other
conversations (spec item 62).
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

SCHEMA = [
    "CREATE TABLE IF NOT EXISTS trading_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS trading_strategies (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, raw TEXT NOT NULL DEFAULT '',
        json TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS trading_alerts (
        id TEXT PRIMARY KEY, symbol TEXT NOT NULL, timeframe TEXT NOT NULL,
        kind TEXT NOT NULL, params TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
        created_at DOUBLE PRECISION NOT NULL, last_triggered DOUBLE PRECISION)""",
    """CREATE TABLE IF NOT EXISTS trading_journal (
        id TEXT PRIMARY KEY, ts DOUBLE PRECISION NOT NULL, symbol TEXT NOT NULL DEFAULT '',
        strategy TEXT NOT NULL DEFAULT '', setup TEXT NOT NULL DEFAULT '',
        entry DOUBLE PRECISION, exit DOUBLE PRECISION, result DOUBLE PRECISION,
        risk DOUBLE PRECISION, notes TEXT NOT NULL DEFAULT '', screenshot TEXT,
        ai_comment TEXT NOT NULL DEFAULT '', feedback TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS trading_audit (
        id TEXT PRIMARY KEY, ts DOUBLE PRECISION NOT NULL, user_id TEXT NOT NULL DEFAULT '',
        device_id TEXT NOT NULL DEFAULT '', action TEXT NOT NULL, symbol TEXT NOT NULL DEFAULT '',
        order_json TEXT, permission TEXT NOT NULL DEFAULT '', result TEXT NOT NULL DEFAULT '',
        error TEXT NOT NULL DEFAULT '', request_id TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS trading_orders (
        request_id TEXT PRIMARY KEY, ts DOUBLE PRECISION NOT NULL, device_id TEXT NOT NULL,
        symbol TEXT NOT NULL, direction TEXT NOT NULL, lot DOUBLE PRECISION, stop DOUBLE PRECISION,
        take DOUBLE PRECISION, mode TEXT NOT NULL, status TEXT NOT NULL, response TEXT)""",
    """CREATE TABLE IF NOT EXISTS trading_memory (
        id TEXT PRIMARY KEY, content TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '',
        created_at DOUBLE PRECISION NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_trading_audit_ts ON trading_audit(ts)",
    "CREATE INDEX IF NOT EXISTS idx_trading_journal_ts ON trading_journal(ts)",
]


def _new_id() -> str:
    return uuid.uuid4().hex


class TradingStore:
    def __init__(self, db) -> None:
        self.db = db
        self._init_schema()

    def _init_schema(self) -> None:
        for stmt in SCHEMA:
            try:
                self.db.execute(stmt)
            except Exception:
                # A concurrent create can race; ignore "already exists" style errors.
                pass

    # -- config ----------------------------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.db.query_one("SELECT value FROM trading_settings WHERE key=?", (key,))
        if row is None:
            return default
        try:
            return json.loads(dict(row)["value"])
        except (json.JSONDecodeError, TypeError):
            return default

    def set_setting(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO trading_settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )

    # -- strategies ------------------------------------------------------
    def save_strategy(self, strategy: dict[str, Any]) -> dict[str, Any]:
        sid = strategy.get("id") or _new_id()
        now = time.time()
        self.db.execute(
            "INSERT INTO trading_strategies(id, name, raw, json, created_at) VALUES(?, ?, ?, ?, ?)",
            (sid, strategy.get("name", "Estratégia"), strategy.get("raw", ""),
             json.dumps(strategy), now),
        )
        return {**strategy, "id": sid, "created_at": now}

    def list_strategies(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM trading_strategies ORDER BY created_at DESC")
        out = []
        for r in rows:
            d = dict(r)
            try:
                data = json.loads(d["json"])
            except (json.JSONDecodeError, KeyError):
                data = {}
            data["id"] = d["id"]
            data["created_at"] = d["created_at"]
            out.append(data)
        return out

    def get_strategy(self, sid: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM trading_strategies WHERE id=?", (sid,))
        if row is None:
            return None
        d = dict(row)
        try:
            data = json.loads(d["json"])
        except (json.JSONDecodeError, KeyError):
            data = {}
        data["id"] = d["id"]
        return data

    def delete_strategy(self, sid: str) -> None:
        self.db.execute("DELETE FROM trading_strategies WHERE id=?", (sid,))

    # -- alerts ----------------------------------------------------------
    def create_alert(self, alert: dict[str, Any]) -> dict[str, Any]:
        aid = _new_id()
        now = time.time()
        self.db.execute(
            "INSERT INTO trading_alerts(id, symbol, timeframe, kind, params, enabled, created_at) "
            "VALUES(?, ?, ?, ?, ?, 1, ?)",
            (aid, alert.get("symbol", ""), alert.get("timeframe", "M15"),
             alert.get("kind", "price"), json.dumps(alert.get("params") or {}), now),
        )
        return self.get_alert(aid)

    def get_alert(self, aid: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM trading_alerts WHERE id=?", (aid,))
        return self._alert_dict(row) if row else None

    def list_alerts(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM trading_alerts ORDER BY created_at DESC")
        return [self._alert_dict(r) for r in rows]

    @staticmethod
    def _alert_dict(row) -> dict[str, Any]:
        d = dict(row)
        try:
            d["params"] = json.loads(d.get("params") or "{}")
        except json.JSONDecodeError:
            d["params"] = {}
        d["enabled"] = bool(d.get("enabled"))
        return d

    def set_alert_enabled(self, aid: str, enabled: bool) -> None:
        self.db.execute("UPDATE trading_alerts SET enabled=? WHERE id=?", (1 if enabled else 0, aid))

    def mark_alert_triggered(self, aid: str) -> None:
        self.db.execute("UPDATE trading_alerts SET last_triggered=? WHERE id=?", (time.time(), aid))

    def delete_alert(self, aid: str) -> None:
        self.db.execute("DELETE FROM trading_alerts WHERE id=?", (aid,))

    # -- journal ---------------------------------------------------------
    def add_journal(self, entry: dict[str, Any]) -> dict[str, Any]:
        jid = _new_id()
        self.db.execute(
            "INSERT INTO trading_journal(id, ts, symbol, strategy, setup, entry, exit, result, risk, "
            "notes, screenshot, ai_comment, feedback) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (jid, entry.get("ts", time.time()), entry.get("symbol", ""), entry.get("strategy", ""),
             entry.get("setup", ""), entry.get("entry"), entry.get("exit"), entry.get("result"),
             entry.get("risk"), entry.get("notes", ""), entry.get("screenshot"),
             entry.get("ai_comment", ""), entry.get("feedback", "")),
        )
        return self.get_journal(jid)

    def get_journal(self, jid: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM trading_journal WHERE id=?", (jid,))
        return dict(row) if row else None

    def list_journal(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM trading_journal ORDER BY ts DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def update_journal(self, jid: str, patch: dict[str, Any]) -> None:
        allowed = {"symbol", "strategy", "setup", "entry", "exit", "result", "risk",
                   "notes", "screenshot", "ai_comment", "feedback"}
        fields = {k: v for k, v in patch.items() if k in allowed}
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE trading_journal SET {sets} WHERE id=?", (*fields.values(), jid))

    def delete_journal(self, jid: str) -> None:
        self.db.execute("DELETE FROM trading_journal WHERE id=?", (jid,))

    # -- audit -----------------------------------------------------------
    def add_audit(self, event: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO trading_audit(id, ts, user_id, device_id, action, symbol, order_json, "
            "permission, result, error, request_id) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_new_id(), event.get("ts", time.time()), event.get("user_id", ""),
             event.get("device_id", ""), event.get("action", ""), event.get("symbol", ""),
             json.dumps(event.get("order")) if event.get("order") is not None else None,
             event.get("permission", ""), event.get("result", ""), event.get("error", ""),
             event.get("request_id", "")),
        )

    def list_audit(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM trading_audit ORDER BY ts DESC LIMIT ?", (limit,))
        out = []
        for r in rows:
            d = dict(r)
            if d.get("order_json"):
                try:
                    d["order"] = json.loads(d["order_json"])
                except json.JSONDecodeError:
                    d["order"] = None
            d.pop("order_json", None)
            out.append(d)
        return out

    # -- order idempotency ----------------------------------------------
    def get_order(self, request_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM trading_orders WHERE request_id=?", (request_id,))
        if row is None:
            return None
        d = dict(row)
        if d.get("response"):
            try:
                d["response"] = json.loads(d["response"])
            except json.JSONDecodeError:
                pass
        return d

    def record_order(self, order: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO trading_orders(request_id, ts, device_id, symbol, direction, lot, stop, take, "
            "mode, status, response) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(request_id) DO UPDATE SET status=excluded.status, response=excluded.response",
            (order["request_id"], order.get("ts", time.time()), order.get("device_id", ""),
             order.get("symbol", ""), order.get("direction", ""), order.get("lot"),
             order.get("stop"), order.get("take"), order.get("mode", "analysis"),
             order.get("status", "pending"),
             json.dumps(order.get("response")) if order.get("response") is not None else None),
        )

    def trades_today(self, device_id: str, mode: str) -> int:
        start = time.time() - (time.time() % 86400)
        row = self.db.query_one(
            "SELECT COUNT(*) AS n FROM trading_orders WHERE device_id=? AND mode=? AND ts>=? AND status='confirmed'",
            (device_id, mode, start),
        )
        return int(dict(row)["n"]) if row else 0

    # -- private trading memory -----------------------------------------
    def add_memory(self, content: str, tags: str = "") -> dict[str, Any]:
        mid = _new_id()
        now = time.time()
        self.db.execute(
            "INSERT INTO trading_memory(id, content, tags, created_at) VALUES(?, ?, ?, ?)",
            (mid, content, tags, now),
        )
        return {"id": mid, "content": content, "tags": tags, "created_at": now}

    def list_memories(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.query("SELECT * FROM trading_memory ORDER BY created_at DESC")]

    def delete_memory(self, mid: str) -> None:
        self.db.execute("DELETE FROM trading_memory WHERE id=?", (mid,))
