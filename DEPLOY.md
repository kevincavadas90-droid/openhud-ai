# OpenHUD AI — hospedagem pública permanente

Este guia leva o OpenHUD AI de "rodando no runtime temporário do OpenHands"
para **hospedagem pública permanente**, com HTTPS, WebSocket, SSE, banco
persistente e variáveis de ambiente.

O site público e o aplicativo são **o mesmo processo FastAPI**. Publicar o
servidor já publica o site, a API, o WebSocket do agente e o SSE do chat.

---

## 1. Requisitos do que vamos publicar

| Recurso | Por quê | Consequência na escolha |
| --- | --- | --- |
| **HTTPS** | Login, cookies e WebSocket | Toda plataforma moderna dá TLS automático |
| **WebSocket** | Agente do PC (`/ws/agent`) | Evite só-serverless (Cloud Run/Lambda puros) |
| **SSE** | Streaming do chat | Precisa de resposta longa (não bufferizar) |
| **Disco OU Postgres** | Contas, memória, tokens | Free tier sem disco **exige** Postgres externo |
| **Um processo** | Fila de jobs em memória | Não escale para várias réplicas sem repensar a fila |

> O OpenHUD é **stateful** (SQLite + chave criptografada + fila de jobs em
> memória). Por isso o alvo recomendado é **uma instância com disco persistente**
> (Fly.io + volume, ou um VPS pequeno). Se usar PaaS sem disco, configure
> **PostgreSQL** para os dados não sumirem.

---

## 2. Plataforma escolhida: **Render** (plano grátis) + Postgres no **Neon**

Para o objetivo **site público + API + login + banco persistente**, com
simplicidade e custo zero, a opção recomendada é **Render** (Blueprint, deploy a
partir do repositório GitHub) com um **Postgres gratuito no Neon**.

Por que esta escolha:

| Critério | Como o Render + Neon atende |
| --- | --- |
| Custo | **Grátis** (web service free + Postgres free no Neon) |
| Site + API + login | Um único processo FastAPI serve tudo |
| HTTPS/WSS/SSE | Automáticos (WebSocket do agente e streaming do chat funcionam) |
| Deploy simples | **Blueprint** lê o `render.yaml`; conecta o repo e sobe |
| Banco persistente | Postgres do Neon sobrevive a reinícios/redeploys |
| Segredos | Render gera `OPENHUD_PASSWORD`, `OPENHUD_SESSION_SECRET` e `OPENHUD_ENCRYPTION_KEY` |

> **Limitação honesta do plano grátis:** o serviço *dorme* após ~15 min ocioso e
> a primeira visita demora alguns segundos para acordar; o disco é **efêmero**
> (por isso o banco vai no Neon e a chave de criptografia vai em variável de
> ambiente). Para sempre-ligado sem dormir, o plano pago do Render (Starter) ou
> um VPS pequeno resolvem — mas isso deixa de ser custo zero.

Alternativas (mesmo `Dockerfile`, se você preferir depois): Fly.io com volume
(pago, ~US$2/mês, sempre-ligado) e Railway. Veja o **Apêndice A**.

---

## 3. O que já está pronto no repositório

| Arquivo | Para quê |
| --- | --- |
| `Dockerfile` | Imagem única (uvicorn + API + SSE + WS + SPA), usuário não-root, healthcheck |
| `.dockerignore` | Imagem limpa (sem `.git`, `data/`, `.env`, artefatos) |
| `fly.toml` | Fly.io: volume `/data`, healthcheck `/health`, HTTPS forçado |
| `render.yaml` | Render Blueprint (free): gera segredos, aponta para Postgres externo |
| `railway.json` | Railway: build por Dockerfile, healthcheck `/health` |
| `docker-compose.yml` | VPS/local: app + Postgres opcional |
| `.env.example` | **Todas** as variáveis, comentadas |

Endpoints de plataforma (sem login):

- `GET /health` → `{"status":"ok",...}` (liveness)
- `GET /ready` → checa o banco; 503 se não estiver pronto (readiness)
- `GET /version` → JSON com versão e metadados do release

---

## 4. Variáveis de ambiente

Mínimas para produção:

```bash
OPENHUD_PASSWORD=<senha-forte-do-operador>   # protege o app
OPENHUD_SESSION_SECRET=<token-48-bytes>       # cookies de sessão estáveis
OPENHUD_AUTH=on
OPENHUD_ACCOUNTS=on
OPENHUD_PUBLIC_URL=https://SEU-DOMINIO        # canonical, sitemap, e-mails
OPENHUD_DATA_DIR=/data                        # se houver volume
OPENHUD_DATABASE_URL=postgresql://...         # se NÃO houver disco
```

Opcionais: `OPENHUD_DOWNLOAD_URL`, `OPENHUD_DONATION_URL`, `OPENHUD_SMTP_*`,
`OPENHUD_CORS_ORIGINS`, chaves de IA (`GROQ_API_KEY`, …). Veja `.env.example`.

Gerar segredos:

```bash
python -c "import secrets;print(secrets.token_urlsafe(24))"   # senha
python -c "import secrets;print(secrets.token_urlsafe(48))"   # session secret
```

---

## 5. Passo a passo: Render (plataforma escolhida)

### 5.1 Publicar em 5 passos

1. **Suba o código no GitHub** (veja §7). Repositório sugerido: `openhud-ai`.
2. **Crie um Postgres grátis no [neon.tech](https://neon.tech)** e copie a
   connection string (`postgresql://...?sslmode=require`).
3. Em **[render.com](https://render.com) → New → Blueprint**, selecione o
   repositório. O Render lê o `render.yaml` e cria o serviço web.
4. No painel do serviço, preencha as variáveis marcadas `sync: false`
   (veja a tabela da §4):
   - `OPENHUD_DATABASE_URL` → a URL do Neon (obrigatória para persistência);
   - `OPENHUD_PUBLIC_URL` → `https://SEU-APP.onrender.com` (ou domínio próprio);
   - `OPENHUD_DOWNLOAD_URL` / `OPENHUD_DONATION_URL` / `OPENHUD_SMTP_*` (opcionais).
   `OPENHUD_PASSWORD`, `OPENHUD_SESSION_SECRET` e `OPENHUD_ENCRYPTION_KEY` já são
   gerados automaticamente pelo Blueprint.
5. **Deploy**. O healthcheck é `/health`.

Confira:

```bash
curl https://SEU-APP.onrender.com/health
curl https://SEU-APP.onrender.com/ready
curl https://SEU-APP.onrender.com/version
```

Domínio próprio: **Settings → Custom Domain** no Render e aponte o CNAME.

### 5.2 Resumo (o que colar)

| Item | Valor |
| --- | --- |
| **PLATAFORMA** | Render (Blueprint, plano free) + Postgres Neon (free) |
| **ARQUIVO DE CONFIGURAÇÃO** | `render.yaml` (e `Dockerfile`) |
| **COMANDO DE DEPLOY** | Painel: *New → Blueprint* → repositório → *Apply* (sem CLI) |
| **VARIÁVEIS NECESSÁRIAS** | `OPENHUD_DATABASE_URL`, `OPENHUD_PUBLIC_URL` (obrigatórias); `OPENHUD_DOWNLOAD_URL`, `OPENHUD_DONATION_URL`, `OPENHUD_SMTP_*` (opcionais). `OPENHUD_PASSWORD`/`OPENHUD_SESSION_SECRET`/`OPENHUD_ENCRYPTION_KEY` são gerados pelo Blueprint |

---

## 6. PostgreSQL em produção

- **Quando:** sempre que a plataforma não tiver disco persistente.
- **Onde:** Neon (free), Supabase (free), Railway Postgres, Aiven, ou o serviço
  `db` do `docker-compose.yml`.
- **Como:** defina `OPENHUD_DATABASE_URL` (tem prioridade sobre o `DATABASE_URL`
  genérico que algumas plataformas injetam). O app detecta o driver e usa
  Postgres em vez de SQLite — sem mudar código.
- **Driver:** já incluído (`psycopg[binary]`).

---

## 7. Publicar o código e a release no GitHub (pré-requisito)

### 7.1 Com um comando (recomendado)

O repositório traz um publicador que faz tudo: empacota o código-fonte, cria o
repositório (se o token permitir), faz push, cria a tag `v5.1.0`, abre a release
e envia os ativos (`.zip` do código e, se existir, o instalador `.exe`):

```bash
# Só o pacote + manifesto (funciona sem rede, em qualquer plataforma):
python tools/prepare_release.py

# Publicar de fato (precisa de um token com escopo `repo`):
GITHUB_TOKEN=... python tools/publish_release.py --repo SEU-USUARIO/openhud-ai

# Simular sem alterar nada:
python tools/publish_release.py --repo SEU-USUARIO/openhud-ai --dry-run
```

No fim ele imprime exatamente as variáveis para colar na plataforma
(`OPENHUD_SOURCE_URL`, `OPENHUD_DOWNLOAD_URL`).

> **Limite de permissão:** o token do OpenHands deste ambiente **não** tem
> escopo de criar repositórios (`Resource not accessible by integration`). Se o
> seu também não tiver, crie o repositório em https://github.com/new e rode o
> script de novo — ele fará o push e a release automaticamente.

### 7.2 Manualmente

```bash
git remote add origin https://github.com/SEU-USUARIO/openhud.git
git branch -M master
git push -u origin master
gh repo create SEU-USUARIO/openhud --private --source=. --push   # alternativa
```

Depois, anexe `dist/OpenHUD-AI-Complete-5.1.0.zip` (e o `.exe`, se houver) a uma
Release, e aponte Render/Railway/Fly para esse repositório.

---

## 8. Checklist de publicação

- [ ] Repositório no GitHub (público ou privado).
- [ ] `OPENHUD_PASSWORD` e `OPENHUD_SESSION_SECRET` fortes definidos.
- [ ] `OPENHUD_PUBLIC_URL` com o domínio final (HTTPS).
- [ ] Persistência: volume `/data` **ou** `OPENHUD_DATABASE_URL`.
- [ ] `/health` e `/ready` respondendo.
- [ ] `/register`, `/login`, `/account` funcionando (crie uma conta de teste).
- [ ] `/download` mostrando o botão **só** quando `OPENHUD_DOWNLOAD_URL` existir.
- [ ] `/pricing` mostrando o botão de doação **só** quando `OPENHUD_DONATION_URL` existir.
- [ ] `OPENHUD_SMTP_*` configurado para e-mails de verificação/recuperação.
- [ ] Domínio próprio + HTTPS ativo (WebSocket exige `wss://`).
- [ ] Backup do banco (Neon/Railway têm snapshots; em VPS, agende `pg_dump`).

---

## 9. O que NÃO dá para automatizar daqui

O ambiente do OpenHands não possui credenciais de nenhuma plataforma de
hospedagem nem um token do GitHub com escopo `repo`. Portanto:

- **Não** há deploy permanente automático — o projeto está **100% pronto** para
  deploy, mas a criação da conta na plataforma e o `fly deploy` / `railway up` /
  "New → Blueprint" precisam da sua ação (login/autorização externa).
- **Não** invente um domínio: `OPENHUD_PUBLIC_URL` fica vazio até você definir.

Assim que você rodar os passos da §5, o site estará em um endereço permanente e
real, e você deve atualizar `OPENHUD_PUBLIC_URL` para ele.

---

## Apêndice A. Alternativas (mesmo Dockerfile)

A plataforma escolhida é o **Render**. Os arquivos abaixo já estão no
repositório caso você prefira outra opção depois — nenhum deles é obrigatório.

### A.1 Fly.io (sempre-ligado, pago ~US$2/mês, com volume)

```bash
curl -L https://fly.io/install.sh | sh && fly auth login
fly apps create openhud-ai
fly volumes create openhud_data --size 1 --region gru
fly secrets set OPENHUD_PASSWORD=... OPENHUD_SESSION_SECRET=... \
  OPENHUD_PUBLIC_URL=https://openhud-ai.fly.dev
fly deploy
```

Config em `fly.toml` (volume `/data`, healthcheck `/health`, HTTPS forçado).

### A.2 Railway (Postgres com 1 clique)

```bash
npm i -g @railway/cli && railway login && railway init
# Painel: New -> Database -> PostgreSQL (injeta DATABASE_URL)
railway up
```

Config em `railway.json` (build por Dockerfile, healthcheck `/health`).

### A.3 VPS (Docker Compose + HTTPS com Caddy)

```bash
git clone <SEU-REPO> openhud && cd openhud
export OPENHUD_PASSWORD=$(python3 -c "import secrets;print(secrets.token_urlsafe(24))")
export OPENHUD_SESSION_SECRET=$(python3 -c "import secrets;print(secrets.token_urlsafe(48))")
export OPENHUD_ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")
docker compose up -d --build
```

`Caddyfile`:

```
openhud.SEUDOMINIO.com {
    reverse_proxy 127.0.0.1:8000
}
```

