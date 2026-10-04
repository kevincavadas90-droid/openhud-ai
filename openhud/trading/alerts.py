"""Alert engine: evaluate user-defined conditions against real market data.

Supported alert kinds (spec item 51): price, indicator, breakout, volatility,
spread and a custom strategy-condition alert. Evaluation is pure and returns
``triggered`` only when the condition is actually met on the supplied data.
"""
from __future__ import annotations

from typing import Any

from . import indicators as ind
from .core import Strategy, evaluate_strategy


def evaluate_alert(alert: dict[str, Any], data: dict[str, Any], *, spread: float | None = None) -> dict[str, Any]:
    kind = alert.get("kind")
    params = alert.get("params") or {}
    closes = data.get("closes") or []
    highs = data.get("highs") or []
    lows = data.get("lows") or []
    if not closes:
        return {"triggered": False, "reason": "sem dados"}

    if kind == "price":
        target = params.get("value")
        op = params.get("op", ">=")
        if target is None:
            return {"triggered": False, "reason": "alerta de preço sem valor"}
        price = closes[-1]
        hit = price >= target if op == ">=" else price <= target
        return {"triggered": hit, "observed": price, "target": target, "reason": f"preço {price} {op} {target}"}

    if kind == "indicator":
        name = params.get("indicator", "rsi")
        period = int(params.get("period", 14))
        op = params.get("op", "<")
        value = params.get("value")
        series = _indicator_series(name, period, data)
        if series is None or series[-1] is None:
            return {"triggered": False, "reason": f"indicador {name} indisponível"}
        obs = series[-1]
        if op == "<":
            hit = obs < value
        elif op == ">":
            hit = obs > value
        else:
            hit = obs == value
        return {"triggered": hit, "observed": obs, "target": value, "reason": f"{name}({period}) {obs:.2f} {op} {value}"}

    if kind == "breakout":
        lookback = int(params.get("lookback", 20))
        direction = params.get("direction", "alta")
        bo = ind.detect_breakout(closes, highs, lows, lookback)
        hit = bo.get("detected") and bo.get("direction") == direction
        return {"triggered": hit, "reason": f"rompimento de {direction} em {lookback} barras", "detail": bo}

    if kind == "volatility":
        atr_vals = ind.atr(highs, lows, closes, int(params.get("period", 14)))
        state = ind.volatility_state(atr_vals, closes)
        target = params.get("state", "alta")
        return {"triggered": state["state"] == target, "observed": state["state"], "reason": f"volatilidade {state['state']} (alvo {target})"}

    if kind == "spread":
        if spread is None:
            return {"triggered": False, "reason": "spread indisponível"}
        max_spread = params.get("max")
        hit = max_spread is not None and spread > max_spread
        return {"triggered": hit, "observed": spread, "reason": f"spread {spread} > {max_spread}"}

    if kind == "strategy":
        strat = Strategy.from_dict(params.get("strategy") or {})
        sig = evaluate_strategy(strat, data)
        if not sig.get("ok"):
            return {"triggered": False, "reason": sig.get("error", "sem dados")}
        want = params.get("signal", "compra")
        return {"triggered": sig["signal"] == want, "observed": sig["signal"], "reason": f"estratégia sinalizou {sig['signal']}"}

    return {"triggered": False, "reason": f"tipo de alerta desconhecido: {kind}"}


def _indicator_series(name: str, period: int, data: dict[str, Any]) -> list[float | None] | None:
    closes = data.get("closes") or []
    highs = data.get("highs") or []
    lows = data.get("lows") or []
    if name == "rsi":
        return ind.rsi(closes, period)
    if name == "sma":
        return ind.sma(closes, period)
    if name == "ema":
        return ind.ema(closes, period)
    if name == "atr":
        return ind.atr(highs, lows, closes, period)
    if name == "adx":
        return ind.adx(highs, lows, closes, period)
    if name == "macd":
        return ind.macd(closes).get("hist")
    if name == "stoch":
        return ind.stochastic(highs, lows, closes).get("k")
    return None
