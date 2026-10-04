"""Tool abstractions shared by every OpenHUD tool.

A tool declares its JSON-schema parameters, whether it needs user
confirmation, and how to execute. The registry produces provider-agnostic
tool specs and enforces the confirmation gate.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..config import Settings


@dataclass
class ToolContext:
    """Everything a tool may need at execution time."""

    workspace_dir: Path
    settings: Settings
    secrets: Any = None  # SecretStore
    db: Any = None  # Database
    conversation_id: str | None = None
    autonomy: str = "supervised"  # supervised | autonomous
    allow_network: bool = True
    emit: Callable[[str, str], None] | None = None  # (kind, detail) -> None

    def log(self, kind: str, detail: str) -> None:
        if self.emit:
            self.emit(kind, detail)


@dataclass
class ToolResult:
    ok: bool
    output: str
    meta: dict[str, Any] = field(default_factory=dict)

    def to_text(self) -> str:
        prefix = "" if self.ok else "ERRO: "
        return prefix + self.output


class Tool(ABC):
    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    requires_confirmation: bool = False

    def spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    @abstractmethod
    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult: ...


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def specs(self, enabled: set[str] | None = None) -> list[dict[str, Any]]:
        tools = self._tools.values()
        if enabled is not None:
            tools = [t for t in tools if t.name in enabled]
        return [t.spec() for t in tools]

    def execute(self, name: str, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(False, f"Ferramenta desconhecida: {name}")
        try:
            return tool.run(args, ctx)
        except Exception as exc:  # tools must never crash the agent loop
            return ToolResult(False, f"{type(exc).__name__}: {exc}")
