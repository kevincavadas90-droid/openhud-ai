"""Sandboxed execution for generated code.

Best-effort isolation using OS resource limits (CPU time, address space,
file size, process count) plus a wall-clock timeout. This is *not* a
security boundary on the same level as a container or VM, and network access
cannot be blocked here without root/namespaces — that limitation is reported
honestly rather than hidden.

Commands run inside the workspace directory only. The caller decides what to
run; this module never grants extra privileges.
"""
from __future__ import annotations

import os
import resource
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SandboxLimits:
    timeout: int = 30
    cpu_seconds: int = 20
    memory_mb: int = 512
    max_file_mb: int = 16
    max_processes: int = 64
    network_isolation: bool = False  # not enforceable without root here


@dataclass
class SandboxResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    timed_out: bool = False
    limits: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "stdout": self.stdout, "stderr": self.stderr,
            "exit_code": self.exit_code, "timed_out": self.timed_out,
            "limits": self.limits, "error": self.error,
        }


def _preexec(limits: SandboxLimits):  # pragma: no cover - runs in child process
    def _apply() -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
        mem = limits.memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        fsize = limits.max_file_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
        # RLIMIT_NPROC counts processes per real UID across the whole host, so
        # in a shared-UID container it can be lower than what already exists and
        # make every fork fail. Only apply it when it is safely above current usage.
        if limits.max_processes > 0:
            try:
                current = len(os.listdir("/proc"))
                if limits.max_processes > current + 16:
                    resource.setrlimit(resource.RLIMIT_NPROC,
                                       (limits.max_processes, limits.max_processes))
            except (ValueError, OSError):
                pass
        os.setsid()

    return _apply


def run_command(command: str, cwd: Path, limits: SandboxLimits | None = None) -> SandboxResult:
    """Run a shell command inside ``cwd`` with resource limits."""
    limits = limits or SandboxLimits()
    cwd = Path(cwd).resolve()
    if not cwd.exists():
        return SandboxResult(False, error=f"Diretório não existe: {cwd}")
    meta = {
        "timeout_s": limits.timeout, "cpu_s": limits.cpu_seconds,
        "memory_mb": limits.memory_mb, "max_file_mb": limits.max_file_mb,
        "network_isolation": limits.network_isolation,
        "note": "Isolamento de rede não é aplicável neste ambiente (requer root/namespaces).",
    }
    try:
        proc = subprocess.run(
            command, shell=True, cwd=str(cwd), capture_output=True, text=True,
            timeout=limits.timeout, preexec_fn=_preexec(limits),
        )
    except subprocess.TimeoutExpired as exc:
        return SandboxResult(False, _dec(exc.stdout), _dec(exc.stderr), None, True, meta,
                             f"Timeout de {limits.timeout}s excedido.")
    except Exception as exc:
        return SandboxResult(False, error=f"{type(exc).__name__}: {exc}", limits=meta)
    return SandboxResult(
        proc.returncode == 0, proc.stdout[-20000:], proc.stderr[-8000:],
        proc.returncode, False, meta,
        "" if proc.returncode == 0 else f"Comando terminou com código {proc.returncode}.",
    )


def run_python(code: str, cwd: Path, limits: SandboxLimits | None = None) -> SandboxResult:
    """Run a Python snippet with the workspace on sys.path."""
    import tempfile

    limits = limits or SandboxLimits()
    with tempfile.NamedTemporaryFile("w", suffix=".py", dir=str(Path(cwd)), delete=False) as tmp:
        tmp.write(code)
        path = tmp.name
    try:
        env_prefix = f"PYTHONPATH={cwd} "
        return run_command(f"{env_prefix}{sys.executable} {path}", cwd, limits)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _dec(data) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", "replace")
    return str(data)
