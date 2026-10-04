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
| Testes | pytest — **29 testes, todos passando** |

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

Cada ferramenta pode ser habilitada/desabilitada na aba **Ferramentas**.
Todo caminho de arquivo é validado para permanecer dentro do workspace.

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
│   └── runtime.py       # singletons e resolução de configuração
├── tools/               # filesystem, execução, web, memória
├── agent/
│   ├── loop.py          # laço do agente (streaming de eventos)
│   ├── prompts.py       # prompt de sistema
│   ├── confirm.py       # broker de confirmação interativa
│   └── scheduler.py     # execução de tarefas recorrentes
├── web/
│   ├── app.py           # API REST + SSE
│   ├── auth.py          # senha, cookie de sessão assinado
│   ├── ratelimit.py     # limite de tentativas
│   └── static/          # interface web
└── __main__.py          # ponto de entrada
```

O laço do agente é um gerador de eventos (`token`, `tool_start`,
`tool_result`, `confirmation`, `error`, `done`) transmitidos ao navegador
via Server-Sent Events. Cada turno roda em uma thread de trabalho.

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

## 11. Status das funcionalidades

### Concluídas e verificadas
- Agente com laço de execução, streaming e persistência.
- 15 ferramentas reais (incl. `pc_metrics`, `pc_diagnose`, `pc_game_profile`)
  + sistema de confirmação e autonomia.
- **Agente de PC (PC↔site)**: hub WebSocket, pareamento por código de uso
  único, tokens de dispositivo, permissões por categoria, telemetria real
  (CPU/RAM/GPU/disco/rede/processos), diagnóstico de gargalos e perfis de jogo.
- Múltiplos provedores de modelo e chaves criptografadas.
- **Cadeia de fallback** entre 11 provedores + Ollama local, com *retry* de
  falhas transitórias e relatório honesto das tentativas.
- **Provedor sem chave** (Pollinations) para funcionar sem configuração.
- **Login por senha** com cookie de sessão assinado e limite de tentativas.
- **PostgreSQL** opcional via `DATABASE_URL` (testado contra Postgres real).
- Memória de longo prazo, histórico, projetos e registro de atividades.
- Análise de dados (CSV/JSON) e tarefas agendadas em segundo plano.
- Interface web completa e responsiva (painel do PC, jogos, desempenho,
  conexão, chat, com indicador do provedor e logout).
- `Dockerfile` + `render.yaml`; **build do container validado** neste ambiente.
- Suíte de **39 testes** automatizados, todos passando.

### Dependem de configuração externa
- **Chave de API** de um provedor (Groq/Google/OpenRouter) para respostas
  mais confiáveis; sem ela, usa-se Pollinations (keyless) ou Ollama local.
- **Chave do Brave Search** é opcional; sem ela, a busca usa DuckDuckGo.
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
  `build_default_registry()`.
