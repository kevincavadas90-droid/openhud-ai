"""System tools exposed to the chat agent: diagnostics, mode and personality.

These let the agent inspect the real health of the system and read/update the
active mode and personality traits (which it must never claim are real
feelings). Diagnostics never fabricate a healthy status.
"""
from __future__ import annotations

from typing import Any

from .base import Tool, ToolContext, ToolResult


def _runtime():
    from ..core.runtime import runtime

    return runtime


class SelfDiagnoseTool(Tool):
    name = "self_diagnose"
    description = (
        "Executa o auto-diagnóstico do sistema (banco, LLM, voz, jobs, PC agents, MT5, "
        "plugins, armazenamento, codex) e retorna o status real de cada componente."
    )
    parameters = {"type": "object", "properties": {}}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        from ..core.diagnostics import run_diagnostics

        diag = run_diagnostics(_runtime())
        lines = [f"{c['name']}: {c['status']} — {c.get('detail', '')}" for c in diag["checks"]]
        return ToolResult(diag["ok"], "\n".join(lines), diag)


class SetModeTool(Tool):
    name = "set_mode"
    description = "Consulta ou define o modo ativo da IA (auto, codex, trading, voice, etc.)."
    parameters = {
        "type": "object",
        "properties": {"mode": {"type": "string", "description": "vazio para consultar"}},
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        from ..core.modes import MODE_KEYS

        rt = _runtime()
        mode = (args.get("mode") or "").strip()
        if not mode:
            current = rt.get_settings().get("mode", "auto")
            return ToolResult(True, f"Modo atual: {current}. Disponíveis: {', '.join(MODE_KEYS)}")
        if mode not in MODE_KEYS:
            return ToolResult(False, f"Modo inválido. Disponíveis: {', '.join(MODE_KEYS)}")
        rt.update_settings({"mode": mode})
        return ToolResult(True, f"Modo definido para {mode}.")


class GetPersonalityTool(Tool):
    name = "get_personality"
    description = "Lê os traços de personalidade atuais da IA (empatia, humor, energia, etc.)."
    parameters = {"type": "object", "properties": {}}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        s = _runtime().get_settings()
        return ToolResult(True, f"Estilo: {s.get('personality_style')}; traços: {s.get('personality') or 'padrão'}")


class RememberPreferenceTool(Tool):
    name = "remember_preference"
    description = (
        "Guarda uma preferência do usuário na memória privada (marcada como 'preferencia'), "
        "usada para adaptar o estilo das respostas. Não guarde dados sensíveis."
    )
    parameters = {
        "type": "object",
        "properties": {"preference": {"type": "string"}},
        "required": ["preference"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        rt = _runtime()
        if ctx.db is None:
            return ToolResult(False, "Banco indisponível")
        ctx.db.add_memory(args["preference"], tags="preferencia")
        return ToolResult(True, "Preferência registrada.")


class ScamCheckTool(Tool):
    name = "scam_check"
    description = (
        "Analisa um texto e/ou endereço de página em busca de sinais de golpe, phishing, "
        "falso suporte ou engenharia social. Retorna o nível de risco e os sinais encontrados. "
        "Use antes de orientar o usuário a informar dados ou fazer pagamentos."
    )
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Texto visível na página/mensagem."},
            "url": {"type": "string", "description": "Endereço (URL) da página, se houver."},
        },
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        from ..core.scam_guard import analyze_text

        report = analyze_text(args.get("text", ""), args.get("url", ""))
        lines = [report.message()]
        for f in report.findings:
            lines.append(f"• {f['label']}: {f.get('explanation', '')} (ex.: \"{f.get('evidence', '')}\")")
        if report.risk == "low":
            lines.append("Mesmo assim, nunca informe senhas ou códigos em páginas desconhecidas.")
        return ToolResult(True, "\n".join(lines), report.to_dict())


class TaskControlTool(Tool):
    name = "task_control"
    description = (
        "Controla a tarefa atual: cancelar, pausar ou retomar. Aceita comandos como "
        "'pare', 'cancela', 'pausa', 'retome'. Use quando o usuário pedir para parar."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["cancel", "pause", "resume", "status"]},
        },
        "required": ["action"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        from ..core.assist import controller

        cid = ctx.conversation_id or ""
        action = args.get("action", "status")
        if action == "cancel":
            controller.request_cancel(cid)
            return ToolResult(True, "Tarefa cancelada.")
        if action == "pause":
            controller.request_pause(cid, True)
            return ToolResult(True, "Tarefa pausada.")
        if action == "resume":
            controller.request_pause(cid, False)
            return ToolResult(True, "Tarefa retomada.")
        rec = controller.get(cid)
        return ToolResult(True, rec.to_dict() if rec else "Nenhuma tarefa ativa.")


class SetAutonomyLevelTool(Tool):
    name = "set_autonomy_level"
    description = (
        "Consulta ou define o nível de autonomia do assistente de computador: "
        "observe, guide, assisted ou automatic."
    )
    parameters = {
        "type": "object",
        "properties": {"level": {"type": "string", "enum": ["observe", "guide", "assisted", "automatic", ""]}},
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        from ..core.assist import AUTONOMY_LEVELS

        rt = _runtime()
        level = (args.get("level") or "").strip()
        if not level:
            cur = rt.get_settings().get("autonomy_level", "guide")
            return ToolResult(True, f"Nível atual: {cur}. Opções: {', '.join(AUTONOMY_LEVELS)}")
        if level not in AUTONOMY_LEVELS:
            return ToolResult(False, f"Nível inválido. Opções: {', '.join(AUTONOMY_LEVELS)}")
        rt.update_settings({"autonomy_level": level})
        return ToolResult(True, f"Nível de autonomia definido para {level}.")


class SetProfileTool(Tool):
    name = "set_profile"
    description = (
        "Consulta ou define o perfil do usuário: standard, beginner, power_user ou accessibility. "
        "Isso adapta a linguagem e o nível de explicação."
    )
    parameters = {
        "type": "object",
        "properties": {"profile": {"type": "string", "enum": ["standard", "beginner", "power_user", "accessibility", ""]}},
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        from ..core.assist import PROFILES

        rt = _runtime()
        profile = (args.get("profile") or "").strip()
        if not profile:
            cur = rt.get_settings().get("profile", "standard")
            return ToolResult(True, f"Perfil atual: {cur}. Opções: {', '.join(PROFILES)}")
        if profile not in PROFILES:
            return ToolResult(False, f"Perfil inválido. Opções: {', '.join(PROFILES)}")
        rt.update_settings({"profile": profile})
        return ToolResult(True, f"Perfil definido para {profile}.")


def build_system_tools() -> list[Tool]:
    return [
        SelfDiagnoseTool(), SetModeTool(), GetPersonalityTool(), RememberPreferenceTool(),
        ScamCheckTool(), TaskControlTool(), SetAutonomyLevelTool(), SetProfileTool(),
    ]
