"""Trading REST API (``/api/trading/*``).

All endpoints require the authenticated web session (enforced by the app
middleware). They return structured JSON with an explicit ``ok`` flag. Order
submission goes through the server-side policy in :mod:`openhud.trading.service`
and is audited; real trading is disabled by default.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core.agent_hub import get_hub
from ..core.runtime import runtime
from ..trading.core import DEFAULT_TRADING_PERMISSIONS, MODES, TRADING_PERMISSION_KEYS, RiskLimits
from ..trading.service import TradingService
from ..trading.store import TradingStore

router = APIRouter()

_store = TradingStore(runtime.db)
_service = TradingService(_store)


def get_service() -> TradingService:
    return _service


# --------------------------------------------------------------------------
# payloads
# --------------------------------------------------------------------------
class StrategyPayload(BaseModel):
    text: str
    name: str | None = None
    timeframe: str = "M15"


class BacktestPayload(BaseModel):
    symbol: str
    strategy_id: str | None = None
    strategy: dict[str, Any] | None = None
    timeframe: str = "M15"
    count: int = 500
    device_id: str | None = None
    initial_balance: float = 10_000.0
    risk_pct: float = 1.0


class AlertPayload(BaseModel):
    symbol: str
    timeframe: str = "M15"
    kind: str
    params: dict[str, Any] = {}


class AlertTogglePayload(BaseModel):
    enabled: bool


class JournalPayload(BaseModel):
    symbol: str = ""
    strategy: str = ""
    setup: str = ""
    entry: float | None = None
    exit: float | None = None
    result: float | None = None
    risk: float | None = None
    notes: str = ""
    screenshot: str | None = None
    ai_comment: str = ""
    feedback: str = ""


class JournalPatch(BaseModel):
    symbol: str | None = None
    strategy: str | None = None
    setup: str | None = None
    entry: float | None = None
    exit: float | None = None
    result: float | None = None
    risk: float | None = None
    notes: str | None = None
    screenshot: str | None = None
    ai_comment: str | None = None
    feedback: str | None = None


class ModePayload(BaseModel):
    device_id: str | None = None
    mode: str


class LimitsPayload(BaseModel):
    device_id: str | None = None
    limits: dict[str, Any]


class StopPayload(BaseModel):
    device_id: str | None = None
    active: bool = True


class PaperOpenPayload(BaseModel):
    symbol: str
    direction: str
    entry: float
    lot: float
    stop: float | None = None
    take: float | None = None
    device_id: str | None = None


class PaperClosePayload(BaseModel):
    position_id: str
    price: float
    device_id: str | None = None


class PrepareOrderPayload(BaseModel):
    device_id: str | None = None
    symbol: str
    direction: str
    risk_pct: float = 1.0
    entry: float
    stop: float
    take: float | None = None
    strategy_name: str = ""
    reason: str = ""
    request_id: str | None = None


class ExecuteOrderPayload(BaseModel):
    device_id: str | None = None
    symbol: str
    direction: str
    lot: float
    stop: float | None = None
    take: float | None = None
    request_id: str
    strategy_name: str = ""
    reason: str = ""
    confirmed: bool = False


class ClosePositionPayload(BaseModel):
    device_id: str | None = None
    ticket: int


# --------------------------------------------------------------------------
# status & market data
# --------------------------------------------------------------------------
@router.get("/api/trading/config")
def trading_config() -> dict[str, Any]:
    """Static policy surface for the UI: modes, permissions, risk notice."""
    return {
        "modes": MODES,
        "default_mode": "analysis",
        "permission_keys": TRADING_PERMISSION_KEYS,
        "default_permissions": DEFAULT_TRADING_PERMISSIONS,
        "default_limits": RiskLimits().to_dict(),
        "risk_notice": (
            "Operações financeiras envolvem risco de perda. Análises da IA não garantem "
            "resultados. Você é responsável por ativar e autorizar operações reais."
        ),
    }


EDUCATION = {
    "trilha": [
        {"passo": 1, "titulo": "Aprender", "texto": "Entenda ativo, timeframe, spread, alavancagem e o que é stop."},
        {"passo": 2, "titulo": "Analisar", "texto": "Use o painel para ler tendência, volatilidade e estrutura. Sem operar."},
        {"passo": 3, "titulo": "Simular", "texto": "Faça paper trading com preços reais para testar sem risco."},
        {"passo": 4, "titulo": "Backtest", "texto": "Rode a estratégia no histórico e leia drawdown e profit factor."},
        {"passo": 5, "titulo": "Demo", "texto": "Só depois ative o modo demo, com limites de risco baixos."},
        {"passo": 6, "titulo": "Real", "texto": "Opcional e de sua responsabilidade. Comece com risco mínimo."},
    ],
    "glossario": {
        "ativo": "Instrumento negociado (ex.: EURUSD, XAUUSD).",
        "timeframe": "Duração de cada barra do gráfico (M15 = 15 minutos).",
        "spread": "Diferença entre compra e venda; é um custo por operação.",
        "alavancagem": "Multiplica o tamanho da posição e também o risco.",
        "lote": "Tamanho da posição; define quanto cada ponto vale.",
        "stop loss": "Preço que encerra a operação para limitar a perda.",
        "take profit": "Preço que encerra a operação com o lucro alvo.",
        "drawdown": "Queda do capital desde o topo; mede o pior momento.",
        "risco/retorno": "Relação entre o que se arrisca e o que se espera ganhar.",
    },
    "aviso": "Conteúdo educativo. Não é recomendação de investimento nem garantia de resultado.",
}


@router.get("/api/trading/education")
def trading_education() -> dict[str, Any]:
    return EDUCATION


@router.get("/api/trading/status")
def trading_status(device_id: str | None = None) -> dict[str, Any]:
    return _service.status(device_id)


@router.get("/api/trading/account")
def trading_account(device_id: str | None = None) -> dict[str, Any]:
    return _service.account(device_id)


@router.get("/api/trading/symbol")
def trading_symbol(symbol: str, device_id: str | None = None) -> dict[str, Any]:
    return _service.symbol(symbol, device_id)


@router.get("/api/trading/rates")
def trading_rates(symbol: str, timeframe: str = "M15", count: int = 300,
                  device_id: str | None = None) -> dict[str, Any]:
    return _service.rates(symbol, timeframe, count, device_id)


@router.get("/api/trading/positions")
def trading_positions(device_id: str | None = None) -> dict[str, Any]:
    return _service.positions(device_id)


@router.get("/api/trading/orders")
def trading_pending_orders(device_id: str | None = None) -> dict[str, Any]:
    return _service.pending_orders(device_id)


@router.get("/api/trading/analyse")
def trading_analyse(symbol: str, timeframe: str = "M15", multi: bool = False,
                    device_id: str | None = None) -> dict[str, Any]:
    return _service.analyse(symbol, timeframe, device_id=device_id, multi=multi)


# --------------------------------------------------------------------------
# strategies & backtest
# --------------------------------------------------------------------------
@router.get("/api/trading/strategies")
def list_strategies() -> list[dict[str, Any]]:
    return _service.list_strategies()


@router.post("/api/trading/strategies")
def create_strategy(payload: StrategyPayload) -> dict[str, Any]:
    return _service.parse_and_save(payload.text, name=payload.name, timeframe=payload.timeframe)


@router.delete("/api/trading/strategies/{sid}")
def delete_strategy(sid: str) -> dict[str, bool]:
    _store.delete_strategy(sid)
    return {"deleted": True}


@router.post("/api/trading/backtest")
def backtest(payload: BacktestPayload) -> dict[str, Any]:
    strategy = payload.strategy
    if payload.strategy_id:
        strategy = _store.get_strategy(payload.strategy_id)
        if strategy is None:
            raise HTTPException(404, "Estratégia não encontrada")
    if not strategy:
        raise HTTPException(400, "Informe strategy_id ou strategy")
    return _service.backtest(
        strategy, payload.symbol, payload.timeframe, payload.count, payload.device_id,
        payload.initial_balance, payload.risk_pct,
    )


# --------------------------------------------------------------------------
# simulation / paper trading
# --------------------------------------------------------------------------
@router.get("/api/trading/paper")
def paper_summary(device_id: str | None = None) -> dict[str, Any]:
    acc = _service.paper_account(device_id)["account"]
    return {"ok": True, "summary": acc.summary(), "positions": acc.positions, "closed": acc.closed[-50:]}


@router.post("/api/trading/paper/open")
def paper_open(payload: PaperOpenPayload) -> dict[str, Any]:
    return _service.paper_open(
        symbol=payload.symbol, direction=payload.direction, entry=payload.entry, lot=payload.lot,
        stop=payload.stop, take=payload.take, device_id=payload.device_id,
    )


@router.post("/api/trading/paper/close")
def paper_close(payload: PaperClosePayload) -> dict[str, Any]:
    return _service.paper_close(payload.position_id, payload.price, payload.device_id)


# --------------------------------------------------------------------------
# alerts
# --------------------------------------------------------------------------
@router.get("/api/trading/alerts")
def list_alerts() -> list[dict[str, Any]]:
    return _store.list_alerts()


@router.post("/api/trading/alerts")
def create_alert(payload: AlertPayload) -> dict[str, Any]:
    return _store.create_alert(payload.model_dump())


@router.post("/api/trading/alerts/evaluate")
def evaluate_alerts(device_id: str | None = None) -> dict[str, Any]:
    return _service.evaluate_alerts(device_id)


@router.post("/api/trading/alerts/{aid}/toggle")
def toggle_alert(aid: str, payload: AlertTogglePayload) -> dict[str, Any]:
    _store.set_alert_enabled(aid, payload.enabled)
    return {"ok": True}


@router.delete("/api/trading/alerts/{aid}")
def delete_alert(aid: str) -> dict[str, bool]:
    _store.delete_alert(aid)
    return {"deleted": True}


# --------------------------------------------------------------------------
# journal
# --------------------------------------------------------------------------
@router.get("/api/trading/journal")
def list_journal(limit: int = 200) -> list[dict[str, Any]]:
    return _store.list_journal(limit)


@router.post("/api/trading/journal")
def add_journal(payload: JournalPayload) -> dict[str, Any]:
    return _store.add_journal(payload.model_dump())


@router.patch("/api/trading/journal/{jid}")
def patch_journal(jid: str, payload: JournalPatch) -> dict[str, Any]:
    _store.update_journal(jid, {k: v for k, v in payload.model_dump().items() if v is not None})
    return _store.get_journal(jid) or {}


@router.delete("/api/trading/journal/{jid}")
def delete_journal(jid: str) -> dict[str, bool]:
    _store.delete_journal(jid)
    return {"deleted": True}


# --------------------------------------------------------------------------
# audit
# --------------------------------------------------------------------------
@router.get("/api/trading/audit")
def list_audit(limit: int = 200) -> list[dict[str, Any]]:
    return _store.list_audit(limit)


# --------------------------------------------------------------------------
# mode, limits, emergency stop
# --------------------------------------------------------------------------
@router.get("/api/trading/mode")
def get_mode(device_id: str | None = None) -> dict[str, Any]:
    dev_id = _service.resolve_mt5_device(device_id)
    if dev_id is None:
        return {"ok": False, "error": "Nenhum PC conectado."}
    dev = get_hub().get_device(dev_id)
    return {"ok": True, "device_id": dev_id, "trading_mode": dev.trading_mode,
            "emergency_stop": dev.emergency_stop, "risk_limits": dev.risk_limits,
            "mt5_status": dev.mt5_status}


@router.post("/api/trading/mode")
def set_mode(payload: ModePayload) -> dict[str, Any]:
    dev_id = _service.resolve_mt5_device(payload.device_id)
    if dev_id is None:
        raise HTTPException(404, "Nenhum PC conectado.")
    try:
        return {"ok": True, "device": get_hub().set_trading_mode(dev_id, payload.mode)}
    except KeyError:
        raise HTTPException(404, "Dispositivo não encontrado")
    except (ValueError, PermissionError) as exc:
        raise HTTPException(403, str(exc))


@router.post("/api/trading/limits")
def set_limits(payload: LimitsPayload) -> dict[str, Any]:
    dev_id = _service.resolve_mt5_device(payload.device_id)
    if dev_id is None:
        raise HTTPException(404, "Nenhum PC conectado.")
    try:
        return {"ok": True, "device": get_hub().set_risk_limits(dev_id, payload.limits)}
    except KeyError:
        raise HTTPException(404, "Dispositivo não encontrado")


@router.post("/api/trading/stop")
def emergency_stop(payload: StopPayload) -> dict[str, Any]:
    dev_id = _service.resolve_mt5_device(payload.device_id)
    if dev_id is None:
        raise HTTPException(404, "Nenhum PC conectado.")
    try:
        result = get_hub().set_emergency_stop(dev_id, payload.active)
    except KeyError:
        raise HTTPException(404, "Dispositivo não encontrado")
    _store.add_audit({"action": "emergency_stop", "device_id": dev_id,
                      "result": "on" if payload.active else "off"})
    return {"ok": True, "device": result}


# --------------------------------------------------------------------------
# order preparation, execution and close
# --------------------------------------------------------------------------
@router.post("/api/trading/order/prepare")
def prepare_order(payload: PrepareOrderPayload) -> dict[str, Any]:
    dev_id = _service.resolve_mt5_device(payload.device_id)
    if dev_id is None:
        raise HTTPException(404, "Nenhum PC conectado.")
    return _service.prepare_order(
        device_id=dev_id, symbol=payload.symbol, direction=payload.direction,
        risk_pct=payload.risk_pct, entry=payload.entry, stop=payload.stop, take=payload.take,
        request_id=payload.request_id, strategy_name=payload.strategy_name, reason=payload.reason,
    )


@router.post("/api/trading/order/execute")
def execute_order(payload: ExecuteOrderPayload) -> dict[str, Any]:
    dev_id = _service.resolve_mt5_device(payload.device_id)
    if dev_id is None:
        raise HTTPException(404, "Nenhum PC conectado.")
    return _service.execute_order(
        device_id=dev_id, symbol=payload.symbol, direction=payload.direction, lot=payload.lot,
        stop=payload.stop, take=payload.take, request_id=payload.request_id,
        strategy_name=payload.strategy_name, reason=payload.reason, confirmed=payload.confirmed,
    )


@router.post("/api/trading/close")
def close_position(payload: ClosePositionPayload) -> dict[str, Any]:
    dev_id = _service.resolve_mt5_device(payload.device_id)
    if dev_id is None:
        raise HTTPException(404, "Nenhum PC conectado.")
    return _service.close_position(dev_id, payload.ticket)


# --------------------------------------------------------------------------
# briefs & quick assistant
# --------------------------------------------------------------------------
@router.get("/api/trading/brief")
def daily_brief(symbols: str, timeframe: str = "M15", device_id: str | None = None) -> dict[str, Any]:
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    return _service.daily_brief(symbol_list, timeframe, device_id)


@router.get("/api/trading/scan")
def quick_scan(symbols: str, timeframe: str = "M15", strategy_id: str | None = None,
               device_id: str | None = None) -> dict[str, Any]:
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    strategy = _store.get_strategy(strategy_id) if strategy_id else None
    return _service.quick_scan(symbol_list, strategy, timeframe, device_id)
