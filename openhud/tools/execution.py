"""Code execution tools: shell commands and Python.

Commands run inside the workspace with a hard timeout. Destructive patterns
are refused unless the user has explicitly enabled unrestricted mode.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from .base import Tool, ToolContext, ToolResult

# Runner that executes a script and, if its final statement is an expression
# (e.g. ``21 * 2``), prints that value. This makes REPL-style snippets behave
# as users and models expect, instead of silently producing no output.
_PY_RUNNER = (
    "import ast, sys\n"
    "path = sys.argv[1]\n"
    "code = open(path, encoding='utf-8').read()\n"
    "tree = ast.parse(code, filename=path)\n"
    "ns = {'__name__': '__main__'}\n"
    "if tree.body and isinstance(tree.body[-1], ast.Expr):\n"
    "    last = tree.body.pop()\n"
    "    exec(compile(tree, path, 'exec'), ns)\n"
    "    value = eval(compile(ast.Expression(last.value), path, 'eval'), ns)\n"
    "    if value is not None:\n"
    "        print(repr(value))\n"
    "else:\n"
    "    exec(compile(tree, path, 'exec'), ns)\n"
)

# Patterns that are always refused regardless of autonomy level. These are
# destructive or affect the host beyond the sandbox. The list is deliberately
# conservative: it blocks catastrophes, not normal development work.
BLOCKED_PATTERNS = [
    "rm -rf /",
    "mkfs",
    "dd if=/dev/zero",
    ":(){:|:&};:",
    "shutdown",
    "reboot",
    "> /dev/sda",
]


def _looks_destructive(command: str) -> str | None:
    lowered = command.lower()
    for pattern in BLOCKED_PATTERNS:
        if pattern in lowered:
            return pattern
    return None


class ShellTool(Tool):
    name = "run_shell"
    description = (
        "Executa um comando de shell no diretório de workspace e retorna a saída. "
        "Use para instalar dependências, rodar testes, git, etc."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Comando a executar."},
            "timeout": {"type": "integer", "description": "Timeout em segundos.", "default": 120},
        },
        "required": ["command"],
    }
    requires_confirmation = True

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        command = args.get("command", "").strip()
        if not command:
            return ToolResult(False, "Comando vazio.")
        blocked = _looks_destructive(command)
        if blocked:
            return ToolResult(False, f"Comando bloqueado por segurança (padrão proibido: {blocked}).")
        timeout = min(int(args.get("timeout", ctx.settings.shell_timeout)), 600)
        ctx.log("shell", command)
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(ctx.workspace_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(False, f"Comando excedeu o timeout de {timeout}s.")
        output = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        output = output.strip() or "(sem saída)"
        if len(output) > 20000:
            output = output[:20000] + "\n...[truncado]"
        return ToolResult(proc.returncode == 0, output, {"returncode": proc.returncode})


class PythonTool(Tool):
    name = "run_python"
    description = (
        "Executa código Python em um subprocesso isolado e retorna stdout/stderr. "
        "Se a última instrução for uma expressão (ex.: 21*2), o valor é impresso."
    )
    parameters = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Código Python a executar."},
            "timeout": {"type": "integer", "default": 60},
        },
        "required": ["code"],
    }
    requires_confirmation = True

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        code = args.get("code", "")
        if not code.strip():
            return ToolResult(False, "Código vazio.")
        timeout = min(int(args.get("timeout", 60)), 600)
        ctx.log("python", f"executando {len(code)} bytes de código")
        with tempfile.NamedTemporaryFile(
            "w", suffix=".py", dir=str(ctx.workspace_dir), delete=False, encoding="utf-8"
        ) as fh:
            fh.write(code)
            script_path = fh.name
        try:
            proc = subprocess.run(
                [sys.executable, "-c", _PY_RUNNER, script_path],
                cwd=str(ctx.workspace_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(False, f"Código excedeu o timeout de {timeout}s.")
        finally:
            try:
                Path(script_path).unlink()
            except OSError:
                pass
        output = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        output = output.strip() or "(sem saída)"
        if len(output) > 20000:
            output = output[:20000] + "\n...[truncado]"
        return ToolResult(proc.returncode == 0, output, {"returncode": proc.returncode})


def build_execution_tools() -> list[Tool]:
    return [ShellTool(), PythonTool()]
