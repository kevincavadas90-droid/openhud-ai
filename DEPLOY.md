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

## 2. Plataformas recomendadas (comparação honesta, 2026)

| Plataforma | Free tier | Disco persistente | WebSocket/SSE | Observação |
| --- | --- | --- | --- | --- |
| **Fly.io** | Não (paga por uso, ~US$2/mês) | **Sim** (volumes) | Sim | **Melhor opção**: barato, always-on, volume + Postgres |
| **Render** | Sim (dorme ~15 min) | **Não** no free | Sim | Free exige Postgres externo; pago (Starter) tem disco |
| **Railway** | US$1 de crédito/mês | Volume pago + Postgres | Sim | Fácil de subir; Postgres com 1 clique |
| **Koyeb** | Só Postgres grátis | Não | Sim | Compute free removido; Pro a partir de US$29 |
| **VPS (Hetzner/DO)** | Não (~US$4–6/mês) | Sim | Sim | Mais controle; ótimo para servir o instalador |

**Recomendação para hospedagem permanente e barata:** **Fly.io** com um volume
de 1 GB (≈ US$2/mês) — sempre ligado, disco real, WebSocket/SSE nativos.
Se quiser custo zero no começo: **Render free + Postgres no Neon** (o serviço
dorme quando ocioso; a primeira visita acorda em segundos).

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

## 5. Passo a passo por plataforma

### 5.1 Fly.io (recomendado — permanente e barato)

```bash
# 1. Instale o CLI e faça login
curl -L https://fly.io/install.sh | sh
fly auth login

# 2. Crie o app (o nome em fly.toml é "openhud-ai"; ajuste se já existir)
fly apps create openhud-ai

# 3. Crie o volume persistente onde o SQLite/segredos ficam
fly volumes create openhud_data --size 1 --region gru

# 4. Defina os segredos (nunca vão para o repositório)
fly secrets set OPENHUD_PASSWORD=... OPENHUD_SESSION_SECRET=... \
  OPENHUD_PUBLIC_URL=https://openhud-ai.fly.dev

# 5. Publique
fly deploy

# 6. Confira
curl https://openhud-ai.fly.dev/health
curl https://openhud-ai.fly.dev/ready
```

Domínio próprio: `fly certs add openhud.SEUDOMINIO.com` e aponte o DNS.

### 5.2 Render (custo zero, com Postgres externo)

1. Suba o repositório no GitHub (veja §7).
2. Crie um Postgres grátis no **neon.tech** (ou supabase.com) e copie a URL.
3. Em render.com: **New → Blueprint** → selecione o repositório (usa `render.yaml`).
4. No painel, preencha as variáveis marcadas `sync: false`:
   `OPENHUD_DATABASE_URL`, `OPENHUD_PUBLIC_URL`, `OPENHUD_DOWNLOAD_URL`,
   `OPENHUD_DONATION_URL`, `OPENHUD_SMTP_*`.
5. Deploy. O healthcheck é `/health`.

> Free tier dorme após ~15 min. A primeira visita acorda em alguns segundos.
> **Sem `OPENHUD_DATABASE_URL`, as contas resetam a cada reinício.**

### 5.3 Railway

```bash
npm i -g @railway/cli
railway login
railway init          # cria/vincula o projeto
# No painel: New → Database → PostgreSQL (injeta DATABASE_URL automaticamente)
railway variables set OPENHUD_PASSWORD=... OPENHUD_SESSION_SECRET=... \
  OPENHUD_PUBLIC_URL=https://SEU-APP.up.railway.app
railway up
```

O `railway.json` já define build por Dockerfile e healthcheck `/health`.

### 5.4 VPS (Docker Compose, com HTTPS)

```bash
# No servidor:
git clone <SEU-REPO> openhud && cd openhud
export OPENHUD_PASSWORD=$(python3 -c "import secrets;print(secrets.token_urlsafe(24))")
export OPENHUD_SESSION_SECRET=$(python3 -c "import secrets;print(secrets.token_urlsafe(48))")
docker compose up -d --build            # SQLite + volume
# ou, com Postgres gerenciado pelo compose:
docker compose --profile postgres up -d --build
```

Coloque um proxy TLS na frente (Caddy é o mais simples):

```
# Caddyfile
openhud.SEUDOMINIO.com {
    reverse_proxy 127.0.0.1:8000
}
```

O Caddy emite o certificado e faz proxy de WebSocket/SSE automaticamente.

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
