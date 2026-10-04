"""Native plugins.

Only plugins whose underlying integration *actually exists* are listed here.
Each native plugin maps to a category the agent already supports, and reports
its real availability. There are no placeholder/fake plugins.

Installed third-party plugins (manifests dropped into ``data/plugins/``) are
listed with their declared risk; they are never auto-granted admin rights.
"""
from __future__ import annotations

from .manifest import Manifest

# Category → (tools, permissions, availability check description)
NATIVE_PLUGINS: list[dict] = [
    {
        "name": "browser", "version": "1.0.0", "author": "OpenHUD",
        "description": "Pesquisa e requisições HTTP reais (web_search, fetch_url, http_request).",
        "tools": ["web_search", "fetch_url", "http_request"],
        "permissions": ["network"],
        "available": True,
    },
    {
        "name": "files", "version": "1.0.0", "author": "OpenHUD",
        "description": "Leitura e escrita de arquivos no workspace.",
        "tools": ["read_file", "write_file", "list_files", "delete_file"],
        "permissions": ["read_files", "write_files"],
        "available": True,
    },
    {
        "name": "pc", "version": "1.0.0", "author": "OpenHUD",
        "description": "Telemetria, diagnóstico e perfis de jogos do PC via PC Agent.",
        "tools": ["pc_metrics", "pc_diagnose", "pc_game_profile"],
        "permissions": ["read_telemetry"],
        "available": True,
    },
    {
        "name": "mt5", "version": "1.0.0", "author": "OpenHUD",
        "description": "Análise e trading via MetaTrader 5 (sujeito às permissões do módulo MT5).",
        "tools": ["mt5_status", "mt5_account", "mt5_analyse", "trading_strategy", "trading_backtest",
                  "trading_daily_brief", "trading_paper", "trading_prepare_order", "trading_execute_order"],
        "permissions": ["read_telemetry", "execute_command"],
        "available": True,
    },
    {
        "name": "data", "version": "1.0.0", "author": "OpenHUD",
        "description": "Análise de dados e planilhas.",
        "tools": ["analyze_data"],
        "permissions": ["read_files"],
        "available": True,
    },
    {
        "name": "memory", "version": "1.0.0", "author": "OpenHUD",
        "description": "Memória de longo prazo (lembrar/recuperar).",
        "tools": ["remember", "recall"],
        "permissions": ["read_config", "write_config"],
        "available": True,
    },
    {
        "name": "execution", "version": "1.0.0", "author": "OpenHUD",
        "description": "Execução de shell e Python no workspace (sandbox de recursos).",
        "tools": ["run_shell", "run_python"],
        "permissions": ["execute_command"],
        "available": True,
    },
    {
        "name": "images", "version": "1.0.0", "author": "OpenHUD",
        "description": "Geração de imagens (Pollinations/OpenAI).",
        "tools": [], "permissions": ["network"], "available": True,
    },
    {
        "name": "video", "version": "1.0.0", "author": "OpenHUD",
        "description": "Render de vídeo local com ffmpeg + narração.",
        "tools": [], "permissions": ["write_files", "network"], "available": True,
    },
    {
        "name": "audio", "version": "1.0.0", "author": "OpenHUD",
        "description": "Narração, transcrição e processamento de áudio.",
        "tools": [], "permissions": ["network"], "available": True,
    },
    {
        "name": "documents", "version": "1.0.0", "author": "OpenHUD",
        "description": "Leitura e edição de documentos no workspace.",
        "tools": ["read_file", "write_file"], "permissions": ["read_files", "write_files"],
        "available": True,
    },
    {
        "name": "automation", "version": "1.0.0", "author": "OpenHUD",
        "description": "Tarefas agendadas recorrentes (scheduler).",
        "tools": [], "permissions": ["execute_command"], "available": True,
    },
]

# Categories requested in the spec that have no real integration yet.
UNAVAILABLE: dict[str, str] = {
    "github": "Sem integração GitHub configurada (token/API).",
    "games": "Use o plugin 'pc' (perfis de jogos); catálogo dedicado não implementado.",
    "cloud": "Nenhum provedor de nuvem configurado.",
}


def native_manifests() -> list[Manifest]:
    out = []
    for p in NATIVE_PLUGINS:
        out.append(Manifest(
            name=p["name"], version=p["version"], author=p["author"],
            description=p["description"], source="native",
            permissions=list(p["permissions"]), tools=list(p["tools"]),
        ))
    return out


def unavailable_plugins() -> list[dict]:
    return [{"name": k, "reason": v} for k, v in UNAVAILABLE.items()]
