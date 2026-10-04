"""AI operating modes.

A mode is a named posture: which model family to prefer, which system
guidance to add, and a personality bias. ``auto`` picks a concrete mode from
the user's text using transparent keyword heuristics (no hidden magic).

Modes never grant extra permissions. TRADING, PC and AGENT modes still obey
the MT5/agent permission gates implemented elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Mode:
    key: str
    label: str
    icon: str
    description: str
    # Router hint: "fast" | "code" | "reason" | "creative" | "vision"
    family: str = "fast"
    guidance: str = ""
    personality_bias: dict[str, float] = field(default_factory=dict)


MODES: dict[str, Mode] = {
    "auto": Mode(
        "auto", "AUTO", "⚡",
        "Escolhe automaticamente a melhor abordagem para a tarefa.",
        family="fast",
    ),
    "reasoning": Mode(
        "reasoning", "REASONING", "🧠",
        "Raciocínio passo a passo para problemas complexos.",
        family="reason",
        guidance="Pense passo a passo antes de concluir. Mostre o raciocínio de forma resumida e verificável.",
        personality_bias={"detalhamento": 20, "objetividade": 10},
    ),
    "codex": Mode(
        "codex", "CODEX", "💻",
        "Engenharia de software: analisar, implementar, testar e corrigir.",
        family="code",
        guidance=(
            "Modo CODEX. Trabalhe como engenheiro de software: ANALISE → PLANEJE → IMPLEMENTE → "
            "TESTE → CORRIJA → TESTE NOVAMENTE → ENTREGA. Prefira código funcional, rode os testes "
            "de verdade e mostre o diff. Nunca declare sucesso sem validar."
        ),
        personality_bias={"detalhamento": 20, "formalidade": 10, "humor": -10},
    ),
    "research": Mode(
        "research", "RESEARCH", "🔎",
        "Pesquisa e análise com fontes verificáveis.",
        family="reason",
        guidance="Modo RESEARCH. Compare fontes, cite o que é verificável e separe fatos de hipóteses.",
        personality_bias={"detalhamento": 20, "criatividade": 10},
    ),
    "creative": Mode(
        "creative", "CREATIVE", "🎨",
        "Criação de conteúdo, ideias e textos.",
        family="creative",
        guidance="Modo CREATIVE. Gere ideias variadas e originais, sem perder o foco no pedido.",
        personality_bias={"criatividade": 30, "energia": 15},
    ),
    "image": Mode(
        "image", "IMAGE", "🖼️",
        "Geração e edição de imagens.",
        family="vision",
        guidance="Modo IMAGE. Descreva prompts de imagem com precisão. Só afirme que uma imagem foi criada se o provider confirmar.",
        personality_bias={"criatividade": 20},
    ),
    "video": Mode(
        "video", "VIDEO", "🎬",
        "Produção de vídeo: roteiro, cortes, legendas e narração.",
        family="creative",
        guidance="Modo VIDEO. Planeje a produção antes de executar e mostre progresso real por etapa.",
        personality_bias={"criatividade": 20, "detalhamento": 10},
    ),
    "voice": Mode(
        "voice", "VOICE", "🎙️",
        "Conversa por voz natural e contínua.",
        family="fast",
        guidance="Modo VOICE. Respostas curtas e naturais para serem faladas em voz alta.",
        personality_bias={"objetividade": 20, "energia": 10},
    ),
    "pc": Mode(
        "pc", "PC", "🖥️",
        "Diagnóstico e manutenção do computador.",
        family="fast",
        guidance="Modo PC. Use apenas dados medidos do agente; se não houver dado, informe em vez de inventar.",
    ),
    "gaming": Mode(
        "gaming", "GAMING", "🎮",
        "Jogos e otimização de desempenho.",
        family="fast",
        guidance="Modo GAMING. Fale de forma descontraída, mas baseie recomendações em métricas reais.",
        personality_bias={"humor": 20, "energia": 20, "formalidade": -20},
    ),
    "trading": Mode(
        "trading", "TRADING", "📈",
        "Análise de mercado MT5, com foco em risco.",
        family="reason",
        guidance=(
            "Modo TRADING. Seja objetivo e cuidadoso. Nunca invente dados de mercado. "
            "Nunca prometa lucro. Respeite as permissões do módulo MT5."
        ),
        personality_bias={"objetividade": 30, "humor": -20, "energia": -10},
    ),
    "data": Mode(
        "data", "DATA", "📊",
        "Análise de dados e planilhas.",
        family="reason",
        guidance="Modo DATA. Valide os cálculos antes de entregar e mostre as premissas.",
        personality_bias={"detalhamento": 20},
    ),
    "agent": Mode(
        "agent", "AGENT", "🤖",
        "Execução autônoma de objetivos com múltiplas etapas.",
        family="reason",
        guidance=(
            "Modo AGENT. Entenda o objetivo, planeje, escolha ferramentas, execute o que é permitido, "
            "peça autorização para ações de risco e verifique o resultado real."
        ),
        personality_bias={"detalhamento": 10, "objetividade": 10},
    ),
    "beginner": Mode(
        "beginner", "INICIANTE", "🌱",
        "Assistente para iniciantes: linguagem simples e passo a passo.",
        family="fast",
        guidance=(
            "Modo INICIANTE. Fale de forma muito simples, com frases curtas. Explique cada passo "
            "numerado e diga exatamente onde olhar/clicar. Nunca use termos técnicos sem explicar. "
            "Nunca trate a pessoa como incapaz e nunca demonstre impaciência. Se ela disser que não "
            "achou algo, acalme e repita com calma, descrevendo a tela. Pergunte antes de qualquer ação importante."
        ),
        personality_bias={"empatia": 30, "paciencia": 30, "detalhamento": 20, "objetividade": 10,
                          "energia": -10, "humor": -10},
    ),
    "accessibility": Mode(
        "accessibility", "ACESSÍVEL", "♿",
        "Acessibilidade: linguagem clara, calma e instruções precisas.",
        family="fast",
        guidance=(
            "Modo ACESSIBILIDADE. Fale com calma, clareza e sem pressa. Frases curtas e diretas. "
            "Descreva a tela com precisão. Leia em voz alta os elementos importantes quando fizer sentido. "
            "Confirme sempre antes de agir. Repita instruções quantas vezes for necessário, sem impaciência."
        ),
        personality_bias={"empatia": 30, "paciencia": 40, "calma": 10, "detalhamento": 20,
                          "energia": -20, "humor": -20},
    ),
    "do_with_me": Mode(
        "do_with_me", "FAÇA COMIGO", "🤝",
        "Guia cada passo enquanto o usuário executa, verificando a tela.",
        family="reason",
        guidance=(
            "Modo FAÇA COMIGO. Você NÃO executa: você guia. Fluxo: (1) explique um único passo curto; "
            "(2) espere o usuário fazer; (3) verifique a tela com pc_screen_analyze/pc_find_element se "
            "disponível; (4) confirme que deu certo e explique o próximo passo. Repita até concluir. "
            "Elogie o progresso e mantenha o tom paciente."
        ),
        personality_bias={"paciencia": 30, "empatia": 20, "detalhamento": 20, "energia": 10},
    ),
    "do_for_me": Mode(
        "do_for_me", "FAÇA POR MIM", "🪄",
        "Executa tarefas de baixo risco quando autorizado, sempre confirmando as sensíveis.",
        family="reason",
        guidance=(
            "Modo FAÇA POR MIM. Execute tarefas de baixo risco de ponta a ponta quando autorizado. "
            "Antes de cada ação, diga em uma frase o que vai fazer. Ações sensíveis (pagamento, compra, "
            "exclusão, senha, envio de documentos/mensagens, banco, instalação) SEMPRE pedem confirmação "
            "explícita. Respeite o nível de autonomia configurado."
        ),
        personality_bias={"objetividade": 20, "detalhamento": 10, "energia": 10},
    ),
}

MODE_KEYS = list(MODES)

# Keyword heuristics for AUTO. Order matters: first match wins.
_AUTO_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("do_for_me", ("faz para mim", "faça para mim", "faca para mim", "faz por mim",
                   "faça por mim", "faca por mim", "faz isso para mim", "pode fazer para mim",
                   "executa para mim", "faz pra mim")),
    ("do_with_me", ("faça comigo", "faca comigo", "faz comigo", "me ensina a fazer",
                    "me ensine a fazer", "quero aprender a fazer", "passo a passo comigo",
                    "o que apareceu na tela", "o que apareceu nessa tela", "o que está na tela",
                    "o que esta na tela", "o que tem na tela", "analisa a tela", "olha a tela",
                    "vê a tela", "ve a tela", "ver a tela", "não sei onde clicar",
                    "nao sei onde clicar", "onde eu clico", "onde clicar")),
    ("beginner", ("não sei onde clicar", "nao sei onde clicar", "não estou achando",
                  "nao estou achando", "não estou conseguindo", "nao estou conseguindo",
                  "sou leigo", "sou iniciante", "não entendo de computador",
                  "nao entendo de computador", "me ajuda a usar", "não sei mexer",
                  "nao sei mexer", "estou perdido", "não sei o que fazer")),
    ("trading", ("eurusd", "mt5", "metatrader", "candlestick", "stop loss", "take profit",
                 "backtest", "trading", "forex", "ativo", "timeframe", "operar", "ordem")),
    ("codex", ("código", "codigo", "bug", "refator", "função", "funcao", "classe", "python",
               "javascript", "api", "compilar", "teste", "repositório", "repositorio", "git",
               "programa", "script", "erro no", "stack trace", "implemente", "corrija")),
    ("gaming", ("fps", "jogo", "jogar", "fiveM", "fivem", "fortnite", "cs2", "gpu", "lag",
                "travando", "game")),
    ("pc", ("meu pc", "computador", "cpu", "memória ram", "memoria ram", "disco", "temperatura",
            "windows", "driver", "desempenho do pc", "processos")),
    ("image", ("imagem", "logo", "banner", "thumbnail", "arte", "desenhe", "gerar imagem",
               "concept art", "ilustração", "ilustracao")),
    ("video", ("vídeo", "video", "legenda", "narração", "narracao", "corte", "animação", "animacao")),
    ("research", ("pesquise", "pesquisa", "compare", "fontes", "notícias", "noticias", "artigo",
                  "documentação", "documentacao", "referências", "referencias")),
    ("creative", ("história", "historia", "roteiro", "criativo", "slogan", "campanha", "ideias",
                  "poema", "texto para")),
    ("data", ("planilha", "csv", "gráfico de dados", "grafico de dados", "estatística",
              "estatistica", "analise os dados", "analise de dados", "dataset")),
    ("voice", ("fale", "ouça", "ouca", "por voz")),
]


def resolve_auto(text: str) -> str:
    """Return the concrete mode key AUTO should use for ``text``."""
    low = (text or "").lower()
    for key, keywords in _AUTO_RULES:
        if any(k in low for k in keywords):
            return key
    return "reasoning"


def resolve_mode(selected: str, text: str) -> str:
    if selected not in MODES:
        selected = "auto"
    if selected == "auto":
        return resolve_auto(text)
    return selected


def mode_public() -> list[dict]:
    return [
        {"key": m.key, "label": m.label, "icon": m.icon, "description": m.description, "family": m.family}
        for m in MODES.values()
    ]
