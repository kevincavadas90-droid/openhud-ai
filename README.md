# OpenHUD — IA multifuncional autônoma

OpenHUD é uma inteligência artificial pessoal multifuncional, extensível e
configurável. Ela combina um agente de execução com ferramentas reais
(terminal, Python, arquivos, internet, APIs), memória de longo prazo,
múltiplos provedores de modelo e uma interface web moderna.

O objetivo não é apenas conversar, mas **executar tarefas concretas**.

---

## 1. Diagnóstico do ambiente (estado atual)

| Item | Valor |
| --- | --- |
| Linguagem | Python 3.13 |
| Framework web | FastAPI + Uvicorn |
| Banco de dados | SQLite (WAL) ou PostgreSQL (`DATABASE_URL`) |
| Front-end | HTML/CSS/JS puro (sem build) |
| Provedores de modelo | Cadeia de fallback com 11 provedores + Ollama local |
| Sem chave | Pollinations (keyless) e Ollama local |
| Execução | Terminal e Python em sandbox de workspace |
| Autenticação | Senha (`OPENHUD_PASSWORD`) + cookie de sessão assinado |
| Testes | pytest — **150 testes, todos passando** |
| Site público | Páginas de marketing servidas pelo mesmo app (sem login) |
| Distribuição | Instalador Windows (Inno Setup) + GitHub Releases / URL externa |

Nenhum código pré-existente foi encontrado no repositório: o OpenHUD foi
construído do zero nesta estrutura.

---

## 2. Instalação

Requer Python 3.11+.

```bash
git clone <repo> && cd project
./start.sh          # idempotente: venv + Ollama local + servidor web
```

O `start.sh` sobe tudo o que o app precisa — inclusive um **Ollama local**
(keyless, ilimitado) — e pode ser rodado quantas vezes quiser: o que já estiver
no ar é reaproveitado. Use `./run.sh` se quiser apenas o servidor Python
(sem Ollama).

Ou manualmente:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m openhud
```

A interface fica em `http://localhost:8000`.

Variáveis de ambiente úteis:

| Variável | Padrão | Função |
| --- | --- | --- |
| `OPENHUD_PORT` | `8000` (ou `PORT`) | Porta do servidor |
| `OPENHUD_HOST` | `0.0.0.0` | Host do servidor |
| `OPENHUD_DATA_DIR` | `./data` | Banco, chaves, segredos |
| `OPENHUD_WORKSPACE` | `./workspace` | Sandbox de arquivos/execução |
| `OPENHUD_MAX_STEPS` | `25` | Etapas máximas do agente |
| `OPENHUD_PASSWORD` | — | Senha de acesso ao app (obrigatória em produção) |
| `OPENHUD_SESSION_SECRET` | gerado | Segredo fixo para assinar o cookie de sessão |
| `OPENHUD_AUTH` | `on` | `off` desliga o login (só para uso local/privado) |
| `DATABASE_URL` | — | URL PostgreSQL; vazio usa SQLite |
| `OPENHUD_DOWNLOAD_URL` | — | URL real do instalador (GitHub Releases/CDN) exibida em `/download` |
| `OPENHUD_SERVE_INSTALLER` | `off` | `1` serve o instalador local em `/download/file` (VPS) |
| `OPENHUD_RELEASE_DIR` | — | Pasta alternativa onde procurar `OpenHUD-AI-Setup.exe` |

---

## 3. Configurar um modelo

Abra **Configurações** na interface e escolha o provedor:

- **OpenAI / Groq / DeepSeek / OpenRouter / Cerebras / Mistral / Google** —
  cole a chave em *Chaves de API* (`openai`, `groq`, ...).
- **Anthropic** — chave `anthropic`.
- **Ollama (local)** — rode `ollama serve` e escolha o provedor `ollama`;
  não precisa de chave. Ex.: modelo `qwen2.5:3b`.
- **Pollinations (sem chave)** — nenhuma chave é necessária. É o provedor
  padrão de uma instalação nova, para que o app já funcione de imediato.

A Base URL é ajustada automaticamente por provedor e pode ser sobrescrita
para apontar a qualquer endpoint OpenAI-compatível.

### Cadeia de fallback

Cada turno usa uma **cadeia de provedores** em ordem de prioridade: o
provedor escolhido primeiro, depois um provedor sem chave (Pollinations) e,
por fim, o Ollama local. Se um provedor falhar por instabilidade
(HTTP 5xx/erro de rede), ele é tentado novamente algumas vezes com *backoff*
antes de passar para o próximo. Limites de uso (429/402) passam direto para
o próximo provedor. A interface mostra **qual provedor respondeu** em cada
mensagem, e o erro final lista cada tentativa com o motivo real — nada é
mascarado.

As chaves são **criptografadas com Fernet** (`data/secret.key`, permissão
0600) e nunca são exibidas por completo — apenas uma prévia mascarada.

---

## 4. Como usar

1. Crie uma conversa (ou um projeto para agrupar conversas).
2. Descreva a tarefa em linguagem natural.
3. O agente decide quais ferramentas usar, executa e mostra cada passo no
   chat e no **Registro de atividades**.

### Níveis de autonomia

- **Supervisionado** (padrão): ferramentas que alteram estado (shell,
  escrita de arquivo, requisições, exclusão) pedem confirmação via modal.
- **Autônomo**: as ações são executadas direto, mas comandos claramente
  destrutivos continuam bloqueados por segurança.

Alterne em Configurações ou pelo botão *alternar autonomia* no topo do chat.

---

## 5. Ferramentas

| Ferramenta | Função | Confirmação |
| --- | --- | --- |
| `read_file` | Ler arquivo do workspace | não |
| `write_file` | Criar/sobrescrever arquivo | sim |
| `list_files` | Listar diretórios | não |
| `delete_file` | Remover arquivo | sim |
| `run_shell` | Executar comando de shell | sim |
| `run_python` | Executar código Python | sim |
| `web_search` | Pesquisa na internet | não |
| `fetch_url` | Baixar página como texto | não |
| `http_request` | Chamar APIs HTTP | sim |
| `analyze_data` | Analisar CSV/JSON (linhas, colunas, estatísticas) | não |
| `remember` / `recall` | Memória de longo prazo | não |
| `pc_metrics` / `pc_diagnose` / `pc_game_profile` | Telemetria, diagnóstico e perfil de jogo do PC | não |
| `mt5_status` / `mt5_account` | Estado do MetaTrader 5 e da conta | não |
| `mt5_analyse` | Análise técnica + price action + multi-timeframe | não |
| `trading_strategy` | Interpretar/salvar estratégia em linguagem natural | não |
| `trading_backtest` | Backtest em histórico real | não |
| `trading_daily_brief` | Resumo diário de mercado | não |
| `trading_paper` | Simulação (paper trading) | não |
| `trading_prepare_order` | Calcular risco/lote/margem (sem enviar) | não |
| `trading_execute_order` | Enviar ordem ao MT5 (DEMO/REAL) | sim |
| `generate_image` | Gerar imagem (Pollinations/OpenAI) | não |
| `narrate_audio` | Narração TTS real (Edge) | não |
| `render_video` | Enfileirar render de vídeo (ffmpeg) | não |
| `job_status` | Progresso real de um job | não |
| `speak` | Texto → fala (cadeia TTS) | não |
| `codex_analyze` | Analisar projeto (linguagens, testes, entradas) | não |
| `codex_plan` | Plano de implementação | não |
| `codex_propose` | Propor alterações (diff, sem aplicar) | não |
| `codex_apply` / `codex_revert` | Aplicar/reverter changeset | sim |
| `codex_test` | Rodar pytest e reportar passou/falhou reais | não |
| `self_diagnose` | Auto-diagnóstico do sistema | não |
| `set_mode` / `get_personality` | Modo ativo e traços de personalidade | não |
| `remember_preference` | Guardar preferência do usuário | não |

Cada ferramenta pode ser habilitada/desabilitada na aba **Ferramentas**.
Todo caminho de arquivo é validado para permanecer dentro do workspace.

---

## 5b. Fase 4 — Voz, personalidade, Codex, plugins e multimodalidade

### Modos da IA
`auto`, `reasoning`, `codex`, `research`, `creative`, `image`, `video`,
`voice`, `pc`, `gaming`, `trading`, `data`, `agent`. O modo `auto` escolhe um
modo concreto por palavras-chave (regras transparentes em
`openhud/core/modes.py`). O modo ativo aparece no topo do chat e pode ser
trocado no seletor. Modos **não** concedem permissões extras: MT5 e PC Agent
continuam sujeitos às suas travas.

### Personalidade
Traços numéricos (empatia, humor, energia, curiosidade, paciência,
formalidade, objetividade, detalhamento, criatividade) + estilo nomeado,
editáveis em **Configurações → Personalidade**. A IA recebe apenas *tom e
estilo*; ela é instruída a nunca alegar sentimentos reais. O modo adaptativo
ajusta traços a partir de preferências salvas (transparente e inspecionável).

### Voz (STT + TTS)
- **TTS real** via Edge Neural (`edge-tts`), com fallback para o TTS do
  navegador e OpenAI quando há chave.
- **STT** pelo microfone do navegador (Web Speech API); transcrição no
  servidor é best-effort e reporta erro real quando indisponível.
- 12 idiomas, estilos de voz, velocidade, tom, **conversa contínua** e
  **wake word** (o microfone ativo é indicado claramente).
- Privacidade: áudio **não** é salvo por padrão; histórico de voz só é
  gravado com opt-in e pode ser apagado no centro de privacidade.

### Codex (engenharia de software)
Analisa o projeto, planeja, propõe changesets com **diff antes/depois**,
aplica/reverte com snapshots e roda a suíte de testes de verdade. Execução em
sandbox com limites de CPU, memória, tamanho de arquivo e timeout. O
isolamento de rede **não** é aplicável neste ambiente (informado honestamente).

### Plugins
Catálogo de plugins nativos (browser, files, pc, mt5, codex, data, memory,
execution, images, video, audio, documents, automation) com permissões
classificadas por risco. Plugins externos são descritos por um
`manifest.json` em `data/plugins/<nome>/`; instalar só registra o manifesto
(nada é executado) e risco ALTO/CRÍTICO exige confirmação explícita. O que não
tem integração real é listado como indisponível, com o motivo.

### Multimodalidade e mídia
Geração de imagem (Pollinations keyless por padrão, OpenAI opcional),
narração em áudio, render de vídeo por ffmpeg (via fila de jobs com progresso
real). Dependências opcionais ausentes (ffmpeg/PIL/numpy) degradam com erro
honesto, nunca com sucesso falso.

### Inteligência e aprendizado contínuo
Aprendizado baseado em **experiências** (ação → contexto → resultado →
feedback), sem treinar o modelo. A aba **Inteligência** mostra taxa de
sucesso, ferramentas mais usadas, problemas recorrentes e soluções que
funcionaram. A memória tem camadas: curto prazo (conversa), longo prazo
(curada), episódica (experiências) e semântica (fatos/preferências).

### Privacidade e Admin
Centro de privacidade para ver/apagar histórico de voz, memória e
experiências e exportar os dados (sem segredos). O painel Admin traz
auto-diagnóstico de todos os subsistemas, tentativas por provedor, jobs e
eventos de segurança — cada componente reporta seu estado real.

---

## 6. Arquitetura

```
openhud/
├── config.py            # caminhos e variáveis de ambiente
├── core/
│   ├── crypto.py        # criptografia Fernet dos segredos
│   ├── db.py            # SQLite + factory de banco
│   ├── db_pg.py         # backend PostgreSQL (mesma interface)
│   ├── secrets_store.py # armazenamento seguro de chaves
│   ├── llm.py           # adaptadores OpenAI-compatível e Anthropic
│   ├── providers.py     # cadeia de fallback entre provedores
│   ├── modes.py         # 13 modos de operação + roteamento automático
│   ├── personality.py   # traços/estilos e adaptação a preferências
│   ├── router.py        # roteamento por família de modelo
│   ├── context.py       # montagem de contexto por turno
│   ├── sanitizer.py     # defesa contra injeção de prompt
│   ├── learning.py      # experiências (aprendizado contínuo)
│   ├── jobs.py          # fila de jobs persistente com progresso real
│   ├── diagnostics.py   # auto-diagnóstico de todos os subsistemas
│   └── runtime.py       # singletons e resolução de configuração
├── voice/               # TTS/STT (idiomas, estilos, serviço)
├── media/               # imagens, áudio e vídeo
├── codex/               # análise, changesets (diff) e sandbox
├── plugins/             # manifestos, plugins nativos e gerenciador
├── trading/             # MÓDULO MT5 (lógica pura, testável)
│   ├── core.py          # permissões, modos, risco, estratégias, backtest, paper
│   ├── indicators.py    # SMA/EMA/RSI/MACD/ATR/ADX/estocástico/Bollinger + price action
│   ├── analysis.py      # análise técnica, price action e multi-timeframe
│   ├── alerts.py        # motor de alertas
│   ├── store.py         # persistência (estratégias, alertas, diário, auditoria)
│   └── service.py       # orquestra site ↔ hub ↔ MT5 (permissão, risco, idempotência)
├── tools/               # filesystem, execução, web, memória, PC, trading, mídia, codex, sistema
├── agent/
│   ├── loop.py          # laço do agente (streaming de eventos)
│   ├── prompts.py       # prompt de sistema (modo + personalidade + memória)
│   ├── confirm.py       # broker de confirmação interativa
│   ├── mt5_bridge.py    # integração real com MetaTrader5 (roda no PC)
│   └── scheduler.py     # execução de tarefas recorrentes
├── web/
│   ├── app.py           # API REST + SSE
│   ├── auth.py          # senha, cookie de sessão assinado
│   ├── ai_api.py        # API REST da Fase 4 (voz, codex, plugins, mídia, admin)
│   ├── trading_api.py   # API REST do módulo MT5
│   ├── ratelimit.py     # limite de tentativas
│   └── static/          # interface web
└── __main__.py          # ponto de entrada
```

O laço do agente é um gerador de eventos (`token`, `tool_start`,
`tool_result`, `confirmation`, `provider`, `route`, `error`, `done`)
transmitidos ao navegador via Server-Sent Events. Cada turno roda em uma
thread de trabalho. Saída de ferramentas que lê conteúdo externo (web,
arquivos, shell) é sanitizada e embrulhada como dado antes de ir ao modelo.

---

## 7. API REST

| Método | Rota | Descrição |
| --- | --- | --- |
| POST | `/api/login` / `/api/logout` | Iniciar/encerrar sessão |
| GET | `/api/me` | Estado da sessão atual |
| GET | `/api/health` | Estado e se o provedor está configurado |
| GET | `/api/providers` | Cadeia de fallback e provedores prontos |
| GET | `/api/models` | Provedores, modelos sugeridos e Base URLs |
| GET/PUT | `/api/settings` | Ler/atualizar configurações |
| GET/POST/DELETE | `/api/secrets` | Gerenciar chaves (criptografadas) |
| GET/POST/DELETE | `/api/projects` | Projetos |
| GET/POST/DELETE | `/api/conversations` | Conversas |
| POST | `/api/conversations/{id}/messages` | Enviar mensagem (resposta SSE) |
| GET | `/api/tools` | Ferramentas e estado |
| GET/POST/PUT/DELETE | `/api/memories` | Memória de longo prazo |
| GET | `/api/activities` | Registro de atividades |
| GET/POST/PUT/DELETE | `/api/tasks` | Tarefas agendadas recorrentes |
| GET/POST | `/api/files` | Listar/ler/escrever no workspace |
| POST | `/api/confirmations/{id}` | Aprovar/recusar uma ação |
| GET | `/api/trading/config` | Modos, permissões, limites e aviso de risco |
| GET | `/api/trading/education` | Trilha do iniciante e glossário |
| GET | `/api/trading/status` | Estado do MT5 e da conta conectada |
| GET | `/api/trading/account` · `/symbol` · `/rates` · `/positions` · `/orders` | Dados reais de mercado/conta |
| GET | `/api/trading/analyse` | Análise técnica (single ou `multi=true`) |
| GET/POST/DELETE | `/api/trading/strategies` | Estratégias salvas |
| POST | `/api/trading/backtest` | Backtest em histórico real |
| GET/POST/DELETE | `/api/trading/alerts` (+ `/evaluate`, `/{id}/toggle`) | Alertas |
| GET/POST | `/api/trading/paper` (+ `/open`, `/close`) | Simulação (paper trading) |
| GET/POST/PATCH/DELETE | `/api/trading/journal` | Diário de operações |
| GET | `/api/trading/audit` | Registro de auditoria |
| GET/POST | `/api/trading/mode` | Modo de operação (learn→real) |
| POST | `/api/trading/limits` | Limites de risco |
| POST | `/api/trading/stop` | STOP TRADING de emergência |
| POST | `/api/trading/order/prepare` · `/execute` | Pré-ordem (risco) e envio (idempotente) |
| POST | `/api/trading/close` | Fechar posição |
| GET | `/api/trading/brief` · `/scan` | Resumo diário e varredura rápida |
| GET | `/api/ai/modes` · PUT `/api/ai/mode` | Listar/definir o modo da IA |
| GET/PUT | `/api/ai/personality` | Ler/atualizar traços e estilo |
| GET | `/api/ai/voice/status` · PUT `/api/ai/voice/config` | Estado e configuração de voz |
| POST | `/api/ai/voice/speak` · `/voice/transcribe` · `/voice/transcript` | TTS, STT e gravação opt-in |
| GET/DELETE | `/api/ai/voice/history` | Histórico de voz (opt-in) |
| POST | `/api/ai/codex/analyze` · `/plan` · `/test` · `/sandbox` | Análise, plano, testes e sandbox |
| GET/POST | `/api/ai/codex/changes` (+ `/{id}/apply`,`/reject`,`/revert`) | Changesets com diff |
| GET | `/api/ai/plugins` · POST `/plugins/install` · PUT/DELETE `/plugins/{name}` | Plugins |
| GET | `/api/ai/media/providers` · POST `/images/generate` · `/audio/narrate` · `/video/render` | Mídia |
| GET | `/api/ai/jobs` (+ `/{id}`, `/{id}/cancel`) | Fila de jobs com progresso |
| GET | `/api/ai/media/file` | Servir mídia gerada (restrito a `generated/`) |
| GET | `/api/ai/intelligence` · POST `/api/ai/experiences` | Painel de inteligência |
| GET | `/api/ai/privacy/export` · DELETE `/privacy/memory` · `/privacy/experiences` | Privacidade |
| GET | `/api/ai/diagnostics` · `/api/ai/admin/overview` | Auto-diagnóstico e admin |

---

## 8. Testes

```bash
.venv/bin/python -m pytest -q
```

Cobrem: criptografia de segredos, persistência, sandbox de arquivos e
bloqueio de comandos destrutivos, execução real de Python (incluindo o valor
da última expressão), análise de dados, ciclo de vida de tarefas, o laço do
agente (com e sem confirmação, aprovação e recusa), o streaming SSE e toda a
API REST. `test_providers.py` cobre a **cadeia de fallback** (falha do
primeiro provedor, esgotamento com relatório de todas as tentativas, montagem
da cadeia keyless e uso da Base URL do usuário) e a **autenticação**
(senha + token de sessão). Os testes usam **servidores HTTP locais reais**
como LLM e como provedores; todo o restante (agente, ferramentas, banco,
HTTP, auth) é código real, sem mocks do nosso próprio código.

---

## 8b. Tarefas agendadas

Na aba **Tarefas**, agende um prompt recorrente (intervalo mínimo de 30s).
O agendador roda em segundo plano, executa cada tarefa em uma conversa nova e
registra o resultado. Tarefas rodam em modo autônomo; os bloqueios de
comandos destrutivos continuam valendo.

---

## 9. Autenticação

Toda a aplicação fica atrás de login por senha (`OPENHUD_PASSWORD`). A sessão
é um cookie `HttpOnly` assinado (`OPENHUD_SESSION_SECRET`), com validade de
7 dias e `SameSite=Lax`; em HTTPS o cookie é marcado como `Secure`. Sem
senha configurada, o OpenHUD **gera uma senha aleatória** no primeiro boot e
a imprime no log — configure `OPENHUD_PASSWORD` para uma senha fixa.

As rotas `/api/*` respondem `401` sem sessão; páginas protegidas redirecionam
para `/login`. O endpoint de login tem limite de tentativas por IP.

## 10. Segurança

- Chaves criptografadas em repouso; nunca retornadas por completo.
- Arquivos confinados ao workspace (`OPENHUD_WORKSPACE`).
- Comandos destrutivos conhecidos são sempre recusados.
- Ações sensíveis pedem confirmação no modo supervisionado.
- Login por senha, cookie de sessão assinado e limite de tentativas.
- Nenhuma tentativa de contornar autenticação de terceiros.

## 10b. Implantação (hospedagem gratuita)

O container expõe a porta definida por `PORT`/`OPENHUD_PORT` e guarda todo o
estado em `OPENHUD_DATA_DIR`. Há três caminhos:

1. **Docker / VPS (recomendado, permanente)**
   ```bash
   docker build -t openhud .
   docker run -d --name openhud -p 8000:8000 \
     -e OPENHUD_PASSWORD='uma-senha-forte' \
     -v openhud-data:/data openhud
   ```
2. **Render (plano free)** — faça push para o GitHub, depois *New > Blueprint*
   e aponte para `render.yaml`. O Render injeta `PORT` e gera a senha; adicione
   um disco em `/data` para persistir o estado.
3. **Railway / Fly.io / Cloud Run** — usam o `Dockerfile` diretamente; defina
   `OPENHUD_PASSWORD`, `OPENHUD_SESSION_SECRET` e um volume em `/data`.

Para banco permanente sem cartão de crédito, crie um Postgres gratuito em
**Neon**, **Supabase** ou **Aiven** e defina `DATABASE_URL` — o OpenHUD passa
a persistir conversas, memória e tarefas no Postgres automaticamente.

Sem nenhuma chave de API, a instalação nova responde via **Pollinations**
(keyless) e, se houver um Ollama local, usa-o como reforço. Para respostas
mais confiáveis, adicione uma chave gratuita de **Groq** ou **Google AI
Studio** em Configurações.

### Validado neste ambiente
- `docker build` concluído; container sobe, responde `/api/health` e serve o
  login (modo keyless, `provider: pollinations`).
- Conexão do agente pela URL pública **HTTPS/WSS** funciona (pareamento +
  token), então o mesmo fluxo serve para um host na nuvem.

### Onde hospedar de graça (pesquisa de outubro/2026)
| Plataforma | Cartão? | WebSocket | Observação |
|---|---|---|---|
| **Render** (free) | não | sim | dorme após 15 min sem tráfego; acorda em ~60 s |
| **Railway** (free) | não | sim | US$ 1/mês de crédito; pausa quando acaba |
| **Google Cloud Run** | sim | sim | cota mensal; exige cartão |
| **Fly.io** | sim | sim | sem free tier novo; ~US$ 2/mês |

Para uso 24/7 sem dormir, a opção mais barata é um VPS próprio (~US$ 3–5/mês)
ou o Fly.io pago. O `render.yaml` já está pronto para o caminho sem cartão.

---

## 10c. Agente de PC (OpenHUD Agent)

O site **nunca** acessa o PC diretamente: o agente instalado no PC inicia a
conexão de saída (WebSocket) para o servidor. Isso funciona atrás de NAT, sem
abrir portas e sem IP fixo.

### Fluxo de conexão
1. No site, abra **Painel do PC → Conectar este computador → Gerar código**.
   O código vale 10 minutos e é de uso único.
2. No PC, rode o agente (Python 3.10+):
   ```bash
   pip install -r requirements-agent.txt
   python -m openhud.agent.agent_client \
     --server https://SEU-OPENHUD --pair CODIGO --name "Meu PC"
   ```
3. O agente guarda um **token** e reconecta sozinho depois
   (`--server` apenas, sem `--pair`). Revogue um dispositivo a qualquer
   momento no painel.

### Windows
- O mesmo comando funciona no PowerShell. Para uso diário, crie um `.exe`
  autônomo (sem Python instalado):
  ```powershell
  pip install pyinstaller -r requirements-agent.txt
  python -m openhud.agent.build_exe
  dist\openhud-agent.exe --server https://SEU-OPENHUD --pair CODIGO
  ```
- Para iniciar com o Windows, coloque um atalho do `.exe` na pasta
  `shell:startup`.

### Permissões (nada é coletado sem autorização)
`system`, `cpu`, `gpu`, `ram`, `storage`, `processes`, `temperatures`,
`network`, `games`, `commands`. Cada uma pode ser ligada/desligada no painel;
o servidor bloqueia o que não foi autorizado e devolve erro explícito.

### Ferramentas de PC no chat
Com um dispositivo conectado, o agente de IA pode chamar:
- `pc_metrics` — CPU/RAM/GPU/disco/rede/processos em tempo real;
- `pc_diagnose` — gargalos e recomendações (com dado observado, análise,
  recomendação, impacto e risco);
- `pc_game_profile` — perfil por jogo (FPS medido, ajustes sugeridos).

As respostas citam sempre os números reais medidos; quando não há dado
(ex.: GPU ausente), o agente informa isso em vez de inventar.

---

## 10d. Módulo MetaTrader 5 (MT5)

Análise, monitoramento, alertas, automação controlada, gestão de risco e
execução — integrado ao OpenHUD. **O site nunca acessa a conta diretamente**:
tudo passa pelo OpenHUD Agent no PC onde o MetaTrader 5 está aberto.

> ⚠️ Operações financeiras envolvem risco de perda. As análises da IA **não
> garantem resultados**. O módulo não promete lucro. Ativar operações reais é
> decisão e responsabilidade do usuário.

### Requisitos no PC
- Windows com **MetaTrader 5** instalado e aberto, com uma conta conectada
  (demo ou real).
- `pip install MetaTrader5` (somente Windows). O agente funciona sem ele,
  informando que o MT5 não está disponível.
- O agente precisa das permissões de trading (aba **Conectar → Permissões**).
  O padrão já habilita leitura/análise/alertas/demo; **REAL vem desligado**.

### Modos de operação
| Modo | O que faz | Permissão exigida |
| --- | --- | --- |
| `learn` | Explica conceitos, sem tocar no mercado | — |
| `analysis` (padrão) | Lê e analisa; cria alertas; backtest | `ALLOW_MARKET_READ` |
| `simulation` | Paper trading com preços reais informados | — |
| `demo` | Envia ordens em conta demo | `ALLOW_DEMO_TRADING` |
| `real` | Envia ordens em conta real (com confirmação) | `ALLOW_REAL_TRADING` |

### O que está implementado
- **Análise**: SMA/EMA/RSI/MACD/Bollinger/ATR/ADX/Estocástico/VWAP, suportes e
  resistências, estrutura (topos/fundos), rompimentos, volatilidade e
  **multi-timeframe** (M5→H4). Só reporta o que os dados confirmam.
- **Estratégias**: descreva em linguagem natural ("EMA 9 + EMA 21 + RSI 14");
  a IA mostra as regras interpretadas (entrada/saída/stop/take/filtros).
- **Backtest**: sobre histórico real, com taxa de acerto, profit factor,
  drawdown, sequências e aviso de que resultados passados não garantem futuro.
- **Alertas**: preço, indicador, rompimento, volatilidade e spread.
- **Paper trading**: saldo, equity, posições e estatísticas simuladas.
- **Operações**: pré-ordem calcula lote por risco%, stop, take, margem e R:R;
  valida limites (perda diária, nº de ops, posições, lote, ativos, horários).
  O envio é **idempotente** por `request_id` e sempre auditado.
- **Segurança**: STOP TRADING de emergência, permissões separadas, nenhum
  martingale, nenhum dado de conta é inventado; se o MT5 não responder, o erro
  real é exibido.

### No chat
Basta pedir, por exemplo: *"Analise EURUSD no H1 e me explique a estrutura"*,
*"Crie um alerta se o RSI do XAUUSD ficar abaixo de 30"*, *"Faça um backtest
da minha estratégia EMA no GBPUSD"*. O agente usa as ferramentas `mt5_*` e
`trading_*` e reporta exatamente o que conseguiu executar.

---

## 10e. Assistente de computador, acessibilidade e aplicativo Windows (Fase 5)

### Assistente de computador
A aba **Assistente** transforma o agente num ajudante que entende linguagem
natural ("Quero entrar no meu e-mail", "Não sei onde clicar", "Pode fazer para
mim?") e escolhe como ajudar:

- **Modos `do_for_me` e `do_with_me`** no roteamento automático: a IA decide
  entre *fazer junto* (guiar) e *fazer para você* (executar), conforme o nível
  de autonomia e o perfil.
- **Perfis** (`standard`, `beginner`, `power_user`, `accessibility`) que
  adaptam a linguagem, o tamanho das explicações e o nível de detalhe técnico.
- **Níveis de autonomia** (`observe`, `guide`, `assisted`, `automatic`):
  - `observe`/`guide`: a IA **não controla** o PC — mostra onde clicar e explica.
  - `assisted`: executa ações simples **só após confirmação**.
  - `automatic`: conclui tarefas autorizadas, mas **ações sensíveis ainda
    pedem confirmação** (ver abaixo).
- **Visão de tela** (`screen_analyze`, `screen_find`, `screen_highlight`):
  captura + OCR no PC pareado, lista elementos (botões, campos, menus),
  localiza por descrição e destaca na tela. Sem as bibliotecas nativas
  (`mss`, `pytesseract`, `pyautogui`) ou sem PC pareado, retorna erro honesto.
- **Controle** (mouse/teclado/abrir URL), sempre sob o *gate* de autonomia.

### Estados de tarefa e controle (Part 14/15)
Toda conversa tem um estado visível: `OBSERVANDO`, `ENTENDENDO`,
`AGUARDANDO VOCÊ`, `EXECUTANDO`, `AGUARDANDO CONFIRMAÇÃO`, `CONCLUÍDO`,
`ERRO`, `CANCELADO`. A barra no topo do chat mostra o estado e oferece
**PARAR** e **PAUSAR/RETOMAR**. Também é possível cancelar por voz/frase curta
("pare", "pausa", "continue").

### Ações sensíveis (Part 8)
Mesmo em autonomia automática, o *gate* nunca executa sem confirmação ações
classificadas como sensíveis: **pagamentos/transferências, senhas e dados
bancários, exclusão de arquivos, execução de arquivos desconhecidos,
publicações em massa, compras**. A detecção é feita por palavras-chave nos
argumentos das ferramentas de controle e por uma lista fixa de ferramentas
perigosas (`trading_execute_order`, `delete_file`). Ferramentas comuns
(`run_python`, `write_file`) mantêm a semântica normal de confirmação para
não bloquear o trabalho autônomo.

### Proteção contra golpes e phishing (Part 13)
O endpoint `/api/assistant/scam-check` e o cartão "Proteção contra golpes"
apontam **sinais** de risco (urgência, pedido de senha/código, domínio
parecido com banco, link encurtado) com um nível `low`/`medium`/`high`.
Nunca afirma com certeza — apenas alerta e recomenda verificar no canal
oficial.

### Acessibilidade (Part 20)
Preferências em **Configurações → Acessibilidade**: texto maior, botões
grandes, alto contraste, ler respostas em voz alta, voz mais calma e linguagem
simples. São aplicadas na hora (classes no `<body>`) e persistem no banco.

### Aplicativo Windows (Parts 16/17)
`openhud/desktop/` contém o aplicativo oficial:
- `app.py`: inicia o servidor local, abre o navegador e fica na **bandeja do
  sistema**; na primeira execução gera e mostra uma senha local. Pode rodar
  como **agente** (`--agent <servidor> --pair <código>`).
- `build.py`: empacota com **PyInstaller** (`OpenHUD AI.exe`).
- `installer/openhud.iss`: instalador **Inno Setup**. Atalhos e inicialização
  automática são **opcionais e desmarcados**; a desinstalação remove os
  arquivos do app e pergunta se deve apagar os dados locais.

```bash
pip install -r requirements-desktop.txt
python -m openhud.desktop.build          # gera dist/OpenHUD AI.exe (no Windows)
iscc installer/openhud.iss               # gera "OpenHUD AI Setup.exe"
```

### Hospedagem oficial (Parts 18/21/22/23)
- **Container**: `Dockerfile` com `HEALTHCHECK` em `/health` e volume `/data`.
- **Stack**: `docker-compose.yml` (SQLite por padrão; perfil `postgres`
  opcional). Defina `OPENHUD_PASSWORD` e, para TLS, coloque atrás de um proxy.
- **Saúde**: `/health` (liveness) e `/ready` (checa o banco).
- **Backups**: `/api/assistant/maintenance/backup` cria backup real com
  `PRAGMA integrity_check` (SQLite) ou `pg_dump` (Postgres); `restore` guarda
  uma cópia de segurança antes de substituir.
- **Migrações**: o schema é criado de forma idempotente e a versão é gravada
  em `settings.schema_version` (`/api/assistant/maintenance/schema`).
- **Atualizações seguras**: `/api/assistant/update/check` lê um manifesto
  HTTPS com `version`/`artifacts[].sha256` e **não executa nada**; o download
  verifica o hash antes de gravar.

---

## 10f. Fase 6 — Teste no Windows, instalador, site público e distribuição

### Site público
O mesmo processo FastAPI serve um site de marketing **sem login**, separado do
app:

- `/` (início), `/features`, `/how-it-works`, `/pricing`, `/help`, `/privacy`,
  `/download`, `/changelog`, `/version`.
- O app fica em `/app` e nas rotas internas (`/chat`, `/settings`, …) e
  **exige sessão**; sem login, redireciona para `/login`.
- `openhud/web/site.py` monta as páginas a partir de um *shell* comum (nav +
  rodapé) e dos dados reais de `openhud/core/release.py`.

### Página de download honesta
`/download` **nunca inventa** um arquivo. Ela lê `/api/site/release`, que
resolve o instalador em três níveis:

1. `OPENHUD_DOWNLOAD_URL` — link real (GitHub Releases / CDN) → botão aparece;
2. artefato local em `dist/` ou `installer/Output/` → calcula **tamanho e
   SHA-256 reais**;
3. nada → mostra o aviso "não publicado" e explica o que falta.

Para servir o arquivo pelo próprio app (VPS), defina
`OPENHUD_SERVE_INSTALLER=1` (rota `/download/file`).

### Diagnóstico real do agente
`openhud/agent/selfcheck.py` (ou `openhud-agent.exe --diagnose`) verifica
Windows, arquitetura, Python, rede/HTTPS, WebSocket, autenticação, permissões,
captura de tela, OCR, mouse, teclado, clipboard, navegador, áudio, microfone,
TTS, STT, GPU, CPU, RAM e armazenamento. Cada item recebe um status honesto:
**PASS**, **WARNING**, **FAIL**, **NOT INSTALLED** ou **NOT PERMITTED** —
nunca um "ok" inventado.

```bash
python -m openhud.agent.selfcheck            # relatório legível
python -m openhud.agent.selfcheck --json     # para máquinas
openhud-agent.exe --diagnose                 # no agente instalado
```

### Aplicativo desktop
- `desktop/config.py`: configuração persistente (servidor, token, grupos de
  permissão) em `%APPDATA%\OpenHUD\desktop.json`.
- `desktop/wizard.py`: assistente de primeira execução que explica o produto,
  coleta o pareamento e deixa o usuário escolher as permissões — **nada de
  controle é ativado sozinho**.
- `desktop/runtime.py`: roda o `AgentClient` em uma thread própria, com estados
  reais de conexão.
- `desktop/tray.py`: bandeja com status real ("OpenHUD conectado" /
  "OpenHUD desconectado"), abrir interface, configurações, diagnóstico,
  conectar/desconectar e sair.

### Instalador oficial
`installer/openhud.iss` (Inno Setup) gera `OpenHUD-AI-Setup.exe`:

- instalação por usuário por padrão (admin opcional);
- atalhos de área de trabalho e menu Iniciar **opcionais e desmarcados**;
- "iniciar com o Windows" **opcional e desmarcado**;
- sem serviços e sem tarefas agendadas;
- desinstalação limpa que pergunta se deve apagar os dados locais.

```bat
python -m openhud.desktop.build      :: dist\OpenHUD AI.exe
python -m openhud.agent.build_exe    :: dist\openhud-agent.exe
iscc installer\openhud.iss           :: installer\Output\OpenHUD-AI-Setup.exe
python tools\make_release.py         :: release.json com tamanho + SHA-256 reais
```

### Documentação de distribuição
- `WINDOWS_TEST.md`: procedimento de teste real no Windows, com resultados
  esperados e o que registrar.
- `DEPLOY.md`: comparação de hospedagem gratuita (Render, Fly.io, Koyeb,
  Railway, VPS), banco (Neon/Supabase) e como publicar o site + distribuir o
  instalador.
- `CHANGELOG.md` e `LICENSE` (MIT).

> Transparência: o build do `.exe` e do instalador **precisa** ser feito no
> Windows. Este ambiente é Linux, então os scripts estão prontos e testados na
> parte portável, mas nenhum `.exe` foi gerado aqui — e nada aqui finge que foi.

---

## 11. Status das funcionalidades

### Concluídas e verificadas
- Agente com laço de execução, streaming e persistência.
- 58 ferramentas reais (incl. `pc_metrics`, `pc_diagnose`, `pc_game_profile`,
  `screen_capture`, `screen_analyze`, `screen_find`, `screen_highlight`,
  `mouse_*`, `keyboard_*`, `window_list`, controle de tarefas e verificação de
  golpes) + sistema de confirmação e autonomia.
- **Agente de PC (PC↔site)**: hub WebSocket, pareamento por código de uso
  único, tokens de dispositivo, permissões por categoria, telemetria real
  (CPU/RAM/GPU/disco/rede/processos), diagnóstico de gargalos e perfis de jogo.
- **Módulo MT5**: análise técnica + price action + multi-timeframe, estratégias
  em linguagem natural, backtest sobre histórico real, alertas, paper trading,
  gestão de risco (lote por risco%, limites, perda diária), pré-ordem,
  execução idempotente e auditada, STOP TRADING de emergência e trilha
  educativa. Nada é inventado: sem MT5, retorna o erro real.
- **Fase 4 — Voz, personalidade, Codex, plugins e multimodalidade**:
  - 13 modos de operação com roteamento automático transparente;
  - motor de personalidade (traços + estilo) e aprendizado adaptativo;
  - voz: TTS real (Edge), STT no navegador, 12 idiomas, estilos, conversa
    contínua e wake word, com privacidade por padrão;
  - Codex: análise de projeto, plano, changesets com diff/aplicar/reverter,
    execução de testes real e sandbox com limites;
  - plugins nativos + manifestos externos com permissões por risco;
  - geração de imagem, narração e render de vídeo com fila de jobs real;
  - painel de Inteligência (experiências, taxa de sucesso, ferramentas);
  - centro de Privacidade e painel Admin com auto-diagnóstico real;
  - proteção contra injeção de prompt no conteúdo externo das ferramentas.
- **Fase 5 — Assistente de computador, acessibilidade e app Windows**:
  - assistente em linguagem natural com modos `do_for_me`/`do_with_me` e
    roteamento automático;
  - perfis de usuário e 4 níveis de autonomia com *gate* de ações sensíveis;
  - visão de tela (captura + OCR + localizar/destacar elementos) e controle
    de mouse/teclado/URL no PC pareado;
  - estados de tarefa visíveis e controle PARAR/PAUSAR/RETOMAR (+ voz);
  - proteção contra golpes/phishing com níveis de risco;
  - acessibilidade (texto grande, alto contraste, leitura em voz alta);
  - aplicativo Windows (bandeja + `--agent`), build PyInstaller e instalador
    Inno Setup com atalhos/inicialização opcionais e desinstalação limpa;
  - `docker-compose.yml`, healthchecks, backup/restore real com verificação de
    integridade, versão de schema e atualização segura por manifesto HTTPS.
- **Fase 6 — Site público, download, diagnóstico, instalador e distribuição**:
  - site público sem login (`/`, `/features`, `/how-it-works`, `/pricing`,
    `/help`, `/privacy`, `/download`, `/changelog`, `/version`), com o app
    protegido em `/app`;
  - página de download que mostra tamanho e SHA-256 **reais** e só exibe o
    botão quando há instalador publicado (`OPENHUD_DOWNLOAD_URL`) ou artefato
    local — nunca um link falso;
  - `openhud/agent/selfcheck.py`: diagnóstico real com status PASS / WARNING /
    FAIL / NOT INSTALLED / NOT PERMITTED (e `--diagnose` no agente);
  - app desktop com assistente de primeira execução, configuração persistente,
    runtime do agente em thread própria e bandeja com status de conexão real;
  - instalador Inno Setup oficial (`OpenHUD-AI-Setup.exe`) com atalhos e
    inicialização opcionais e desinstalação limpa;
  - `WINDOWS_TEST.md`, `DEPLOY.md`, `CHANGELOG.md`, `LICENSE` (MIT) e ícones
    reais (`tools/make_brand_assets.py`, `tools/make_release.py`).
- Múltiplos provedores de modelo e chaves criptografadas.
- **Cadeia de fallback** entre 11 provedores + Ollama local, com *retry* de
  falhas transitórias e relatório honesto das tentativas.
- **Provedor sem chave** (Pollinations) para funcionar sem configuração.
- **Login por senha** com cookie de sessão assinado e limite de tentativas.
- **PostgreSQL** opcional via `DATABASE_URL` (testado contra Postgres real).
- Memória de longo prazo, histórico, projetos e registro de atividades.
- Análise de dados (CSV/JSON) e tarefas agendadas em segundo plano.
- Interface web completa e responsiva (painel do PC, jogos, desempenho,
  conexão, chat, Codex, imagens, vídeo, plugins, inteligência, privacidade,
  admin, com indicador do provedor/modo e logout).
- `Dockerfile` + `render.yaml`; **build do container validado** neste ambiente.
- Suíte de **150 testes** automatizados, todos passando.

### Dependem de configuração externa
- **Chave de API** de um provedor (Groq/Google/OpenRouter) para respostas
  mais confiáveis; sem ela, usa-se Pollinations (keyless) ou Ollama local.
- **Visão de tela e controle do PC**: exigem um PC pareado com as permissões
  `screen`/`control` e as bibliotecas nativas (`mss`, `pytesseract`,
  `pyautogui`, `pynput`, `pygetwindow`, `pyperclip`). Sem isso, os endpoints
  retornam erro honesto e a IA apenas orienta por texto.
- **Aplicativo Windows / instalador**: o build (PyInstaller) e a compilação do
  Inno Setup precisam ser executados **no Windows**; neste ambiente Linux os
  scripts estão prontos mas não geram o `.exe`.
- **Chave do Brave Search** é opcional; sem ela, a busca usa DuckDuckGo.
- **ffmpeg** é necessário para render de vídeo e processamento de áudio
  avançado; sem ele, esses recursos retornam erro honesto.
- **Transcrição no servidor (STT)** exige `openai-whisper` ou uma chave
  OpenAI; o padrão é a transcrição pelo microfone do navegador.
- **Isolamento de rede no sandbox** não é aplicável neste ambiente (exige
  root/namespaces); os limites de CPU/memória/arquivo/timeout são aplicados.
- **MT5 (execução real)**: exige Windows com MetaTrader 5 aberto, o pacote
  `MetaTrader5` instalado e uma conta conectada; sem isso, o módulo funciona
  em análise/simulação e informa o motivo real ao tentar ler o mercado.
- **URL permanente**: depende de uma conta em Render/Railway/Fly ou de um
  servidor próprio — o `Dockerfile` está pronto para qualquer um deles. A
  criação do repositório Git na nuvem precisa de um token com permissão de
  criar repositório (o token deste ambiente é de integração, sem essa
  permissão); o código e os arquivos de deploy já estão prontos.
- **Banco permanente**: crie um Postgres gratuito (Neon/Supabase/Aiven) e
  defina `DATABASE_URL`; sem isso o estado fica no disco local.
- **Métricas de GPU**: exigem uma GPU NVIDIA com driver e `nvidia-ml-py` no
  PC; sem isso, o diagnóstico informa "GPU não detectada" em vez de inventar.
- Integrações com serviços de terceiros (e-mail, planilhas na nuvem,
  agendamento) não estão incluídas por padrão — o sistema é extensível:
  adicione novas ferramentas em `openhud/tools/` e registre-as em
  `build_default_registry()`, ou crie um plugin externo com `manifest.json`.
