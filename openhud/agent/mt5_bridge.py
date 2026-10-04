"""MetaTrader 5 bridge — runs on the user's PC, never on the server.

The ``MetaTrader5`` Python package is imported lazily so the agent works fine
when MT5 is not installed. Every function returns ``{"ok": False, "error": ...}``
when the terminal or the account is unavailable; no value is ever invented.

Only the local MT5 terminal API is used. Trading account passwords are never
collected or stored — the terminal keeps the session.
"""
from __future__ import annotations

import platform
from typing import Any

# Timeframes exposed to the user (spec item 46).
TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]


def _mt5():
    """Import MetaTrader5 or raise a clear, catchable error."""
    try:
        import MetaTrader5 as mt5  # type: ignore
    except Exception as exc:  # not installed / wrong OS
        raise RuntimeError(
            "O pacote MetaTrader5 não está instalado neste PC "
            f"({type(exc).__name__}). Instale com: pip install MetaTrader5 "
            "(somente Windows)."
        ) from exc
    return mt5


def _tf(mt5, name: str):
    mapping = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
        "W1": mt5.TIMEFRAME_W1,
        "MN1": mt5.TIMEFRAME_MN1,
    }
    if name not in mapping:
        raise ValueError(f"Timeframe inválido: {name}")
    return mapping[name]


def mt5_status() -> dict[str, Any]:
    """Detect MT5 installation, terminal and account connection."""
    if platform.system() != "Windows":
        return {
            "ok": True,
            "installed": False,
            "terminal": False,
            "connected": False,
            "platform": platform.system(),
            "note": "A integração MT5 requer Windows; este PC não é Windows.",
        }
    try:
        mt5 = _mt5()
    except RuntimeError as exc:
        return {"ok": True, "installed": False, "terminal": False, "connected": False, "note": str(exc)}
    try:
        initialized = mt5.initialize()
        if not initialized:
            return {
                "ok": True, "installed": True, "terminal": False, "connected": False,
                "note": f"Terminal MT5 não respondeu: {mt5.last_error()}",
            }
        info = mt5.terminal_info()
        acc = mt5.account_info()
        return {
            "ok": True,
            "installed": True,
            "terminal": bool(info and info.connected),
            "connected": acc is not None,
            "company": getattr(info, "company", None),
            "name": getattr(info, "name", None),
            "build": getattr(info, "build", None),
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def account_info() -> dict[str, Any]:
    try:
        mt5 = _mt5()
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}
    if not mt5.initialize():
        return {"ok": False, "error": f"Não consigo acessar os dados do MT5 neste momento ({mt5.last_error()})."}
    acc = mt5.account_info()
    if acc is None:
        return {"ok": False, "error": "Nenhuma conta conectada no terminal MT5."}
    return {
        "ok": True,
        "data": {
            "login": acc.login,
            "server": acc.server,
            "broker": acc.company,
            "currency": acc.currency,
            "leverage": acc.leverage,
            "balance": acc.balance,
            "equity": acc.equity,
            "margin": acc.margin,
            "margin_free": acc.margin_free,
            "margin_level": acc.margin_level,
            "profit": acc.profit,
            "trade_allowed": bool(getattr(acc, "trade_allowed", False)),
        },
    }


def symbol_info(symbol: str) -> dict[str, Any]:
    try:
        mt5 = _mt5()
        if not mt5.initialize():
            return {"ok": False, "error": "MT5 indisponível."}
        mt5.symbol_select(symbol, True)
        s = mt5.symbol_info(symbol)
        if s is None:
            return {"ok": False, "error": f"Símbolo '{symbol}' não encontrado no MT5."}
        tick = mt5.symbol_info_tick(symbol)
        market_open = bool(tick and tick.bid and tick.ask)
        return {
            "ok": True,
            "data": {
                "symbol": symbol,
                "digits": s.digits,
                "point": s.point,
                "spread": s.spread,
                "trade_allowed": bool(getattr(s, "trade_mode", 0) != 0),
                "volume_min": s.volume_min,
                "volume_step": s.volume_step,
                "volume_max": s.volume_max,
                "contract_size": s.trade_contract_size,
                "bid": getattr(tick, "bid", None) if tick else None,
                "ask": getattr(tick, "ask", None) if tick else None,
                "market_open": market_open,
            },
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def rates(symbol: str, timeframe: str = "M15", count: int = 300) -> dict[str, Any]:
    try:
        mt5 = _mt5()
        if not mt5.initialize():
            return {"ok": False, "error": "MT5 indisponível."}
        mt5.symbol_select(symbol, True)
        data = mt5.copy_rates_from_pos(symbol, _tf(mt5, timeframe), 0, int(count))
        if data is None or len(data) == 0:
            return {"ok": False, "error": f"Sem dados históricos para {symbol} {timeframe}."}
        closes = [float(r["close"]) for r in data]
        return {
            "ok": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "data": {
                "time": [int(r["time"]) for r in data],
                "open": [float(r["open"]) for r in data],
                "high": [float(r["high"]) for r in data],
                "low": [float(r["low"]) for r in data],
                "closes": closes,
                "volumes": [float(r["tick_volume"]) for r in data],
            },
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def positions() -> dict[str, Any]:
    try:
        mt5 = _mt5()
        if not mt5.initialize():
            return {"ok": False, "error": "MT5 indisponível."}
        pos = mt5.positions_get()
        if pos is None:
            return {"ok": True, "data": []}
        return {
            "ok": True,
            "data": [
                {
                    "ticket": p.ticket, "symbol": p.symbol,
                    "direction": "compra" if p.type == mt5.POSITION_TYPE_BUY else "venda",
                    "volume": p.volume, "price_open": p.price_open, "price_current": p.price_current,
                    "sl": p.sl, "tp": p.tp, "profit": p.profit, "comment": p.comment,
                }
                for p in pos
            ],
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def orders() -> dict[str, Any]:
    try:
        mt5 = _mt5()
        if not mt5.initialize():
            return {"ok": False, "error": "MT5 indisponível."}
        pending = mt5.orders_get()
        if pending is None:
            return {"ok": True, "data": []}
        return {
            "ok": True,
            "data": [
                {"ticket": o.ticket, "symbol": o.symbol, "volume": o.volume,
                 "price_open": o.price_open, "sl": o.sl, "tp": o.tp, "comment": o.comment}
                for o in pending
            ],
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def send_order(
    *,
    symbol: str,
    direction: str,
    lot: float,
    stop: float | None = None,
    take: float | None = None,
    comment: str = "OpenHUD",
    deviation: int = 20,
    magic: int = 20261004,
) -> dict[str, Any]:
    """Submit a market order. Only reachable after the server-side permission and
    risk checks. Returns the broker's real result; never claims success without a
    confirmation from MT5."""
    try:
        mt5 = _mt5()
        if not mt5.initialize():
            return {"ok": False, "error": "MT5 indisponível; ordem não enviada."}
        mt5.symbol_select(symbol, True)
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return {"ok": False, "error": f"Sem cotação para {symbol}; ordem não enviada."}
        if direction not in ("compra", "venda"):
            return {"ok": False, "error": "Direção inválida."}
        price = tick.ask if direction == "compra" else tick.bid
        order_type = mt5.ORDER_TYPE_BUY if direction == "compra" else mt5.ORDER_TYPE_SELL
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lot),
            "type": order_type,
            "price": price,
            "deviation": deviation,
            "magic": magic,
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if stop:
            request["sl"] = float(stop)
        if take:
            request["tp"] = float(take)
        result = mt5.order_send(request)
        if result is None:
            return {"ok": False, "error": f"Ordem rejeitada sem resposta do MT5 ({mt5.last_error()})."}
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {
                "ok": False,
                "retcode": result.retcode,
                "error": f"Ordem não confirmada pelo MT5 (retcode {result.retcode}: {result.comment}).",
                "request": {k: request[k] for k in ("symbol", "volume", "price")},
            }
        return {
            "ok": True,
            "confirmed": True,
            "order": result.order,
            "deal": result.deal,
            "price": result.price,
            "volume": result.volume,
            "retcode": result.retcode,
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def close_position(ticket: int) -> dict[str, Any]:
    try:
        mt5 = _mt5()
        if not mt5.initialize():
            return {"ok": False, "error": "MT5 indisponível."}
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return {"ok": False, "error": f"Posição {ticket} não encontrada."}
        p = pos[0]
        tick = mt5.symbol_info_tick(p.symbol)
        if tick is None:
            return {"ok": False, "error": "Sem cotação para fechar a posição."}
        close_type = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask
        request = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": p.volume,
            "type": close_type, "position": ticket, "price": price, "deviation": 20,
            "magic": 20261004, "comment": "OpenHUD close", "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code = getattr(result, "retcode", "?")
            return {"ok": False, "error": f"Fechamento não confirmado pelo MT5 (retcode {code})."}
        return {"ok": True, "confirmed": True, "ticket": ticket, "price": result.price}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
