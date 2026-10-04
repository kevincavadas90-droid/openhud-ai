"""Computer-assistant REST API (Phase 5).

Exposes the assistant policy surfaces to the SPA: user profiles, autonomy
levels, accessibility preferences, live task state with cancel/pause, the
control centre (devices / tasks / security / health), screen-analysis and
input-control proxies, and the privacy statement.

Everything here is honest about availability: endpoints that need a connected
PC return the real reason when none is present, and never fabricate a result.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import settings
from ..core.accessibility import DEFAULTS as A11Y_DEFAULTS, from_settings as a11y_from_settings, labels as a11y_labels
from ..core.assist import (
    AUTONOMY_LEVELS,
    PROFILES,
    controller as task_controller,
    detect_control_phrase,
)
from ..core.runtime import runtime
from ..core.scam_guard import analyze_text

router = APIRouter(prefix="/api/assistant")


# --------------------------------------------------------------------------
# payloads
# --------------------------------------------------------------------------
class ProfilePayload(BaseModel):
    profile: str


class AutonomyPayload(BaseModel):
    level: str


class AccessibilityPayload(BaseModel):
    large_text: bool | None = None
    big_buttons: bool | None = None
    high_contrast: bool | None = None
    read_aloud: bool | None = None
    calm_voice: bool | None = None
    simple_language: bool | None = None


class TaskActionPayload(BaseModel):
    action: str  # cancel | pause | resume


class CommandPayload(BaseModel):
    command: str
    args: dict[str, Any] = {}


class ScamPayload(BaseModel):
    text: str = ""
    url: str = ""


class UpdateCheckPayload(BaseModel):
    manifest_url: str | None = None


class DevicePayload(BaseModel):
    device_id: str | None = None


# --------------------------------------------------------------------------
# profiles / autonomy / accessibility
# --------------------------------------------------------------------------
@router.get("/profiles")
def list_profiles() -> dict[str, Any]:
    return {"profiles": [{"key": k, **v} for k, v in PROFILES.items()],
            "current": runtime.get_settings().get("profile", "standard")}


@router.put("/profile")
def set_profile(payload: ProfilePayload) -> dict[str, Any]:
    if payload.profile not in PROFILES:
        raise HTTPException(400, f"Perfil inválido. Use um de: {', '.join(PROFILES)}")
    runtime.update_settings({"profile": payload.profile})
    # Choosing the accessibility profile turns on its UI helpers by default.
    if payload.profile == "accessibility":
        cur = a11y_from_settings(runtime.get_settings())
        cur.update({"large_text": True, "big_buttons": True, "high_contrast": True, "calm_voice": True})
        runtime.update_settings({"accessibility": cur})
    return {"profile": payload.profile}


@router.get("/autonomy")
def get_autonomy() -> dict[str, Any]:
    return {"levels": [{"key": k, **v} for k, v in AUTONOMY_LEVELS.items()],
            "current": runtime.get_settings().get("autonomy_level", "guide")}


@router.put("/autonomy")
def set_autonomy(payload: AutonomyPayload) -> dict[str, Any]:
    if payload.level not in AUTONOMY_LEVELS:
        raise HTTPException(400, f"Nível inválido. Use um de: {', '.join(AUTONOMY_LEVELS)}")
    runtime.update_settings({"autonomy_level": payload.level})
    return {"level": payload.level}


@router.get("/accessibility")
def get_accessibility() -> dict[str, Any]:
    return {"preferences": a11y_from_settings(runtime.get_settings()),
            "available": list(A11Y_DEFAULTS), "labels": a11y_labels()}


@router.put("/accessibility")
def set_accessibility(payload: AccessibilityPayload) -> dict[str, Any]:
    current = a11y_from_settings(runtime.get_settings())
    for k, v in payload.model_dump().items():
        if v is not None and k in A11Y_DEFAULTS:
            current[k] = bool(v)
    runtime.update_settings({"accessibility": current})
    return {"preferences": current}


# --------------------------------------------------------------------------
# task state + control (cancel / pause / resume)
# --------------------------------------------------------------------------
@router.get("/tasks")
def list_task_states() -> list[dict[str, Any]]:
    return task_controller.list()


@router.get("/tasks/{conversation_id}")
def get_task_state(conversation_id: str) -> dict[str, Any]:
    rec = task_controller.get(conversation_id)
    if rec is None:
        return {"conversation_id": conversation_id, "state": "idle", "label": "SEM TAREFA"}
    return rec.to_dict()


@router.post("/tasks/{conversation_id}/action")
def task_action(conversation_id: str, payload: TaskActionPayload) -> dict[str, Any]:
    action = payload.action
    if action == "cancel":
        ok = task_controller.request_cancel(conversation_id)
    elif action == "pause":
        ok = task_controller.request_pause(conversation_id, True)
    elif action == "resume":
        ok = task_controller.request_pause(conversation_id, False)
    else:
        raise HTTPException(400, "Ação inválida. Use cancel, pause ou resume.")
    return {"ok": ok, "action": action}


@router.post("/control-phrase")
def control_phrase(payload: ScamPayload) -> dict[str, Any]:
    """Detect a spoken 'pare'/'cancela'/'pausa' command without running a turn."""
    phrase = detect_control_phrase(payload.text)
    return {"phrase": phrase}


# --------------------------------------------------------------------------
# scam check
# --------------------------------------------------------------------------
@router.post("/scam-check")
def scam_check(payload: ScamPayload) -> dict[str, Any]:
    return analyze_text(payload.text, payload.url).to_dict()


# --------------------------------------------------------------------------
# screen analysis / control proxies (require a connected PC)
# --------------------------------------------------------------------------
def _first_device() -> str:
    from ..core.agent_hub import get_hub

    hub = get_hub()
    devices = [d for d in hub.list_devices() if d["id"] != "local"]
    online = [d for d in devices if d["online"]]
    chosen = online or devices
    if not chosen:
        raise HTTPException(503, "Nenhum computador conectado. Abra o OpenHUD Agent no PC.")
    return chosen[0]["id"]


@router.post("/screen/analyze")
def screen_analyze(payload: DevicePayload) -> dict[str, Any]:
    from ..core.agent_hub import get_hub

    device_id = payload.device_id or _first_device()
    try:
        res = get_hub().request(device_id, "screen_analyze", {}, timeout=45.0)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except (TimeoutError, RuntimeError) as exc:
        raise HTTPException(504, str(exc))
    if not res.get("ok"):
        raise HTTPException(502, res.get("error", "Falha ao analisar a tela."))
    return res


@router.post("/screen/find")
def screen_find(payload: CommandPayload, device_id: str | None = None) -> dict[str, Any]:
    from ..core.agent_hub import get_hub

    dev = device_id or _first_device()
    try:
        res = get_hub().request(dev, "screen_find", payload.args, timeout=45.0)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except (TimeoutError, RuntimeError) as exc:
        raise HTTPException(504, str(exc))
    if not res.get("ok"):
        raise HTTPException(502, res.get("error", "Falha ao procurar o elemento."))
    return res


@router.post("/screen/highlight")
def screen_highlight(payload: CommandPayload, device_id: str | None = None) -> dict[str, Any]:
    from ..core.agent_hub import get_hub

    dev = device_id or _first_device()
    try:
        res = get_hub().request(dev, "screen_highlight", payload.args, timeout=45.0)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except (TimeoutError, RuntimeError) as exc:
        raise HTTPException(504, str(exc))
    if not res.get("ok"):
        raise HTTPException(502, res.get("error", "Falha ao destacar o elemento."))
    return res


@router.get("/screen/capabilities")
def screen_capabilities(device_id: str | None = None) -> dict[str, Any]:
    from ..core.agent_hub import get_hub

    hub = get_hub()
    devices = [d for d in hub.list_devices() if d["id"] != "local"]
    if not devices:
        return {"ok": False, "error": "Nenhum PC pareado.", "devices": []}
    out = []
    for d in devices:
        caps = (d.get("info") or {}).get("capabilities") or {}
        out.append({"device_id": d["id"], "name": d["name"], "online": d["online"],
                    "permissions": {k: d["permissions"].get(k) for k in ("screen", "control")},
                    "capabilities": caps})
    return {"ok": True, "devices": out}


# --------------------------------------------------------------------------
# control centre (Part 24) and automatic diagnostics (Part 25)
# --------------------------------------------------------------------------
@router.get("/control-center")
def control_center() -> dict[str, Any]:
    from ..core.diagnostics import run_diagnostics
    from ..core.agent_hub import get_hub

    db = runtime.db
    try:
        devices = get_hub().list_devices()
    except Exception:
        devices = []

    activities = db.list_activities(limit=1000)
    sensitive = [a for a in activities if a["kind"] in
                 ("confirmation", "auto_approve", "blocked", "injection_warning", "scam_warning")]
    security = [a for a in activities if a["kind"] in
                ("error", "blocked", "confirmation", "auto_approve", "provider_fail",
                 "injection_warning", "scam_warning")]
    jobs = runtime.jobs.list(limit=100)

    return {
        "devices": [
            {
                "id": d["id"], "name": d["name"], "platform": d["platform"],
                "online": d["online"], "last_seen": d["last_seen"],
                "info": d.get("info") or {},
                "permissions": d.get("permissions") or {},
            }
            for d in devices
        ],
        "tasks": {
            "live": task_controller.list(),
            "scheduled": db.list_tasks(),
            "jobs": [{"id": j["id"], "kind": j["kind"], "status": j["status"],
                      "progress": j["progress"], "error": j.get("error"),
                      "created_at": j["created_at"]} for j in jobs],
        },
        "security": {
            "sensitive_actions": sensitive[-30:],
            "events": security[-40:],
        },
        "health": run_diagnostics(runtime),
    }


@router.get("/diagnose")
def diagnose_assistant() -> dict[str, Any]:
    """Plain-language diagnosis of the assistant's moving parts (Part 25)."""
    from ..core.agent_hub import get_hub
    from ..core.diagnostics import run_diagnostics

    diag = run_diagnostics(runtime)
    problems: list[dict[str, str]] = []
    fixes: list[str] = []

    checks = {c["name"]: c for c in diag["checks"]}
    if checks.get("pc_agents", {}).get("status") != "ok":
        problems.append({"area": "PC Agent", "detail": checks.get("pc_agents", {}).get("detail", "")})
        fixes.append("Abra o OpenHUD Agent no computador e faça o pareamento em 'Conectar PC'.")
    if checks.get("screen", {}).get("status") != "ok":
        problems.append({"area": "Visão de tela", "detail": checks.get("screen", {}).get("detail", "")})
        fixes.append("Instale 'mss', 'pytesseract' e 'pyautogui' no PC e conceda a permissão 'screen'.")
    if checks.get("llm", {}).get("status") != "ok":
        problems.append({"area": "Modelo de IA", "detail": checks.get("llm", {}).get("detail", "")})
        fixes.append("Adicione uma chave de provedor em Configurações ou use o provedor sem chave.")
    if checks.get("voice", {}).get("status") != "ok":
        problems.append({"area": "Voz", "detail": checks.get("voice", {}).get("detail", "")})
        fixes.append("A voz usa o navegador por padrão; instale 'edge-tts' no servidor para TTS neural.")
    if checks.get("database", {}).get("status") != "ok":
        problems.append({"area": "Banco de dados", "detail": checks.get("database", {}).get("detail", "")})
        fixes.append("Verifique DATABASE_URL ou o disco em OPENHUD_DATA_DIR.")
    return {
        "ok": not problems,
        "problems": problems,
        "suggested_fixes": fixes,
        "checks": diag["checks"],
    }


@router.get("/privacy")
def privacy_statement() -> dict[str, Any]:
    """Machine-readable privacy statement (also rendered by the SPA)."""
    return {
        "data_on_pc": [
            "Métricas de hardware (CPU, RAM, GPU, disco, rede, processos) quando você concede cada categoria.",
            "Capturas de tela apenas quando a permissão 'screen' está ativa e você pede a análise.",
            "O token do dispositivo fica no PC; o servidor guarda só o hash.",
        ],
        "data_on_server": [
            "Conversas, memória de longo prazo, experiências e configurações.",
            "Chaves de API criptografadas (Fernet); nunca em texto puro e nunca no front-end.",
            "Registro de atividades e de ações sensíveis para auditoria.",
        ],
        "screen_capture": (
            "A captura ocorre no PC. A imagem é processada para descrever a tela; nada é "
            "gravado continuamente. Sem a permissão 'screen', a captura é recusada."
        ),
        "pc_commands": (
            "Os comandos vão do servidor ao PC pelo WebSocket; o PC só executa o que as "
            "permissões concedidas permitem. Controle de mouse/teclado exige 'control'."
        ),
        "memory": "Você pode ver, editar e apagar a memória, as experiências e o histórico de voz.",
        "delete_data": "Use a aba Privacidade para exportar ou apagar seus dados.",
        "disconnect": "Revogue o dispositivo na aba Conectar PC para cortar o acesso do computador.",
        "defaults": {
            "screen_permission": False,
            "control_permission": False,
            "save_audio": False,
            "save_voice_history": False,
            "autonomy_level": runtime.get_settings().get("autonomy_level", "guide"),
        },
        "workspace": str(settings.workspace_dir),
    }


# --------------------------------------------------------------------------
# updates (Part 19) — check only; never auto-runs anything
# --------------------------------------------------------------------------
@router.get("/update/version")
def update_version() -> dict[str, Any]:
    from .. import __version__

    return {"version": __version__}


@router.post("/update/check")
def update_check(payload: UpdateCheckPayload) -> dict[str, Any]:
    from .. import __version__
    from ..core.updates import check_for_update

    url = payload.manifest_url or runtime.get_settings().get("update_url", "")
    info = check_for_update(__version__, url)
    return info.to_dict()


@router.post("/update/download")
def update_download(payload: CommandPayload) -> dict[str, Any]:
    """Download one verified artifact for manual installation. Never executes it."""
    from ..core.updates import download_artifact

    url = payload.args.get("url", "")
    sha = payload.args.get("sha256", "")
    if not url:
        raise HTTPException(400, "Informe a URL do artefato.")
    res = download_artifact(url, sha, settings.data_dir / "updates")
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "Falha no download."))
    return res


# --------------------------------------------------------------------------
# maintenance (Part 21): backup / restore / schema version
# --------------------------------------------------------------------------
@router.get("/maintenance/backups")
def list_backups() -> list[dict[str, Any]]:
    from ..core.maintenance import list_backups as _list

    return _list(settings.data_dir)


@router.post("/maintenance/backup")
def create_backup() -> dict[str, Any]:
    from ..core.maintenance import create_backup as _create

    res = _create(runtime.db, settings.data_dir)
    if not res.get("ok"):
        raise HTTPException(500, res.get("error", "Falha ao criar backup."))
    return res


@router.post("/maintenance/restore")
def restore_backup(payload: CommandPayload) -> dict[str, Any]:
    from ..core.maintenance import restore_backup as _restore

    name = payload.args.get("name", "")
    if not name:
        raise HTTPException(400, "Informe o nome do backup.")
    res = _restore(runtime.db, settings.data_dir, name)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "Falha ao restaurar."))
    return res


@router.get("/maintenance/schema")
def schema_version() -> dict[str, Any]:
    from ..core.maintenance import SCHEMA_VERSION

    return {"schema_version": runtime.db.get_setting("schema_version", SCHEMA_VERSION),
            "current": SCHEMA_VERSION}
