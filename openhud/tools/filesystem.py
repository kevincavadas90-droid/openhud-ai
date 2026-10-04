"""Filesystem tools, sandboxed to the workspace directory.

Every path is resolved and checked to stay inside the workspace, so the
agent can read, write and list files without escaping its sandbox.
"""
from __future__ import annotations

from pathlib import Path

from .base import Tool, ToolContext, ToolResult


def _resolve(ctx: ToolContext, raw: str) -> Path:
    candidate = (ctx.workspace_dir / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
    workspace = ctx.workspace_dir.resolve()
    if workspace != candidate and workspace not in candidate.parents:
        raise ValueError(f"Caminho fora do workspace permitido: {raw}")
    return candidate


def _rel(ctx: ToolContext, path: Path) -> str:
    try:
        return str(path.relative_to(ctx.workspace_dir.resolve()))
    except ValueError:
        return str(path)


class ReadFileTool(Tool):
    name = "read_file"
    description = "Lê o conteúdo de um arquivo de texto dentro do workspace."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Caminho relativo ao workspace."},
            "max_bytes": {"type": "integer", "description": "Limite de bytes a ler.", "default": 200000},
        },
        "required": ["path"],
    }

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        path = _resolve(ctx, args["path"])
        if not path.exists():
            return ToolResult(False, f"Arquivo não encontrado: {args['path']}")
        if path.is_dir():
            return ToolResult(False, f"{args['path']} é um diretório; use list_files.")
        limit = int(args.get("max_bytes", 200000))
        data = path.read_bytes()[:limit]
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return ToolResult(False, f"Arquivo binário ({len(data)} bytes); leitura como texto não suportada.")
        truncated = path.stat().st_size > limit
        return ToolResult(True, text + ("\n...[truncado]" if truncated else ""))


class WriteFileTool(Tool):
    name = "write_file"
    description = "Cria ou sobrescreve um arquivo de texto dentro do workspace."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "append": {"type": "boolean", "default": False},
        },
        "required": ["path", "content"],
    }
    requires_confirmation = True

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        path = _resolve(ctx, args["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        content = args.get("content", "")
        if args.get("append"):
            with path.open("a", encoding="utf-8") as fh:
                fh.write(content)
        else:
            path.write_text(content, encoding="utf-8")
        ctx.log("file", f"Escrito {_rel(ctx, path)} ({len(content)} bytes)")
        return ToolResult(True, f"Arquivo salvo: {_rel(ctx, path)} ({len(content)} bytes)")


class ListFilesTool(Tool):
    name = "list_files"
    description = "Lista arquivos e diretórios dentro do workspace."
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "default": "."}},
    }

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        base = _resolve(ctx, args.get("path", "."))
        if not base.exists():
            return ToolResult(False, f"Caminho não encontrado: {args.get('path')}")
        lines = []
        for entry in sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name)):
            kind = "dir " if entry.is_dir() else "file"
            size = "" if entry.is_dir() else f" ({entry.stat().st_size}b)"
            lines.append(f"{kind}  {entry.name}{size}")
        return ToolResult(True, "\n".join(lines) or "(vazio)")


class DeleteFileTool(Tool):
    name = "delete_file"
    description = "Remove um arquivo dentro do workspace. Requer confirmação."
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    requires_confirmation = True

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        path = _resolve(ctx, args["path"])
        if not path.exists():
            return ToolResult(False, f"Arquivo não encontrado: {args['path']}")
        if path.is_dir():
            return ToolResult(False, "delete_file só remove arquivos, não diretórios.")
        path.unlink()
        ctx.log("file", f"Removido {_rel(ctx, path)}")
        return ToolResult(True, f"Removido: {_rel(ctx, path)}")


def build_filesystem_tools() -> list[Tool]:
    return [ReadFileTool(), WriteFileTool(), ListFilesTool(), DeleteFileTool()]
