"""Trading core: permissions, modes, risk, strategies, backtest and paper trading.

This module is deliberately free of MT5, FastAPI and network concerns so it can
be unit-tested directly. It answers one question per function and never returns
fabricated data: when inputs are missing it returns ``ok=False`` with an explicit
reason.
"""
from __future__ import annotations

import math
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

# --------------------------------------------------------------------------
# permissions & modes
# --------------------------------------------------------------------------
# Separate, explicit trading permissions (spec item 55). Real trading is OFF by
# default; closing positions is allowed because it reduces risk.
TRADING_PERMISSION_KEYS = [
    "ALLOW_MARKET_READ",
    "ALLOW_ANALYSIS",
    "ALLOW_ALERTS",
    "ALLOW_DEMO_TRADING",
    "ALLOW_REAL_TRADING",
    "ALLOW_ORDER_MODIFICATION",
    "ALLOW_ORDER_CLOSE",
]

DEFAULT_TRADING_PERMISSIONS: dict[str, bool] = {
    "ALLOW_MARKET_READ": True,
    "ALLOW_ANALYSIS": True,
    "ALLOW_ALERTS": True,
    "ALLOW_DEMO_TRADING": True,
    "ALLOW_REAL_TRADING": False,
    "ALLOW_ORDER_MODIFICATION": False,
    "ALLOW_ORDER_CLOSE": True,
}

# Operating modes. "analysis" is the default for new users (spec item 72).
MODES = ["learn", "analysis", "simulation", "demo", "real"]
DEFAULT_MODE = "analysis"

MODES_REQUIRING_PERMISSION = {
    "demo": "ALLOW_DEMO_TRADING",
    "real": "ALLOW_REAL_TRADING",
}


def utc_now() -> float:
    return time.time()


# --------------------------------------------------------------------------
# risk limits & risk engine
# --------------------------------------------------------------------------
@dataclass
class RiskLimits:
    max_risk_per_trade_pct: float = 1.0
    max_daily_loss_pct: float = 3.0
    max_trades_per_day: int = 10
    max_open_positions: int = 3
    max_lot: float = 1.0
    allowed_symbols: list[str] = field(default_factory=list)  # empty = any
    allowed_hours: list[int] = field(default_factory=list)  # empty = any
    allowed_strategies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RiskLimits":
        data = data or {}
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def compute_risk(
    *,
    balance: float,
    equity: float,
    risk_pct: float,
    entry: float,
    stop: float,
    lot_step: float = 0.01,
    min_lot: float = 0.01,
    max_lot: float = 100.0,
    contract_size: float = 100_000.0,
    tick_value: float | None = None,
    take: float | None = None,
) -> dict[str, Any]:
    """Position sizing and risk validation. Returns ``ok=False`` on bad inputs.

    Risk amount = balance * risk_pct / 100. Lot is derived from the stop distance
    and the instrument's value per price unit. Never increases lot after a loss
    (that is handled by the caller/limits, not here).
    """
    if balance <= 0 or equity <= 0:
        return {"ok": False, "error": "Saldo/equity inválidos (conta não conectada?)."}
    if risk_pct <= 0 or risk_pct > 100:
        return {"ok": False, "error": "Percentual de risco inválido."}
    if entry <= 0 or stop <= 0:
        return {"ok": False, "error": "Preços de entrada/stop inválidos."}
    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        return {"ok": False, "error": "Stop igual à entrada: risco indefinido."}

    risk_amount = balance * risk_pct / 100.0
    # Value of one lot for a 1.0 price move, in account currency.
    value_per_price = tick_value if tick_value else contract_size
    raw_lot = risk_amount / (stop_distance * value_per_price)
    step = lot_step if lot_step > 0 else 0.01
    # Round to the nearest step within a small tolerance so 0.2 does not become
    # 0.19 due to floating-point representation.
    steps = raw_lot / step
    lot = math.floor(steps + 1e-9) * step
    lot = max(min_lot, min(lot, max_lot))
    lot = round(lot, 2)

    risk_actual = lot * stop_distance * value_per_price
    rr = None
    if take is not None and take > 0:
        reward = abs(take - entry) * lot * value_per_price
        rr = round(reward / risk_actual, 2) if risk_actual else None

    warnings: list[str] = []
    if raw_lot < min_lot:
        warnings.append(
            "O risco configurado é menor que o lote mínimo do ativo; "
            "o lote mínimo já implica risco maior que o definido."
        )
    if risk_actual > risk_amount * 1.05:
        warnings.append("Risco efetivo acima do alvo (arredondamento para o lote mínimo).")

    return {
        "ok": True,
        "risk_amount": round(risk_amount, 2),
        "risk_actual": round(risk_actual, 2),
        "risk_actual_pct": round(risk_actual / balance * 100, 3),
        "lot": lot,
        "stop_distance": round(stop_distance, 6),
        "reward_risk": rr,
        "warnings": warnings,
    }


def check_limits(
    limits: RiskLimits,
    *,
    symbol: str,
    hour: int,
    open_positions: int,
    trades_today: int,
    daily_pnl: float,
    balance: float,
    lot: float,
) -> dict[str, Any]:
    """Validate a proposed trade against the user's limits. Returns the list of
    violations (empty = allowed). Never silently ignores a limit."""
    violations: list[str] = []
    if limits.allowed_symbols and symbol not in limits.allowed_symbols:
        violations.append(f"Ativo '{symbol}' fora da lista permitida.")
    if limits.allowed_hours and hour not in limits.allowed_hours:
        violations.append(f"Horário {hour}h fora da janela permitida.")
    if open_positions >= limits.max_open_positions:
        violations.append(f"Máximo de posições abertas atingido ({limits.max_open_positions}).")
    if trades_today >= limits.max_trades_per_day:
        violations.append(f"Máximo de operações por dia atingido ({limits.max_trades_per_day}).")
    if balance > 0 and daily_pnl <= -(balance * limits.max_daily_loss_pct / 100.0):
        violations.append("Limite de perda diária atingido — STOP automático.")
    if lot > limits.max_lot:
        violations.append(f"Lote {lot} acima do máximo permitido ({limits.max_lot}).")
    return {"ok": not violations, "violations": violations}


# --------------------------------------------------------------------------
# strategy representation & parsing
# --------------------------------------------------------------------------
@dataclass
class Condition:
    kind: str  # "indicator" | "cross"
    indicator: str
    period: int | None = None
    op: str = ">"  # ">", "<", ">=", "<=", "cross_above", "cross_below"
    value: float | None = None
    ref_indicator: str | None = None
    ref_period: int | None = None
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Condition":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


@dataclass
class Strategy:
    name: str
    raw: str
    entry_long: list[Condition] = field(default_factory=list)
    entry_short: list[Condition] = field(default_factory=list)
    exit: list[Condition] = field(default_factory=list)
    stop: dict[str, Any] = field(default_factory=lambda: {"type": "atr", "mult": 1.5})
    take: dict[str, Any] = field(default_factory=lambda: {"type": "atr", "mult": 3.0})
    filters: list[Condition] = field(default_factory=list)
    timeframe: str = "M15"
    symbols: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "raw": self.raw,
            "entry_long": [c.to_dict() for c in self.entry_long],
            "entry_short": [c.to_dict() for c in self.entry_short],
            "exit": [c.to_dict() for c in self.exit],
            "stop": self.stop,
            "take": self.take,
            "filters": [c.to_dict() for c in self.filters],
            "timeframe": self.timeframe,
            "symbols": self.symbols,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Strategy":
        data = data or {}
        return cls(
            name=data.get("name", "Estratégia"),
            raw=data.get("raw", ""),
            entry_long=[Condition.from_dict(c) for c in data.get("entry_long", [])],
            entry_short=[Condition.from_dict(c) for c in data.get("entry_short", [])],
            exit=[Condition.from_dict(c) for c in data.get("exit", [])],
            stop=data.get("stop") or {"type": "atr", "mult": 1.5},
            take=data.get("take") or {"type": "atr", "mult": 3.0},
            filters=[Condition.from_dict(c) for c in data.get("filters", [])],
            timeframe=data.get("timeframe", "M15"),
            symbols=data.get("symbols", []),
            notes=data.get("notes", []),
        )


_INDICATOR_ALIASES = {
    "ema": "ema",
    "sma": "sma",
    "média": "sma",
    "media": "sma",
    "rsi": "rsi",
    "macd": "macd",
    "bollinger": "bollinger",
    "bollinger bands": "bollinger",
    "atr": "atr",
    "adx": "adx",
    "stochastic": "stochastic",
    "estocástico": "stochastic",
    "vwap": "vwap",
}


def _find_indicators(text: str) -> list[tuple[str, int | None]]:
    found: list[tuple[str, int | None]] = []
    for m in re.finditer(r"(ema|sma|rsi|macd|atr|adx|stochastic|bollinger|vwap|média|media)\s*(\d+)?", text, re.I):
        name = m.group(1).lower()
        canonical = _INDICATOR_ALIASES.get(name)
        if canonical:
            period = int(m.group(2)) if m.group(2) else None
            found.append((canonical, period))
    return found


def parse_strategy(text: str, name: str | None = None, timeframe: str = "M15") -> Strategy:
    """Turn a natural-language description into structured rules.

    Supports the common forms ("EMA 9 + EMA 21 + RSI", "RSI abaixo de 30",
    "cruzamento de EMA 9 com EMA 21"). When a rule cannot be parsed it is kept as
    a note so the interpreted strategy is shown honestly instead of guessing.
    """
    raw = (text or "").strip()
    low = raw.lower()
    inds = _find_indicators(low)
    strat = Strategy(name=name or (raw[:40] or "Estratégia sem nome"), raw=raw, timeframe=timeframe)
    if not inds:
        strat.notes.append("Nenhum indicador reconhecido no texto; regras precisam ser definidas manualmente.")
        return strat

    periods = {name: [] for name in set(_INDICATOR_ALIASES.values())}
    mentioned: set[str] = set()
    for canon, period in inds:
        mentioned.add(canon)
        if period:
            periods.setdefault(canon, []).append(period)

    # Moving-average crossover: two EMAs/SMAs -> cross above for long, below for short.
    for ma in ("ema", "sma"):
        ps = sorted(set(periods.get(ma, [])))
        if len(ps) >= 2:
            fast, slow = ps[0], ps[1]
            strat.entry_long.append(Condition("cross", ma, fast, "cross_above", ref_indicator=ma, ref_period=slow,
                                              label=f"{ma.upper()} {fast} cruza acima de {ma.upper()} {slow}"))
            strat.entry_short.append(Condition("cross", ma, fast, "cross_below", ref_indicator=ma, ref_period=slow,
                                               label=f"{ma.upper()} {fast} cruza abaixo de {ma.upper()} {slow}"))

    # RSI thresholds / filter. Only when RSI was actually mentioned.
    if "rsi" in mentioned:
        p = (periods.get("rsi") or [14])[0]
        below = re.search(r"rsi[^\d]*(?:abaixo de|menor que|<)\s*(\d+)", low)
        above = re.search(r"rsi[^\d]*(?:acima de|maior que|>)\s*(\d+)", low)
        if below:
            strat.filters.append(Condition("indicator", "rsi", p, "<", value=float(below.group(1)),
                                           label=f"RSI {p} < {below.group(1)} (sobrevendido)"))
        elif above:
            strat.filters.append(Condition("indicator", "rsi", p, ">", value=float(above.group(1)),
                                           label=f"RSI {p} > {above.group(1)} (sobrecomprado)"))
        else:
            strat.filters.append(Condition("indicator", "rsi", p, ">", value=50.0,
                                           label=f"RSI {p} > 50 (confirmação de força)"))
        # RSI exit: opposite extreme.
        strat.exit.append(Condition("indicator", "rsi", p, ">", value=70.0, label=f"RSI {p} > 70 (saída compra)"))
        strat.exit.append(Condition("indicator", "rsi", p, "<", value=30.0, label=f"RSI {p} < 30 (saída venda)"))

    if "macd" in mentioned:
        strat.filters.append(Condition("indicator", "macd", None, ">", value=0.0, label="MACD acima de zero"))
    if "atr" in mentioned:
        p = (periods.get("atr") or [14])[0]
        strat.notes.append(f"ATR {p} disponível para dimensionar stop/take.")
    if "adx" in mentioned:
        p = (periods.get("adx") or [14])[0]
        strat.filters.append(Condition("indicator", "adx", p, ">", value=20.0, label=f"ADX {p} > 20 (tendência)"))

    if not strat.entry_long and not strat.entry_short:
        strat.notes.append("Não foi possível derivar uma regra de entrada; descreva o gatilho (ex.: 'EMA 9 cruza EMA 21').")
    return strat


# --------------------------------------------------------------------------
# strategy evaluation
# --------------------------------------------------------------------------
def _series_for(name: str, period: int | None, data: dict[str, Any]) -> list[float | None] | None:
    from . import indicators as ind

    closes = data.get("closes") or []
    highs = data.get("highs") or []
    lows = data.get("lows") or []
    volumes = data.get("volumes") or []
    if not closes:
        return None
    if name == "sma":
        return ind.sma(closes, period or 20)
    if name == "ema":
        return ind.ema(closes, period or 20)
    if name == "rsi":
        return ind.rsi(closes, period or 14)
    if name == "atr":
        return ind.atr(highs, lows, closes, period or 14)
    if name == "adx":
        return ind.adx(highs, lows, closes, period or 14)
    if name == "vwap":
        return ind.vwap(highs, lows, closes, volumes)
    if name == "macd":
        return ind.macd(closes).get("macd")
    return None


def _condition_met(cond: Condition, data: dict[str, Any], i: int) -> bool:
    left = _series_for(cond.indicator, cond.period, data)
    if left is None or i >= len(left) or left[i] is None:
        return False
    lv = left[i]
    if cond.kind == "cross":
        ref = _series_for(cond.ref_indicator or cond.indicator, cond.ref_period, data)
        if ref is None or i < 1 or i >= len(ref) or ref[i] is None or ref[i - 1] is None or left[i - 1] is None:
            return False
        prev = left[i - 1] - ref[i - 1]
        now = left[i] - ref[i]
        if cond.op == "cross_above":
            return prev <= 0 < now
        if cond.op == "cross_below":
            return prev >= 0 > now
        return False
    if cond.value is not None:
        rv = cond.value
    else:
        ref = _series_for(cond.ref_indicator or "", cond.ref_period, data)
        if ref is None or i >= len(ref) or ref[i] is None:
            return False
        rv = ref[i]
    if cond.op == ">":
        return lv > rv
    if cond.op == "<":
        return lv < rv
    if cond.op == ">=":
        return lv >= rv
    if cond.op == "<=":
        return lv <= rv
    return False


def evaluate_strategy(strategy: Strategy, data: dict[str, Any]) -> dict[str, Any]:
    """Evaluate the strategy on the latest closed bar of ``data``.

    ``data`` holds parallel lists: closes, highs, lows, volumes. Returns a signal
    with the conditions that matched, plus the risk framing. It does not execute
    anything.
    """
    closes = data.get("closes") or []
    if len(closes) < 5:
        return {"ok": False, "error": "Não há dados suficientes para uma análise confiável."}
    i = len(closes) - 1
    long_hits = [c for c in strategy.entry_long if _condition_met(c, data, i)]
    short_hits = [c for c in strategy.entry_short if _condition_met(c, data, i)]
    filter_hits = [c for c in strategy.filters if _condition_met(c, data, i)]

    long_ok = bool(strategy.entry_long) and len(long_hits) == len(strategy.entry_long) and len(filter_hits) == len(strategy.filters)
    short_ok = bool(strategy.entry_short) and len(short_hits) == len(strategy.entry_short) and len(filter_hits) == len(strategy.filters)

    if long_ok and not short_ok:
        signal = "compra"
    elif short_ok and not long_ok:
        signal = "venda"
    else:
        signal = "neutro"

    return {
        "ok": True,
        "signal": signal,
        "index": i,
        "price": closes[i],
        "matched": {
            "entry_long": [c.label for c in long_hits],
            "entry_short": [c.label for c in short_hits],
            "filters": [c.label for c in filter_hits],
        },
        "entry_long_rules": len(strategy.entry_long),
        "entry_short_rules": len(strategy.entry_short),
        "filter_rules": len(strategy.filters),
    }


# --------------------------------------------------------------------------
# backtest
# --------------------------------------------------------------------------
def _stop_take_levels(strategy: Strategy, data: dict[str, Any], i: int, entry: float, direction: str) -> tuple[float | None, float | None]:
    from . import indicators as ind

    stop = take = None
    if strategy.stop.get("type") == "atr":
        atr_vals = ind.atr(data["highs"], data["lows"], data["closes"], int(strategy.stop.get("period", 14)))
        av = atr_vals[i]
        if av:
            stop = entry - av * strategy.stop.get("mult", 1.5) * (1 if direction == "compra" else -1)
    elif strategy.stop.get("type") == "percent":
        pct = strategy.stop.get("value", 1.0) / 100.0
        stop = entry * (1 - pct) if direction == "compra" else entry * (1 + pct)
    if strategy.take.get("type") == "atr":
        atr_vals = ind.atr(data["highs"], data["lows"], data["closes"], int(strategy.take.get("period", 14)))
        av = atr_vals[i]
        if av:
            take = entry + av * strategy.take.get("mult", 3.0) * (1 if direction == "compra" else -1)
    elif strategy.take.get("type") == "percent":
        pct = strategy.take.get("value", 2.0) / 100.0
        take = entry * (1 + pct) if direction == "compra" else entry * (1 - pct)
    return stop, take


def run_backtest(
    data: dict[str, Any],
    strategy: Strategy,
    *,
    spread_points: float = 0.0,
    initial_balance: float = 10_000.0,
    risk_pct: float = 1.0,
) -> dict[str, Any]:
    """Backtest the strategy bar-by-bar on historical data (no look-ahead).

    Returns honest statistics. Historical results do not guarantee future ones.
    """
    closes = data.get("closes") or []
    highs = data.get("highs") or []
    lows = data.get("lows") or []
    if len(closes) < 60:
        return {"ok": False, "error": "Histórico insuficiente para backtest (mínimo ~60 barras)."}
    if not strategy.entry_long and not strategy.entry_short:
        return {"ok": False, "error": "A estratégia não tem regra de entrada definida."}

    balance = initial_balance
    peak = balance
    max_dd = 0.0
    trades: list[dict[str, Any]] = []
    wins: list[float] = []
    losses: list[float] = []
    consec_wins = consec_losses = 0
    max_consec_wins = max_consec_losses = 0

    i = 55
    while i < len(closes) - 1:
        window = {"closes": closes[: i + 1], "highs": highs[: i + 1], "lows": lows[: i + 1],
                  "volumes": (data.get("volumes") or [0] * len(closes))[: i + 1]}
        sig = evaluate_strategy(strategy, window)
        if not sig.get("ok") or sig["signal"] == "neutro":
            i += 1
            continue
        direction = sig["signal"]
        entry = closes[i]
        stop, take = _stop_take_levels(strategy, data, i, entry, direction)
        if stop is None or take is None:
            i += 1
            continue
        risk_dist = abs(entry - stop)
        if risk_dist <= 0:
            i += 1
            continue
        risk_amount = balance * risk_pct / 100.0
        lot = max(0.01, round(risk_amount / (risk_dist * 100_000.0), 2))

        # Walk forward to the exit bar (stop/take first-touch).
        result = 0.0
        exit_index = i
        for j in range(i + 1, len(closes)):
            exit_index = j
            if direction == "compra":
                if lows[j] <= stop:
                    result = (stop - entry) * lot * 100_000.0
                    break
                if highs[j] >= take:
                    result = (take - entry) * lot * 100_000.0
                    break
            else:
                if highs[j] >= stop:
                    result = (entry - stop) * lot * 100_000.0
                    break
                if lows[j] <= take:
                    result = (entry - take) * lot * 100_000.0
                    break
        else:
            result = (closes[-1] - entry) * lot * 100_000.0 * (1 if direction == "compra" else -1)

        result -= abs(spread_points) * lot * 100_000.0 * 0.5
        balance += result
        peak = max(peak, balance)
        max_dd = max(max_dd, (peak - balance) / peak * 100 if peak else 0.0)
        trade = {
            "entry_index": i, "exit_index": exit_index, "direction": direction,
            "entry": round(entry, 6), "stop": round(stop, 6), "take": round(take, 6),
            "lot": lot, "result": round(result, 2), "balance": round(balance, 2),
        }
        trades.append(trade)
        if result >= 0:
            wins.append(result)
            consec_wins += 1
            consec_losses = 0
            max_consec_wins = max(max_consec_wins, consec_wins)
        else:
            losses.append(result)
            consec_losses += 1
            consec_wins = 0
            max_consec_losses = max(max_consec_losses, consec_losses)
        i = exit_index + 1

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    net = sum(t["result"] for t in trades)
    n = len(trades)
    metrics = {
        "trades": n,
        "win_rate": round(len(wins) / n * 100, 2) if n else None,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else (None if not wins else float("inf")),
        "max_drawdown_pct": round(max_dd, 2),
        "net_result": round(net, 2),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "max_consec_wins": max_consec_wins,
        "max_consec_losses": max_consec_losses,
        "final_balance": round(balance, 2),
    }
    return {
        "ok": True,
        "metrics": metrics,
        "trades": trades[-200:],
        "disclaimer": "Resultados históricos não garantem resultados futuros.",
    }


# --------------------------------------------------------------------------
# paper trading / simulation
# --------------------------------------------------------------------------
@dataclass
class PaperAccount:
    balance: float = 10_000.0
    equity: float = 10_000.0
    positions: list[dict[str, Any]] = field(default_factory=list)
    closed: list[dict[str, Any]] = field(default_factory=list)
    peak_equity: float = 10_000.0
    max_drawdown_pct: float = 0.0

    def open_position(
        self, *, symbol: str, direction: str, entry: float, lot: float,
        stop: float | None = None, take: float | None = None,
    ) -> dict[str, Any]:
        if direction not in ("compra", "venda"):
            return {"ok": False, "error": "Direção inválida."}
        if entry <= 0 or lot <= 0:
            return {"ok": False, "error": "Entrada/lote inválidos."}
        pos = {
            "id": uuid.uuid4().hex[:12], "symbol": symbol, "direction": direction,
            "entry": entry, "lot": lot, "stop": stop, "take": take, "opened_at": utc_now(),
        }
        self.positions.append(pos)
        return {"ok": True, "position": pos}

    def close_position(self, position_id: str, price: float, reason: str = "manual") -> dict[str, Any]:
        pos = next((p for p in self.positions if p["id"] == position_id), None)
        if pos is None:
            return {"ok": False, "error": "Posição não encontrada."}
        pnl = (price - pos["entry"]) * pos["lot"] * 100_000.0
        if pos["direction"] == "venda":
            pnl = -pnl
        self.balance += pnl
        self.equity = self.balance
        self.positions.remove(pos)
        self.peak_equity = max(self.peak_equity, self.equity)
        dd = (self.peak_equity - self.equity) / self.peak_equity * 100 if self.peak_equity else 0.0
        self.max_drawdown_pct = max(self.max_drawdown_pct, dd)
        record = {**pos, "exit": price, "pnl": round(pnl, 2), "reason": reason, "closed_at": utc_now()}
        self.closed.append(record)
        return {"ok": True, "result": record, "balance": round(self.balance, 2)}

    def mark_to_market(self, prices: dict[str, float]) -> float:
        unreal = 0.0
        for p in self.positions:
            price = prices.get(p["symbol"])
            if price is None:
                continue
            pnl = (price - p["entry"]) * p["lot"] * 100_000.0
            if p["direction"] == "venda":
                pnl = -pnl
            unreal += pnl
        self.equity = self.balance + unreal
        return round(self.equity, 2)

    def summary(self) -> dict[str, Any]:
        wins = [c for c in self.closed if c["pnl"] >= 0]
        losses = [c for c in self.closed if c["pnl"] < 0]
        return {
            "balance": round(self.balance, 2),
            "equity": round(self.equity, 2),
            "open_positions": len(self.positions),
            "closed_trades": len(self.closed),
            "win_rate": round(len(wins) / len(self.closed) * 100, 2) if self.closed else None,
            "net_result": round(sum(c["pnl"] for c in self.closed), 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "avg_win": round(sum(c["pnl"] for c in wins) / len(wins), 2) if wins else None,
            "avg_loss": round(sum(c["pnl"] for c in losses) / len(losses), 2) if losses else None,
        }
