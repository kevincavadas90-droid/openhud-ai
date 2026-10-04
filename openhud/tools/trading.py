"""Trading tools exposed to the chat agent.

These wrap the server-side :class:`~openhud.trading.service.TradingService` so the
model can read real MT5 data, analyse it, backtest, simulate and — only when the
user explicitly enabled it — prepare or send an order.

Rules enforced here:
  * read tools return an explicit error when MT5 is unreachable; the model must
    never invent prices, balances or executions;
  * order tools require confirmation and go through the same permission, risk
    and idempotency checks as the web UI.
"""
from __future__ import annotations

from typing import Any

from .base import Tool, ToolContext, ToolResult


def _service():
    from ..web.trading_api import get_service

    return get_service()


class Mt5StatusTool(Tool):
    name = "mt5_status"
    description = (
        "Verifica se o MetaTrader 5 está instalado, aberto e com conta conectada no "
        "PC. Retorna dados reais; se não conseguir acessar, informe o erro."
    )
    parameters = {"type": "object", "properties": {}}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        res = _service().status()
        if not res.get("ok"):
            return ToolResult(False, res.get("error", "MT5 indisponível"))
        if not res.get("connected"):
            return ToolResult(True, f"MT5 presente mas sem conta conectada. {res.get('note', '')}".strip())
        return ToolResult(True, f"MT5 conectado ({res.get('name')} build {res.get('build')}).")


class Mt5AccountTool(Tool):
    name = "mt5_account"
    description = "Lê saldo, equity, margem, margem livre e lucro da conta MT5 conectada. Nunca inventa valores."
    parameters = {"type": "object", "properties": {}}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        res = _service().account()
        if not res.get("ok"):
            return ToolResult(False, res.get("error", "Conta indisponível"))
        a = res["account"]
        text = (
            f"Conta {a.get('login')} @ {a.get('server')} ({a.get('broker')})\n"
            f"Saldo: {a.get('balance')} {a.get('currency')} · Equity: {a.get('equity')}\n"
            f"Margem: {a.get('margin')} · Margem livre: {a.get('margin_free')} · Nível: {a.get('margin_level')}\n"
            f"Lucro flutuante: {a.get('profit')} · Negociação permitida: {a.get('trade_allowed')}"
        )
        return ToolResult(True, text)


class Mt5AnalyseTool(Tool):
    name = "mt5_analyse"
    description = (
        "Analisa o mercado no MT5: indicadores, price action, suportes/resistências, "
        "estrutura e (se multi=true) vários timeframes. Use dados reais; sem dados, "
        "responda 'Não há dados suficientes para uma análise confiável.'"
    )
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Ativo, ex.: EURUSD"},
            "timeframe": {"type": "string", "description": "M1,M5,M15,M30,H1,H4,D1,W1,MN1", "default": "M15"},
            "multi": {"type": "boolean", "description": "Analisar múltiplos timeframes", "default": False},
        },
        "required": ["symbol"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        res = _service().analyse(
            args["symbol"], args.get("timeframe", "M15"),
            multi=bool(args.get("multi", False)),
        )
        if not res.get("ok"):
            return ToolResult(False, res.get("error", "Sem dados"))
        lines = [f"Análise {res.get('symbol')} ({res.get('timeframe') or res.get('detail_timeframe')})"]
        detail = res.get("detail") if res.get("multi_timeframe") else res
        if res.get("multi_timeframe"):
            mt = res["multi_timeframe"]
            lines.append(f"Consenso multi-timeframe: {mt['consensus']} (alinhado: {mt['aligned']})")
            for tf, v in mt["per_timeframe"].items():
                lines.append(f"  {tf}: tendência {v['trend']} · estrutura {v['structure']} · RSI {v['rsi']}")
        for f in (detail or {}).get("findings", []):
            lines.append(f"• {f['label']} — {f['detail']}")
        return ToolResult(True, "\n".join(lines))


class TradingStrategyTool(Tool):
    name = "trading_strategy"
    description = (
        "Converte uma estratégia descrita em linguagem natural (ex.: 'EMA 9 + EMA 21 + RSI') "
        "em regras estruturadas e salva. Mostra entrada, saída, stop, take, filtros, "
        "timeframe e ativos."
    )
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "name": {"type": "string"},
            "timeframe": {"type": "string", "default": "M15"},
        },
        "required": ["text"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        res = _service().parse_and_save(args["text"], args.get("name"), args.get("timeframe", "M15"))
        s = res["interpreted"]
        lines = [f"Estratégia interpretada: {s['name']}"]
        lines.append("Entrada (compra): " + ("; ".join(c["label"] for c in s["entry_long"]) or "—"))
        lines.append("Entrada (venda): " + ("; ".join(c["label"] for c in s["entry_short"]) or "—"))
        lines.append("Saída: " + ("; ".join(c["label"] for c in s["exit"]) or "—"))
        lines.append("Filtros: " + ("; ".join(c["label"] for c in s["filters"]) or "—"))
        lines.append(f"Stop: {s['stop']} · Take: {s['take']} · Timeframe: {s['timeframe']}")
        for n in s.get("notes", []):
            lines.append(f"Observação: {n}")
        return ToolResult(True, "\n".join(lines))


class TradingBacktestTool(Tool):
    name = "trading_backtest"
    description = (
        "Testa uma estratégia em dados históricos reais do MT5. Retorna operações, taxa de "
        "acerto, profit factor, drawdown, resultado líquido e sequências. Resultados "
        "históricos NÃO garantem resultados futuros."
    )
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "strategy_id": {"type": "string"},
            "timeframe": {"type": "string", "default": "M15"},
            "count": {"type": "integer", "default": 500},
        },
        "required": ["symbol", "strategy_id"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        from ..web.trading_api import _store

        strategy = _store.get_strategy(args["strategy_id"])
        if strategy is None:
            return ToolResult(False, "Estratégia não encontrada.")
        res = _service().backtest(strategy, args["symbol"], args.get("timeframe", "M15"),
                                  int(args.get("count", 500)))
        if not res.get("ok"):
            return ToolResult(False, res.get("error", "Backtest indisponível"))
        m = res["metrics"]
        text = (
            f"Backtest {res['symbol']} {res['timeframe']}\n"
            f"Operações: {m['trades']} · Acerto: {m['win_rate']}% · Profit factor: {m['profit_factor']}\n"
            f"Resultado líquido: {m['net_result']} · Drawdown máx: {m['max_drawdown_pct']}%\n"
            f"Média ganho: {m['avg_win']} · Média perda: {m['avg_loss']}\n"
            f"Sequências: {m['max_consec_wins']} ganhos / {m['max_consec_losses']} perdas\n"
            f"{res['disclaimer']}"
        )
        return ToolResult(True, text)


class TradingBriefTool(Tool):
    name = "trading_daily_brief"
    description = "Gera um resumo diário do mercado para uma lista de ativos, com tendência, volatilidade e condições. Não inventa oportunidades."
    parameters = {
        "type": "object",
        "properties": {
            "symbols": {"type": "array", "items": {"type": "string"}},
            "timeframe": {"type": "string", "default": "M15"},
        },
        "required": ["symbols"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        res = _service().daily_brief(args["symbols"], args.get("timeframe", "M15"))
        if not res.get("ok"):
            return ToolResult(False, res.get("error", "Sem dados"))
        lines = ["Resumo do mercado:"]
        for e in res["symbols"]:
            if not e.get("ok"):
                lines.append(f"{e['symbol']}: sem dados ({e.get('error')})")
                continue
            lines.append(
                f"{e['symbol']}: tendência {e['trend']} · volatilidade {e['volatility']} · "
                f"estrutura {e['structure']} · preço {e['price']}"
            )
        if not res["opportunities"]:
            lines.append("Nenhuma configuração compatível encontrada.")
        return ToolResult(True, "\n".join(lines))


class TradingPaperTool(Tool):
    name = "trading_paper"
    description = (
        "Simulação (paper trading): abre ou fecha uma posição fictícia usando preços reais "
        "informados. Não envia nada ao MT5. Use para validar uma estratégia antes do modo demo."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["open", "close", "summary"]},
            "symbol": {"type": "string"},
            "direction": {"type": "string", "enum": ["compra", "venda"]},
            "entry": {"type": "number"},
            "lot": {"type": "number"},
            "stop": {"type": "number"},
            "take": {"type": "number"},
            "position_id": {"type": "string"},
            "price": {"type": "number"},
        },
        "required": ["action"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        svc = _service()
        action = args["action"]
        if action == "open":
            res = svc.paper_open(
                symbol=args.get("symbol", ""), direction=args.get("direction", "compra"),
                entry=float(args.get("entry", 0)), lot=float(args.get("lot", 0.01)),
                stop=args.get("stop"), take=args.get("take"),
            )
        elif action == "close":
            res = svc.paper_close(args.get("position_id", ""), float(args.get("price", 0)))
        else:
            acc = svc.paper_account()["account"]
            return ToolResult(True, str(acc.summary()))
        if not res.get("ok"):
            return ToolResult(False, res.get("error", "Falha na simulação"))
        return ToolResult(True, str(res))


class TradingPrepareOrderTool(Tool):
    name = "trading_prepare_order"
    description = (
        "Calcula lote, risco, margem e valida os limites para uma possível ordem. "
        "NÃO envia nada ao MT5. Mostre o preview ao usuário antes de qualquer execução."
    )
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "direction": {"type": "string", "enum": ["compra", "venda"]},
            "entry": {"type": "number"},
            "stop": {"type": "number"},
            "take": {"type": "number"},
            "risk_pct": {"type": "number", "default": 1.0},
            "strategy_name": {"type": "string"},
        },
        "required": ["symbol", "direction", "entry", "stop"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        res = _service().prepare_order(
            device_id=_service().resolve_mt5_device() or "",
            symbol=args["symbol"], direction=args["direction"], risk_pct=float(args.get("risk_pct", 1.0)),
            entry=float(args["entry"]), stop=float(args["stop"]), take=args.get("take"),
            strategy_name=args.get("strategy_name", ""),
        )
        if not res.get("ok"):
            extra = ("; ".join(res.get("violations", []))) if res.get("violations") else ""
            return ToolResult(False, f"{res.get('error')} {extra}".strip())
        p = res["preview"]
        text = (
            f"Pré-ordem ({p['mode']}): {p['symbol']} {p['direction'].upper()}\n"
            f"Entrada: {p['entry']} · Stop: {p['stop']} · Take: {p['take']}\n"
            f"Lote sugerido: {p['lot']} · Risco: {p['risk_actual']} ({p['risk_actual_pct']}%) · R:R {p['reward_risk']}\n"
            f"Margem: {p['margin']} · Margem livre: {p['margin_free']}\n"
            f"request_id: {res['request_id']}"
        )
        if p.get("warnings"):
            text += "\nAvisos: " + "; ".join(p["warnings"])
        return ToolResult(True, text)


class TradingExecuteOrderTool(Tool):
    name = "trading_execute_order"
    description = (
        "Envia uma ordem ao MT5. Exige confirmação e só funciona nos modos DEMO ou REAL "
        "com a permissão correspondente ativa. Idempotente por request_id: reenviar o mesmo "
        "request_id NÃO duplica a ordem. Nunca diga 'ordem executada' sem confirmação real."
    )
    requires_confirmation = True
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "direction": {"type": "string", "enum": ["compra", "venda"]},
            "lot": {"type": "number"},
            "stop": {"type": "number"},
            "take": {"type": "number"},
            "request_id": {"type": "string"},
            "strategy_name": {"type": "string"},
        },
        "required": ["symbol", "direction", "lot", "request_id"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        res = _service().execute_order(
            device_id=_service().resolve_mt5_device() or "",
            symbol=args["symbol"], direction=args["direction"], lot=float(args["lot"]),
            stop=args.get("stop"), take=args.get("take"), request_id=args["request_id"],
            strategy_name=args.get("strategy_name", ""), confirmed=True,
        )
        if not res.get("ok"):
            return ToolResult(False, res.get("error", "Ordem não confirmada."))
        if res.get("duplicate"):
            return ToolResult(True, f"Ordem já registrada (idempotente): {res.get('response')}")
        return ToolResult(True, f"Ordem confirmada pelo MT5: {res.get('order')} @ {res.get('price')}")


def build_trading_tools() -> list[Tool]:
    return [
        Mt5StatusTool(),
        Mt5AccountTool(),
        Mt5AnalyseTool(),
        TradingStrategyTool(),
        TradingBacktestTool(),
        TradingBriefTool(),
        TradingPaperTool(),
        TradingPrepareOrderTool(),
        TradingExecuteOrderTool(),
    ]
