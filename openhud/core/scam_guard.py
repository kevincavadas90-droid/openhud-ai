"""Scam / phishing / social-engineering detection (Part 7).

Analyses visible text (a page, a window, a message) for common fraud signals
and returns a *risk assessment*, never a verdict. The wording is deliberately
cautious: "há sinais de risco" — never "isto é um golpe com certeza".

The detector is transparent and rule-based: every finding names the signal
that fired, so the user can judge for themselves. It is applied to untrusted
external content only; it never blocks anything on its own.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

# Each rule: (id, human label, explanation, weight, pattern)
_RULES: list[tuple[str, str, str, int, re.Pattern[str]]] = [
    ("password_request", "Pedido de senha",
     "Nenhum site ou suporte legítimo pede sua senha por mensagem, e-mail ou telefone.",
     3, re.compile(r"(informe|digite|confirme|envie|insira)\s+(sua\s+)?senha", re.I)),
    ("password_request_en", "Password request",
     "Legitimate services never ask for your password in a message.",
     3, re.compile(r"(enter|provide|confirm|send|type)\s+your\s+password", re.I)),
    ("otp_request", "Pedido de código de autenticação",
     "Ninguém deve pedir o código que chega por SMS/app; ele é só para você usar.",
     3, re.compile(r"(informe|envie|digite|passe)\s+(o\s+)?(código|codigo|token|2fa|otp)", re.I)),
    ("otp_request_en", "Verification code request",
     "Sharing a verification code lets someone else log in as you.",
     3, re.compile(r"(share|send|provide|give)\s+(the\s+)?(code|otp|2fa|verification code)", re.I)),
    ("card_data", "Pedido de dados de cartão",
     "Dados completos do cartão não devem ser enviados por mensagem ou página desconhecida.",
     3, re.compile(r"(número do cartão|numero do cartao|cvv|código de segurança do cartão|card number)", re.I)),
    ("urgency", "Urgência artificial",
     "Golpes costumam criar pressa para você não pensar.",
     2, re.compile(r"(urgente|imediatamente|agora mesmo|última chance|ultima chance|em \d+ horas|conta será bloqueada|conta sera bloqueada)", re.I)),
    ("threat", "Ameaça de bloqueio/ação judicial",
     "Ameaças de bloqueio imediato são um sinal clássico de fraude.",
     2, re.compile(r"(sua conta (será|sera) (bloqueada|suspensa|encerrada)|processo judicial|ação legal|acao legal|multa)", re.I)),
    ("prize", "Prêmio ou ganho inesperado",
     "Você não ganha prêmios em sorteios nos quais não se inscreveu.",
     2, re.compile(r"(você foi selecionado|voce foi selecionado|você ganhou|voce ganhou|prêmio de|premio de|resgate seu prêmio)", re.I)),
    ("fake_support", "Falso suporte técnico",
     "Suporte legítimo não liga do nada pedindo acesso ou pagamento.",
     3, re.compile(r"(suporte (técnico|tecnico) (da microsoft|da apple|do banco)|seu (computador|pc) está infectado|está com vírus|equipe de suporte ligou)", re.I)),
    ("remote_access", "Pedido de acesso remoto",
     "Permitir acesso remoto a um desconhecido dá controle total da sua máquina.",
     3, re.compile(r"(anydesk|teamviewer|acesso remoto|remote access|permita o controle)", re.I)),
    ("crypto_investment", "Investimento com lucro garantido",
     "Não existe lucro garantido; promessas assim são sinal de fraude.",
     2, re.compile(r"(lucro garantido|retorno garantido|ganhe \d+%|renda garantida|investimento garantido)", re.I)),
    ("payment_redirect", "Pagamento fora do site oficial",
     "Pagamentos fora do canal oficial costumam indicar golpe.",
     2, re.compile(r"(pague via pix para|depósito em conta pessoal|transferência para conta particular|whatsapp para pagamento)", re.I)),
    ("suspicious_download", "Download suspeito",
     "Arquivos executáveis enviados por mensagem ou em sites desconhecidos são perigosos.",
     2, re.compile(r"(baixe (o|este) (programa|arquivo|instalador)|download\.exe|\.apk fora da loja)", re.I)),
]

# Domain patterns that raise suspicion (lookalikes, free hosts, IPs).
_SUSPICIOUS_DOMAIN_HINTS = [
    ("ip_address", "Endereço de IP no lugar de um domínio", 2,
     re.compile(r"^https?://\d{1,3}(\.\d{1,3}){3}")),
    ("punycode", "Domínio com caracteres que imitam outro site (punycode)", 2,
     re.compile(r"^https?://xn--", re.I)),
    ("free_host", "Página hospedada em serviço gratuito, comum em golpes", 1,
     re.compile(r"^https?://[^/]*\.(000webhostapp|weebly|wixsite|blogspot|github\.io|glitch\.me|netlify\.app)\b", re.I)),
    ("long_subdomain", "Muitos subdomínios, possível imitação de banco", 2,
     re.compile(r"^https?://(?:[^./]+\.){4,}", re.I)),
]

# Brand names commonly imitated; combined with a non-official domain → signal.
_BRANDS = ["nubank", "itau", "itaú", "bradesco", "santander", "caixa", "banco do brasil",
           "mercadolivre", "mercado livre", "amazon", "netflix", "whatsapp", "instagram",
           "facebook", "microsoft", "apple", "google", "paypal", "binance"]


@dataclass
class ScamReport:
    risk: str = "low"  # low | medium | high
    score: int = 0
    findings: list[dict[str, Any]] = field(default_factory=list)
    url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"risk": self.risk, "score": self.score, "findings": self.findings,
                "url": self.url, "message": self.message()}

    def message(self) -> str:
        if self.risk == "low":
            return "Não encontrei sinais claros de risco neste conteúdo."
        if self.risk == "medium":
            return ("Há alguns sinais de risco. Vá com calma, confira a fonte antes de "
                    "informar qualquer dado e não faça pagamentos.")
        return ("Pare um momento. Há sinais fortes de possível golpe. "
                "Recomendo não continuar e não informar dados, senhas ou códigos.")


def analyze_text(text: str, url: str = "") -> ScamReport:
    """Assess fraud signals in visible text and/or a URL."""
    report = ScamReport(url=url)
    body = text or ""

    for rid, label, explain, weight, pat in _RULES:
        m = pat.search(body)
        if m:
            report.score += weight
            report.findings.append({
                "id": rid, "label": label, "explanation": explain, "weight": weight,
                "evidence": m.group(0)[:120],
            })

    if url:
        parsed = urlparse(url if "://" in url else "http://" + url)
        for did, label, weight, pat in _SUSPICIOUS_DOMAIN_HINTS:
            if pat.search(url):
                report.score += weight
                report.findings.append({"id": did, "label": label, "weight": weight,
                                        "explanation": "O endereço tem características usadas em golpes.",
                                        "evidence": url[:120]})
        host = (parsed.hostname or "").lower()
        for brand in _BRANDS:
            if brand.replace(" ", "") in host.replace("-", "").replace(" ", ""):
                # A brand in the hostname that is not the brand's real domain.
                official = f"{brand.split()[0]}.com"
                if official not in host:
                    report.score += 2
                    report.findings.append({
                        "id": "brand_imitation", "label": f"Possível imitação de {brand}",
                        "weight": 2, "evidence": host,
                        "explanation": "O endereço usa o nome de uma marca conhecida, mas não é o site oficial dela.",
                    })
                break

    if report.score >= 5:
        report.risk = "high"
    elif report.score >= 2:
        report.risk = "medium"
    else:
        report.risk = "low"
    return report


def analyze_page(text: str, url: str = "") -> dict[str, Any]:
    return analyze_text(text, url).to_dict()
