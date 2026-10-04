"""Tools that let the agent read and write long-term memory."""
from __future__ import annotations

from .base import Tool, ToolContext, ToolResult


class RememberTool(Tool):
    name = "remember"
    description = (
        "Guarda uma informação durável na memória de longo prazo "
        "(preferências do usuário, decisões, contexto de projetos)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Informação a lembrar."},
            "tags": {"type": "string", "description": "Tags separadas por vírgula."},
        },
        "required": ["content"],
    }

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        content = args.get("content", "").strip()
        if not content:
            return ToolResult(False, "Conteúdo vazio.")
        if ctx.db is None:
            return ToolResult(False, "Memória indisponível neste contexto.")
        entry = ctx.db.add_memory(content, args.get("tags", ""))
        ctx.log("memory", f"Memorizado: {content[:80]}")
        return ToolResult(True, f"Memorizado (id={entry['id']}).")


class RecallTool(Tool):
    name = "recall"
    description = "Busca informações na memória de longo prazo."
    parameters = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        if ctx.db is None:
            return ToolResult(False, "Memória indisponível neste contexto.")
        rows = ctx.db.search_memories(args.get("query", ""), limit=10)
        if not rows:
            return ToolResult(True, "Nada encontrado na memória.")
        return ToolResult(
            True,
            "\n".join(f"- [{r['id'][:8]}] {r['content']}" + (f" (tags: {r['tags']})" if r["tags"] else "") for r in rows),
        )


def build_memory_tools() -> list[Tool]:
    return [RememberTool(), RecallTool()]
