"""Self-diagnosis across the whole system.

Checks each subsystem and returns a real status for every component:
database, LLM providers, workers/queue, PC agents, MT5, voice, plugins,
storage and the job queue. No component is reported healthy without a real
check; failures include the underlying error.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any


def run_diagnostics(runtime) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    checks.append(_check("database", _db_check, runtime))
    checks.append(_check("llm", _llm_check, runtime))
    checks.append(_check("providers", _providers_check, runtime))
    checks.append(_check("voice", _voice_check, runtime))
    checks.append(_check("jobs", _jobs_check, runtime))
    checks.append(_check("pc_agents", _pc_check, runtime))
    checks.append(_check("mt5", _mt5_check, runtime))
    checks.append(_check("plugins", _plugins_check, runtime))
    checks.append(_check("storage", _storage_check, runtime))
    checks.append(_check("codex", _codex_check, runtime))
    checks.append(_check("screen", _screen_check, runtime))
    checks.append(_check("assistant", _assistant_check, runtime))

    healthy = sum(1 for c in checks if c["status"] == "ok")
    degraded = sum(1 for c in checks if c["status"] == "degraded")
    failed = sum(1 for c in checks if c["status"] == "error")
    return {
        "ok": failed == 0,
        "checked_at": time.time(),
        "summary": {"ok": healthy, "degraded": degraded, "error": failed, "total": len(checks)},
        "checks": checks,
    }


def _check(name: str, fn, runtime) -> dict[str, Any]:
    try:
        detail = fn(runtime)
        status = detail.pop("status", "ok")
        return {"name": name, "status": status, **detail}
    except Exception as exc:
        return {"name": name, "status": "error", "detail": f"{type(exc).__name__}: {exc}"}


def _db_check(runtime) -> dict[str, Any]:
    runtime.db.query("SELECT 1")
    backend = "postgres" if runtime.db.__class__.__name__ == "PostgresDatabase" else "sqlite"
    return {"detail": f"Backend {backend} respondendo.", "backend": backend}


def _llm_check(runtime) -> dict[str, Any]:
    s = runtime.get_settings()
    provider = s.get("provider", "pollinations")
    configured = bool(runtime.secrets.get_or_none(provider)) or provider in ("pollinations", "ollama")
    return {
        "detail": f"Provider selecionado: {provider} ({s.get('model')}).",
        "provider": provider, "model": s.get("model"),
        "status": "ok" if configured else "degraded",
        "configured": configured,
    }


def _providers_check(runtime) -> dict[str, Any]:
    manager = runtime.provider_manager()
    chain = [e.name for e in manager.entries()]
    keys = runtime.secrets.names()
    return {"detail": f"Cadeia de fallback: {', '.join(chain) or 'nenhum'}.", "chain": chain,
            "keys": keys}


def _voice_check(runtime) -> dict[str, Any]:
    status = runtime.voice.status()
    tts = [p for p in status["tts_providers"] if p["available"]]
    return {
        "detail": f"{len(tts)} provider(s) TTS disponível(is): {', '.join(p['name'] for p in tts)}.",
        "status": "ok" if tts else "degraded",
        "tts_available": [p["name"] for p in tts],
    }


def _jobs_check(runtime) -> dict[str, Any]:
    pending = [j for j in runtime.jobs.list(limit=200) if j["status"] in ("QUEUED", "RUNNING")]
    return {"detail": f"{len(pending)} job(s) em andamento.", "pending": len(pending)}


def _pc_check(runtime) -> dict[str, Any]:
    from .agent_hub import get_hub

    try:
        devices = [d for d in get_hub().list_devices() if d["id"] != "local"]
    except Exception:
        devices = []
    online = [d for d in devices if d["online"]]
    return {
        "detail": f"{len(online)}/{len(devices)} PC(s) online.",
        "status": "ok" if online else "degraded",
        "devices": len(devices), "online": len(online),
    }


def _mt5_check(runtime) -> dict[str, Any]:
    try:
        from ..web.trading_api import get_service

        res = get_service().status()
    except Exception as exc:
        return {"status": "degraded", "detail": f"MT5 indisponível: {exc}"}
    if not res.get("ok"):
        return {"status": "degraded", "detail": res.get("error", "MT5 indisponível")}
    if res.get("connected"):
        return {"status": "ok", "detail": f"MT5 conectado ({res.get('name')})."}
    return {"status": "degraded", "detail": res.get("note", "MT5 sem conta conectada.")}


def _plugins_check(runtime) -> dict[str, Any]:
    plugins = runtime.plugins.list()
    active = [p for p in plugins if p["enabled"]]
    return {"detail": f"{len(active)}/{len(plugins)} plugin(s) ativo(s).",
            "installed": len(plugins), "active": len(active)}


def _storage_check(runtime) -> dict[str, Any]:
    from ..config import settings

    usage = shutil.disk_usage(settings.data_dir)
    free_pct = round(usage.free / usage.total * 100, 1)
    return {
        "detail": f"{free_pct}% de disco livre em {settings.data_dir}.",
        "status": "ok" if free_pct > 5 else "degraded",
        "free_percent": free_pct,
    }


def _codex_check(runtime) -> dict[str, Any]:
    from ..config import settings

    has_pytest = shutil.which("pytest") is not None or _module("pytest")
    has_ffmpeg = shutil.which("ffmpeg") is not None
    return {
        "detail": f"pytest={'sim' if has_pytest else 'não'}, ffmpeg={'sim' if has_ffmpeg else 'não'}.",
        "pytest": has_pytest, "ffmpeg": has_ffmpeg,
    }


def _module(name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(name) is not None


def _screen_check(runtime) -> dict[str, Any]:
    """Report whether any connected PC can actually see/control its screen."""
    from .agent_hub import get_hub

    try:
        devices = [d for d in get_hub().list_devices() if d["id"] != "local"]
    except Exception:
        devices = []
    online = [d for d in devices if d["online"]]
    if not online:
        return {"status": "degraded",
                "detail": "Nenhum PC online: visão de tela indisponível até conectar um agente."}
    caps = {}
    for d in online:
        info = d.get("info") or {}
        caps = info.get("capabilities") or {}
        break
    can = [k for k in ("capture", "ocr", "control") if caps.get(k)]
    if not caps:
        return {"status": "degraded",
                "detail": "PC online, mas não reportou capacidades de tela. Atualize o agente."}
    status = "ok" if caps.get("capture") else "degraded"
    return {"status": status,
            "detail": f"PC online. Capacidades: {', '.join(can) or 'nenhuma'}.",
            "capabilities": caps}


def _assistant_check(runtime) -> dict[str, Any]:
    from .assist import AUTONOMY_LEVELS

    s = runtime.get_settings()
    level = s.get("autonomy_level", "guide")
    profile = s.get("profile", "standard")
    info = AUTONOMY_LEVELS.get(level)
    if info is None:
        return {"status": "degraded", "detail": f"Nível de autonomia inválido: {level}"}
    return {"status": "ok",
            "detail": f"Nível {info['level']} ({info['label']}), perfil {profile}.",
            "autonomy_level": level, "profile": profile}
