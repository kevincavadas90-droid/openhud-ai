"""FastAPI application: REST API, SSE streaming and the web UI.

The agent loop is blocking, so each turn runs in a worker thread and its
events are streamed to the browser over Server-Sent Events.
"""
from __future__ import annotations

import json
import os
import queue
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..agent.confirm import broker
from ..agent.loop import Agent
from ..agent.scheduler import scheduler
from ..config import settings
from ..core.agent_hub import init_hub
from ..core.llm import DEFAULT_BASE_URLS
from ..core.providers import KEYLESS_PROVIDERS
from ..core.runtime import KEYED_PROVIDERS, runtime
from .accounts_api import ACCOUNT_PUBLIC_PATHS, init_accounts
from .accounts_api import router as accounts_router
from .agent_api import router as agent_router
from .ai_api import router as ai_router
from .assistant_api import router as assistant_router
from .auth import COOKIE_NAME, SESSION_TTL, AuthManager
from .ratelimit import chat_limiter, login_limiter
from .site import PUBLIC_SITE_PATHS, router as site_router
from .trading_api import router as trading_router

auth = AuthManager(settings.data_dir)
hub = init_hub(runtime.db)
accounts = init_accounts(runtime.db)


@asynccontextmanager
async def lifespan(_: FastAPI):
    scheduler.start()
    runtime.start_workers()
    yield
    scheduler.stop()
    runtime.job_queue.stop()


app = FastAPI(title="OpenHUD AI", version="5.1.1", lifespan=lifespan)

# CORS is opt-in and never wildcard-by-default: the browser UI is same-origin,
# so CORS only matters for a separately hosted front-end or the desktop client.
# Set OPENHUD_CORS_ORIGINS to a comma-separated allow-list to enable it.
_cors_origins = settings.cors_origins
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Authorization"],
    )

app.include_router(agent_router)
app.include_router(trading_router)
app.include_router(ai_router)
app.include_router(assistant_router)
app.include_router(accounts_router)
app.include_router(site_router)
agent = Agent(runtime)
db = runtime.db


# Public paths that never require a session (login flow + marketing site +
# assets + health). The site router lists its own public paths so they stay in
# sync in one place.
PUBLIC_PATHS = {"/login", "/api/login", "/api/health", "/health", "/ready",
                "/favicon.ico", "/ws/agent"} | PUBLIC_SITE_PATHS | ACCOUNT_PUBLIC_PATHS


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def require_auth(request: Request, call_next):
    path = request.url.path
    if not auth.enabled or path in PUBLIC_PATHS or path.startswith("/static/"):
        return await call_next(request)
    if auth.verify_token(request.cookies.get(COOKIE_NAME)):
        return await call_next(request)
    # A signed-in user account also unlocks the app (multi-user deployment).
    from .accounts_api import current_user

    if current_user(request) is not None:
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "Não autenticado"}, status_code=401)
    # Browser navigation to a protected page -> send to login.
    return RedirectResponse("/login", status_code=302)


# Security headers applied to every response. The CSP allows inline scripts and
# styles because the no-build SPA and account pages embed them, and permits the
# Google Fonts hosts used by the marketing site; everything else is same-origin.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: blob:; "
    "media-src 'self' data: blob:; "
    "connect-src 'self' ws: wss:; "
    "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=(self)")
    response.headers.setdefault("Content-Security-Policy", _CSP)
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    if proto.split(",")[0].strip() == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response

MODEL_SUGGESTIONS: dict[str, list[str]] = {
    "pollinations": ["openai", "openai-fast"],
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "o4-mini"],
    "anthropic": ["claude-sonnet-4-20250514", "claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"],
    "groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "openai/gpt-oss-120b"],
    "google": ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "openrouter": ["meta-llama/llama-3.3-70b-instruct:free", "openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet"],
    "cerebras": ["llama-3.3-70b", "llama3.1-8b"],
    "mistral": ["mistral-large-latest", "mistral-small-latest"],
    "github": ["openai/gpt-4o-mini", "openai/gpt-4o"],
    "ollama": ["llama3.1", "qwen2.5", "mistral", "codellama"],
}

# Providers that are usable with no API key at all.
KEYLESS_NAMES = set(KEYLESS_PROVIDERS) | {"ollama"}


# --------------------------------------------------------------------------
# models
# --------------------------------------------------------------------------
class SettingsPatch(BaseModel):
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    autonomy: str | None = None
    allow_network: bool | None = None
    supports_tools: bool | None = None
    enabled_tools: list[str] | None = None
    max_steps: int | None = None


class SecretPayload(BaseModel):
    name: str
    value: str


class ProjectPayload(BaseModel):
    name: str
    description: str = ""


class ConversationPayload(BaseModel):
    project_id: str | None = None
    title: str = "Nova conversa"


class MessagePayload(BaseModel):
    text: str


class MemoryPayload(BaseModel):
    content: str
    tags: str = ""


class FileWritePayload(BaseModel):
    path: str
    content: str


class ConfirmPayload(BaseModel):
    approved: bool


class TaskPayload(BaseModel):
    name: str
    prompt: str
    interval_seconds: int = 3600


class TaskTogglePayload(BaseModel):
    enabled: bool


class LoginPayload(BaseModel):
    password: str


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------
@app.post("/api/login")
def login(payload: LoginPayload, request: Request) -> JSONResponse:
    ip = _client_ip(request)
    if not login_limiter.allow(ip):
        raise HTTPException(429, "Muitas tentativas. Tente novamente em alguns minutos.")
    if not auth.verify_password(payload.password):
        raise HTTPException(401, "Senha incorreta")
    token = auth.issue_token()
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        COOKIE_NAME, token, max_age=SESSION_TTL, httponly=True, samesite="lax",
        secure=bool(request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"),
        path="/",
    )
    return resp


@app.post("/api/logout")
def logout() -> JSONResponse:
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


@app.get("/api/me")
def me(request: Request) -> dict[str, Any]:
    return {"authenticated": auth.verify_token(request.cookies.get(COOKIE_NAME))}


@app.get("/login")
def login_page() -> FileResponse:
    return FileResponse(settings.static_dir / "login.html")


# --------------------------------------------------------------------------
# settings & secrets
# --------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict[str, Any]:
    s = runtime.get_settings()
    configured = s["provider"] in KEYLESS_NAMES or bool(runtime.secrets.get_or_none(s["provider"]))
    return {
        "status": "ok",
        "provider": s["provider"],
        "model": s["model"],
        "configured": configured,
        "auth": auth.enabled,
    }


@app.get("/health")
def health_root() -> dict[str, Any]:
    """Liveness probe for hosting platforms (no auth)."""
    return {"status": "ok", "app": "openhud", "version": app.version}


@app.get("/ready")
def ready() -> JSONResponse:
    """Readiness probe: verifies the database answers. Returns 503 if not."""
    try:
        db.query("SELECT 1")
        return JSONResponse({"status": "ready", "database": "ok"})
    except Exception as exc:
        return JSONResponse({"status": "not_ready", "database": f"{type(exc).__name__}: {exc}"},
                            status_code=503)


@app.get("/api/providers")
def providers() -> dict[str, Any]:
    """Show the fallback chain and which providers are ready to answer."""
    manager = runtime.provider_manager()
    configured_keys = set(runtime.secrets.names())
    chain = [
        {"name": e.name, "label": e.label, "priority": e.priority}
        for e in manager.entries()
    ]
    return {
        "selected": runtime.get_settings()["provider"],
        "keyless": sorted(KEYLESS_NAMES),
        "configured_keys": sorted(configured_keys),
        "available": list(KEYED_PROVIDERS),
        "chain": chain,
    }


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return runtime.get_settings()


@app.put("/api/settings")
def update_settings(patch: SettingsPatch) -> dict[str, Any]:
    data = {k: v for k, v in patch.model_dump().items() if v is not None}
    if "provider" in data and "base_url" not in data:
        data["base_url"] = DEFAULT_BASE_URLS.get(data["provider"], DEFAULT_BASE_URLS["openai"])
    return runtime.update_settings(data)


@app.get("/api/secrets")
def list_secrets() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for name in runtime.secrets.names():
        try:
            preview = runtime.secrets.mask(runtime.secrets.get(name))
        except ValueError:
            # Wrong/rotated OPENHUD_ENCRYPTION_KEY: report honestly instead of 500.
            preview = "(indecifrável: confira OPENHUD_ENCRYPTION_KEY)"
        out.append({"name": name, "preview": preview})
    return out


@app.post("/api/secrets")
def set_secret(payload: SecretPayload) -> dict[str, str]:
    runtime.secrets.set(payload.name, payload.value)
    return {"name": payload.name, "preview": runtime.secrets.mask(payload.value)}


@app.delete("/api/secrets/{name}")
def delete_secret(name: str) -> dict[str, bool]:
    runtime.secrets.delete(name)
    return {"deleted": True}


# --------------------------------------------------------------------------
# projects & conversations
# --------------------------------------------------------------------------
@app.get("/api/projects")
def list_projects() -> list[dict[str, Any]]:
    return db.list_projects()


@app.post("/api/projects")
def create_project(payload: ProjectPayload) -> dict[str, Any]:
    return db.create_project(payload.name, payload.description)


@app.delete("/api/projects/{pid}")
def delete_project(pid: str) -> dict[str, bool]:
    db.delete_project(pid)
    return {"deleted": True}


@app.get("/api/conversations")
def list_conversations(project_id: str | None = None) -> list[dict[str, Any]]:
    return db.list_conversations(project_id)


@app.post("/api/conversations")
def create_conversation(payload: ConversationPayload) -> dict[str, Any]:
    return db.create_conversation(payload.project_id, payload.title)


@app.get("/api/conversations/{cid}")
def get_conversation(cid: str) -> dict[str, Any]:
    conv = db.get_conversation(cid)
    if not conv:
        raise HTTPException(404, "Conversa não encontrada")
    return conv


@app.delete("/api/conversations/{cid}")
def delete_conversation(cid: str) -> dict[str, bool]:
    db.delete_conversation(cid)
    return {"deleted": True}


@app.get("/api/conversations/{cid}/messages")
def get_messages(cid: str) -> list[dict[str, Any]]:
    return db.list_messages(cid)


@app.post("/api/conversations/{cid}/messages")
def post_message(cid: str, payload: MessagePayload, request: Request) -> StreamingResponse:
    if not chat_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "Muitas mensagens em pouco tempo. Aguarde alguns segundos.")
    conv = db.get_conversation(cid)
    if not conv:
        raise HTTPException(404, "Conversa não encontrada")
    text = payload.text.strip()
    if not text:
        raise HTTPException(400, "Mensagem vazia")

    # The agent loop persists the user turn; here we only update metadata.
    if conv["title"] == "Nova conversa":
        db.touch_conversation(cid, title=text[:60])
    else:
        db.touch_conversation(cid)

    def event_stream():
        events: queue.Queue = queue.Queue()

        def worker() -> None:
            try:
                for ev in agent.run(cid, text):
                    events.put(ev)
            except Exception as exc:  # surface unexpected failures to the UI
                events.put(_error_event(exc))
            finally:
                events.put(None)

        threading.Thread(target=worker, daemon=True).start()
        while True:
            ev = events.get()
            if ev is None:
                break
            yield f"event: {ev.type}\ndata: {json.dumps(ev.data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _error_event(exc: Exception):
    from ..agent.loop import AgentEvent

    return AgentEvent("error", {"message": f"{type(exc).__name__}: {exc}"})


# --------------------------------------------------------------------------
# tools, memory, activities
# --------------------------------------------------------------------------
@app.get("/api/tools")
def list_tools() -> list[dict[str, Any]]:
    enabled = runtime.enabled_tool_names()
    return [
        {
            "name": t.name,
            "description": t.description,
            "requires_confirmation": t.requires_confirmation,
            "enabled": enabled is None or t.name in enabled,
        }
        for t in runtime.registry.all()
    ]


@app.get("/api/pc/status")
def pc_status() -> dict[str, Any]:
    """Quick view of connected PCs, used by the chat to know if PC tools apply."""
    try:
        hub = runtime_hub()
        devices = hub.list_devices()
    except Exception:
        devices = []
    real = [d for d in devices if d["id"] != "local"]
    online = [d for d in real if d["online"]]
    return {
        "connected": bool(online),
        "count": len(real),
        "online": len(online),
        "devices": [{"id": d["id"], "name": d["name"], "online": d["online"]} for d in real],
    }


def runtime_hub():
    from ..core.agent_hub import get_hub

    return get_hub()


@app.get("/api/models")
def list_models() -> dict[str, Any]:
    return {
        "providers": list(MODEL_SUGGESTIONS),
        "suggestions": MODEL_SUGGESTIONS,
        "base_urls": DEFAULT_BASE_URLS,
        "keyless": sorted(KEYLESS_NAMES),
    }


@app.get("/api/memories")
def list_memories() -> list[dict[str, Any]]:
    return db.list_memories()


@app.post("/api/memories")
def create_memory(payload: MemoryPayload) -> dict[str, Any]:
    return db.add_memory(payload.content, payload.tags)


@app.put("/api/memories/{mid}")
def update_memory(mid: str, payload: MemoryPayload) -> dict[str, bool]:
    db.update_memory(mid, payload.content, payload.tags)
    return {"updated": True}


@app.delete("/api/memories/{mid}")
def delete_memory(mid: str) -> dict[str, bool]:
    db.delete_memory(mid)
    return {"deleted": True}


@app.get("/api/activities")
def list_activities(conversation_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    return db.list_activities(conversation_id, limit)


# --------------------------------------------------------------------------
# scheduled tasks
# --------------------------------------------------------------------------
@app.get("/api/tasks")
def list_tasks() -> list[dict[str, Any]]:
    return db.list_tasks()


@app.post("/api/tasks")
def create_task(payload: TaskPayload) -> dict[str, Any]:
    if payload.interval_seconds < 30:
        raise HTTPException(400, "O intervalo mínimo é 30 segundos")
    return db.create_task(payload.name, payload.prompt, payload.interval_seconds)


@app.put("/api/tasks/{tid}")
def toggle_task(tid: str, payload: TaskTogglePayload) -> dict[str, bool]:
    if not db.get_task(tid):
        raise HTTPException(404, "Tarefa não encontrada")
    db.set_task_enabled(tid, payload.enabled)
    return {"enabled": payload.enabled}


@app.delete("/api/tasks/{tid}")
def delete_task(tid: str) -> dict[str, bool]:
    db.delete_task(tid)
    return {"deleted": True}


# --------------------------------------------------------------------------
# files
# --------------------------------------------------------------------------
def _safe_path(raw: str) -> Path:
    workspace = settings.workspace_dir.resolve()
    candidate = (workspace / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
    if candidate != workspace and workspace not in candidate.parents:
        raise HTTPException(400, "Caminho fora do workspace")
    return candidate


@app.get("/api/files")
def list_files(path: str = ".") -> list[dict[str, Any]]:
    base = _safe_path(path)
    if not base.exists() or not base.is_dir():
        raise HTTPException(404, "Diretório não encontrado")
    out = []
    for entry in sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name)):
        out.append({
            "name": entry.name,
            "is_dir": entry.is_dir(),
            "size": 0 if entry.is_dir() else entry.stat().st_size,
            "path": str(entry.relative_to(settings.workspace_dir.resolve())),
        })
    return out


@app.get("/api/files/content")
def read_file(path: str) -> dict[str, Any]:
    target = _safe_path(path)
    if not target.exists() or target.is_dir():
        raise HTTPException(404, "Arquivo não encontrado")
    data = target.read_bytes()[:200000]
    try:
        return {"path": path, "content": data.decode("utf-8")}
    except UnicodeDecodeError:
        raise HTTPException(400, "Arquivo binário")


@app.post("/api/files")
def write_file(payload: FileWritePayload) -> dict[str, Any]:
    target = _safe_path(payload.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload.content, encoding="utf-8")
    return {"path": payload.path, "bytes": len(payload.content)}


# --------------------------------------------------------------------------
# confirmations
# --------------------------------------------------------------------------
@app.get("/api/confirmations")
def list_confirmations() -> list[dict[str, Any]]:
    return broker.list_pending()


@app.post("/api/confirmations/{request_id}")
def resolve_confirmation(request_id: str, payload: ConfirmPayload) -> dict[str, bool]:
    ok = broker.resolve(request_id, payload.approved)
    if not ok:
        raise HTTPException(404, "Confirmação não encontrada ou expirada")
    return {"resolved": True, "approved": payload.approved}


# --------------------------------------------------------------------------
# static UI
# --------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")


@app.get("/app")
def index() -> FileResponse:
    return FileResponse(settings.static_dir / "index.html", headers={"Cache-Control": "no-cache"})


# SPA routes: every app page is served by the single-page UI, which switches
# views client-side. Unknown paths fall through to the UI (which redirects to
# login when the session is missing).
APP_PAGES = {"/app", "/chat", "/pc", "/trading", "/games", "/performance", "/memory", "/projects",
             "/tools", "/settings", "/codex", "/plugins", "/images", "/video", "/intelligence",
             "/privacy", "/admin", "/assistant", "/accessibility", "/control-center",
             "/files", "/tasks", "/activity"}


@app.get("/{page}")
def spa_page(page: str) -> FileResponse:
    if f"/{page}" in APP_PAGES:
        return FileResponse(settings.static_dir / "index.html", headers={"Cache-Control": "no-cache"})
    raise HTTPException(404, "Página não encontrada")
