"""Market analysis engine: turns raw OHLCV into an honest, structured read.

Combines a small, relevant set of indicators with price action and, when several
timeframes are supplied, a multi-timeframe summary. It never invents patterns:
each finding carries the concrete value it was derived from.
"""
from __future__ import annotations

from typing import Any

from . import indicators as ind


def _last(series: list[float | None]) -> float | None:
    for v in reversed(series):
        if v is not None:
            return v
    return None


def analyse_timeframe(data: dict[str, Any]) -> dict[str, Any]:
    """Analyse a single timeframe from parallel OHLCV lists."""
    closes = data.get("closes") or []
    highs = data.get("highs") or []
    lows = data.get("lows") or []
    volumes = data.get("volumes") or [0.0] * len(closes)
    if len(closes) < 30:
        return {"ok": False, "error": "Não há dados suficientes para uma análise confiável."}

    rsi14 = ind.rsi(closes, 14)
    ema9 = ind.ema(closes, 9)
    ema21 = ind.ema(closes, 21)
    macd = ind.macd(closes)
    bb = ind.bollinger(closes, 20, 2.0)
    atr14 = ind.atr(highs, lows, closes, 14)
    adx14 = ind.adx(highs, lows, closes, 14)
    stoch = ind.stochastic(highs, lows, closes)
    vw = ind.vwap(highs, lows, closes, volumes)
    sr = ind.support_resistance(highs, lows)
    tr = ind.trend(closes)
    struct = ind.structure(highs, lows, closes)
    vol = ind.volatility_state(atr14, closes)
    breakout = ind.detect_breakout(closes, highs, lows)
    vprofile = ind.volume_profile(highs, lows, closes, volumes)

    price = closes[-1]
    findings: list[dict[str, Any]] = []

    rsi_now = _last(rsi14)
    if rsi_now is not None:
        if rsi_now >= 70:
            findings.append({"kind": "rsi", "label": "RSI em sobrecompra",
                             "detail": f"RSI(14) = {rsi_now:.1f}", "bias": "baixa"})
        elif rsi_now <= 30:
            findings.append({"kind": "rsi", "label": "RSI em sobrevenda",
                             "detail": f"RSI(14) = {rsi_now:.1f}", "bias": "alta"})

    e9, e21 = _last(ema9), _last(ema21)
    if e9 is not None and e21 is not None:
        bias = "alta" if e9 > e21 else "baixa"
        findings.append({"kind": "ma", "label": f"EMA 9 {'acima' if e9 > e21 else 'abaixo'} da EMA 21",
                         "detail": f"EMA9={e9:.5f} EMA21={e21:.5f}", "bias": bias})

    hist = _last(macd["hist"])
    if hist is not None:
        findings.append({"kind": "macd", "label": f"MACD histograma {'positivo' if hist > 0 else 'negativo'}",
                         "detail": f"hist={hist:.5f}", "bias": "alta" if hist > 0 else "baixa"})

    adx_now = _last(adx14)
    if adx_now is not None:
        strength = "tendência forte" if adx_now >= 25 else ("tendência fraca" if adx_now >= 20 else "sem tendência definida")
        findings.append({"kind": "adx", "label": f"ADX indica {strength}",
                         "detail": f"ADX(14) = {adx_now:.1f}", "bias": "neutro"})

    k = _last(stoch["k"])
    if k is not None:
        if k >= 80:
            findings.append({"kind": "stoch", "label": "Estocástico em sobrecompra",
                             "detail": f"%K = {k:.1f}", "bias": "baixa"})
        elif k <= 20:
            findings.append({"kind": "stoch", "label": "Estocástico em sobrevenda",
                             "detail": f"%K = {k:.1f}", "bias": "alta"})

    upper, lower = _last(bb["upper"]), _last(bb["lower"])
    if upper is not None and lower is not None:
        pos = "acima da banda superior" if price > upper else ("abaixo da banda inferior" if price < lower else "dentro das bandas")
        findings.append({"kind": "bollinger", "label": f"Preço {pos}",
                         "detail": f"preço={price:.5f} bandas=[{lower:.5f}, {upper:.5f}]", "bias": "neutro"})

    if breakout.get("detected"):
        findings.append({"kind": "breakout",
                         "label": f"Rompimento de {breakout['direction']}",
                         "detail": f"nível {breakout['level']:.5f}", "bias": breakout["direction"]})

    if sr["support"] or sr["resistance"]:
        findings.append({"kind": "levels", "label": "Suportes/resistências identificados",
                         "detail": f"suportes={sr['support']} resistências={sr['resistance']}", "bias": "neutro"})

    if vprofile.get("poc"):
        findings.append({"kind": "volume_profile", "label": "Volume Profile (POC)",
                         "detail": f"preço de maior volume ≈ {vprofile['poc']:.5f}", "bias": "neutro"})

    findings.append({"kind": "trend", "label": f"Tendência: {tr['direction']}",
                     "detail": tr.get("reason", ""), "bias": tr["direction"] if tr["direction"] in ("alta", "baixa") else "neutro"})
    findings.append({"kind": "structure", "label": f"Estrutura: {struct['structure']}",
                     "detail": struct.get("detail", ""), "bias": "neutro"})
    findings.append({"kind": "volatility", "label": f"Volatilidade: {vol['state']}",
                     "detail": f"ATR(14)={vol.get('atr')}", "bias": "neutro"})

    return {
        "ok": True,
        "price": price,
        "indicators": {
            "rsi14": rsi_now, "ema9": e9, "ema21": e21,
            "macd": _last(macd["macd"]), "macd_signal": _last(macd["signal"]), "macd_hist": hist,
            "bb_upper": upper, "bb_lower": lower, "atr14": _last(atr14), "adx14": adx_now,
            "stoch_k": k, "vwap": _last(vw),
        },
        "support_resistance": sr,
        "volume_profile": vprofile,
        "trend": tr,
        "structure": struct,
        "volatility": vol,
        "breakout": breakout,
        "findings": findings,
        "bars": len(closes),
    }


def multi_timeframe(frames: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Combine several timeframes into a directional summary.

    Expected keys are timeframe names (M5, M15, H1, H4, ...). Each value is the
    parallel OHLCV dict for that timeframe.
    """
    per: dict[str, Any] = {}
    for tf, data in frames.items():
        result = analyse_timeframe(data)
        if result.get("ok"):
            per[tf] = {
                "trend": result["trend"]["direction"],
                "structure": result["structure"]["structure"],
                "rsi": result["indicators"]["rsi14"],
                "price": result["price"],
            }
    if not per:
        return {"ok": False, "error": "Não há dados suficientes para uma análise confiável."}

    votes = {"alta": 0, "baixa": 0, "lateral": 0, "indefinida": 0}
    for v in per.values():
        votes[v["trend"]] = votes.get(v["trend"], 0) + 1
    consensus = max(votes, key=lambda k: votes[k])
    aligned = votes[consensus] >= max(2, len(per) - 1)
    return {
        "ok": True,
        "per_timeframe": per,
        "votes": votes,
        "consensus": consensus,
        "aligned": aligned,
        "note": "Consenso entre timeframes." if aligned else "Timeframes divergentes; sem alinhamento claro.",
    }


def context_summary(analysis: dict[str, Any], spread: float | None = None, session: str | None = None) -> dict[str, Any]:
    """Assemble the context block the model should consider (spec item 60)."""
    if not analysis.get("ok"):
        return {"ok": False, "error": analysis.get("error", "Sem análise.")}
    missing: list[str] = []
    if spread is None:
        missing.append("spread")
    if session is None:
        missing.append("sessão")
    return {
        "ok": True,
        "timeframe_context": analysis.get("trend"),
        "volatility": analysis.get("volatility"),
        "spread": spread,
        "session": session,
        "structure": analysis.get("structure"),
        "missing": missing,
        "note": "Não há dados suficientes para uma análise confiável." if len(missing) > 1 else None,
    }
