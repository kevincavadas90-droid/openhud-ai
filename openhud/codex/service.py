"""CODEX service: deterministic project analysis and test execution.

The autonomous *implementation* step is driven by the normal agent loop with
CODEX guidance (see the API layer). Everything in this module is real,
deterministic and testable without an LLM: static analysis of a project tree,
detection of test/dependency files, and running the project's test suite in
the sandbox with genuine pass/fail counts.

Nothing here fabricates results: if pytest is missing or fails, that is what
is returned.
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .sandbox import SandboxLimits, run_command

IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".mypy_cache"}
LANG_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".jsx": "JavaScript", ".html": "HTML", ".css": "CSS", ".java": "Java",
    ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP", ".cs": "C#",
    ".c": "C", ".cpp": "C++", ".sh": "Shell", ".sql": "SQL", ".json": "JSON",
    ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML",
}
DEP_FILES = ("requirements.txt", "pyproject.toml", "package.json", "Cargo.toml",
             "go.mod", "Gemfile", "pom.xml", "build.gradle", "composer.json")


@dataclass
class Analysis:
    root: str
    file_count: int = 0
    total_lines: int = 0
    languages: dict[str, int] = field(default_factory=dict)
    test_files: list[str] = field(default_factory=list)
    dependency_files: list[str] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)
    python_syntax_errors: list[dict[str, str]] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    tree: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root, "file_count": self.file_count, "total_lines": self.total_lines,
            "languages": self.languages, "test_files": self.test_files,
            "dependency_files": self.dependency_files, "entrypoints": self.entrypoints,
            "python_syntax_errors": self.python_syntax_errors, "findings": self.findings,
            "tree": self.tree[:200],
        }


class CodexService:
    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace)

    # -- analysis --------------------------------------------------------
    def analyze(self, project_path: str = ".") -> Analysis:
        root = self._resolve(project_path)
        analysis = Analysis(root=str(root))
        if not root.exists():
            analysis.findings.append(f"Caminho não encontrado: {root}")
            return analysis

        for path in self._walk(root):
            rel = str(path.relative_to(root))
            analysis.tree.append(rel)
            analysis.file_count += 1
            lang = LANG_BY_EXT.get(path.suffix.lower())
            if lang:
                analysis.languages[lang] = analysis.languages.get(lang, 0) + 1
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            analysis.total_lines += text.count("\n") + 1
            low = rel.lower()
            if re.search(r"(^|/)(test_|.*_test\.|tests?/)", low):
                analysis.test_files.append(rel)
            if path.name in DEP_FILES:
                analysis.dependency_files.append(rel)
            if path.name in ("main.py", "__main__.py", "app.py", "index.js", "server.py"):
                analysis.entrypoints.append(rel)
            if path.suffix == ".py":
                try:
                    ast.parse(text)
                except SyntaxError as exc:
                    analysis.python_syntax_errors.append({"path": rel, "error": f"linha {exc.lineno}: {exc.msg}"})

        if analysis.file_count == 0:
            analysis.findings.append("Projeto vazio.")
        if analysis.test_files:
            analysis.findings.append(f"{len(analysis.test_files)} arquivo(s) de teste encontrado(s).")
        else:
            analysis.findings.append("Nenhum teste encontrado — considere criar testes.")
        if analysis.python_syntax_errors:
            analysis.findings.append(f"{len(analysis.python_syntax_errors)} erro(s) de sintaxe Python.")
        if not analysis.dependency_files:
            analysis.findings.append("Nenhum arquivo de dependências detectado.")
        return analysis

    # -- plan ------------------------------------------------------------
    def plan(self, objective: str, analysis: Analysis | None = None) -> dict[str, Any]:
        steps = [
            "Analisar a estrutura e as dependências do projeto.",
            "Definir a arquitetura e os arquivos a criar/alterar.",
            "Implementar as mudanças (mostrando diff antes/depois).",
            "Executar os testes automatizados.",
            "Corrigir falhas encontradas e testar novamente.",
            "Documentar e entregar.",
        ]
        return {
            "objective": objective,
            "steps": steps,
            "detected": {
                "languages": (analysis.languages if analysis else {}),
                "has_tests": bool(analysis.test_files) if analysis else False,
            },
        }

    # -- tests -----------------------------------------------------------
    def run_tests(self, project_path: str = ".", timeout: int = 180) -> dict[str, Any]:
        cwd = self._resolve(project_path)
        if not cwd.exists():
            return {"ok": False, "error": f"Caminho não encontrado: {cwd}", "tests": None}
        result = run_command("python3 -m pytest -q", cwd, SandboxLimits(timeout=timeout, cpu_seconds=timeout))
        parsed = _parse_pytest(result.stdout + "\n" + result.stderr)
        return {
            "ok": result.ok, "exit_code": result.exit_code, "timed_out": result.timed_out,
            "stdout": result.stdout[-8000:], "stderr": result.stderr[-4000:],
            "tests": parsed, "error": result.error,
        }

    def _walk(self, root: Path):
        for path in sorted(root.rglob("*")):
            if any(part in IGNORE_DIRS for part in path.parts):
                continue
            if path.is_file():
                yield path

    def _resolve(self, rel: str) -> Path:
        workspace = self.workspace.resolve()
        target = (workspace / rel).resolve() if not Path(rel).is_absolute() else Path(rel).resolve()
        if target != workspace and workspace not in target.parents:
            raise ValueError(f"Caminho fora do workspace: {rel}")
        return target


def _parse_pytest(output: str) -> dict[str, Any] | None:
    """Extract real pass/fail counts from pytest's summary line."""
    m = re.search(r"(\d+) passed", output)
    f = re.search(r"(\d+) failed", output)
    e = re.search(r"(\d+) error", output)
    if not (m or f or e):
        return None
    return {
        "passed": int(m.group(1)) if m else 0,
        "failed": int(f.group(1)) if f else 0,
        "errors": int(e.group(1)) if e else 0,
    }
