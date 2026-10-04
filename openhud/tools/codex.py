"""Codex tools exposed to the chat agent.

Analysis and test execution are real and deterministic. Proposing a change
set records before/after/diff without touching files; applying it writes the
files and can be reverted. Test runs execute the project's suite in the
sandbox and report the genuine pass/fail counts.
"""
from __future__ import annotations

from typing import Any

from .base import Tool, ToolContext, ToolResult


def _runtime():
    from ..core.runtime import runtime

    return runtime


class CodexAnalyzeTool(Tool):
    name = "codex_analyze"
    description = (
        "Analisa um projeto/repositório no workspace: linguagens, arquivos de teste, "
        "dependências, pontos de entrada e erros de sintaxe Python."
    )
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "default": "."}},
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        analysis = _runtime().codex.analyze(args.get("path", "."))
        data = analysis.to_dict()
        lines = [
            f"Arquivos: {data['file_count']} · linhas: {data['total_lines']}",
            f"Linguagens: {data['languages']}",
            f"Testes: {data['test_files'][:10]}",
            f"Entrada: {data['entrypoints'][:10]}",
            f"Observações: {'; '.join(data['findings'])}",
        ]
        return ToolResult(True, "\n".join(lines), data)


class CodexPlanTool(Tool):
    name = "codex_plan"
    description = "Produz um plano de implementação para um objetivo de programação."
    parameters = {
        "type": "object",
        "properties": {"objective": {"type": "string"}},
        "required": ["objective"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        rt = _runtime()
        plan = rt.codex.plan(args["objective"], rt.codex.analyze("."))
        return ToolResult(True, "Etapas:\n" + "\n".join(f"{i+1}. {s}" for i, s in enumerate(plan["steps"])),
                          plan)


class CodexProposeTool(Tool):
    name = "codex_propose"
    description = (
        "Propõe alterações de código (criar/editar/remover arquivos) SEM aplicar. "
        "Retorna um changeset_id com o diff antes/depois para revisão e aprovação."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "changes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": ["string", "null"], "description": "null remove o arquivo"},
                    },
                    "required": ["path"],
                },
            },
        },
        "required": ["title", "changes"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        from ..codex import ChangeStore
        from ..config import settings

        store = ChangeStore(settings.data_dir / "codex", settings.workspace_dir)
        cs = store.create(args["title"], args["changes"])
        return ToolResult(True, f"Changeset {cs.id} proposto ({len(cs.changes)} alteração(ões)). "
                                "Revise e aplique com codex_apply.", cs.to_dict())


class CodexApplyTool(Tool):
    name = "codex_apply"
    description = "Aplica um changeset proposto, gravando os arquivos. Pode ser revertido depois."
    parameters = {
        "type": "object",
        "properties": {"changeset_id": {"type": "string"}},
        "required": ["changeset_id"],
    }
    requires_confirmation = True

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        from ..codex import ChangeStore
        from ..config import settings

        store = ChangeStore(settings.data_dir / "codex", settings.workspace_dir)
        cs = store.get(args["changeset_id"])
        if not cs:
            return ToolResult(False, "Changeset não encontrado")
        store.apply(cs)
        return ToolResult(True, f"Changeset {cs.id} aplicado ({len(cs.changes)} arquivo(s)).", cs.to_dict())


class CodexRevertTool(Tool):
    name = "codex_revert"
    description = "Reverte um changeset aplicado, restaurando o conteúdo anterior dos arquivos."
    parameters = {
        "type": "object",
        "properties": {"changeset_id": {"type": "string"}},
        "required": ["changeset_id"],
    }
    requires_confirmation = True

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        from ..codex import ChangeStore
        from ..config import settings

        store = ChangeStore(settings.data_dir / "codex", settings.workspace_dir)
        cs = store.get(args["changeset_id"])
        if not cs:
            return ToolResult(False, "Changeset não encontrado")
        store.revert(cs)
        return ToolResult(True, f"Changeset {cs.id} revertido.", cs.to_dict())


class CodexTestTool(Tool):
    name = "codex_test"
    description = "Executa a suíte de testes do projeto (pytest) no sandbox e reporta passou/falhou reais."
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "default": "."}},
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        res = _runtime().codex.run_tests(args.get("path", "."))
        tests = res.get("tests")
        if tests:
            summary = f"{tests['passed']} passou, {tests['failed']} falhou, {tests['errors']} erro(s)"
        else:
            summary = "Sem resumo de testes (pytest pode não estar disponível)."
        return ToolResult(res.get("ok", False), summary + "\n" + (res.get("stdout", "")[-1500:]), res)


def build_codex_tools() -> list[Tool]:
    return [CodexAnalyzeTool(), CodexPlanTool(), CodexProposeTool(), CodexApplyTool(),
            CodexRevertTool(), CodexTestTool()]
