"""Technical indicators and price-action helpers — pure Python, no dependencies.

All functions take lists of floats ordered oldest→newest and return lists of the
same length, using ``None`` for positions that cannot be computed yet (instead
of silently dropping values). This keeps index alignment with candles so callers
never analyse the wrong bar.

The implementations follow the standard definitions; the model is told to use a
small, relevant set of indicators rather than dozens.
"""
from __future__ import annotations

from typing import Any, Iterable

Series = list[float]


def _clean(values: Iterable[Any]) -> Series:
    return [float(v) for v in values]


def sma(values: Series, period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if period <= 0:
        return out
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= period:
            running -= values[i - period]
        if i >= period - 1:
            out[i] = running / period
    return out


def ema(values: Series, period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    k = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(values: Series, period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain = gains / period
    avg_loss = losses / period
    out[period] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return out


def macd(values: Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict[str, list[float | None]]:
    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)
    line: list[float | None] = [
        (f - s) if f is not None and s is not None else None for f, s in zip(ema_fast, ema_slow)
    ]
    line_clean = [v if v is not None else 0.0 for v in line]
    sig_raw = ema(line_clean, signal)
    sig = [s if line[i] is not None else None for i, s in enumerate(sig_raw)]
    hist = [
        (line[i] - sig[i]) if line[i] is not None and sig[i] is not None else None
        for i in range(len(line))
    ]
    return {"macd": line, "signal": sig, "hist": hist}


def bollinger(values: Series, period: int = 20, mult: float = 2.0) -> dict[str, list[float | None]]:
    mid = sma(values, period)
    upper: list[float | None] = [None] * len(values)
    lower: list[float | None] = [None] * len(values)
    for i in range(len(values)):
        if mid[i] is None:
            continue
        window = values[i - period + 1 : i + 1]
        m = mid[i]
        var = sum((x - m) ** 2 for x in window) / period
        sd = var ** 0.5
        upper[i] = m + mult * sd
        lower[i] = m - mult * sd
    return {"middle": mid, "upper": upper, "lower": lower}


def atr(highs: Series, lows: Series, closes: Series, period: int = 14) -> list[float | None]:
    n = len(closes)
    tr: list[float] = [0.0] * n
    for i in range(n):
        if i == 0:
            tr[i] = highs[i] - lows[i]
        else:
            tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    out: list[float | None] = [None] * n
    if n < period:
        return out
    prev = sum(tr[:period]) / period
    out[period - 1] = prev
    for i in range(period, n):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def adx(highs: Series, lows: Series, closes: Series, period: int = 14) -> list[float | None]:
    n = len(closes)
    out: list[float | None] = [None] * n
    if n <= period * 2:
        return out
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    tr = [0.0] * n
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm[i] = up if (up > down and up > 0) else 0.0
        minus_dm[i] = down if (down > up and down > 0) else 0.0
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))

    def _wilder(series: list[float]) -> list[float | None]:
        res: list[float | None] = [None] * n
        if n < period:
            return res
        acc = sum(series[1 : period + 1])
        res[period] = acc
        for i in range(period + 1, n):
            acc = acc - acc / period + series[i]
            res[i] = acc
        return res

    tr_w = _wilder(tr)
    plus_w = _wilder(plus_dm)
    minus_w = _wilder(minus_dm)
    dx: list[float | None] = [None] * n
    for i in range(n):
        if tr_w[i] in (None, 0) or plus_w[i] is None or minus_w[i] is None:
            continue
        pdi = 100 * plus_w[i] / tr_w[i]
        mdi = 100 * minus_w[i] / tr_w[i]
        denom = pdi + mdi
        dx[i] = 0.0 if denom == 0 else 100 * abs(pdi - mdi) / denom
    first = next((i for i, v in enumerate(dx) if v is not None), None)
    if first is None:
        return out
    start = first + period - 1
    if start >= n:
        return out
    acc = sum(v for v in dx[first : start + 1] if v is not None)
    out[start] = acc / period
    for i in range(start + 1, n):
        if dx[i] is None:
            continue
        out[i] = (out[i - 1] * (period - 1) + dx[i]) / period if out[i - 1] is not None else dx[i]
    return out


def stochastic(
    highs: Series, lows: Series, closes: Series, k_period: int = 14, d_period: int = 3
) -> dict[str, list[float | None]]:
    n = len(closes)
    k: list[float | None] = [None] * n
    for i in range(k_period - 1, n):
        hh = max(highs[i - k_period + 1 : i + 1])
        ll = min(lows[i - k_period + 1 : i + 1])
        k[i] = 50.0 if hh == ll else 100 * (closes[i] - ll) / (hh - ll)
    k_clean = [v if v is not None else 0.0 for v in k]
    d_raw = sma(k_clean, d_period)
    d = [v if k[i] is not None else None for i, v in enumerate(d_raw)]
    return {"k": k, "d": d}


def vwap(highs: Series, lows: Series, closes: Series, volumes: Series) -> list[float | None]:
    n = len(closes)
    out: list[float | None] = [None] * n
    cum_pv = 0.0
    cum_v = 0.0
    for i in range(n):
        typical = (highs[i] + lows[i] + closes[i]) / 3
        vol = volumes[i] if i < len(volumes) else 0.0
        cum_pv += typical * vol
        cum_v += vol
        if cum_v > 0:
            out[i] = cum_pv / cum_v
    return out


def volume_profile(
    highs: Series, lows: Series, closes: Series, volumes: Series, bins: int = 24
) -> dict[str, Any]:
    """Approximate volume profile: volume by price bucket + point of control."""
    if not closes:
        return {"buckets": [], "poc": None, "value_area": None}
    lo = min(lows)
    hi = max(highs)
    if hi <= lo:
        return {"buckets": [], "poc": None, "value_area": None}
    size = (hi - lo) / bins
    buckets = [0.0] * bins
    for i in range(len(closes)):
        idx = min(bins - 1, int((closes[i] - lo) / size))
        vol = volumes[i] if i < len(volumes) else 1.0
        buckets[idx] += vol
    poc_idx = max(range(bins), key=lambda j: buckets[j])
    poc = lo + (poc_idx + 0.5) * size
    return {
        "buckets": [
            {"low": lo + j * size, "high": lo + (j + 1) * size, "volume": buckets[j]}
            for j in range(bins)
        ],
        "poc": poc,
        "value_area": {"low": lo, "high": hi},
    }


# --------------------------------------------------------------------------
# price action
# --------------------------------------------------------------------------
def swing_points(highs: Series, lows: Series, left: int = 2, right: int = 2) -> dict[str, list[dict[str, Any]]]:
    """Return confirmed swing highs/lows (fractals). No look-ahead: a swing is
    only confirmed ``right`` bars after it forms."""
    n = len(highs)
    sh: list[dict[str, Any]] = []
    sl: list[dict[str, Any]] = []
    for i in range(left, n - right):
        window_h = highs[i - left : i + right + 1]
        window_l = lows[i - left : i + right + 1]
        if highs[i] == max(window_h):
            sh.append({"index": i, "price": highs[i]})
        if lows[i] == min(window_l):
            sl.append({"index": i, "price": lows[i]})
    return {"highs": sh, "lows": sl}


def support_resistance(highs: Series, lows: Series, lookback: int = 60, max_levels: int = 5) -> dict[str, list[float]]:
    n = len(highs)
    start = max(0, n - lookback)
    swings = swing_points(highs[start:], lows[start:], left=2, right=2)
    resistances = sorted({round(p["price"], 6) for p in swings["highs"]}, reverse=True)[:max_levels]
    supports = sorted({round(p["price"], 6) for p in swings["lows"]})[:max_levels]
    return {"support": supports, "resistance": resistances}


def trend(closes: Series, fast: int = 20, slow: int = 50) -> dict[str, Any]:
    if len(closes) < slow:
        return {"direction": "indefinida", "reason": "histórico insuficiente"}
    f = sma(closes, fast)[-1]
    s = sma(closes, slow)[-1]
    if f is None or s is None:
        return {"direction": "indefinida", "reason": "histórico insuficiente"}
    if f > s * 1.001:
        return {"direction": "alta", "reason": f"SMA{fast} acima da SMA{slow}"}
    if f < s * 0.999:
        return {"direction": "baixa", "reason": f"SMA{fast} abaixo da SMA{slow}"}
    return {"direction": "lateral", "reason": "médias praticamente iguais"}


def volatility_state(atr_values: list[float | None], closes: Series, window: int = 50) -> dict[str, Any]:
    valid = [v for v in atr_values if v is not None]
    if not valid or not closes:
        return {"state": "indefinida", "atr": None}
    atr_now = valid[-1]
    recent = valid[-window:]
    avg = sum(recent) / len(recent)
    ratio = atr_now / avg if avg else 1.0
    if ratio > 1.4:
        state = "alta"
    elif ratio < 0.7:
        state = "baixa"
    else:
        state = "normal"
    return {"state": state, "atr": atr_now, "ratio": round(ratio, 2)}


def structure(highs: Series, lows: Series, closes: Series) -> dict[str, Any]:
    """Classify market structure from the last confirmed swings."""
    sw = swing_points(highs, lows)
    sh = sw["highs"][-3:]
    sl = sw["lows"][-3:]
    if len(sh) < 2 or len(sl) < 2:
        return {"structure": "indefinida", "detail": "poucos pivôs confirmados"}
    higher_highs = sh[-1]["price"] > sh[-2]["price"]
    higher_lows = sl[-1]["price"] > sl[-2]["price"]
    lower_highs = sh[-1]["price"] < sh[-2]["price"]
    lower_lows = sl[-1]["price"] < sl[-2]["price"]
    if higher_highs and higher_lows:
        return {"structure": "tendência de alta", "detail": "topos e fundos ascendentes"}
    if lower_highs and lower_lows:
        return {"structure": "tendência de baixa", "detail": "topos e fundos descendentes"}
    return {"structure": "consolidação", "detail": "estrutura sem direção clara"}


def detect_breakout(closes: Series, highs: Series, lows: Series, lookback: int = 20) -> dict[str, Any]:
    if len(closes) < lookback + 1:
        return {"detected": False, "reason": "histórico insuficiente"}
    prior_high = max(highs[-lookback - 1 : -1])
    prior_low = min(lows[-lookback - 1 : -1])
    last = closes[-1]
    if last > prior_high:
        return {"detected": True, "direction": "alta", "level": prior_high}
    if last < prior_low:
        return {"detected": True, "direction": "baixa", "level": prior_low}
    return {"detected": False, "reason": "preço dentro do intervalo recente"}
