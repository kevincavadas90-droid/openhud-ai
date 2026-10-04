"""Public marketing site for OpenHUD AI.

Self-contained, server-rendered pages sharing one shell (nav + footer + SEO)
so the brand stays consistent. Pages are public (no session required) and
contain no secrets. The download page reads real metadata from
:mod:`openhud.core.release` — it never invents a file, size or hash. The pricing
page reads a real donation URL from ``OPENHUD_DONATION_URL`` (never invented).

Routes:
    /            landing            /download   Windows installer + source
    /features    feature list       /changelog  release notes
    /how-it-works step by step      /version    JSON version
    /pricing     honest pricing     /help       FAQ + manual
    /privacy     privacy summary    /sitemap.xml /robots.txt
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse

from .. import __version__
from ..config import settings
from ..core import release as release_mod
from .shell import DEFAULT_DESCRIPTION, SITE_NAME, page_shell

router = APIRouter()

# Paths that are part of the public marketing site and never require a session.
PUBLIC_SITE_PATHS = {
    "/", "/features", "/how-it-works", "/pricing", "/help", "/privacy",
    "/download", "/download/file", "/download/source", "/changelog", "/version",
    "/api/site/release", "/api/site/changelog", "/api/site/config",
    "/sitemap.xml", "/robots.txt",
    "/static/site/logo.svg", "/static/site/favicon.svg",
}

# Simple, consistent line icons (Feather-style, stroke = currentColor).
_ICONS = {
    "monitor": '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
    "activity": '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    "cpu": '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3"/>',
    "gauge": '<path d="M12 20a8 8 0 1 0-8-8"/><path d="M12 12l4-4"/><circle cx="12" cy="12" r="1.5"/>',
    "hard-drive": '<path d="M22 12H2M5.5 6h13l3.5 6v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-6z"/><circle cx="7" cy="16" r="1"/>',
    "gamepad": '<path d="M6 12h4M8 10v4M15 11h.01M18 13h.01"/><rect x="2" y="6" width="20" height="12" rx="6"/>',
    "terminal": '<path d="M4 17l6-6-6-6M12 19h8"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "mic": '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 19v3"/>',
    "layers": '<path d="M12 2l9 5-9 5-9-5 9-5zM3 12l9 5 9-5M3 17l9 5 9-5"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="M21 15l-5-5L5 21"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "plug": '<path d="M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0zM12 18v4"/>',
    "brain": '<path d="M9 3a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 2V3a3 3 0 0 0-3 0zM15 3a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-6 2V3a3 3 0 0 1 3 0z"/>',
    "zap": '<path d="M13 2L3 14h7l-1 8 10-12h-7z"/>',
    "users": '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
    "heart": '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 1 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8z"/>',
}


def _icon(name: str) -> str:
    path = _ICONS.get(name, "")
    return (f'<span class="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{path}</svg></span>')


def _is_authed(request: Request) -> bool:
    try:
        from .accounts_api import current_user
        from .auth import COOKIE_NAME

        if current_user(request) is not None:
            return True
        from .app import auth

        return auth.verify_token(request.cookies.get(COOKIE_NAME))
    except Exception:
        return False


def _shell(request: Request, title: str, description: str, active: str, body: str,
           **kw) -> str:
    return page_shell(title, description, active, body,
                      authenticated=_is_authed(request), **kw)


@router.get("/", response_class=HTMLResponse)
def landing(request: Request) -> str:
    return FileResponse(settings.static_dir / "site" / "index.html",
                        headers={"Cache-Control": "no-cache"})


@router.get("/version")
def version_json() -> JSONResponse:
    rel = release_mod.get_release()
    return JSONResponse({
        "app": "openhud",
        "product": release_mod.PRODUCT,
        "version": __version__,
        "platform": release_mod.PLATFORM,
        "download": rel.to_dict(),
    })


@router.get("/api/site/release")
def api_release() -> dict[str, Any]:
    return release_mod.get_release().to_dict()


@router.get("/api/site/changelog")
def api_changelog() -> dict[str, Any]:
    return {"entries": release_mod.changelog()}


@router.get("/api/site/config")
def api_site_config() -> dict[str, Any]:
    """Public, non-sensitive site configuration used by the pages."""
    return {
        "donation_url": release_mod.donation_url(),
        "accounts_enabled": os.environ.get("OPENHUD_ACCOUNTS", "on").lower()
        not in {"off", "0", "false"},
        "public_url": os.environ.get("OPENHUD_PUBLIC_URL", "").rstrip("/"),
    }


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------
@router.get("/features", response_class=HTMLResponse)
def features(request: Request) -> str:
    cards = [
        ("monitor", "Assistente de computador", "Entende pedidos em linguagem natural e ajuda a resolver: abrir programas, encontrar botões, preencher campos e navegar."),
        ("activity", "Monitoramento real do PC", "Telemetria de CPU, GPU, RAM, disco e rede com dados observados — nunca valores inventados."),
        ("cpu", "Diagnóstico de desempenho", "Identifica gargalos e recomenda ajustes com base no hardware e no uso reais da sua máquina."),
        ("gamepad", "Jogos", "Detecta jogos instalados, perfil sugerido por jogo e leitura de FPS quando o jogo está aberto."),
        ("gauge", "GPU, CPU, RAM e disco", "Leitura multi-vendor de GPU (NVIDIA, AMD, Intel) e uso de memória, armazenamento e rede."),
        ("terminal", "Automações e comandos", "Tarefas agendadas, scripts e execução de comandos autorizados, com bloqueio de padrões destrutivos."),
        ("mic", "Voz e conversa contínua", "Converse por voz, com transcrição no navegador e respostas faladas; comandos como parar, pausar e continuar."),
        ("layers", "Memória e aprendizado", "Memória de longo prazo, projetos e histórico para manter o contexto entre sessões."),
        ("image", "Recursos multimodais", "Geração de imagem, narração e render de vídeo em fila, além de leitura de tela por OCR."),
        ("plug", "Integrações e plugins", "Barramento de ferramentas extensível e plugins com permissões por risco."),
        ("brain", "Codex de engenharia", "Análise de projeto, planos, changesets com diff/aplicar/reverter e execução de testes."),
        ("lock", "Segurança e permissões", "Tela, controle e voz desligados por padrão; ações sensíveis sempre pedem confirmação explícita."),
    ]
    items = "".join(
        f'<div class="card">{_icon(ic)}<h3>{t}</h3><p>{d}</p></div>' for ic, t, d in cards
    )
    body = f"""
  <section class="block" style="border-top:none">
    <div class="wrap">
      <div class="section-head"><h2>Recursos</h2><p>O que o OpenHUD AI faz de verdade — sem promessas que não podemos cumprir.</p></div>
      <div class="grid c3">{items}</div>
    </div>
  </section>
  <section class="block">
    <div class="wrap center">
      <h2>Pronto para começar?</h2>
      <p>Crie sua conta e baixe o aplicativo para Windows.</p>
      <div class="cta" style="justify-content:center;display:flex;gap:12px;flex-wrap:wrap">
        <a class="btn lg" href="/register">Criar conta</a>
        <a class="btn ghost lg" href="/download">Baixar OpenHUD AI</a>
      </div>
    </div>
  </section>"""
    return _shell(request, "Recursos", "Recursos do OpenHUD AI: monitoramento do PC, otimização, jogos, automações, voz e segurança.",
                  "/features", body, canonical="/features")


@router.get("/how-it-works", response_class=HTMLResponse)
def how_it_works(request: Request) -> str:
    steps = [
        ("Criar conta", "Crie sua conta no site com e-mail e senha. É rápido e não exige cartão."),
        ("Baixar o OpenHUD AI", "Baixe o aplicativo para Windows na página de download."),
        ("Entrar", "Abra o aplicativo e entre com a sua conta — o mesmo e-mail e senha do site."),
        ("Vincular computador", "O aplicativo registra este computador na sua conta, com um token de dispositivo."),
        ("Configurar permissões", "Escolha o que o OpenHUD pode acessar: Básico, Tela, Controle, Automação e Voz."),
        ("Usar o assistente", "Converse por texto ou voz. A IA orienta ou executa dentro do que você permitiu."),
    ]
    items = "".join(
        f'<div class="step"><span class="n">{i+1}</span><div><h3>{t}</h3><p>{d}</p></div></div>'
        for i, (t, d) in enumerate(steps)
    )
    body = f"""
  <section class="block" style="border-top:none">
    <div class="wrap">
      <div class="section-head"><h2>Como funciona</h2><p>Do site ao aplicativo no Windows, em seis passos.</p></div>
      <div class="grid c2" style="align-items:start;gap:40px">
        <div class="steps">{items}</div>
        <div>
          <div class="card" style="margin-bottom:16px"><h3>Arquitetura</h3><p>Site público ⇄ servidor central (API, WebSocket, contas, memória, IA, tarefas, agentes) ⇄ aplicativo Windows. O aplicativo sempre inicia a conexão de saída (HTTPS/WSS); o seu computador nunca fica exposto à internet.</p></div>
          <div class="card"><h3>Privacidade por padrão</h3><p>Captura de tela, controle e voz ficam desligados até você autorizar. Você pode revogar qualquer permissão a qualquer momento.</p></div>
        </div>
      </div>
    </div>
  </section>"""
    return _shell(request, "Como funciona", "Como o OpenHUD AI funciona, do cadastro ao aplicativo no Windows.",
                  "/how-it-works", body, canonical="/how-it-works")


@router.get("/pricing", response_class=HTMLResponse)
def pricing(request: Request) -> str:
    donation = release_mod.donation_url()
    if donation:
        donate_action = (f'<a class="btn lg" href="{donation}" target="_blank" rel="noopener noreferrer">'
                         f'APOIAR O PROJETO</a>')
        donate_note = "Obrigado! Cada contribuição ajuda a manter os servidores e o desenvolvimento."
    else:
        donate_action = '<button class="btn lg" disabled title="Configure OPENHUD_DONATION_URL">APOIAR O PROJETO</button>'
        donate_note = ("O link de doação ainda não foi configurado. Defina a variável de ambiente "
                       "<code>OPENHUD_DONATION_URL</code> para ativar este botão — não inventamos um endereço de pagamento.")
    body = f"""
  <section class="block" style="border-top:none">
    <div class="wrap">
      <div class="section-head"><h2>Planos</h2><p>Os planos comerciais do OpenHUD AI estão em desenvolvimento.</p></div>
      <div class="grid c2">
        <div class="card price-card featured">
          <span class="tag">Disponível agora</span>
          <h3>Durante o desenvolvimento</h3>
          <div class="amount">Grátis</div>
          <p>O OpenHUD AI é gratuito durante o desenvolvimento. Não há cobranças hoje e nenhum recurso é bloqueado por pagamento.</p>
          <ul>
            <li>Conta, login e dispositivos vinculados</li>
            <li>Monitoramento do PC, jogos e diagnóstico</li>
            <li>Assistente de computador, visão de tela e voz</li>
            <li>Automações, memória e plugins</li>
            <li>Permissões e confirmação de ações sensíveis</li>
          </ul>
          <a class="btn lg" href="/download">Baixar OpenHUD AI</a>
        </div>
        <div class="card price-card">
          <span class="tag">Em estruturação</span>
          <h3>Planos comerciais</h3>
          <div class="amount">—</div>
          <p>Os recursos pagos ainda estão sendo estruturados. Quando existirem, serão anunciados aqui com transparência, preços claros e sem letras miúdas.</p>
          <ul>
            <li>Sem cobranças hoje</li>
            <li>Nada é bloqueado por pagamento</li>
            <li>Aviso público antes de qualquer mudança</li>
          </ul>
        </div>
      </div>
    </div>
  </section>
  <section class="block">
    <div class="wrap">
      <div class="donate">
        <div>
          <h3>Ajude a manter o projeto</h3>
          <p>Doações ajudam a pagar servidores e infraestrutura, e a financiar novos recursos. {donate_note}</p>
        </div>
        <div>{donate_action}</div>
      </div>
      <p class="muted" style="margin-top:18px;font-size:14px">Não prometemos que o OpenHUD AI será gratuito para sempre — mas, enquanto for, avisaremos antes de qualquer mudança.</p>
    </div>
  </section>"""
    return _shell(request, "Preços", "Planos do OpenHUD AI em desenvolvimento. Gratuito durante o desenvolvimento; apoie o projeto.",
                  "/pricing", body, canonical="/pricing")


@router.get("/help", response_class=HTMLResponse)
def help_page(request: Request) -> str:
    faqs = [
        ("O OpenHUD controla meu computador sozinho?", "Não. O controle é desligado por padrão. Você concede as permissões e pode revogá-las a qualquer momento; ações sensíveis sempre pedem confirmação."),
        ("Preciso abrir porta no roteador?", "Não. O agente inicia uma conexão de saída (WSS) com o servidor. Seu computador não fica exposto à internet."),
        ("Funciona sem chave de IA?", "Sim. Há um provedor sem chave e suporte a modelo local. Para mais qualidade, adicione a chave de um provedor em Configurações."),
        ("Como crio minha conta?", "Acesse /register, informe nome, e-mail e uma senha. Você já entra automaticamente após o cadastro."),
        ("Esqueci minha senha. E agora?", "Use /forgot-password com o seu e-mail. Se o e-mail existir, enviamos um link de redefinição válido por 1 hora."),
        ("Como instalo no Windows?", "Baixe o instalador em /download, execute e siga o assistente. Você pode escolher atalhos e iniciar com o Windows (opção desmarcada por padrão)."),
        ("Como desinstalo?", "Painel de Controle → Aplicativos → OpenHUD AI → Desinstalar. O desinstalador remove os arquivos e pergunta se você quer apagar seus dados locais."),
        ("Como funcionam as atualizações?", "O aplicativo verifica um manifesto HTTPS com versão e soma SHA-256. Nada é executado automaticamente; o download é verificado antes de aplicar, com rollback."),
        ("Minha tela é enviada para algum lugar?", "A captura é usada para responder ao seu pedido e processada conforme as permissões que você concedeu. Áudio não é salvo por padrão."),
    ]
    items = "".join(f'<details class="qa"><summary>{q}</summary><p>{a}</p></details>' for q, a in faqs)
    body = f"""
  <section class="block" style="border-top:none">
    <div class="wrap">
      <div class="section-head"><h2>Ajuda</h2><p>Perguntas frequentes e o manual de instalação.</p></div>
      <div class="faq">{items}</div>
    </div>
  </section>
  <section class="block">
    <div class="wrap">
      <div class="section-head"><h2>Manual de instalação (Windows)</h2></div>
      <div class="steps">
        <div class="step"><span class="n">1</span><div><h3>Baixe o instalador</h3><p>Em <a href="/download">/download</a>. Confira a versão e o SHA-256 exibidos.</p></div></div>
        <div class="step"><span class="n">2</span><div><h3>Execute o instalador</h3><p>Dê duplo clique em <span class="mono">OpenHUD-AI-Setup.exe</span> e siga o assistente.</p></div></div>
        <div class="step"><span class="n">3</span><div><h3>Entre na sua conta</h3><p>Na primeira execução, o aplicativo pede para entrar ou criar conta.</p></div></div>
        <div class="step"><span class="n">4</span><div><h3>Vincule e use</h3><p>Confirme as permissões e comece a conversar por texto ou voz.</p></div></div>
      </div>
    </div>
  </section>"""
    return _shell(request, "Ajuda", "Ajuda e manual de instalação do OpenHUD AI.", "/help", body, canonical="/help")


@router.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request) -> str:
    body = """
  <section class="block" style="border-top:none">
    <div class="wrap">
      <div class="section-head"><h2>Privacidade</h2><p>Resumo direto do que o OpenHUD AI faz e não faz com os seus dados.</p></div>
      <div class="grid c2">
        <div class="card"><h3>Coletamos o mínimo</h3><p>Não usamos rastreadores de terceiros, pixels de anúncio nem analytics invasivos. O site não coleta dados sem a sua ação.</p></div>
        <div class="card"><h3>Senhas protegidas</h3><p>Senhas são guardadas apenas como hash PBKDF2-SHA256 com sal próprio. Nunca armazenamos senha em texto puro e nunca colocamos credenciais no frontend.</p></div>
        <div class="card"><h3>Permissões explícitas</h3><p>Tela, controle e voz ficam desligados até você autorizar. Você pode revogar a qualquer momento.</p></div>
        <div class="card"><h3>Sem segredos no frontend</h3><p>Chaves de API ficam no servidor, em armazenamento criptografado. Nada de tokens no navegador.</p></div>
        <div class="card"><h3>Áudio e tela</h3><p>Áudio não é salvo por padrão. Capturas são usadas para responder ao seu pedido, conforme as permissões concedidas.</p></div>
        <div class="card"><h3>Seus dados, sua escolha</h3><p>Você pode alterar sua senha, gerenciar dispositivos e excluir a sua conta na página Minha conta.</p></div>
      </div>
    </div>
  </section>"""
    return _shell(request, "Privacidade", "Privacidade e proteção de dados no OpenHUD AI.", "/privacy", body, canonical="/privacy")


@router.get("/download", response_class=HTMLResponse)
def download_page(request: Request) -> str:
    body = """
  <section class="block" style="border-top:none">
    <div class="wrap">
      <div class="section-head">
        <h2>Baixar OpenHUD AI</h2>
        <p>Aplicativo para Windows 10/11 (64 bits) com desinstalador. Confira versão, tamanho e SHA-256 reais abaixo.</p>
      </div>
      <div class="dl-card">
        <div class="dl-head">
          <h3 style="margin:0">OpenHUD AI para Windows</h3>
          <span id="dl-badge" class="badge warn">verificando…</span>
        </div>
        <p id="dl-desc" style="margin-top:10px">Instalador oficial (Inno Setup) · atalhos e início automático opcionais.</p>
        <div class="dl-meta" id="dl-meta"></div>
        <div id="dl-action"><button class="btn lg" disabled>Carregando…</button></div>
        <div id="dl-notice"></div>
        <details class="qa" style="margin-top:20px"><summary>Requisitos</summary><ul id="dl-req"></ul></details>
        <details class="qa" style="margin-top:10px"><summary>Changelog</summary><div id="dl-changelog" style="margin-top:10px"></div></details>
        <details class="qa" style="margin-top:10px"><summary>SHA-256</summary><p class="mono" id="dl-sha">—</p></details>
        <details class="qa" style="margin-top:10px"><summary>Manual de instalação</summary>
          <p>1. Baixe o arquivo. 2. Dê duplo clique em <span class="mono">OpenHUD-AI-Setup.exe</span>. 3. Siga o assistente. 4. Na primeira execução, entre na sua conta e escolha as permissões. Atalhos e iniciar com o Windows são desmarcados por padrão.</p>
        </details>
      </div>
      <div class="dl-card" style="margin-top:22px">
        <div class="dl-head">
          <h3 style="margin:0">Código-fonte completo</h3>
          <span id="src-badge" class="badge warn">verificando…</span>
        </div>
        <p style="margin-top:10px">Todo o projeto em Python: servidor, agente Windows, ferramentas, testes e scripts do instalador. Licença MIT.</p>
        <div class="dl-meta" id="src-meta"></div>
        <div id="src-action"><button class="btn lg" disabled>Carregando…</button></div>
        <div id="src-notice"></div>
      </div>
    </div>
  </section>
<script>
async function loadRelease() {
  const badge = document.getElementById("dl-badge");
  const meta = document.getElementById("dl-meta");
  const action = document.getElementById("dl-action");
  const notice = document.getElementById("dl-notice");
  const req = document.getElementById("dl-req");
  const sha = document.getElementById("dl-sha");
  const chlog = document.getElementById("dl-changelog");
  try {
    const d = await fetch("/api/site/release").then(r => r.json());
    req.innerHTML = (d.requirements || []).map(x => `<li>${x}</li>`).join("");
    sha.textContent = d.sha256 || "será exibido após a publicação do instalador";
    meta.innerHTML = `
      <div><div class="k">Versão</div><div class="v">${d.version}</div></div>
      <div><div class="k">Plataforma</div><div class="v">${d.platform}</div></div>
      <div><div class="k">Tamanho</div><div class="v">${d.size_human || "—"}</div></div>
      <div><div class="k">Arquivo</div><div class="v mono">${d.filename}</div></div>
      <div><div class="k">Publicado em</div><div class="v">${d.released_at ? new Date(d.released_at).toLocaleDateString("pt-BR") : "—"}</div></div>
      <div><div class="k">Requisitos</div><div class="v">${d.min_windows}</div></div>`;
    if (d.published && d.url) {
      badge.className = "badge ok"; badge.textContent = "disponível";
      action.innerHTML = `<a class="btn lg" href="${d.url}" rel="noopener">BAIXAR PARA WINDOWS</a>`;
    } else {
      badge.className = "badge err"; badge.textContent = "não publicado";
      action.innerHTML = `<button class="btn lg" disabled>Indisponível no momento</button>`;
      notice.innerHTML = `<div class="notice" style="margin-top:16px"><strong>O instalador ainda não foi publicado.</strong><br>Assim que o arquivo oficial for hospedado (GitHub Releases ou CDN) e a variável <code>OPENHUD_DOWNLOAD_URL</code> for definida, o botão aparece aqui automaticamente. Não exibimos um link falso.</div>`;
    }
  } catch (e) {
    badge.className = "badge err"; badge.textContent = "erro";
    action.innerHTML = `<button class="btn lg" disabled>Erro ao carregar</button>`;
  }
  try {
    const c = await fetch("/api/site/changelog").then(r => r.json());
    chlog.innerHTML = c.entries.map(e => `<div style="margin-bottom:10px"><strong>${e.version}</strong> ${e.date ? "· " + e.date : ""}<ul style="padding-left:18px">${e.items.map(i => `<li>${i}</li>`).join("")}</ul></div>`).join("");
  } catch (e) {}
}
async function loadSource() {
  const badge = document.getElementById("src-badge");
  const meta = document.getElementById("src-meta");
  const action = document.getElementById("src-action");
  const notice = document.getElementById("src-notice");
  try {
    const d = await fetch("/api/site/release").then(r => r.json());
    if (d.source_zip_available && d.source_zip_url) {
      badge.className = "badge ok"; badge.textContent = "disponível";
      meta.innerHTML = `
        <div><div class="k">Arquivo</div><div class="v mono">${d.source_zip_name}</div></div>
        <div><div class="k">Tamanho</div><div class="v">${d.source_zip_size_human || "—"}</div></div>
        <div><div class="k">SHA-256</div><div class="v mono" style="word-break:break-all">${d.source_zip_sha256 || "—"}</div></div>`;
      action.innerHTML = `<a class="btn lg" href="${d.source_zip_url}" rel="noopener">BAIXAR CÓDIGO-FONTE (.zip)</a>`;
    } else {
      badge.className = "badge warn"; badge.textContent = "não publicado";
      meta.innerHTML = "";
      action.innerHTML = `<button class="btn lg" disabled>Indisponível no momento</button>`;
      notice.innerHTML = `<div class="notice" style="margin-top:16px">O pacote de código-fonte ainda não foi publicado neste servidor. Gere-o com <code>python tools/make_source_zip.py</code> ou defina <code>OPENHUD_SOURCE_URL</code>.</div>`;
    }
  } catch (e) {
    badge.className = "badge err"; badge.textContent = "erro";
    action.innerHTML = `<button class="btn lg" disabled>Erro ao carregar</button>`;
  }
}
loadRelease();
loadSource();
</script>"""
    return _shell(request, "Baixar para Windows", "Baixe o OpenHUD AI para Windows 10/11 (64 bits), com tamanho e SHA-256 reais.",
                  "/download", body, canonical="/download")


@router.get("/download/file")
def download_file():
    """Serve the locally-built installer when the operator opted in.

    Disabled unless ``OPENHUD_SERVE_INSTALLER`` is set; free PaaS hosts are not
    a good place to serve large binaries (see DEPLOY.md). When disabled or the
    artifact is missing we return an honest 404 instead of a broken link.
    """
    if os.environ.get("OPENHUD_SERVE_INSTALLER", "").lower() not in {"1", "true", "on"}:
        raise HTTPException(404, "Download local desativado.")
    artifact = release_mod._first_existing_artifact()
    if artifact is None:
        raise HTTPException(404, "Instalador ainda não foi gerado.")
    return FileResponse(artifact, filename=artifact.name,
                        media_type="application/octet-stream")


@router.get("/download/source")
def download_source():
    """Serve the source ZIP when it exists and serving is opted in.

    Honest 404 otherwise — the source bundle is never fabricated.
    """
    source = release_mod._first_existing_source()
    if source is None:
        raise HTTPException(404, "Pacote de código-fonte ainda não foi gerado.")
    if os.environ.get("OPENHUD_SERVE_SOURCE", "").lower() not in {"1", "true", "on"}:
        raise HTTPException(404, "Download do código-fonte local desativado.")
    return FileResponse(source, filename=source.name, media_type="application/zip")


@router.get("/changelog", response_class=HTMLResponse)
def changelog_page(request: Request) -> str:
    entries = release_mod.changelog()
    blocks = "".join(
        f'<div class="card" style="margin-bottom:14px"><h3>{e["version"]}'
        + (f' <span class="badge">{e["date"]}</span>' if e.get("date") else "")
        + '</h3><ul style="padding-left:18px;color:var(--muted);margin:0">'
        + "".join(f"<li>{i}</li>" for i in e["items"])
        + "</ul></div>"
        for e in entries
    )
    body = f"""
  <section class="block" style="border-top:none">
    <div class="wrap">
      <div class="section-head"><h2>Changelog</h2><p>Histórico de versões do OpenHUD AI.</p></div>
      {blocks}
    </div>
  </section>"""
    return _shell(request, "Changelog", "Histórico de versões do OpenHUD AI.", "/download", body,
                  canonical="/changelog")


@router.get("/sitemap.xml")
def sitemap() -> PlainTextResponse:
    base = os.environ.get("OPENHUD_PUBLIC_URL", "").rstrip("/")
    paths = ["/", "/features", "/how-it-works", "/download", "/pricing", "/help",
             "/privacy", "/changelog", "/register", "/login"]
    urls = "".join(
        f"<url><loc>{base}{p}</loc><changefreq>weekly</changefreq></url>" if base
        else f"<url><loc>{p}</loc></url>"
        for p in paths
    )
    xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    return PlainTextResponse(xml, media_type="application/xml")


@router.get("/robots.txt")
def robots() -> PlainTextResponse:
    base = os.environ.get("OPENHUD_PUBLIC_URL", "").rstrip("/")
    lines = ["User-agent: *", "Allow: /", "Disallow: /api/", "Disallow: /app",
             "Disallow: /account", "Disallow: /settings", "Disallow: /login",
             "Disallow: /register", "Disallow: /reset-password", "Disallow: /forgot-password"]
    if base:
        lines.append(f"Sitemap: {base}/sitemap.xml")
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain")
