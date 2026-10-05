# AGENTS.md — OpenHUD

Memória persistente do repositório para agentes que trabalharem neste projeto.

## Visão geral
OpenHUD é uma IA pessoal multifuncional: agente LLM + ferramentas reais +
memória + interface web. Python 3.11+, FastAPI, SQLite, front-end sem build.

## Comandos essenciais
- Tudo de uma vez: `./start.sh` (idempotente: venv + Ollama local + servidor)
- Só o servidor: `./run.sh` (cria `.venv` e inicia)
- Rodar servidor: `.venv/bin/python -m openhud`
- Testes: `.venv/bin/python -m pytest -q`
- Teste único: `.venv/bin/python -m pytest tests/test_api.py::test_streaming_turn_autonomous -q`

> Esta sandbox é reiniciada periodicamente e **perde processos e arquivos
> fora do repo** (o Ollama em `/usr/local` some). Depois de qualquer reinício,
> rode `./start.sh` — ele reinstala o Ollama e sobe tudo. Não há daemon cron
> no container, então a recuperação é manual.

## Convenções
- Estado de runtime em `data/` (ignorado no git). Workspace do agente em
  `workspace/` (`OPENHUD_WORKSPACE`).
- Segredos: SEMPRE via `SecretStore` (Fernet). Nunca logar valores brutos;
  a API só devolve prévia mascarada.
- Ferramentas novas: criar em `openhud/tools/`, herdar de `Tool`, e registrar
  em `build_default_registry()` (`openhud/tools/__init__.py`). Marcar
  `requires_confirmation = True` se alterar estado.
- Seleção de ferramentas: a config usa **blacklist** (`disabled_tools`), não
  whitelist — ferramentas novas ficam habilitadas por padrão. Não reintroduza
  `enabled_tools`.
- Caminhos de arquivo devem passar por `_resolve`/`_safe_path` para ficar
  dentro do workspace.
- O laço do agente (`openhud/agent/loop.py`) é o dono da persistência do turno
  do usuário. A camada HTTP não deve duplicar isso.

## Agente de PC (PC↔site)
- `openhud/core/agent_hub.py`: singleton `get_hub()`; hub WebSocket com
  pareamento por código de uso único, tokens de dispositivo e permissões por
  categoria (`PERMISSION_KEYS`). O PC **sempre** inicia a conexão (funciona
  atrás de NAT). `hub.loop` é setado no handler WS para permitir requisições
  servidor→PC.
- `openhud/agent/telemetry.py` + `diagnostics.py`: rodam **no PC**, não no
  servidor. Sem GPU NVIDIA, o diagnóstico reporta "GPU não detectada" — nunca
  inventa métricas.
- `openhud/agent/agent_client.py`: cliente do PC (`--server`, `--pair`,
  `--name`, `--interval`). Guarda o token e reconecta sozinho.
  `build_exe.py` gera um `.exe` com PyInstaller.
- `openhud/web/agent_api.py`: REST (`/api/agents*`) + WS (`/ws/agent`). O WS
  está em `PUBLIC_PATHS` (autentica pelo token do dispositivo, não pelo cookie).
- `openhud/tools/pc.py`: `pc_metrics`, `pc_diagnose`, `pc_game_profile` no chat.
  Se o hub não estiver inicializado, devolvem erro explícito.

## Módulo MT5 (trading)
- `openhud/trading/` é **lógica pura e testável** (sem MT5, FastAPI ou rede):
  `core.py` (permissões, modos, risco, estratégias, backtest, paper),
  `indicators.py` (SMA/EMA/RSI/MACD/ATR/ADX/estocástico/Bollinger/VWAP +
  price action, com `None` para barras sem valor — mantém alinhamento de índice),
  `analysis.py` (técnica + multi-timeframe), `alerts.py`, `store.py` (tabelas
  `trading_*`), `service.py` (orquestra site↔hub↔MT5).
- `openhud/agent/mt5_bridge.py` roda **no PC** e importa `MetaTrader5`
  preguiçosamente. Sem o pacote/terminal, retorna `ok=False` com o erro real —
  nunca inventa preço/saldo/execução. `agent_client._execute_mt5` liga os
  comandos `mt5_*`.
- Permissões de trading em `TRADING_PERMISSION_KEYS` (mesma store de permissões
  do PC). `ALLOW_REAL_TRADING` é **False** por padrão. `set_trading_mode` exige
  a permissão do modo; `hub.request("mt5_send_order")` revalida modo+permissão e
  respeita `emergency_stop`. Dispositivos antigos recebem as novas chaves via
  backfill em `AgentHub._load`.
- Envio de ordem é **idempotente** por `request_id` (tabela `trading_orders`) e
  sempre auditado (`trading_audit`). Modo `real` exige `confirmed=True`.
- API em `openhud/web/trading_api.py` (`/api/trading/*`); ferramentas de chat em
  `openhud/tools/trading.py`; UI na view `trading` (`/trading`) do SPA.
- **Regra de ouro**: erros reais devem aparecer. Sem MT5, as respostas são
  "Não consigo acessar os dados do MT5 neste momento." — não fabrique dados.

## Fase 4 — voz, personalidade, Codex, plugins, multimodalidade
- `openhud/core/modes.py`: 13 modos (`auto`…`agent`) + `resolve_mode`/`resolve_auto`
  por palavras-chave. Modos **não** concedem permissões — MT5/PC seguem com suas travas.
- `openhud/core/personality.py`: traços 0–100 + estilo; `guidance()` injeta só tom.
  A IA é instruída a **nunca** alegar sentimentos reais. `adapt()` ajusta por preferências.
- `openhud/core/context.py`: monta o contexto do turno (modo, persona, memórias,
  experiências, dicas). `openhud/core/learning.py`: experiências (sem treinar modelo).
- `openhud/core/sanitizer.py`: `detect`/`sanitize`/`wrap_untrusted`. O laço
  (`_UNTRUSTED_TOOLS` em `agent/loop.py`) sanitiza e embrulha saída de ferramentas
  externas (web, arquivos, shell) como DADOS antes de ir ao modelo.
- `openhud/core/jobs.py`: `JobStore`+`JobQueue` (worker único, FIFO, progresso/logs
  reais). `runtime.job_queue` e `runtime.start_workers()` (chamado no lifespan).
- `openhud/voice/`: TTS (edge/openai/browser) + STT (browser/whisper/openai).
  Áudio **não** é salvo por padrão; histórico só com opt-in (`voice_save_history`).
- `openhud/media/`: imagens (pollinations/openai), áudio, vídeo (ffmpeg). Sem
  dependência opcional, retorna erro honesto — **nunca** sucesso falso.
- `openhud/codex/`: `analyze`, `plan`, `run_tests`, changesets com diff
  (`diffs.py`) e sandbox (`sandbox.py`). `RLIMIT_NPROC` só é aplicado se for
  seguro (em container compartilhado ele quebraria todo fork).
- `openhud/plugins/`: nativos + manifestos externos em `data/plugins/<nome>/`.
  Instalar só registra o manifesto (não executa); risco ALTO/CRÍTICO exige `ack`.
- `openhud/core/diagnostics.py`: `run_diagnostics(runtime)` checa cada subsistema
  e reporta `ok`/`degraded`/`error` real. `openhud/web/ai_api.py`: rotas `/api/ai/*`.
- Front-end: views `codex`, `images`, `video`, `plugins`, `intelligence`, `privacy`,
  `admin`; barra de voz no chat; seletor de modo; personalidade/voz em Configurações.
  Ao mudar `app.js`/`styles.css`, **bump o `?v=`** em `index.html`.

## Fase 5 — assistente de computador, acessibilidade, app Windows
- `openhud/core/assist.py`: `PROFILES`, `AUTONOMY_LEVELS` (observe/guide/assisted/
  automatic), `TASK_STATES`, `classify_action` (palavras-chave + `TOOL_SENSITIVITY`),
  `gate(tool, args, settings, tool_requires_confirmation, tool_is_control,
  legacy_autonomy)`, `profile_guidance`, `detect_control_phrase`, e o
  `TaskController` (`controller`/`task_controller`) com begin/set_state/
  request_cancel/request_pause/wait_if_paused/finish/clear.
  - **Gate**: ferramentas de **controle** usam varredura de texto; ferramentas
    comuns NÃO (evita falso positivo em código/conteúdo). `run_python`/`run_shell`
    **não** são sempre-sensíveis — só `trading_execute_order` e `delete_file`.
    Assim a autonomia automática não trava, mas pagamentos/senha/exclusão pedem
    confirmação sempre.
  - `gate` SEMPRE retorna `reason` em decisões `confirm`/`block` (o loop usa).
- `openhud/core/scam_guard.py`: `analyze_text(text, url)` → sinais + risco.
- `openhud/agent/screen.py`: funções puras `detect_elements`, `find_matches`,
  `summarize_screen`, `elements_from_dicts`, `capabilities`. Captura/OCR só com
  libs nativas; degrada com erro honesto.
- `openhud/tools/assistant.py`: `build_assistant_tools()`, `CONTROL_TOOLS`
  (`screen_*`, `mouse_*`, `keyboard_*`, `window_list`, `pc_open_url`).
- `openhud/web/assistant_api.py`: `/api/assistant/*` (profiles, autonomy,
  accessibility, tasks, scam-check, screen/*, control-center, diagnose, privacy,
  update/*, maintenance/*).
- `openhud/desktop/`: app Windows (bandeja/`--agent`), `build.py` (PyInstaller).
  `installer/openhud.iss` (Inno Setup; atalhos/inicialização opcionais).
- `openhud/core/updates.py`: verificação de manifesto HTTPS (check-only, verifica
  sha256, recusa HTTP fora de localhost). `openhud/core/maintenance.py`: backup/
  restore SQLite com `integrity_check` + `pg_dump` para Postgres + `SCHEMA_VERSION`.
- Front-end: views `assistant` e `control-center`; barra de estado de tarefa no
  chat (PARAR/PAUSAR); acessibilidade em Configurações; backup/update em Privacidade.
- `docker-compose.yml` (SQLite padrão, perfil `postgres`). `Dockerfile` com
  `HEALTHCHECK` em `/health`.

## Fase 7 — contas de usuário e produto real
- `openhud/core/accounts.py`: `AccountManager` (users, sessions, tokens,
  devices). Helpers `_dict`/`_one`/`_all` normalizam `sqlite3.Row`→dict **sem
  recursão** (a versão recursiva antiga estourava). `hash_password` /
  `verify_password_hash` (PBKDF2-SHA256, salt aleatório).
- `openhud/web/accounts_api.py`: `router`, `init_accounts`,
  `ACCOUNT_PUBLIC_PATHS`, `require_csrf(request, body_csrf)`, `_is_https`,
  `_client_ip`, `current_user`, `get_accounts`. Endpoints `/api/account/*`.
  **Ordem do CSRF importa**: valide antes de ler o corpo sensível.
- `openhud/web/shell.py`: shell comum das páginas (nav ciente de sessão + SEO).
- `openhud/web/site.py`: site público reescrito (SEO, ícones, doação,
  navegação por sessão).
- `openhud/core/mail.py`: e-mail por `OPENHUD_SMTP_*`; sem SMTP devolve
  `email_sent=false` e loga o link. `OPENHUD_EXPOSE_RESET_LINK=1` só em testes.
- `openhud/core/release.py`: helper de doação (`OPENHUD_DONATION_URL`).
- **Dispositivos do usuário**: `AgentHub.register_device(name, platform, info)`
  cria dispositivo+token; `AccountManager.link_device` guarda o vínculo.
  `/api/agent/register-device` (em `web/agent_api.py`) é o que o app Windows
  chama após o login.
- `openhud/desktop/account.py`: login do app Windows via `urllib` (stdlib).
  Cuidados: `_set_cookie` lê **todos** os `Set-Cookie` (`get_all`), e o CSRF é
  **rotacionado no login** — use o cookie novo antes de registrar o dispositivo.
- `openhud/desktop/wizard.py`: `run_wizard(..., login=...)`; sem `login`
  (testes/offline) mantém o fluxo antigo de pareamento.
- CSS do chip de usuário no fim de `static/styles.css`; páginas em
  `static/account/`; landing em `static/site/index.html`.

## Armadilhas conhecidas
- `TestClient` do Starlette serializa requisições por um único portal: um
  POST feito durante um stream SSE causa deadlock no teste (não em produção).
  Resolva confirmações a partir de uma thread auxiliar nos testes.
- O terminal desta sandbox rejeita comandos multi-linha colados; escreva
  scripts em arquivo e execute com `bash arquivo.sh`.
- Cache de SPA: `index.html` é servido com `Cache-Control: no-cache` e os
  assets usam `?v=N`. Ao mudar `app.js`/`styles.css`, **bump o `?v=`** em
  `index.html` — senão o navegador continua rodando o JS antigo e parece que
  a correção "não funcionou".

## Configuração de modelo
Provedores: openai, anthropic, groq, deepseek, openrouter, cerebras, mistral,
google, github, pollinations (keyless), ollama (local).
Base URLs em `DEFAULT_BASE_URLS` (`openhud/core/llm.py`). `supports_tools`
controla o envio de ferramentas ao provedor.

### Cadeia de fallback (`openhud/core/providers.py`)
`build_provider_manager()` monta a ordem: provedor escolhido → outro provedor
com chave → Pollinations (keyless) → Ollama local. `ProviderManager.chat()`
tenta cada um; falhas 5xx/rede têm `TRANSIENT_RETRIES` com backoff, e falhas
têm cooldown (`FAILURE_COOLDOWN_SECONDS`) para não martelar provedor morto.
O provedor escolhido SEMPRE usa a `base_url`/`model` das settings do usuário
(importante: os testes locais dependem disso). `AllProvidersFailed` lista cada
tentativa; a UI mostra `provider` respondido e nunca mascara o erro real.

## Autenticação
Dois modos coexistem:
- **Contas** (Fase 7): `openhud/core/accounts.py` (`AccountManager`) +
  `openhud/web/accounts_api.py`. Tabelas `users`, `user_sessions`,
  `password_resets`, `email_verifications`, `user_devices`. Senhas
  PBKDF2-SHA256; sessões/resets guardados só como hash; CSRF (cookie
  `openhud_csrf` + `X-CSRF-Token`);
  rate limiters próprios em `web/ratelimit.py`. Páginas e rotas públicas
  listadas em `ACCOUNT_PUBLIC_PATHS` (aplicado no middleware de `web/app.py`).
- **Operador**: `openhud/web/auth.py`, senha via `OPENHUD_PASSWORD` (senão
  gera aleatória e loga); cookie `hud_session` assinado (HMAC) com
  `OPENHUD_SESSION_SECRET`; `OPENHUD_AUTH=off` desliga. Middleware em
  `web/app.py` protege `/api/*` (401) e páginas (302 `/login`).

`current_user(request)` retorna a conta logada ou `None` (modo operador).

## Banco de dados
`create_database(path, database_url)` em `core/db.py` escolhe SQLite (padrão)
ou `PostgresDatabase` (`core/db_pg.py`) quando `DATABASE_URL` está definido.
Ambos expõem a MESMA interface; `_translate` troca `?` por `%s`. Requer
`psycopg[binary]` (já em requirements.txt).

## Deploy
Plataforma escolhida: **Render (plano free) + Postgres no Neon** (custo zero,
HTTPS/WSS/SSE automáticos, banco persistente). `Dockerfile` (estado em `/data`)
+ `render.yaml` (Blueprint). A porta vem de `OPENHUD_PORT` ou `PORT`
(`config.py`). Guia completo em `DEPLOY.md`; alternativas (Fly/Railway/VPS) no
Apêndice A. No free tier o disco é **efêmero**: use `OPENHUD_DATABASE_URL`
(Neon) para persistir o banco **e** `OPENHUD_ENCRYPTION_KEY` (Fernet) para que
as chaves de API cifradas continuem legíveis após um redeploy — sem ela o
`SecretCipher` (`core/crypto.py`) geraria uma nova chave e perderia os segredos.
`OPENHUD_PASSWORD`/`OPENHUD_SESSION_SECRET`/`OPENHUD_ENCRYPTION_KEY` são gerados
pelo `render.yaml` (`generateValue: true`).

## Site público e distribuição (Fase 6)
- `openhud/web/site.py`: páginas públicas **sem login** (`/`, `/features`,
  `/how-it-works`, `/pricing`, `/help`, `/privacy`, `/download`, `/changelog`,
  `/version`) montadas a partir de um shell comum. As rotas públicas estão em
  `PUBLIC_SITE_PATHS`, importado por `web/app.py` para `PUBLIC_PATHS`.
- O app (SPA) mudou de `/` para `/app`; `PUBLIC_PATHS` libera o site; `/app` e
  as rotas internas continuam exigindo sessão (302 `/login`). `login.html`
  redireciona para `/app`.
- `openhud/core/release.py`: metadados do instalador resolvidos em 3 níveis
  (`OPENHUD_DOWNLOAD_URL` → artefato local em `dist/` ou `installer/Output/` →
  nada). SHA-256 e tamanho são calculados do arquivo real; `published` só é
  true com URL real. `_artifact_dirs()` lê `OPENHUD_RELEASE_DIR` de forma
  preguiçosa (testável). `changelog()` lê `CHANGELOG.md`; `changelog_summary()`
  usa a entrada da versão atual (ignora a seção `Unreleased`) para as notas de
  `/version` e da página de download.
- `openhud/agent/selfcheck.py`: diagnóstico real (`PASS`/`WARNING`/`FAIL`/
  `NOT INSTALLED`/`NOT PERMITTED`). CLI: `python -m openhud.agent.selfcheck`,
  `openhud-agent.exe --diagnose`. Usa `TelemetryCollector().collect()` (a
  forma correta: `cpu`/`ram`/`gpu`/`disk`).
- `openhud/desktop/`: `config.py` (config persistente + grupos de permissão),
  `wizard.py` (assistente de 1ª execução), `runtime.py` (AgentClient em thread,
  estados reais), `tray.py` (bandeja com status real). `desktop/app.py` ganhou
  `--onboard`, `--diagnose`, `--permissions`, `--agent` com wizard.
- `installer/openhud.iss`: gera `OpenHUD-AI-Setup.exe`; atalhos e autostart
  opcionais/desmarcados; sem serviços; desinstalação limpa com opção de manter
  dados. `installer/openhud.ico` gerado por `tools/make_brand_assets.py`.
- `tools/make_release.py`: escreve `release.json` com tamanho + SHA-256 reais.
- Permissão `voice` adicionada em `core/agent_hub.py` (`PERMISSION_KEYS` e
  `DEFAULT_PERMISSIONS`, default `False`) e em `PERM_LABELS` (`app.js`).
- Docs: `WINDOWS_TEST.md` (procedimento real), `DEPLOY.md`, `CHANGELOG.md`,
  `LICENSE` (MIT). Build do `.exe`/instalador **exige Windows** — não foi
  gerado neste ambiente Linux; nada finge que foi.

## Ollama local (keyless, permanente)
Instalar sem pipe-to-shell: baixar
`https://github.com/ollama/ollama/releases/latest/download/ollama-linux-amd64.tar.zst`
(1.4G), extrair com `zstandard` (pip) para `/usr/local`, `ollama serve`,
`ollama pull qwen2.5:3b`. Roda em CPU e responde na base URL
`http://127.0.0.1:11434/v1`. É o fallback mais confiável sem chave.

## Estado de teste observado
- Pollinations (`https://text.pollinations.ai/openai`) é keyless mas
  INTERMITENTE: alterna entre 200, HTTP 500 (ENOSPC) e HTTP 402. Por isso o
  retry + fallback para Ollama são essenciais. Não confie nele como único
  provedor.
- Suíte: **230 testes** em `tests/`. `test_api.py` faz login real no import
  (`OPENHUD_PASSWORD=test-password`); `test_pc_agent.py` cobre hub, telemetria,
  diagnóstico e a API do agente; `test_trading.py` cobre indicadores, risco,
  estratégias, backtest, alertas, paper, permissões, idempotência e as
  situações de falha do MT5 (sem PC, sem pacote, ordem bloqueada, STOP);
  `test_phase4.py` cobre modos, personalidade, sanitizer, contexto, learning,
  fila de jobs, codex (análise/diff/sandbox/testes), plugins, voz,
  diagnóstico, as rotas `/api/ai/*` e um turno SSE real com roteamento de modo;
  `test_phase5.py` cobre perfis/autonomia/gate, classificação de sensível,
  controller de tarefas, scam guard, funções puras de tela, a API
  `/api/assistant/*`, updates (recusa HTTP), backup/restore e o launcher desktop;
  `test_phase6.py` cobre o site público (páginas sem login, app protegido em
  `/app`), `/version`/`/api/site/release`/`/api/site/changelog`, o cálculo real
  de SHA-256 do instalador, o `selfcheck` (status + gating de permissão), a
  config desktop, o assistente de 1ª execução, o runtime do agente e a
  coerência do script do instalador.
  `test_accounts.py` cobre o `AccountManager` (hash, sessões, resets,
  verificação, dispositivos, exclusão), a API de contas ponta a ponta
  (CSRF, login, reset, exclusão, sessões, dispositivos) e o login do app
  desktop contra um **uvicorn real** (CSRF rotacionado incluído).
  `tests/conftest.py` limpa os rate limiters entre testes (senão o login
  compartilhado estoura o limite e vira 401/429).
- Deploy validado: `docker build` + container respondendo `/api/health`.
  Conexão do agente por **wss** (URL pública HTTPS) testada com pareamento.
- **Cabeçalhos de segurança** (v5.1.1): middleware aplica CSP (mesma origem +
  fontes do Google do site), `X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, `Permissions-Policy` e `Strict-Transport-Security` (só
  quando `x-forwarded-proto` é https). Verificação de deploy público:
  `python tools/verify_public_deploy.py --base-url https://... --full` checa
  páginas, endpoints, cabeçalhos e o fluxo real de conta (registrar/login/logout/
  sessão/excluir) sem mocks.
- **`git` remoto e publicação (CONCLUÍDO)**: o repositório público
  <https://github.com/kevincavadas90-droid/openhud-ai> existe e o `master` foi
  enviado. A tag `v5.1.1` foi enviada e a release
  <https://github.com/kevincavadas90-droid/openhud-ai/releases/tag/v5.1.1> tem o
  ativo `OpenHUD-AI-Complete-5.1.1.zip` (440557 bytes, sha256
  `2f2f07cfc89b72c5cac6da7f69724b6b84678c9fff49f9d490e6375a302dbdc5`). O push
  foi feito com um PAT de **usuário** (escopo `repo`) fornecido pelo operador,
  via `gh auth setup-git` (o token **não** entra no `.git/config`, em URLs nem em
  arquivos do projeto). Esse PAT **não** tem o escopo `workflow`, então arquivos
  em `.github/workflows/` são recusados pelo GitHub — o CI do Actions precisa de
  um token com escopo `workflow`. `git remote -v` mostra a URL sem credenciais.
- **Site publicado neste ambiente**: o proxy público
  `https://work-1-<...>.prod-runtime.all-hands.dev` (porta 12000) serve o site
  sem login; `/download` mostra o ZIP do código-fonte com SHA-256 real e
  `/download/source` entrega o arquivo. O instalador Windows aparece como "não
  publicado" (honesto — nenhum `.exe` foi compilado no Linux). Para subir o
  código novo, reinicie com `nohup bash run_public_demo.sh &` (o script lê a
  senha de `data/.demo_login`, nunca impressa). O cadastro/login de contas
  (`/register`, `/login`, `/account`) também está no ar.
- **Empacotamento**: `python tools/prepare_release.py` gera o ZIP do código-fonte
  **e** o `dist/release-manifest.json` com tamanhos/SHA-256 reais; não inventa um
  instalador ausente. `python tools/publish_release.py --repo owner/name`
  empacota, cria o repo (se o token permitir), faz push, cria a tag/release e
  envia os ativos. `tools/make_source_zip.py` continua disponível isolado. O ZIP
  é artefato de build e **não** é versionado.
  Estado do publish (verificado): a tag `v5.1.1` existe no commit final e o ZIP
  foi reconstruído a partir dele. Publicação no GitHub **feita** (ver acima) com
  um PAT de usuário escopo `repo`; o PAT **não** tem escopo `workflow`. Tudo
  isso é honesto: nada foi fabricado.
- **Deploy público real (Render + Neon)**: o serviço `openhud`
  (`srv-db1gprgu01pc73ecgudg`, plano free, região Oregon, Docker) está **live**
  em `https://openhud.onrender.com`. Deploy feito pela API do Render a partir do
  `master` do GitHub. Segredos de produção (`OPENHUD_PASSWORD`,
  `OPENHUD_SESSION_SECRET`, `OPENHUD_ENCRYPTION_KEY`) foram gerados novos e
  existem **somente** como env vars do Render; `OPENHUD_DATABASE_URL` aponta para
  o Postgres Neon (schema criado sozinho: 24 tabelas). Nunca gravados no Git,
  ZIP, frontend ou logs. Verificado ao vivo: 33/33 no verificador, todas as
  páginas/endpoints 200, cookies `HttpOnly; Secure; SameSite=lax`, CSRF,
  HSTS, CORS não-wildcard, ciclo de conta completo e persistência através de
  restart (login → restart → login). O plano free hiberna por inatividade; a
  primeira requisição pode levar ~30-60s (cold start).
- **Auditoria visual do site público**: corrigido no CSS/HTML gerado — (1) menu
  mobile não transborda mais (antes `.nav-actions` ficava visível no header
  colapsado e estourava a viewport em 19px; agora `.nav-links` e `.nav-actions`
  são ocultados e caem num painel fluido com `flex-wrap`, sem `position:absolute`);
  (2) cada página de conteúdo tem exatamente um `<h1>` (títulos passaram de
  `<h2>` para `<h1>` com `.section-head h1`), corrigindo hierarquia/SEO;
  (3) `/sitemap.xml` não lista mais `/login` e `/register` (que são `noindex` e
  bloqueados no `robots.txt`). Verificado com Chromium headless (Playwright) em
  desktop 1280px e mobile 390px: sem overflow, sem erros de console, 17 links
  internos OK, fluxo de conta (registro/validação/login/logout/recuperação/
  exclusão) aprovado com mensagens claras.
- **Kit de hospedagem permanente**: `Dockerfile` (python:3.13-slim, não-root,
  healthcheck), `.dockerignore`, `fly.toml` (volume `/data`), `render.yaml`
  (free + Postgres externo + `OPENHUD_ENCRYPTION_KEY`), `railway.json`,
  `docker-compose.yml` e `.env.example`.
  Endpoints públicos de plataforma: `/health` (liveness), `/ready` (checa o
  banco), `/version`. CORS é opt-in via `OPENHUD_CORS_ORIGINS` (nunca wildcard;
  lido em `openhud/config.py` como `settings.cors_origins`). Testes em
  `tests/test_deploy.py` cobrem CORS (subprocesso), o manifesto e os arquivos do
  kit. Validado com Docker real: `docker build` + container serve `/health`,
  `/ready`, `/version`, `/`, `/download`, `/login`; caminho Postgres testado com
  `postgres:16-alpine` (schema criado sozinho; conta sobrevive ao
  `docker restart`). `railway.json` precisa ser JSON válido (sem comentários).
- **GPU multi-vendor**: `openhud/agent/gpu.py` (NVIDIA/NVML, AMD/Intel via
  sysfs/CIM/lspci); métricas ao vivo só quando legíveis, nunca inventadas.
- **Teste no Windows**: `installer/windows-smoke-test.ps1` automatiza o
  `WINDOWS_TEST.md` e grava `windows-test-report.json`; PowerShell não existe
  neste ambiente Linux, então o script não pôde ser executado aqui.
