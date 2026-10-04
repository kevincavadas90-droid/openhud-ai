"""Phase 4 REST API: voice, modes/personality, codex, plugins, media,
intelligence dashboard, privacy centre and admin diagnostics.

All endpoints sit behind the same session middleware as the rest of the app.
Nothing here fabricates results: providers report their real availability and
failures are returned with the underlying reason.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from ..config import settings
from ..core.modes import MODES, mode_public
from ..core.personality import STYLES, TRAITS, DEFAULT_TRAITS, Personality
from ..core.runtime import runtime
from ..media.images import ImageService

router = APIRouter(prefix="/api/ai")


# --------------------------------------------------------------------------
# payloads
# --------------------------------------------------------------------------
class VoicePatch(BaseModel):
    voice_enabled: bool | None = None
    voice_language: str | None = None
    voice_style: str | None = None
    voice_rate: str | None = None
    voice_pitch: str | None = None
    voice_provider: str | None = None
    voice_continuous: bool | None = None
    voice_wake_word: bool | None = None
    voice_wake_phrase: str | None = None
    voice_save_audio: bool | None = None
    voice_save_transcript: bool | None = None
    voice_save_history: bool | None = None
    voice_tts_voice: str | None = None


class SpeakPayload(BaseModel):
    text: str


class TranscriptPayload(BaseModel):
    text: str
    language: str | None = None
    conversation_id: str | None = None


class ModePayload(BaseModel):
    mode: str


class PersonalityPayload(BaseModel):
    traits: dict[str, int] | None = None
    style: str | None = None
    adaptive: bool | None = None


class CodexAnalyzePayload(BaseModel):
    path: str = "."


class CodexPlanPayload(BaseModel):
    objective: str
    path: str = "."


class ChangeOp(BaseModel):
    path: str
    content: str | None = None


class CodexChangesPayload(BaseModel):
    title: str
    changes: list[ChangeOp]


class CodexTestPayload(BaseModel):
    path: str = "."


class SandboxPayload(BaseModel):
    code: str
    language: str = "python"
    timeout: int = 30


class PluginInstallPayload(BaseModel):
    name: str
    acknowledge_risk: bool = False


class PluginTogglePayload(BaseModel):
    enabled: bool


class ImagePayload(BaseModel):
    prompt: str
    width: int = 1024
    height: int = 1024
    provider: str = "auto"
    model: str = "flux"
    seed: int | None = None


class VideoPayload(BaseModel):
    script: str
    images: list[str] = []
    voice: str = "pt-BR-FranciscaNeural"


class AudioPayload(BaseModel):
    text: str
    voice: str = "pt-BR-FranciscaNeural"
    style: str = "narrador"


class ExperiencePayload(BaseModel):
    action: str
    context: str = ""
    result: str = ""
    success: bool = True
    feedback: str = ""
    tags: str = ""


# --------------------------------------------------------------------------
# voice
# --------------------------------------------------------------------------
@router.get("/voice/status")
def voice_status() -> dict[str, Any]:
    return runtime.voice.status()


@router.put("/voice/config")
def voice_config(patch: VoicePatch) -> dict[str, Any]:
    data = {k: v for k, v in patch.model_dump().items() if v is not None}
    runtime.voice.update(data)
    return runtime.voice.status()


@router.post("/voice/speak")
def voice_speak(payload: SpeakPayload) -> Response:
    res = runtime.voice.speak(payload.text)
    if not res.get("ok"):
        raise HTTPException(502, detail={"error": res.get("error"), "attempts": res.get("attempts")})
    return Response(content=res["audio"], media_type=res["mime"],
                    headers={"X-Voice-Provider": res.get("provider", "")})


@router.post("/voice/transcribe")
async def voice_transcribe(request: Request) -> dict[str, Any]:
    """Server-side transcription of uploaded audio (best-effort)."""
    audio = await request.body()
    if not audio:
        raise HTTPException(400, "Áudio vazio")
    return runtime.voice.transcribe(audio)


@router.post("/voice/transcript")
def voice_transcript(payload: TranscriptPayload) -> dict[str, Any]:
    """Record a browser-produced transcript when the user opted in."""
    rec = runtime.voice.record_transcript(payload.text, payload.language or "", payload.conversation_id)
    return {"saved": rec is not None, "record": rec}


@router.get("/voice/history")
def voice_history(conversation_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    return runtime.voice.history(conversation_id, limit)


@router.delete("/voice/history")
def voice_history_clear(id: str | None = None) -> dict[str, Any]:
    return {"deleted": runtime.voice.clear_history(id)}


# --------------------------------------------------------------------------
# modes & personality
# --------------------------------------------------------------------------
@router.get("/modes")
def list_modes() -> dict[str, Any]:
    return {"modes": mode_public(), "current": runtime.get_settings().get("mode", "auto")}


@router.put("/mode")
def set_mode(payload: ModePayload) -> dict[str, Any]:
    if payload.mode not in MODES:
        raise HTTPException(400, f"Modo inválido. Use um de: {', '.join(MODES)}")
    runtime.update_settings({"mode": payload.mode})
    return {"mode": payload.mode}


@router.get("/personality")
def get_personality() -> dict[str, Any]:
    s = runtime.get_settings()
    traits = {**DEFAULT_TRAITS, **(s.get("personality") or {})}
    return {
        "traits": traits, "available_traits": TRAITS, "styles": list(STYLES),
        "style": s.get("personality_style", "natural"),
        "adaptive": bool(s.get("personality_adaptive", True)),
        "guidance": Personality(traits, s.get("personality_style", "natural")).guidance(),
    }


@router.put("/personality")
def set_personality(payload: PersonalityPayload) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if payload.traits is not None:
        clean = {k: max(0, min(100, int(v))) for k, v in payload.traits.items() if k in TRAITS}
        patch["personality"] = clean
    if payload.style is not None:
        if payload.style not in STYLES:
            raise HTTPException(400, f"Estilo inválido. Use um de: {', '.join(STYLES)}")
        patch["personality_style"] = payload.style
    if payload.adaptive is not None:
        patch["personality_adaptive"] = payload.adaptive
    runtime.update_settings(patch)
    return get_personality()


# --------------------------------------------------------------------------
# codex
# --------------------------------------------------------------------------
@router.post("/codex/analyze")
def codex_analyze(payload: CodexAnalyzePayload) -> dict[str, Any]:
    try:
        return runtime.codex.analyze(payload.path).to_dict()
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/codex/plan")
def codex_plan(payload: CodexPlanPayload) -> dict[str, Any]:
    try:
        analysis = runtime.codex.analyze(payload.path)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return runtime.codex.plan(payload.objective, analysis)


@router.post("/codex/changes")
def codex_propose(payload: CodexChangesPayload) -> dict[str, Any]:
    from ..codex import ChangeStore

    store = ChangeStore(settings.data_dir / "codex", settings.workspace_dir)
    try:
        cs = store.create(payload.title, [c.model_dump() for c in payload.changes])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return cs.to_dict()


@router.get("/codex/changes")
def codex_list_changes() -> list[dict[str, Any]]:
    from ..codex import ChangeStore

    store = ChangeStore(settings.data_dir / "codex", settings.workspace_dir)
    return store.list()


@router.get("/codex/changes/{cs_id}")
def codex_get_change(cs_id: str) -> dict[str, Any]:
    from ..codex import ChangeStore

    store = ChangeStore(settings.data_dir / "codex", settings.workspace_dir)
    cs = store.get(cs_id)
    if not cs:
        raise HTTPException(404, "Changeset não encontrado")
    return cs.to_dict()


@router.post("/codex/changes/{cs_id}/apply")
def codex_apply(cs_id: str) -> dict[str, Any]:
    from ..codex import ChangeStore

    store = ChangeStore(settings.data_dir / "codex", settings.workspace_dir)
    cs = store.get(cs_id)
    if not cs:
        raise HTTPException(404, "Changeset não encontrado")
    store.apply(cs)
    return cs.to_dict()


@router.post("/codex/changes/{cs_id}/reject")
def codex_reject(cs_id: str) -> dict[str, Any]:
    from ..codex import ChangeStore

    store = ChangeStore(settings.data_dir / "codex", settings.workspace_dir)
    cs = store.get(cs_id)
    if not cs:
        raise HTTPException(404, "Changeset não encontrado")
    store.reject(cs)
    return cs.to_dict()


@router.post("/codex/changes/{cs_id}/revert")
def codex_revert(cs_id: str) -> dict[str, Any]:
    from ..codex import ChangeStore

    store = ChangeStore(settings.data_dir / "codex", settings.workspace_dir)
    cs = store.get(cs_id)
    if not cs:
        raise HTTPException(404, "Changeset não encontrado")
    store.revert(cs)
    return cs.to_dict()


@router.post("/codex/test")
def codex_test(payload: CodexTestPayload) -> dict[str, Any]:
    return runtime.codex.run_tests(payload.path)


@router.post("/codex/sandbox")
def codex_sandbox(payload: SandboxPayload) -> dict[str, Any]:
    from ..codex.sandbox import SandboxLimits, run_python

    limits = SandboxLimits(timeout=min(payload.timeout, 120))
    result = run_python(payload.code, settings.workspace_dir, limits)
    return result.to_dict()


# --------------------------------------------------------------------------
# plugins
# --------------------------------------------------------------------------
@router.get("/plugins")
def list_plugins() -> dict[str, Any]:
    return runtime.plugins.store()


@router.get("/plugins/installed")
def installed_plugins() -> list[dict[str, Any]]:
    return runtime.plugins.list()


@router.post("/plugins/install")
def install_plugin(payload: PluginInstallPayload) -> dict[str, Any]:
    res = runtime.plugins.install(payload.name, acknowledge_risk=payload.acknowledge_risk)
    if not res.get("ok") and res.get("requires_ack"):
        raise HTTPException(409, detail=res)
    if not res.get("ok"):
        raise HTTPException(400, detail=res)
    return res


@router.put("/plugins/{name}")
def toggle_plugin(name: str, payload: PluginTogglePayload) -> dict[str, Any]:
    res = runtime.plugins.set_enabled(name, payload.enabled)
    if not res.get("ok"):
        raise HTTPException(400, detail=res)
    return res


@router.delete("/plugins/{name}")
def remove_plugin(name: str) -> dict[str, Any]:
    res = runtime.plugins.remove(name)
    if not res.get("ok"):
        raise HTTPException(400, detail=res)
    return res


# --------------------------------------------------------------------------
# media
# --------------------------------------------------------------------------
@router.get("/media/providers")
def media_providers() -> dict[str, Any]:
    return {
        "image": runtime.images.providers(),
        "video": runtime.video.providers(),
        "audio": runtime.audio.providers(),
    }


@router.post("/images/generate")
def images_generate(payload: ImagePayload) -> dict[str, Any]:
    res = runtime.images.generate(
        payload.prompt, width=payload.width, height=payload.height,
        provider=payload.provider, model=payload.model, seed=payload.seed,
    )
    if not res.get("ok"):
        raise HTTPException(502, detail=res)
    return res


@router.post("/video/render")
def video_render(payload: VideoPayload) -> dict[str, Any]:
    job = runtime.job_queue.submit("video", {
        "script": payload.script, "images": payload.images, "voice": payload.voice,
    })
    return {"job_id": job["id"], "status": job["status"]}


@router.get("/jobs")
def list_jobs(kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    return runtime.jobs.list(kind, limit)


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = runtime.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job não encontrado")
    return job


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    if not runtime.jobs.cancel(job_id):
        raise HTTPException(400, "Job não encontrado ou já finalizado")
    return {"cancelled": True}


@router.post("/audio/narrate")
def audio_narrate(payload: AudioPayload) -> dict[str, Any]:
    res = runtime.audio.narrate(payload.text, voice=payload.voice, style=payload.style)
    if not res.get("ok"):
        raise HTTPException(502, detail=res)
    return res


@router.get("/media/file")
def media_file(path: str) -> Response:
    """Serve a generated media file, restricted to the generated/ subtree."""
    from fastapi.responses import FileResponse

    base = (settings.workspace_dir / "generated").resolve()
    target = (settings.workspace_dir / path).resolve()
    if base != target and base not in target.parents:
        raise HTTPException(400, "Caminho fora da área de mídia")
    if not target.exists() or target.is_dir():
        raise HTTPException(404, "Arquivo não encontrado")
    return FileResponse(target)


# --------------------------------------------------------------------------
# intelligence dashboard
# --------------------------------------------------------------------------
@router.get("/intelligence")
def intelligence() -> dict[str, Any]:
    db = runtime.db
    stats = runtime.learning.stats()
    memories = db.list_memories()
    prefs = [m for m in memories if "prefer" in (m.get("tags") or "").lower()]
    experiences = runtime.learning.list(limit=100)
    tasks = db.list_tasks()

    # Tools used, from the activity log.
    tool_uses: dict[str, int] = {}
    for act in db.list_activities(limit=1000):
        if act["kind"] == "tool":
            tool_uses[act["detail"]] = tool_uses.get(act["detail"], 0) + 1
    failures = [e for e in experiences if not e["success"]]
    successes = [e for e in experiences if e["success"]]

    return {
        "success_rate": stats["success_rate"],
        "counts": stats,
        "memories": {"total": len(memories), "preferences": len(prefs)},
        "preferences": prefs[:20],
        "experiences": experiences[:30],
        "recurring_problems": _recurring(failures),
        "working_solutions": _recurring(successes),
        "tools_used": sorted(tool_uses.items(), key=lambda kv: kv[1], reverse=True)[:20],
        "tasks": {"total": len(tasks), "enabled": sum(1 for t in tasks if t["enabled"])},
        "modes": mode_public(),
    }


def _recurring(items: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for e in items:
        key = (e["action"] or "")[:80]
        counts[key] = counts.get(key, 0) + 1
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [{"action": k, "count": v} for k, v in top]


@router.post("/experiences")
def add_experience(payload: ExperiencePayload) -> dict[str, Any]:
    return runtime.learning.record(
        payload.action, payload.context, payload.result, payload.success, payload.feedback, payload.tags,
    )


# --------------------------------------------------------------------------
# privacy centre
# --------------------------------------------------------------------------
@router.get("/privacy/export")
def privacy_export() -> dict[str, Any]:
    db = runtime.db
    return {
        "settings": runtime.get_settings(),
        "memories": db.list_memories(),
        "experiences": runtime.learning.list(limit=1000),
        "voice_history": db.list_voice_history(limit=1000),
        "conversations": db.list_conversations(),
        "note": "Exportação de dados do operador. Não inclui segredos criptografados.",
    }


@router.delete("/privacy/memory")
def privacy_clear_memory() -> dict[str, Any]:
    db = runtime.db
    memories = db.list_memories()
    for m in memories:
        db.delete_memory(m["id"])
    return {"deleted": len(memories)}


@router.delete("/privacy/experiences")
def privacy_clear_experiences() -> dict[str, Any]:
    count = len(runtime.learning.list(limit=100000))
    runtime.db.execute("DELETE FROM experiences")
    return {"deleted": count}


# --------------------------------------------------------------------------
# admin / diagnostics
# --------------------------------------------------------------------------
@router.get("/diagnostics")
def diagnostics() -> dict[str, Any]:
    from ..core.diagnostics import run_diagnostics

    return run_diagnostics(runtime)


@router.get("/admin/overview")
def admin_overview() -> dict[str, Any]:
    from ..core.diagnostics import run_diagnostics

    diag = run_diagnostics(runtime)
    db = runtime.db
    activities = db.list_activities(limit=500)
    security_events = [a for a in activities if "error" in a["kind"] or "fail" in a["kind"]]
    provider_attempts: dict[str, dict[str, int]] = {}
    for a in activities:
        if a["kind"] in ("provider_ok", "provider_fail"):
            name = (a["detail"] or "").split(":")[0]
            slot = provider_attempts.setdefault(name, {"ok": 0, "fail": 0})
            slot["ok" if a["kind"] == "provider_ok" else "fail"] += 1
    return {
        "diagnostics": diag,
        "providers": provider_attempts,
        "plugins": runtime.plugins.list(),
        "jobs": runtime.jobs.list(limit=50),
        "tasks": db.list_tasks(),
        "security_events": security_events[:30],
        "usage": {
            "conversations": len(db.list_conversations()),
            "activities": len(activities),
        },
    }
