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
| Banco de dados | SQLite (WAL) |
| Front-end | HTML/CSS/JS puro (sem build) |
| Provedores de modelo | OpenAI-compatível, Anthropic, Ollama/local |
| Execução | Terminal e Python em sandbox de workspace |
| Testes | pytest — **20 testes, todos passando** |

Nenhum código pré-existente foi encontrado no repositório: o OpenHUD foi
construído do zero nesta estrutura.

---

## 2. Instalação

Requer Python 3.11+.

```bash
git clone <repo> && cd project
./run.sh            # cria o venv, instala dependências e inicia
```

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
| `OPENHUD_PORT` | `8000` | Porta do servidor |
| `OPENHUD_HOST` | `0.0.0.0` | Host do servidor |
| `OPENHUD_DATA_DIR` | `./data` | Banco, chaves, segredos |
| `OPENHUD_WORKSPACE` | `./workspace` | Sandbox de arquivos/execução |
| `OPENHUD_MAX_STEPS` | `25` | Etapas máximas do agente |

---

## 3. Configurar um modelo

Abra **Configurações** na interface e escolha o provedor:

- **OpenAI / Groq / DeepSeek / OpenRouter / vLLM** — cole a chave em
  *Chaves de API* (`openai`, `groq`, ...).
- **Anthropic** — chave `anthropic`.
- **Ollama (local)** — rode `ollama serve` e escolha o provedor `ollama`;
  não precisa de chave. Ex.: modelo `llama3.1`.

A Base URL é ajustada automaticamente por provedor e pode ser sobrescrita
para apontar a qualquer endpoint OpenAI-compatível.

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
│   ├── db.py            # SQLite: conversas, memória, atividades, settings
│   ├── secrets_store.py # armazenamento seguro de chaves
│   ├── llm.py           # adaptadores OpenAI-compatível e Anthropic
│   └── runtime.py       # singletons e resolução de configuração
├── tools/               # filesystem, execução, web, memória
├── agent/
│   ├── loop.py          # laço do agente (streaming de eventos)
│   ├── prompts.py       # prompt de sistema
│   ├── confirm.py       # broker de confirmação interativa
│   └── scheduler.py     # execução de tarefas recorrentes
├── web/
│   ├── app.py           # API REST + SSE
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
| GET | `/api/health` | Estado e se o provedor está configurado |
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
bloqueio de comandos destrutivos, execução real de Python, análise de dados,
ciclo de vida de tarefas, o laço do agente (com e sem confirmação, aprovação
e recusa), o streaming SSE e toda a API REST. Os testes usam um **servidor
LLM local simulado**; todo o restante (agente, ferramentas, banco, HTTP) é
código real.

---

## 8b. Tarefas agendadas

Na aba **Tarefas**, agende um prompt recorrente (intervalo mínimo de 30s).
O agendador roda em segundo plano, executa cada tarefa em uma conversa nova e
registra o resultado. Tarefas rodam em modo autônomo; os bloqueios de
comandos destrutivos continuam valendo.

---

## 9. Segurança

- Chaves criptografadas em repouso; nunca retornadas por completo.
- Arquivos confinados ao workspace (`OPENHUD_WORKSPACE`).
- Comandos destrutivos conhecidos são sempre recusados.
- Ações sensíveis pedem confirmação no modo supervisionado.
- Nenhuma tentativa de contornar autenticação de terceiros.

---

## 10. Status das funcionalidades

### Concluídas e verificadas
- Agente com laço de execução, streaming e persistência.
- 12 ferramentas reais + sistema de confirmação e autonomia.
- Múltiplos provedores de modelo e chaves criptografadas.
- Memória de longo prazo, histórico, projetos e registro de atividades.
- Análise de dados (CSV/JSON) e tarefas agendadas em segundo plano.
- Interface web completa e responsiva.
- Suíte de 23 testes automatizados, todos passando.

### Dependem de configuração externa
- **Chave de API** de um provedor (ou Ollama local) para gerar respostas.
- **Chave do Brave Search** é opcional; sem ela, a busca usa DuckDuckGo.
- Integrações com serviços de terceiros (e-mail, planilhas na nuvem,
  agendamento) não estão incluídas por padrão — o sistema é extensível:
  adicione novas ferramentas em `openhud/tools/` e registre-as em
  `build_default_registry()`.
