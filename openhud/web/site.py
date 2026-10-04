"""Public marketing site for OpenHUD AI.

A small, self-contained set of server-rendered pages sharing one shell (nav +
footer) so the brand stays consistent. The pages are public (no session
required) and contain no secrets. The download page reads real metadata from
:mod:`openhud.core.release` — it never invents a file, size or hash.

Routes:
    /            landing            /download   Windows installer
    /features    feature list       /changelog  release notes
    /how-it-works step by step      /version    JSON version
    /pricing     honest pricing     /help       FAQ + manual
    /privacy     privacy summary
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .. import __version__
from ..config import settings
from ..core import release as release_mod

router = APIRouter()

# Paths that are part of the public marketing site and never require a session.
PUBLIC_SITE_PATHS = {
    "/", "/features", "/how-it-works", "/pricing", "/help", "/privacy",
    "/download", "/download/file", "/changelog", "/version",
    "/api/site/release", "/api/site/changelog",
    "/static/site/logo.svg", "/static/site/favicon.svg",
}

NAV = [
    ("/", "Início"),
    ("/features", "Recursos"),
    ("/how-it-works", "Como funciona"),
    ("/download", "Download"),
    ("/pricing", "Preços"),
    ("/help", "Ajuda"),
]


def _shell(title: str, description: str, active: str, body: str) -> str:
    parts = []
    for href, label in NAV:
        cls = ' class="active"' if href == active else ""
        parts.append(f'<a href="{href}"{cls}>{label}</a>')
    links = "".join(parts)
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title} — OpenHUD AI</title>
<meta name="description" content="{description}" />
<link rel="icon" href="/static/site/favicon.svg" type="image/svg+xml" />
<link rel="stylesheet" href="/static/site/site.css" />
</head>
<body>
<header class="site">
  <div class="wrap nav" id="nav">
    <a class="brand" href="/"><img src="/static/site/logo.svg" alt="" /> OpenHUD AI</a>
    <button class="btn ghost nav-toggle" id="nav-toggle" aria-label="Menu">Menu</button>
    <nav class="nav-links">
      {links}
      <a href="/login">Login</a>
      <a class="btn" href="/download">Baixar</a>
    </nav>
  </div>
</header>
<main>
{body}
</main>
<footer class="site">
  <div class="wrap">
    <div class="foot">
      <div>
        <a class="brand" href="/"><img src="/static/site/logo.svg" alt="" /> OpenHUD AI</a>
        <p style="margin-top:10px;font-size:14px">Assistente inteligente para ajudar você a usar seu computador, navegar na internet, controlar tarefas e conversar com IA por voz.</p>
      </div>
      <div><h4>Produto</h4><a href="/features">Recursos</a><a href="/how-it-works">Como funciona</a><a href="/download">Download</a><a href="/pricing">Preços</a></div>
      <div><h4>Suporte</h4><a href="/help">Ajuda</a><a href="/download">Manual de instalação</a><a href="/changelog">Changelog</a><a href="/version">Versão</a></div>
      <div><h4>Conta</h4><a href="/login">Login</a><a href="/privacy">Privacidade</a><a href="/health">Status do serviço</a></div>
    </div>
    <p class="fine">OpenHUD AI · versão <span id="foot-version">{__version__}</span> · Windows 10/11 (64 bits). Este site não coleta dados sem a sua ação.</p>
  </div>
</footer>
<script src="/static/site/site.js"></script>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse)
def landing() -> FileResponse:
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


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------
@router.get("/features", response_class=HTMLResponse)
def features() -> str:
    cards = [
        ("🖥️", "Assistente de computador", "Entende pedidos em linguagem natural e ajuda a resolver: abrir programas, encontrar botões, preencher campos e navegar."),
        ("👀", "Visão de tela", "Captura e lê a tela (OCR) para localizar elementos de verdade. Quando não consegue, informa o motivo — nunca inventa."),
        ("🖱️", "Faça comigo / Faça por mim", "Você escolhe: a IA guia passo a passo, ou executa a tarefa depois da sua autorização."),
        ("🎙️", "Voz e conversa contínua", "Converse por voz com comandos como \"pare\", \"pausa\" e \"continue\"."),
        ("🔒", "Permissões granulares", "Básico, Tela, Controle, Automação e Voz — ligue, desligue e revogue quando quiser."),
        ("🛡️", "Proteção de ações sensíveis", "Pagamentos, senhas, exclusões e downloads pedem confirmação explícita, mesmo no modo automático."),
        ("💬", "Chat, memória e projetos", "Histórico, memória de longo prazo e projetos para manter o contexto."),
        ("🧩", "Ferramentas e automação", "Terminal, arquivos, internet, análise de dados, tarefas agendadas e plugins."),
        ("📊", "Diagnóstico do PC", "Telemetria real de CPU, RAM, GPU, disco e rede, com recomendações baseadas em dados observados."),
    ]
    items = "".join(
        f'<div class="card"><span class="ic">{ic}</span><h3>{t}</h3><p>{d}</p></div>' for ic, t, d in cards
    )
    body = f"""
  <section class="block" style="border-top:none">
    <div class="wrap">
      <div class="section-head"><h2>Recursos</h2><p>Tudo o que o OpenHUD AI faz, com foco em ajudar de verdade — sem promessas que não podemos cumprir.</p></div>
      <div class="grid c3">{items}</div>
    </div>
  </section>
  <section class="block">
    <div class="wrap" style="text-align:center">
      <h2>Quer experimentar?</h2>
      <div class="cta" style="justify-content:center"><a class="btn lg" href="/download">Baixar para Windows</a><a class="btn ghost lg" href="/login">Entrar</a></div>
    </div>
  </section>"""
    return _shell("Recursos", "Recursos do OpenHUD AI.", "/features", body)


@router.get("/how-it-works", response_class=HTMLResponse)
def how_it_works() -> str:
    body = """
  <section class="block" style="border-top:none">
    <div class="wrap">
      <div class="section-head"><h2>Como funciona</h2><p>O site, o servidor central e o aplicativo no Windows trabalham juntos.</p></div>
      <div class="steps">
        <div class="step"><span class="n"></span><div><h3>Crie sua conta e entre</h3><p>Acesse o site, faça login e escolha o modelo de IA e as preferências.</p></div></div>
        <div class="step"><span class="n"></span><div><h3>Baixe e instale o aplicativo</h3><p>Baixe o instalador para Windows, instale e abra o assistente de primeira execução.</p></div></div>
        <div class="step"><span class="n"></span><div><h3>Pareie o computador</h3><p>Um código de uso único liga o aplicativo à sua conta, com um token de dispositivo.</p></div></div>
        <div class="step"><span class="n"></span><div><h3>Escolha as permissões</h3><p>Básico, Tela, Controle, Automação e Voz. O controle nunca é ativado sozinho.</p></div></div>
        <div class="step"><span class="n"></span><div><h3>Converse e receba ajuda</h3><p>Por texto ou voz, a IA orienta ou executa — dentro do que você permitiu.</p></div></div>
      </div>
      <div class="grid c2" style="margin-top:30px">
        <div class="card"><h3>Arquitetura</h3><p>Site público ⇄ servidor central (API, WebSocket, auth, memória, IA, tarefas, agentes) ⇄ aplicativo Windows. O aplicativo sempre inicia a conexão de saída (HTTPS/WSS).</p></div>
        <div class="card"><h3>Privacidade por padrão</h3><p>Captura de tela, controle e voz ficam desligados até você autorizar. Nada de persistência escondida.</p></div>
      </div>
    </div>
  </section>"""
    return _shell("Como funciona", "Como o OpenHUD AI funciona, do site ao aplicativo Windows.", "/how-it-works", body)


@router.get("/pricing", response_class=HTMLResponse)
def pricing() -> str:
    body = """
  <section class="block" style="border-top:none">
    <div class="wrap">
      <div class="section-head"><h2>Preços</h2><p>Grátis para uso pessoal. Não há planos pagos definidos — e não inventamos preços que ainda não existem.</p></div>
      <div class="grid c2">
        <div class="card price-card featured">
          <span class="tag">Disponível</span>
          <h3>Grátis</h3>
          <div class="amount">R$ 0</div>
          <p>Uso pessoal, com os recursos disponíveis na infraestrutura atual.</p>
          <ul>
            <li>Chat, voz e memória</li>
            <li>Assistente de computador e visão de tela</li>
            <li>Aplicativo Windows e agente de PC</li>
            <li>Permissões e confirmação de ações</li>
          </ul>
          <a class="btn lg" href="/download" style="margin-top:18px">Baixar para Windows</a>
        </div>
        <div class="card price-card">
          <span class="tag">Em estudo</span>
          <h3>Planos pagos</h3>
          <div class="amount">—</div>
          <p>Não há planos pagos definidos. Se surgirem, serão anunciados aqui com transparência.</p>
          <ul><li>Sem cobranças hoje</li><li>Nenhum recurso é bloqueado por pagamento</li></ul>
        </div>
      </div>
      <div class="notice" style="margin-top:24px">Na hospedagem gratuita, o servidor pode dormir após um período sem uso e levar alguns segundos para acordar na próxima visita. Isso é uma limitação da infraestrutura gratuita, não do produto.</div>
    </div>
  </section>"""
    return _shell("Preços", "Preços do OpenHUD AI — grátis para uso pessoal.", "/pricing", body)


@router.get("/help", response_class=HTMLResponse)
def help_page() -> str:
    faqs = [
        ("O OpenHUD controla meu computador sozinho?", "Não. O controle é desligado por padrão. Você concede as permissões e pode revogá-las a qualquer momento; ações sensíveis sempre pedem confirmação."),
        ("Preciso abrir porta no roteador?", "Não. O agente inicia uma conexão de saída (WSS) com o servidor. Seu computador não fica exposto à internet."),
        ("Funciona sem chave de IA?", "Sim. Há um provedor sem chave e suporte a modelo local. Para mais qualidade, adicione a chave de um provedor em Configurações."),
        ("Como instalo no Windows?", "Baixe o instalador em /download, execute e siga o assistente. Você pode escolher atalhos e iniciar com o Windows (opção desmarcada por padrão)."),
        ("Como desinstalo?", "Painel de Controle → Aplicativos → OpenHUD AI → Desinstalar. O desinstalador remove os arquivos do programa e pergunta se você quer apagar seus dados locais."),
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
        <div class="step"><span class="n"></span><div><h3>Baixe o instalador</h3><p>Em <a href="/download">/download</a>. Confira a versão e o SHA-256 exibidos.</p></div></div>
        <div class="step"><span class="n"></span><div><h3>Execute o instalador</h3><p>Dê duplo clique em <span class="mono">OpenHUD-AI-Setup.exe</span> e siga o assistente.</p></div></div>
        <div class="step"><span class="n"></span><div><h3>Primeira execução</h3><p>O assistente explica o produto, pede o pareamento e mostra as permissões.</p></div></div>
        <div class="step"><span class="n"></span><div><h3>Conecte e use</h3><p>Confirme a conexão e comece a conversar por texto ou voz.</p></div></div>
      </div>
    </div>
  </section>"""
    return _shell("Ajuda", "Ajuda e manual de instalação do OpenHUD AI.", "/help", body)


@router.get("/privacy", response_class=HTMLResponse)
def privacy_page() -> str:
    body = """
  <section class="block" style="border-top:none">
    <div class="wrap">
      <div class="section-head"><h2>Privacidade</h2><p>Resumo direto do que o OpenHUD AI faz e não faz com os seus dados.</p></div>
      <div class="grid c2">
        <div class="card"><h3>Coletamos o mínimo</h3><p>Não usamos rastreadores de terceiros, pixels de anúncio nem analytics invasivos. O site não coleta dados sem a sua ação.</p></div>
        <div class="card"><h3>Permissões explícitas</h3><p>Tela, controle e voz ficam desligados até você autorizar. Você pode revogar a qualquer momento.</p></div>
        <div class="card"><h3>Sem segredos no frontend</h3><p>Chaves de API ficam no servidor, em armazenamento criptografado. Nada de tokens no navegador.</p></div>
        <div class="card"><h3>Áudio e tela</h3><p>Áudio não é salvo por padrão. Capturas são usadas para responder ao seu pedido, conforme as permissões concedidas.</p></div>
        <div class="card"><h3>Seus dados, sua escolha</h3><p>Você pode exportar e apagar memória, histórico e experiências nas configurações.</p></div>
        <div class="card"><h3>Transparência</h3><p>Se algo depender de configuração externa, dizemos exatamente o que falta — sem mascarar erros.</p></div>
      </div>
    </div>
  </section>"""
    return _shell("Privacidade", "Privacidade no OpenHUD AI.", "/privacy", body)


@router.get("/download", response_class=HTMLResponse)
def download_page() -> str:
    body = """
  <section class="block" style="border-top:none">
    <div class="wrap">
      <div class="section-head">
        <h2>Baixar OpenHUD AI</h2>
        <p>Assistente inteligente para ajudar você a usar seu computador, navegar na internet, controlar tarefas e conversar com IA por voz.</p>
      </div>
      <div class="dl-card">
        <div class="row" style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
          <span style="font-size:22px">🪟</span>
          <h3 style="margin:0">OpenHUD AI para Windows</h3>
          <span id="dl-badge" class="badge warn">verificando…</span>
        </div>
        <p id="dl-desc" style="margin-top:10px">Windows 10/11 (64 bits) · instalador oficial com desinstalador.</p>
        <div class="dl-meta" id="dl-meta"></div>
        <div id="dl-action"><button class="btn lg" disabled>Carregando…</button></div>
        <div id="dl-notice"></div>
        <details class="qa" style="margin-top:20px"><summary>Ver requisitos</summary><ul id="dl-req" class="price-card" style="list-style:none;padding-left:0"></ul></details>
        <details class="qa" style="margin-top:10px"><summary>Ver changelog</summary><div id="dl-changelog" class="mono" style="margin-top:10px"></div></details>
        <details class="qa" style="margin-top:10px"><summary>SHA-256</summary><p class="mono" id="dl-sha">—</p></details>
        <details class="qa" style="margin-top:10px"><summary>Manual de instalação</summary>
          <p>1. Baixe o arquivo. 2. Dê duplo clique em <span class="mono">OpenHUD-AI-Setup.exe</span>. 3. Siga o assistente. 4. Na primeira execução, faça o pareamento e escolha as permissões. Opções de atalho e iniciar com o Windows são desmarcadas por padrão.</p>
        </details>
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
    const r = await fetch("/api/site/release");
    const d = await r.json();
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
      notice.innerHTML = `<div class="notice" style="margin-top:16px"><strong>O instalador ainda não foi publicado.</strong><br>Assim que o arquivo oficial for hospedado (GitHub Releases ou CDN) e a variável <code>OPENHUD_DOWNLOAD_URL</code> for definida, o botão de download aparece aqui automaticamente. Não exibimos um link falso.</div>`;
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
loadRelease();
</script>"""
    return _shell("Baixar para Windows", "Baixe o OpenHUD AI para Windows 10/11 (64 bits).", "/download", body)


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


@router.get("/changelog", response_class=HTMLResponse)
def changelog_page() -> str:
    entries = release_mod.changelog()
    blocks = "".join(
        f'<div class="card" style="margin-bottom:14px"><h3>{e["version"]}'
        + (f' <span class="badge">{e["date"]}</span>' if e.get("date") else "")
        + "</h3><ul style=\"padding-left:18px;color:var(--muted)\">"
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
    return _shell("Changelog", "Histórico de versões do OpenHUD AI.", "/download", body)
