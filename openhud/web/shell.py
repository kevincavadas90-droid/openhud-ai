"""Shared HTML shell for the public site and the account pages.

One place defines the navigation, footer, SEO/Open-Graph tags and the design
system so every page stays visually consistent. The navigation is auth-aware:
it shows "Entrar / Criar conta" for visitors and "Conta / Sair" for signed-in
users.
"""
from __future__ import annotations

from .. import __version__
from ..config import settings

NAV = [
    ("/", "Início"),
    ("/features", "Recursos"),
    ("/how-it-works", "Como funciona"),
    ("/download", "Download"),
    ("/pricing", "Preços"),
    ("/help", "Ajuda"),
]

SITE_NAME = "OpenHUD AI"
DEFAULT_DESCRIPTION = (
    "OpenHUD AI é um assistente inteligente para o seu computador: monitora o PC, "
    "ajuda em tarefas, conversa por voz e age só com a sua permissão."
)


def _base_url() -> str:
    import os

    return os.environ.get("OPENHUD_PUBLIC_URL", "").rstrip("/")


def _nav_links(active: str) -> str:
    return "".join(
        f'<a href="{href}"{" class=\"active\"" if href == active else ""}>{label}</a>'
        for href, label in NAV
    )


def _account_actions(authenticated: bool) -> str:
    if authenticated:
        return ('<a class="btn ghost" href="/account">Minha conta</a>'
                '<a class="btn" href="/app">Abrir app</a>')
    return ('<a class="btn ghost" href="/login">Entrar</a>'
            '<a class="btn" href="/register">Criar conta</a>')


def page_shell(title: str, description: str, active: str, body: str,
               *, authenticated: bool = False, canonical: str = "",
               no_index: bool = False, body_class: str = "") -> str:
    base = _base_url()
    canonical_url = f"{base}{canonical}" if (base and canonical) else canonical
    og_tags = f'<meta property="og:title" content="{title} — {SITE_NAME}" />'
    og_tags += f'\n<meta property="og:description" content="{description}" />'
    og_tags += f'\n<meta property="og:type" content="website" />'
    og_tags += f'\n<meta property="og:site_name" content="{SITE_NAME}" />'
    og_tags += f'\n<meta name="twitter:card" content="summary_large_image" />'
    og_tags += f'\n<meta name="twitter:title" content="{title} — {SITE_NAME}" />'
    og_tags += f'\n<meta name="twitter:description" content="{description}" />'
    if base:
        og_tags += f'\n<meta property="og:image" content="{base}/static/site/app-icon-256.png" />'
    if canonical_url:
        og_tags += f'\n<link rel="canonical" href="{canonical_url}" />'
    robots = '\n<meta name="robots" content="noindex,nofollow" />' if no_index else ""

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title} — {SITE_NAME}</title>
<meta name="description" content="{description}" />{robots}
{og_tags}
<link rel="icon" href="/static/site/favicon.svg" type="image/svg+xml" />
<link rel="apple-touch-icon" href="/static/site/app-icon-256.png" />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;600;700&display=swap" />
<link rel="stylesheet" href="/static/site/site.css?v=5.2.0" />
</head>
<body class="{body_class}">
<header class="site">
  <div class="wrap nav" id="nav">
    <a class="brand" href="/"><img src="/static/site/logo.svg" alt="" width="26" height="26" /> {SITE_NAME}</a>
    <button class="btn ghost nav-toggle" id="nav-toggle" aria-label="Abrir menu">Menu</button>
    <nav class="nav-links">{_nav_links(active)}</nav>
    <div class="nav-actions">{_account_actions(authenticated)}</div>
  </div>
</header>
<main>
{body}
</main>
<footer class="site">
  <div class="wrap">
    <div class="foot">
      <div>
        <a class="brand" href="/"><img src="/static/site/logo.svg" alt="" width="26" height="26" /> {SITE_NAME}</a>
        <p style="margin-top:12px;font-size:14px">Assistente inteligente para usar o computador, monitorar o PC, automatizar tarefas e conversar por voz — com permissões claras.</p>
      </div>
      <div><h4>Produto</h4><a href="/features">Recursos</a><a href="/how-it-works">Como funciona</a><a href="/download">Download</a><a href="/pricing">Preços</a></div>
      <div><h4>Suporte</h4><a href="/help">Ajuda</a><a href="/download">Manual de instalação</a><a href="/changelog">Changelog</a><a href="/version">Versão</a></div>
      <div><h4>Projeto</h4><a href="/login">Entrar</a><a href="/register">Criar conta</a><a href="/privacy">Privacidade</a><a href="/pricing">Apoiar o projeto</a></div>
    </div>
    <p class="fine">OpenHUD AI · versão <span id="foot-version">{__version__}</span> · Windows 10/11 (64 bits). Este site não coleta dados sem a sua ação.</p>
  </div>
</footer>
<script src="/static/site/site.js?v=5.2.0"></script>
</body>
</html>"""
