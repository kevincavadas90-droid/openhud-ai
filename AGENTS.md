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
`openhud/web/auth.py`: senha via `OPENHUD_PASSWORD` (senão gera aleatória e
loga); cookie `hud_session` assinado (HMAC) com `OPENHUD_SESSION_SECRET`;
`OPENHUD_AUTH=off` desliga. Middleware em `web/app.py` protege `/api/*` (401)
e páginas (302 `/login`). Limite de tentativas de login por IP.

## Banco de dados
`create_database(path, database_url)` em `core/db.py` escolhe SQLite (padrão)
ou `PostgresDatabase` (`core/db_pg.py`) quando `DATABASE_URL` está definido.
Ambos expõem a MESMA interface; `_translate` troca `?` por `%s`. Requer
`psycopg[binary]` (já em requirements.txt).

## Deploy
`Dockerfile` (estado em `/data`) + `render.yaml`. A porta vem de
`OPENHUD_PORT` ou `PORT` (`config.py`).

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
- Suíte: **39 testes** em `tests/`. `test_api.py` faz login real no import
  (`OPENHUD_PASSWORD=test-password`); `test_pc_agent.py` cobre hub, telemetria,
  diagnóstico e a API do agente.
- Deploy validado: `docker build` + container respondendo `/api/health`.
  Conexão do agente por **wss** (URL pública HTTPS) testada com pareamento.
- `git` remoto: nenhum. O `GITHUB_TOKEN` deste ambiente é de integração
  (`Resource not accessible by integration`) — **não** cria repositório nem
  faz push. Para publicar, use um token de usuário com escopo `repo`.
