"""Data analysis tools: summarize CSV/JSON files in the workspace.

Uses only the standard library so there is no heavy dependency. Produces a
shape, column list, sample rows and numeric summary that the agent can reason
about or turn into a report.
"""
from __future__ import annotations

import csv
import io
import json
import statistics
from pathlib import Path

from .base import Tool, ToolContext, ToolResult
from .filesystem import _resolve


def _load_rows(path: Path) -> list[dict]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            raise ValueError("JSON deve ser uma lista de objetos")
        return [r if isinstance(r, dict) else {"value": r} for r in data]
    text = path.read_text(encoding="utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def _to_number(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class AnalyzeDataTool(Tool):
    name = "analyze_data"
    description = (
        "Analisa um arquivo CSV ou JSON do workspace: número de linhas/colunas, "
        "colunas, amostra e estatísticas das colunas numéricas."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "sample": {"type": "integer", "default": 5},
        },
        "required": ["path"],
    }

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        path = _resolve(ctx, args["path"])
        if not path.exists() or path.is_dir():
            return ToolResult(False, f"Arquivo não encontrado: {args['path']}")
        try:
            rows = _load_rows(path)
        except (ValueError, json.JSONDecodeError, csv.Error) as exc:
            return ToolResult(False, f"Falha ao ler dados: {exc}")
        if not rows:
            return ToolResult(True, "Arquivo sem linhas de dados.")

        columns: list[str] = []
        for row in rows:
            for key in row:
                if key not in columns:
                    columns.append(key)

        lines = [f"Arquivo: {args['path']}", f"Linhas: {len(rows)}", f"Colunas ({len(columns)}): {', '.join(columns)}"]

        sample = rows[: int(args.get("sample", 5))]
        lines.append("\nAmostra:")
        for row in sample:
            lines.append("  " + json.dumps(row, ensure_ascii=False))

        lines.append("\nResumo numérico:")
        for col in columns:
            values = [_to_number(r.get(col)) for r in rows]
            numbers = [v for v in values if v is not None]
            if not numbers:
                continue
            lines.append(
                f"  {col}: n={len(numbers)} min={min(numbers):g} "
                f"max={max(numbers):g} média={statistics.fmean(numbers):.4g} "
                f"mediana={statistics.median(numbers):g}"
            )
        ctx.log("data", f"Analisado {args['path']} ({len(rows)} linhas)")
        return ToolResult(True, "\n".join(lines))


def build_data_tools() -> list[Tool]:
    return [AnalyzeDataTool()]
