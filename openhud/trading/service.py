"""Server-side trading service: orchestration between the site, the hub and MT5.

This layer never talks to MT5 directly. It sends commands to the connected PC
agent through the hub and applies the server-side policy: permissions, trading
mode, risk limits, emergency stop, order idempotency and audit.

Everything returns a structured result with an explicit ``ok`` flag. When MT5 is
unreachable the error is propagated verbatim — the model and the UI are never
allowed to present invented market data as real.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from ..core.agent_hub import get_hub
from . import alerts as alerts_mod
from . import analysis as analysis_mod
from . import core
from .store import TradingStore

TIMEFRAME_LADDER = ["M5", "M15", "H1", "H4"]


class TradingService:
    def __init__(self, store: TradingStore, audit_user: str = "web") -> None:
        self.store = store
        self.audit_user = audit_user

    # -- helpers ---------------------------------------------------------
    def _hub(self):
        return get_hub()

    def _request(self, device_id: str, command: str, args: dict[str, Any], timeout: float = 25.0) -> dict[str, Any]:
        """Call the PC agent. Raises nothing for expected failures; returns ok=False."""
        try:
            result = self._hub().request(device_id, command, args, timeout=timeout)
        except KeyError:
            return {"ok": False, "error": "Dispositivo não encontrado."}
        except PermissionError as exc:
            return {"ok": False, "error": str(exc), "blocked": True}
        except TimeoutError as exc:
            return {"ok": False, "error": str(exc)}
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}
        return result

    def resolve_mt5_device(self, device_id: str | None = None) -> str | None:
        """Return the device that should serve MT5 data (prefers a connected PC)."""
        devices = self._hub().list_devices()
        if device_id:
            return device_id
        online = [d for d in devices if d["id"] != "local" and d["online"]]
        others = [d for d in devices if d["id"] != "local"]
        chosen = online or others
        return chosen[0]["id"] if chosen else None

    # -- market data -----------------------------------------------------
    def status(self, device_id: str | None = None) -> dict[str, Any]:
        device_id = self.resolve_mt5_device(device_id)
        if device_id is None:
            return {"ok": False, "connected": False, "error": "Nenhum PC conectado para acessar o MT5."}
        res = self._request(device_id, "mt5_status", {})
        if not res.get("ok"):
            return {"ok": False, "connected": False, "device_id": device_id, "error": res.get("error")}
        data = res.get("data") or {}
        self._hub().record_mt5_status(device_id, data)
        return {"ok": True, "device_id": device_id, **data}

    def account(self, device_id: str | None = None) -> dict[str, Any]:
        device_id = self.resolve_mt5_device(device_id)
        if device_id is None:
            return {"ok": False, "error": "Nenhum PC conectado para acessar o MT5."}
        res = self._request(device_id, "mt5_account", {})
        if not res.get("ok"):
            return {"ok": False, "device_id": device_id, "error": res.get("error")}
        return {"ok": True, "device_id": device_id, "account": res.get("data")}

    def symbol(self, symbol: str, device_id: str | None = None) -> dict[str, Any]:
        device_id = self.resolve_mt5_device(device_id)
        if device_id is None:
            return {"ok": False, "error": "Nenhum PC conectado para acessar o MT5."}
        res = self._request(device_id, "mt5_symbol", {"symbol": symbol})
        if not res.get("ok"):
            return {"ok": False, "device_id": device_id, "error": res.get("error")}
        return {"ok": True, "device_id": device_id, "symbol": res.get("data")}

    def rates(self, symbol: str, timeframe: str = "M15", count: int = 300,
              device_id: str | None = None) -> dict[str, Any]:
        device_id = self.resolve_mt5_device(device_id)
        if device_id is None:
            return {"ok": False, "error": "Nenhum PC conectado para acessar o MT5."}
        res = self._request(device_id, "mt5_rates",
                            {"symbol": symbol, "timeframe": timeframe, "count": count}, timeout=30.0)
        if not res.get("ok"):
            return {"ok": False, "device_id": device_id, "error": res.get("error")}
        return {"ok": True, "device_id": device_id, "symbol": symbol, "timeframe": timeframe,
                "data": res.get("data")}

    def positions(self, device_id: str | None = None) -> dict[str, Any]:
        device_id = self.resolve_mt5_device(device_id)
        if device_id is None:
            return {"ok": False, "error": "Nenhum PC conectado para acessar o MT5."}
        res = self._request(device_id, "mt5_positions", {})
        if not res.get("ok"):
            return {"ok": False, "device_id": device_id, "error": res.get("error")}
        return {"ok": True, "device_id": device_id, "positions": res.get("data") or []}

    def pending_orders(self, device_id: str | None = None) -> dict[str, Any]:
        device_id = self.resolve_mt5_device(device_id)
        if device_id is None:
            return {"ok": False, "error": "Nenhum PC conectado para acessar o MT5."}
        res = self._request(device_id, "mt5_orders", {})
        if not res.get("ok"):
            return {"ok": False, "device_id": device_id, "error": res.get("error")}
        return {"ok": True, "device_id": device_id, "orders": res.get("data") or []}

    # -- analysis --------------------------------------------------------
    def analyse(self, symbol: str, timeframe: str = "M15", count: int = 300,
                device_id: str | None = None, multi: bool = False) -> dict[str, Any]:
        if not multi:
            r = self.rates(symbol, timeframe, count, device_id)
            if not r.get("ok"):
                return r
            result = analysis_mod.analyse_timeframe(r["data"])
            if not result.get("ok"):
                return {"ok": False, "error": result.get("error")}
            sym = self.symbol(symbol, device_id)
            spread = (sym.get("symbol") or {}).get("spread") if sym.get("ok") else None
            result["symbol"] = symbol
            result["timeframe"] = timeframe
            result["context"] = analysis_mod.context_summary(result, spread=spread)
            return {"ok": True, "device_id": r["device_id"], **result}

        frames: dict[str, dict[str, Any]] = {}
        for tf in TIMEFRAME_LADDER:
            r = self.rates(symbol, tf, count, device_id)
            if r.get("ok"):
                frames[tf] = r["data"]
        if not frames:
            return {"ok": False, "error": "Não consigo acessar os dados do MT5 neste momento."}
        combined = analysis_mod.multi_timeframe(frames)
        # Detail for the entry timeframe (first available).
        detail_tf = next((tf for tf in TIMEFRAME_LADDER if tf in frames), None)
        detail = analysis_mod.analyse_timeframe(frames[detail_tf]) if detail_tf else {"ok": False}
        return {"ok": True, "symbol": symbol, "multi_timeframe": combined,
                "detail": detail, "detail_timeframe": detail_tf}

    # -- strategies ------------------------------------------------------
    def parse_and_save(self, text: str, name: str | None = None, timeframe: str = "M15") -> dict[str, Any]:
        strat = core.parse_strategy(text, name=name, timeframe=timeframe)
        saved = self.store.save_strategy(strat.to_dict())
        return {"ok": True, "strategy": saved, "interpreted": strat.to_dict()}

    def list_strategies(self) -> list[dict[str, Any]]:
        return self.store.list_strategies()

    def backtest(self, strategy: dict[str, Any], symbol: str, timeframe: str = "M15",
                 count: int = 500, device_id: str | None = None,
                 initial_balance: float = 10_000.0, risk_pct: float = 1.0) -> dict[str, Any]:
        r = self.rates(symbol, timeframe, count, device_id)
        if not r.get("ok"):
            return r
        strat = core.Strategy.from_dict(strategy)
        result = core.run_backtest(r["data"], strat, initial_balance=initial_balance, risk_pct=risk_pct)
        if not result.get("ok"):
            return result
        return {"ok": True, "symbol": symbol, "timeframe": timeframe, **result}

    # -- paper trading ---------------------------------------------------
    def _paper_key(self, device_id: str) -> str:
        return f"paper_{device_id}"

    def paper_account(self, device_id: str | None = None) -> dict[str, Any]:
        device_id = self.resolve_mt5_device(device_id) or "default"
        raw = self.store.get_setting(self._paper_key(device_id)) or {}
        acc = core.PaperAccount(
            balance=raw.get("balance", 10_000.0), equity=raw.get("equity", 10_000.0),
            positions=raw.get("positions", []), closed=raw.get("closed", []),
            peak_equity=raw.get("peak_equity", 10_000.0), max_drawdown_pct=raw.get("max_drawdown_pct", 0.0),
        )
        return {"ok": True, "device_id": device_id, "account": acc}

    def _save_paper(self, device_id: str, acc: core.PaperAccount) -> None:
        self.store.set_setting(self._paper_key(device_id), {
            "balance": acc.balance, "equity": acc.equity, "positions": acc.positions,
            "closed": acc.closed, "peak_equity": acc.peak_equity,
            "max_drawdown_pct": acc.max_drawdown_pct,
        })

    def paper_open(self, *, symbol: str, direction: str, entry: float, lot: float,
                   stop: float | None = None, take: float | None = None,
                   device_id: str | None = None) -> dict[str, Any]:
        device_id = self.resolve_mt5_device(device_id) or "default"
        acc = self.paper_account(device_id)["account"]
        res = acc.open_position(symbol=symbol, direction=direction, entry=entry, lot=lot, stop=stop, take=take)
        if res.get("ok"):
            self._save_paper(device_id, acc)
            self.store.add_audit({"action": "paper_open", "device_id": device_id, "symbol": symbol,
                                  "result": "ok", "order": res["position"]})
        return res

    def paper_close(self, position_id: str, price: float, device_id: str | None = None) -> dict[str, Any]:
        device_id = self.resolve_mt5_device(device_id) or "default"
        acc = self.paper_account(device_id)["account"]
        res = acc.close_position(position_id, price)
        if res.get("ok"):
            self._save_paper(device_id, acc)
            self.store.add_audit({"action": "paper_close", "device_id": device_id, "result": "ok"})
        return res

    # -- alerts ----------------------------------------------------------
    def evaluate_alerts(self, device_id: str | None = None) -> dict[str, Any]:
        device_id = self.resolve_mt5_device(device_id)
        if device_id is None:
            return {"ok": False, "error": "Nenhum PC conectado para avaliar alertas."}
        results = []
        for alert in self.store.list_alerts():
            if not alert.get("enabled"):
                continue
            r = self.rates(alert["symbol"], alert.get("timeframe", "M15"), 200, device_id)
            if not r.get("ok"):
                results.append({**alert, "triggered": False, "error": r.get("error")})
                continue
            ev = alerts_mod.evaluate_alert(alert, r["data"])
            if ev.get("triggered"):
                self.store.mark_alert_triggered(alert["id"])
                self.store.add_audit({"action": "alert_triggered", "device_id": device_id,
                                      "symbol": alert["symbol"], "result": ev.get("reason", "")})
            results.append({**alert, **ev})
        return {"ok": True, "device_id": device_id, "alerts": results}

    # -- order execution (idempotent, guarded) ---------------------------
    def prepare_order(
        self, *, device_id: str, symbol: str, direction: str, risk_pct: float,
        entry: float, stop: float, take: float | None, request_id: str | None = None,
        strategy_name: str = "", reason: str = "",
    ) -> dict[str, Any]:
        """Compute lot and validate limits without sending anything.

        Returns the full order preview (spec item 56) or an explicit error.
        """
        dev = self._hub().get_device(device_id)
        if dev is None:
            return {"ok": False, "error": "Dispositivo não encontrado."}
        if dev.emergency_stop:
            return {"ok": False, "error": "STOP TRADING ativo: novas ordens estão bloqueadas."}
        acct = self.account(device_id)
        if not acct.get("ok"):
            return acct
        acc = acct["account"]
        limits = core.RiskLimits.from_dict(dev.risk_limits)
        sizing = core.compute_risk(
            balance=acc["balance"], equity=acc["equity"], risk_pct=risk_pct,
            entry=entry, stop=stop, take=take,
            max_lot=limits.max_lot,
        )
        if not sizing.get("ok"):
            return sizing
        hour = time.localtime().tm_hour
        trades_today = self.store.trades_today(device_id, dev.trading_mode)
        pos = self.positions(device_id)
        open_positions = len(pos.get("positions") or []) if pos.get("ok") else 0
        check = core.check_limits(
            limits, symbol=symbol, hour=hour, open_positions=open_positions,
            trades_today=trades_today, daily_pnl=acc.get("profit", 0.0) or 0.0,
            balance=acc["balance"], lot=sizing["lot"],
        )
        if not check["ok"]:
            return {"ok": False, "error": "Limites de risco violados.", "violations": check["violations"]}
        return {
            "ok": True,
            "request_id": request_id or uuid.uuid4().hex,
            "preview": {
                "symbol": symbol, "direction": direction, "entry": entry, "lot": sizing["lot"],
                "stop": stop, "take": take, "risk_amount": sizing["risk_amount"],
                "risk_actual": sizing["risk_actual"], "risk_actual_pct": sizing["risk_actual_pct"],
                "reward_risk": sizing["reward_risk"], "margin": acc.get("margin"),
                "margin_free": acc.get("margin_free"),
                "strategy": strategy_name, "reason": reason,
                "mode": dev.trading_mode, "warnings": sizing.get("warnings", []),
            },
            "violations": [],
        }

    def execute_order(
        self, *, device_id: str, symbol: str, direction: str, lot: float,
        stop: float | None, take: float | None, request_id: str,
        strategy_name: str = "", reason: str = "", confirmed: bool = False,
    ) -> dict[str, Any]:
        """Send an order to MT5. Idempotent on ``request_id``; real trading needs
        an explicit confirmation. Records an audit entry either way."""
        existing = self.store.get_order(request_id)
        if existing and existing.get("status") == "confirmed":
            return {"ok": True, "duplicate": True, "status": "confirmed", "response": existing.get("response")}

        dev = self._hub().get_device(device_id)
        if dev is None:
            return {"ok": False, "error": "Dispositivo não encontrado."}
        if dev.emergency_stop:
            self.store.add_audit({"action": "order_blocked", "device_id": device_id, "symbol": symbol,
                                  "error": "STOP TRADING", "request_id": request_id})
            return {"ok": False, "error": "STOP TRADING ativo: novas ordens estão bloqueadas."}
        mode = dev.trading_mode
        if mode not in ("demo", "real"):
            return {"ok": False, "error": f"Modo '{mode}' não permite ordens. Use DEMO ou REAL."}
        if mode == "real" and not confirmed:
            return {"ok": False, "error": "Operação real exige confirmação explícita.", "needs_confirmation": True}
        required = "ALLOW_REAL_TRADING" if mode == "real" else "ALLOW_DEMO_TRADING"
        if not dev.permissions.get(required, False):
            return {"ok": False, "error": f"Permissão {required} não concedida."}

        self.store.record_order({
            "request_id": request_id, "device_id": device_id, "symbol": symbol, "direction": direction,
            "lot": lot, "stop": stop, "take": take, "mode": mode, "status": "pending",
        })
        res = self._request(device_id, "mt5_send_order", {
            "symbol": symbol, "direction": direction, "lot": lot, "stop": stop, "take": take,
            "comment": f"OpenHUD {strategy_name}".strip(),
        }, timeout=40.0)

        status = "confirmed" if res.get("ok") and res.get("confirmed") else "failed"
        self.store.record_order({
            "request_id": request_id, "device_id": device_id, "symbol": symbol, "direction": direction,
            "lot": lot, "stop": stop, "take": take, "mode": mode, "status": status, "response": res,
        })
        self.store.add_audit({
            "action": "order_send", "device_id": device_id, "symbol": symbol, "permission": required,
            "order": {"symbol": symbol, "direction": direction, "lot": lot, "stop": stop, "take": take},
            "result": status, "error": res.get("error", ""), "request_id": request_id,
        })
        return {**res, "status": status, "mode": mode, "request_id": request_id}

    def close_position(self, device_id: str, ticket: int) -> dict[str, Any]:
        dev = self._hub().get_device(device_id)
        if dev is None:
            return {"ok": False, "error": "Dispositivo não encontrado."}
        if not dev.permissions.get("ALLOW_ORDER_CLOSE", False):
            return {"ok": False, "error": "Permissão ALLOW_ORDER_CLOSE não concedida."}
        res = self._request(device_id, "mt5_close_position", {"ticket": ticket}, timeout=40.0)
        self.store.add_audit({
            "action": "order_close", "device_id": device_id, "permission": "ALLOW_ORDER_CLOSE",
            "result": "ok" if res.get("ok") else "failed", "error": res.get("error", ""),
        })
        return res

    # -- briefs & opportunity scan --------------------------------------
    def daily_brief(self, symbols: list[str], timeframe: str = "M15",
                    device_id: str | None = None) -> dict[str, Any]:
        device_id = self.resolve_mt5_device(device_id)
        if device_id is None:
            return {"ok": False, "error": "Nenhum PC conectado para gerar o resumo."}
        entries = []
        for symbol in symbols:
            r = self.rates(symbol, timeframe, 250, device_id)
            if not r.get("ok"):
                entries.append({"symbol": symbol, "ok": False, "error": r.get("error")})
                continue
            a = analysis_mod.analyse_timeframe(r["data"])
            entries.append({
                "symbol": symbol, "ok": a.get("ok"),
                "trend": (a.get("trend") or {}).get("direction"),
                "volatility": (a.get("volatility") or {}).get("state"),
                "structure": (a.get("structure") or {}).get("structure"),
                "price": a.get("price"),
                "findings": [f["label"] for f in a.get("findings", [])],
            })
        opportunities = [e for e in entries if e.get("ok") and e.get("trend") in ("alta", "baixa")]
        return {
            "ok": True, "device_id": device_id, "timeframe": timeframe, "symbols": entries,
            "opportunities": opportunities,
            "note": None if opportunities else "Nenhuma configuração compatível encontrada.",
        }

    def quick_scan(self, symbols: list[str], strategy: dict[str, Any] | None = None,
                   timeframe: str = "M15", device_id: str | None = None) -> dict[str, Any]:
        """Quick trading assistant: check a shortlist and summarise what deserves
        attention, using a saved strategy when supplied."""
        device_id = self.resolve_mt5_device(device_id)
        if device_id is None:
            return {"ok": False, "error": "Nenhum PC conectado para a varredura."}
        found = []
        for symbol in symbols:
            r = self.rates(symbol, timeframe, 300, device_id)
            if not r.get("ok"):
                continue
            if strategy:
                sig = core.evaluate_strategy(core.Strategy.from_dict(strategy), r["data"])
                if sig.get("ok") and sig["signal"] != "neutro":
                    found.append({"symbol": symbol, "signal": sig["signal"], "price": sig["price"]})
            else:
                a = analysis_mod.analyse_timeframe(r["data"])
                if a.get("ok") and a.get("trend", {}).get("direction") in ("alta", "baixa"):
                    found.append({"symbol": symbol, "signal": a["trend"]["direction"], "price": a["price"]})
        return {
            "ok": True, "timeframe": timeframe, "found": found,
            "note": None if found else "Nenhuma configuração compatível encontrada.",
        }
