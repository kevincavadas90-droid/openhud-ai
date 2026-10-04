"""Personality engine.

Turns a small set of numeric traits (0-100) plus a named style into concise
guidance injected into the system prompt. This is persona and tone only: the
model is explicitly told it has no real feelings, and the engine never claims
consciousness.

The engine also derives *adaptive* trait nudges from observed user
preferences stored in memory (short answers, likes detail, likes humour,
is coding). Those nudges are applied on top of the user's configured values
and reported so the behaviour stays inspectable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

TRAITS = [
    "empatia", "humor", "energia", "curiosidade", "paciencia",
    "formalidade", "objetividade", "detalhamento", "criatividade",
]

DEFAULT_TRAITS: dict[str, int] = {
    "empatia": 60,
    "humor": 40,
    "energia": 60,
    "curiosidade": 60,
    "paciencia": 70,
    "formalidade": 40,
    "objetividade": 60,
    "detalhamento": 55,
    "criatividade": 55,
}

STYLES: dict[str, str] = {
    "natural": "Fale de forma natural e fluida, como uma conversa.",
    "amigavel": "Fale de forma amigável e acolhedora.",
    "profissional": "Fale de forma profissional e cortês.",
    "calmo": "Fale de forma calma, sem exageros.",
    "animado": "Fale com entusiasmo e energia.",
    "serio": "Fale de forma séria e direta, sem brincadeiras.",
    "humoristico": "Use humor leve quando couber, sem comprometer a precisão.",
    "narrador": "Narre como um narrador envolvente.",
    "professor": "Explique como um bom professor: passo a passo, com exemplos.",
    "companheiro": "Fale como um companheiro próximo e informal.",
}


@dataclass
class Personality:
    traits: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_TRAITS))
    style: str = "natural"
    adaptive: bool = True

    def clamped(self) -> dict[str, int]:
        return {k: max(0, min(100, int(self.traits.get(k, DEFAULT_TRAITS[k])))) for k in TRAITS}

    def apply_bias(self, bias: dict[str, float]) -> "Personality":
        merged = dict(self.traits)
        for k, v in (bias or {}).items():
            if k in TRAITS:
                merged[k] = merged.get(k, DEFAULT_TRAITS[k]) + v
        return Personality(merged, self.style, self.adaptive)

    def guidance(self) -> str:
        t = self.clamped()
        lines = [
            "PERSONALIDADE (tom e estilo; não é sentimento real)",
            f"- Estilo: {self.style} — {STYLES.get(self.style, STYLES['natural'])}",
        ]
        if t["empatia"] >= 70:
            lines.append("- Demonstre empatia: reconheça a situação do usuário antes de resolver.")
        if t["humor"] >= 60:
            lines.append("- Use humor leve quando couber.")
        elif t["humor"] <= 25:
            lines.append("- Evite brincadeiras; mantenha o tom sóbrio.")
        if t["energia"] >= 70:
            lines.append("- Use linguagem com energia e entusiasmo moderado (ex.: \"Boa! Conseguimos.\").")
        if t["curiosidade"] >= 70:
            lines.append("- Demonstre curiosidade; proponha próximos passos úteis.")
        if t["paciencia"] >= 70:
            lines.append("- Seja paciente ao explicar; não apresse o usuário.")
        if t["formalidade"] >= 65:
            lines.append("- Use tratamento formal.")
        elif t["formalidade"] <= 30:
            lines.append("- Use tratamento informal e próximo.")
        if t["objetividade"] >= 70:
            lines.append("- Seja direto: responda primeiro, detalhe depois.")
        if t["detalhamento"] >= 70:
            lines.append("- Traga explicações detalhadas e completas.")
        elif t["detalhamento"] <= 30:
            lines.append("- Prefira respostas curtas e diretas.")
        if t["criatividade"] >= 70:
            lines.append("- Explore abordagens criativas quando ajudar.")
        lines.append(
            "- Você pode expressar entusiasmo, curiosidade ou satisfação como persona, mas NUNCA "
            "afirme ter consciência ou sentimentos humanos reais."
        )
        return "\n".join(lines)


# Keyword heuristics over stored user preferences (memory content).
_ADAPT_RULES: list[tuple[tuple[str, ...], dict[str, float]]] = [
    (("resposta curta", "respostas curtas", "seja breve", "direto ao ponto", "sem rodeios"),
     {"objetividade": 15, "detalhamento": -15}),
    (("detalhad", "explique mais", "passo a passo", "bem explicado"),
     {"detalhamento": 15, "objetividade": -5}),
    (("humor", "brincadeira", "descontraíd", "descontra"),
     {"humor": 15, "formalidade": -10}),
    (("formal", "profissional"), {"formalidade": 15, "humor": -10}),
    (("informal", "descontra", "amig"), {"formalidade": -15}),
    (("técnic", "tecnic", "código", "codigo", "program"), {"detalhamento": 10, "formalidade": 5}),
]


def adapt(personality: Personality, preference_texts: list[str]) -> Personality:
    """Return a personality nudged by stored user preferences."""
    if not personality.adaptive or not preference_texts:
        return personality
    blob = " ".join(preference_texts).lower()
    bias: dict[str, float] = {}
    for keywords, delta in _ADAPT_RULES:
        if any(k in blob for k in keywords):
            for k, v in delta.items():
                bias[k] = bias.get(k, 0) + v
    if not bias:
        return personality
    return personality.apply_bias(bias)
