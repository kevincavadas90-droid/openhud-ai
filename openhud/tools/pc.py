"""PC tools: let the agent inspect the connected computer.

These tools read live metrics from the Agent Hub (a device connected via the
OpenHUD Agent) or from the server host itself when no PC is connected. They are
read-only and return an explicit error when no telemetry is available — the
model must never invent hardware data.
"""
from __future__ import annotations

from typing import Any

from .base import Tool, ToolContext, ToolResult


def _resolve_metrics() -> tuple[dict[str, Any], str, str | None]:
    """Return (metrics, device_label, error). Prefers a connected real device."""
    from ..core.agent_hub import get_hub

    try:
        hub = get_hub()
    except RuntimeError as exc:
        return {}, "", str(exc)

    devices = hub.list_devices()
    # Prefer a real, online PC; then any real PC's last snapshot; then local.
    online = [d for d in devices if d["id"] != "local" and d["online"]]
    others = [d for d in devices if d["id"] != "local"]
    local = [d for d in devices if d["id"] == "local"]

    chosen = (online or others or local)
    if not chosen:
        return {}, "", "Nenhum computador conectado. Abra o OpenHUD Agent no PC."
    dev = chosen[0]
    if not dev.get("metrics"):
        return {}, dev["name"], (
            f"O dispositivo '{dev['name']}' ainda não enviou métricas. "
            "Verifique se o OpenHUD Agent está rodando no PC."
        )
    return dev["metrics"], dev["name"], None


class PcMetricsTool(Tool):
    name = "pc_metrics"
    description = (
        "Lê métricas reais do computador conectado (CPU, GPU, RAM, disco, rede e "
        "processos). Use antes de diagnosticar ou otimizar o PC. Retorna erro "
        "explícito se nenhum PC estiver conectado — nunca invente dados."
    )
    parameters = {"type": "object", "properties": {}}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        metrics, label, err = _resolve_metrics()
        if err:
            return ToolResult(False, err)
        cpu = metrics.get("cpu") or {}
        ram = metrics.get("ram") or {}
        gpus = metrics.get("gpu") or []
        lines = [f"Dispositivo: {label}"]
        if cpu:
            lines.append(
                f"CPU: {cpu.get('percent')}% · {cpu.get('freq_mhz')} MHz · "
                f"temp {cpu.get('temp_c')}°C · {cpu.get('cores_logical')} threads"
            )
        if ram:
            lines.append(
                f"RAM: {ram.get('percent')}% ({ram.get('used_mb')}/{ram.get('total_mb')} MB)"
            )
        if gpus:
            for g in gpus:
                lines.append(
                    f"GPU {g.get('name')}: {g.get('util_percent')}% · "
                    f"VRAM {g.get('mem_percent')}% ({g.get('mem_used_mb')}/{g.get('mem_total_mb')} MB) · "
                    f"temp {g.get('temp_c')}°C"
                )
        else:
            lines.append("GPU: não detectada")
        for d in (metrics.get("disk") or [])[:3]:
            lines.append(f"Disco {d.get('mount')}: {d.get('percent')}% usado, {d.get('free_gb')} GB livres")
        procs = metrics.get("processes") or []
        if procs:
            top = ", ".join(f"{p['name']} ({p['cpu_percent']}%)" for p in procs[:5])
            lines.append(f"Top processos: {top}")
        return ToolResult(True, "\n".join(lines), {"label": label})


class PcDiagnoseTool(Tool):
    name = "pc_diagnose"
    description = (
        "Executa um diagnóstico do computador conectado com base nos dados reais "
        "coletados e retorna gargalo provável e recomendações (dado → análise → "
        "recomendação → impacto → risco)."
    )
    parameters = {"type": "object", "properties": {}}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        metrics, label, err = _resolve_metrics()
        if err:
            return ToolResult(False, err)
        from ..agent.diagnostics import diagnose

        result = diagnose(metrics)
        if not result.get("ok"):
            return ToolResult(False, result.get("error", "Diagnóstico indisponível"))
        lines = [f"Diagnóstico de {label}"]
        if result.get("bottleneck"):
            lines.append(f"Gargalo provável: {result['bottleneck']['label']} — {result['bottleneck']['explain']}")
        else:
            lines.append(f"Sem gargalo evidente ({result.get('summary', '')}).")
        for f in result.get("findings", []):
            lines.append(
                f"\n• {f['title']} (risco {f['risk_label']})\n"
                f"  Dado: {f['observed']}\n  Análise: {f['analysis']}\n"
                f"  Recomendação: {f['recommendation']}\n  Impacto: {f['impact']}"
            )
        return ToolResult(True, "\n".join(lines))


class PcGameTool(Tool):
    name = "pc_game_profile"
    description = (
        "Analisa o desempenho para um jogo específico (ex.: FiveM, Fortnite, CS2) "
        "usando as métricas reais do PC conectado e retorna recomendações."
    )
    parameters = {
        "type": "object",
        "properties": {
            "game": {"type": "string", "description": "Nome do jogo."},
            "fps": {"type": "number", "description": "FPS médio observado, se conhecido."},
        },
        "required": ["game"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        metrics, label, err = _resolve_metrics()
        if err:
            return ToolResult(False, err)
        from ..agent.diagnostics import suggest_game_profile

        profile = suggest_game_profile(args.get("game", ""), metrics)
        lines = [f"Perfil de jogo: {profile['game']} (em {label})"]
        if args.get("fps") is not None:
            lines.append(f"FPS informado: {args['fps']}")
        if profile.get("bottleneck"):
            lines.append(f"Gargalo: {profile['bottleneck']['label']} — {profile['bottleneck']['explain']}")
        for f in profile.get("findings", []):
            lines.append(
                f"\n• {f['title']}\n  Dado: {f['observed']}\n"
                f"  Recomendação: {f['recommendation']}\n  Impacto: {f['impact']}"
            )
        return ToolResult(True, "\n".join(lines))


def build_pc_tools() -> list[Tool]:
    return [PcMetricsTool(), PcDiagnoseTool(), PcGameTool()]
