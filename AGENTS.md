# AGENTS.md — OpenHUD

Memória persistente do repositório para agentes que trabalharem neste projeto.

## Visão geral
OpenHUD é uma IA pessoal multifuncional: agente LLM + ferramentas reais +
memória + interface web. Python 3.11+, FastAPI, SQLite, front-end sem build.

## Comandos essenciais
- Instalar/rodar: `./run.sh` (cria `.venv` e inicia em `:8000`)
- Rodar servidor: `.venv/bin/python -m openhud`
- Testes: `.venv/bin/python -m pytest -q`
- Teste único: `.venv/bin/python -m pytest tests/test_api.py::test_streaming_turn_autonomous -q`

## Convenções
- Estado de runtime em `data/` (ignorado no git). Workspace do agente em
  `workspace/` (`OPENHUD_WORKSPACE`).
- Segredos: SEMPRE via `SecretStore` (Fernet). Nunca logar valores brutos;
  a API só devolve prévia mascarada.
- Ferramentas novas: criar em `openhud/tools/`, herdar de `Tool`, e registrar
  em `build_default_registry()` (`openhud/tools/__init__.py`). Marcar
  `requires_confirmation = True` se alterar estado.
- Caminhos de arquivo devem passar por `_resolve`/`_safe_path` para ficar
  dentro do workspace.
- O laço do agente (`openhud/agent/loop.py`) é o dono da persistência do turno
  do usuário. A camada HTTP não deve duplicar isso.

## Armadilhas conhecidas
- `TestClient` do Starlette serializa requisições por um único portal: um
  POST feito durante um stream SSE causa deadlock no teste (não em produção).
  Resolva confirmações a partir de uma thread auxiliar nos testes.
- O terminal desta sandbox rejeita comandos multi-linha colados; escreva
  scripts em arquivo e execute com `bash arquivo.sh`.

## Configuração de modelo
Provedores: openai, anthropic, groq, deepseek, openrouter, ollama.
Base URLs em `DEFAULT_BASE_URLS` (`openhud/core/llm.py`). `supports_tools`
controla o envio de ferramentas ao provedor.
