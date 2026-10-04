"""Data-driven diagnostics and optimization engine.

This module turns raw telemetry into structured findings. The logic is
deterministic and rule-based on purpose: recommendations must be traceable to
observed data, never invented. Each finding follows the shape

    DADO OBSERVADO -> ANALISE -> RECOMENDACAO -> IMPACTO -> RISCO

so the UI and the LLM can present the reasoning honestly. The LLM is used only
to phrase these findings in natural language; it is never the source of truth.

The same engine runs on the agent (for offline diagnostics) and on the server.
"""
from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------
# thresholds (percent). Kept explicit so findings are auditable.
# --------------------------------------------------------------------------
CPU_HIGH = 85.0
CPU_VERY_HIGH = 95.0
GPU_HIGH = 90.0
RAM_HIGH = 85.0
RAM_VERY_HIGH = 93.0
VRAM_HIGH = 90.0
TEMP_CPU_WARN = 85.0
TEMP_CPU_CRIT = 95.0
TEMP_GPU_WARN = 83.0
TEMP_GPU_CRIT = 90.0
DISK_LOW_FREE_GB = 15.0


def _risk(level: str) -> str:
    return {"low": "baixo", "medium": "médio", "high": "alto"}.get(level, level)


def _finding(
    title: str,
    observed: str,
    analysis: str,
    recommendation: str,
    impact: str,
    risk: str,
    *,
    safe: bool = True,
) -> dict[str, Any]:
    return {
        "title": title,
        "observed": observed,
        "analysis": analysis,
        "recommendation": recommendation,
        "impact": impact,
        "risk": risk,
        "risk_label": _risk(risk),
        "safe": safe,
    }


def diagnose(metrics: dict[str, Any]) -> dict[str, Any]:
    """Analyse one metrics snapshot and return findings + a bottleneck verdict."""
    findings: list[dict[str, Any]] = []
    if not metrics or not metrics.get("available", True):
        return {
            "ok": False,
            "error": "Sem dados de telemetria disponíveis. Verifique se o OpenHUD Agent está rodando no PC.",
            "findings": [],
            "bottleneck": None,
        }

    cpu = metrics.get("cpu") or {}
    ram = metrics.get("ram") or {}
    gpus = metrics.get("gpu") or []
    gpu = gpus[0] if gpus else {}
    disks = metrics.get("disk") or []
    procs = metrics.get("processes") or []

    cpu_pct = cpu.get("percent")
    gpu_pct = gpu.get("util_percent")
    ram_pct = ram.get("percent")
    vram_pct = gpu.get("mem_percent")
    cpu_temp = cpu.get("temp_c")
    gpu_temp = gpu.get("temp_c")

    # -- bottleneck verdict (needs both CPU and GPU to be meaningful) ----
    bottleneck = None
    if cpu_pct is not None and gpu_pct is not None:
        if cpu_pct >= CPU_VERY_HIGH and gpu_pct < 70:
            bottleneck = {
                "type": "cpu",
                "label": "CPU",
                "explain": (
                    f"CPU em {cpu_pct:.0f}% enquanto a GPU está em {gpu_pct:.0f}%. "
                    "O sistema está limitado pela CPU (a GPU fica esperando)."
                ),
            }
        elif gpu_pct >= GPU_HIGH and (vram_pct or 0) >= VRAM_HIGH:
            bottleneck = {
                "type": "gpu_vram",
                "label": "GPU/VRAM",
                "explain": (
                    f"GPU em {gpu_pct:.0f}% e VRAM em {vram_pct:.0f}%. "
                    "O jogo está predominantemente limitado pela GPU/VRAM."
                ),
            }
        elif gpu_pct >= GPU_HIGH:
            bottleneck = {
                "type": "gpu",
                "label": "GPU",
                "explain": f"GPU em {gpu_pct:.0f}% — limitado pela GPU, que é o caso saudável.",
            }
        elif (ram_pct or 0) >= RAM_VERY_HIGH:
            bottleneck = {
                "type": "ram",
                "label": "RAM",
                "explain": f"RAM em {ram_pct:.0f}%. A falta de memória força o sistema a usar disco (swap).",
            }

    # -- CPU ------------------------------------------------------------
    if cpu_pct is not None and cpu_pct >= CPU_HIGH:
        top = [p for p in procs if (p.get("cpu_percent") or 0) > 5][:3]
        who = ", ".join(f"{p['name']} ({p['cpu_percent']}%)" for p in top) or "não identificado"
        findings.append(
            _finding(
                "CPU com uso alto",
                f"CPU em {cpu_pct:.0f}%. Principais consumidores: {who}.",
                "Uso elevado de CPU reduz o FPS quando a GPU não é o gargalo.",
                "Feche programas em segundo plano desnecessários; em jogos, limite "
                "o número de processos concorrentes.",
                "Pode liberar alguns % de CPU e estabilizar o frametime.",
                "baixo",
            )
        )

    # -- RAM ------------------------------------------------------------
    if ram_pct is not None and ram_pct >= RAM_HIGH:
        findings.append(
            _finding(
                "Memória RAM quase cheia",
                f"RAM em {ram_pct:.0f}% ({ram.get('used_mb')} MB de {ram.get('total_mb')} MB).",
                "Com pouca RAM livre o Windows recorre ao arquivo de paginação no disco, "
                "o que causa travamentos e stuttering.",
                "Feche abas e programas pesados; considere aumentar a RAM se isso for recorrente.",
                "Menos stuttering e carregamentos mais rápidos.",
                "baixo" if ram_pct < RAM_VERY_HIGH else "médio",
            )
        )

    # -- GPU / VRAM -----------------------------------------------------
    if gpu:
        if gpu_pct is not None and gpu_pct >= GPU_HIGH and (vram_pct or 0) >= VRAM_HIGH:
            findings.append(
                _finding(
                    "VRAM no limite",
                    f"GPU em {gpu_pct:.0f}% e VRAM em {vram_pct:.0f}% "
                    f"({gpu.get('mem_used_mb')} MB de {gpu.get('mem_total_mb')} MB).",
                    "Texturas em qualidade muito alta esgotam a VRAM e forçam o "
                    "uso de memória lenta do sistema.",
                    "Reduza texturas de 1 a 2 níveis; evite resolução acima da nativa.",
                    "Elimina quedas bruscas de FPS por falta de VRAM.",
                    "baixo",
                )
            )
    else:
        findings.append(
            _finding(
                "GPU não detectada",
                "Nenhuma GPU NVIDIA respondeu via NVML.",
                "Sem acesso à GPU (driver ausente, GPU não-NVIDIA ou ambiente sem GPU).",
                "Instale/atualize o driver da GPU para habilitar as métricas de GPU.",
                "Permite medir uso, VRAM e temperatura da GPU.",
                "baixo",
            )
        )

    # -- Temperatures ---------------------------------------------------
    if cpu_temp is not None and cpu_temp >= TEMP_CPU_WARN:
        findings.append(
            _finding(
                "CPU quente",
                f"Temperatura da CPU em {cpu_temp:.0f}°C.",
                "Acima de 85°C a CPU reduz a frequência (thermal throttling) e perde desempenho.",
                "Melhore a ventilação/limpeza e verifique a pasta térmica.",
                "Evita perda de desempenho por throttling.",
                "médio" if cpu_temp < TEMP_CPU_CRIT else "alto",
                safe=False,
            )
        )
    if gpu_temp is not None and gpu_temp >= TEMP_GPU_WARN:
        findings.append(
            _finding(
                "GPU quente",
                f"Temperatura da GPU em {gpu_temp:.0f}°C.",
                "GPUs acima de ~83°C tendem a reduzir o clock.",
                "Ajuste a curva de ventoinhas e melhore o fluxo de ar do gabinete.",
                "Mantém o clock alto por mais tempo.",
                "médio" if gpu_temp < TEMP_GPU_CRIT else "alto",
                safe=False,
            )
        )

    # -- Disk -----------------------------------------------------------
    for d in disks:
        if d.get("free_gb") is not None and d["free_gb"] < DISK_LOW_FREE_GB:
            findings.append(
                _finding(
                    "Pouco espaço em disco",
                    f"{d.get('mount')}: {d.get('free_gb')} GB livres de {d.get('total_gb')} GB.",
                    "Discos quase cheios degradam o swap e os carregamentos.",
                    "Remova arquivos temporários e programas não usados.",
                    "Mais espaço para o swap e carregamentos mais rápidos.",
                    "baixo",
                )
            )

    # -- Disk I/O / swap pressure --------------------------------------
    if ram_pct is not None and ram_pct >= RAM_VERY_HIGH and metrics.get("disk_io", {}).get("write_mb", 0):
        findings.append(
            _finding(
                "Uso intenso de disco (provável swap)",
                f"RAM em {ram_pct:.0f}% com escrita em disco de {metrics['disk_io'].get('write_mb')} MB.",
                "O sistema está paginando memória para o disco.",
                "Feche programas pesados; se persistir, aumente a RAM.",
                "Reduz engasgos causados por paginação.",
                "médio",
            )
        )

    # -- Top processes --------------------------------------------------
    heavy = [p for p in procs if (p.get("cpu_percent") or 0) >= 20][:5]
    if heavy:
        names = ", ".join(f"{p['name']} ({p['cpu_percent']}%)" for p in heavy)
        findings.append(
            _finding(
                "Processos consumindo CPU",
                f"Processos acima de 20% de CPU: {names}.",
                "Alguns processos podem competir por CPU com o que você está usando.",
                "Avalie se esses programas são necessários agora.",
                "Pode liberar CPU para o jogo ou aplicação principal.",
                "baixo",
            )
        )

    return {
        "ok": True,
        "bottleneck": bottleneck,
        "findings": findings,
        "summary": _summary(cpu_pct, gpu_pct, ram_pct, vram_pct),
        "metrics_ts": metrics.get("ts"),
    }


def _summary(cpu_pct, gpu_pct, ram_pct, vram_pct) -> str:
    parts = []
    if cpu_pct is not None:
        parts.append(f"CPU {cpu_pct:.0f}%")
    if gpu_pct is not None:
        parts.append(f"GPU {gpu_pct:.0f}%")
    if ram_pct is not None:
        parts.append(f"RAM {ram_pct:.0f}%")
    if vram_pct is not None:
        parts.append(f"VRAM {vram_pct:.0f}%")
    return " · ".join(parts) if parts else "sem dados"


# --------------------------------------------------------------------------
# Game profiles
# --------------------------------------------------------------------------
KNOWN_GAMES = {
    "fivem": "FiveM",
    "gta5": "GTA V",
    "gta v": "GTA V",
    "fortnite": "Fortnite",
    "cs2": "CS2",
    "counter-strike": "CS2",
    "roblox": "Roblox",
    "valorant": "Valorant",
    "league of legends": "League of Legends",
    "minecraft": "Minecraft",
}


def suggest_game_profile(game: str, metrics: dict[str, Any]) -> dict[str, Any]:
    """Turn a live snapshot into an optimisation plan for a specific game."""
    result = diagnose(metrics)
    game_key = (game or "").strip().lower()
    label = KNOWN_GAMES.get(game_key, game.strip() or "Jogo")

    # game-specific, safe-first recommendations layered on the generic ones
    extras: list[dict[str, Any]] = []
    if game_key in {"fivem", "gta v", "gta5"}:
        extras.append(
            _finding(
                "FiveM/GTA V: carga de CPU e RAM",
                "Esses títulos são fortemente limitados por CPU/RAM.",
                "Muitos scripts e mods aumentam o uso de CPU e RAM.",
                "Reduza a densidade de população/tráfego e a distância de visão.",
                "Melhora o frametime e reduz quedas em cidades cheias.",
                "baixo",
            )
        )
    if game_key in {"fortnite", "cs2", "valorant"}:
        extras.append(
            _finding(
                f"{label}: priorizar FPS",
                "Jogos competitivos se beneficiam de framerate alto e estável.",
                "Qualidade gráfica alta adiciona carga de GPU desnecessária para competitivo.",
                "Use preset baixo/médio e desative efeitos de pós-processamento.",
                "Mais FPS e frametime mais consistente.",
                "baixo",
            )
        )

    return {
        "game": label,
        "ok": result["ok"],
        "bottleneck": result.get("bottleneck"),
        "findings": extras + result.get("findings", []),
        "summary": result.get("summary"),
        "error": result.get("error"),
    }


def available_optimizations() -> list[dict[str, Any]]:
    """Catalogue of optimisations the agent can perform.

    ``safe=True`` entries are read-only or fully reversible and can run after a
    single confirmation. ``safe=False`` entries change the system; the agent
    never runs them automatically and always shows how to undo them. Anything
    not listed here is never executed — the agent only reports it as advice.
    """
    return [
        {
            "id": "list_startup",
            "title": "Listar programas de inicialização",
            "risk": "baixo",
            "safe": True,
            "reason": "Programas que iniciam com o Windows consomem CPU/RAM.",
            "undo": "Somente leitura; nada é alterado.",
            "impact": "Permite decidir o que desativar manualmente.",
        },
        {
            "id": "clear_temp",
            "title": "Limpar arquivos temporários do usuário",
            "risk": "baixo",
            "safe": True,
            "reason": "Libera espaço em disco removendo caches temporários seguros.",
            "undo": "Não é necessário desfazer; apaga apenas arquivos temporários regeneráveis.",
            "impact": "Libera espaço e pode reduzir a pressão no disco.",
        },
        {
            "id": "flush_dns",
            "title": "Limpar cache de DNS",
            "risk": "baixo",
            "safe": True,
            "reason": "Resolve problemas de conexão causados por DNS desatualizado.",
            "undo": "O cache se reconstrói sozinho; não é necessário desfazer.",
            "impact": "Pode melhorar a resolução de nomes e a estabilidade da rede.",
        },
        {
            "id": "high_performance",
            "title": "Ativar plano de energia de alto desempenho",
            "risk": "médio",
            "safe": False,
            "reason": "Evita que a CPU reduza a frequência durante jogos.",
            "undo": "Execute 'powercfg /setactive SCHEME_BALANCED' para voltar ao plano equilibrado.",
            "impact": "Frequências mais altas e mais estáveis sob carga.",
        },
    ]
