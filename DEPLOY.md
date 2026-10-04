# OpenHUD AI — Implantação do site público e distribuição

Este guia cobre duas coisas: (1) publicar o **site público + servidor** e
(2) distribuir o **instalador do Windows**. O site e o app são o mesmo processo
FastAPI — publicar o servidor já publica o site.

## 1. Comparação de hospedagem gratuita (real, 2026)

O OpenHUD usa **WebSocket** (agente do PC), **SQLite com WAL** por padrão
(PostgreSQL opcional) e, no modo gratuito, deve **dormir** quando ocioso. Isso
importa na escolha:

| Provedor | WebSocket | Disco persistente | Dorme? | Observação |
| --- | --- | --- | --- | --- |
| **Render** (free) | Sim | **Não** no free tier | Sim, após ~15 min | Precisa de banco externo (Neon/Supabase) e storage externo para o instalador |
| **Fly.io** | Sim | Volumes pagos | Configurável | Tem franquia gratuita limitada; bom para WebSocket |
| **Koyeb** (free) | Sim | Não | Sim | Free tier com limites de instância |
| **Railway** | Sim | Volumes pagos | Configurável | Crédito inicial; depois pago |
| **VPS pequeno** | Sim | Sim | Não | Mais controle; melhor para servir o instalador |

### Banco de dados

- **SQLite (padrão)**: ótimo para uso pessoal em VPS com disco.
- Em PaaS **sem disco persistente**, use PostgreSQL gerenciado:
  - **Neon** (free): bom limite, escala para zero.
  - **Supabase** (free): inclui Postgres + extras; pausa projetos ociosos.

Defina `OPENHUD_DATABASE_URL` (ou o nome usado no seu `config.py`) apontando para
o Postgres. Sem isso, em PaaS sem disco, os dados somem a cada reinício.

### WebSocket

Todos os provedores acima suportam WebSocket. O agente conecta em
`wss://SEU-HOST/ws/agent`. Não é preciso abrir portas no PC do usuário: a
conexão é de **saída**.

## 2. Publicar o servidor (passo a passo)

1. Crie o serviço apontando para este repositório.
2. Build: use o `Dockerfile` do repositório (ou `pip install -r requirements.txt`).
3. Comando de start (ajuste conforme o provedor):
   ```bash
   uvicorn openhud.web.app:app --host 0.0.0.0 --port $PORT
   ```
4. Variáveis de ambiente mínimas:
   ```bash
   OPENHUD_PASSWORD=<senha-forte-do-operador>
   OPENHUD_DATA_DIR=/data                # se houver disco persistente
   OPENHUD_DATABASE_URL=postgres://...   # se não houver disco persistente
   OPENHUD_DOWNLOAD_URL=https://.../OpenHUD-AI-Setup.exe
   ```
5. Abra `https://SEU-HOST/` — o site público deve carregar sem login.
6. Confirme `https://SEU-HOST/health` e `https://SEU-HOST/ready`.

> Aviso honesto: no free tier o serviço dorme. A primeira visita depois disso
> leva alguns segundos para acordar. O site avisa isso na página de preços.

## 3. Distribuir o instalador

O site **nunca** inventa um link. A página `/download` mostra o botão somente
quando existe uma URL real ou um arquivo local real.

### Opção A — GitHub Releases (recomendado)

1. Compile o instalador no Windows (veja `WINDOWS_TEST.md`, seções 3 e 4).
2. Crie uma release com a tag `v5.0.0` e anexe `OpenHUD-AI-Setup.exe`.
3. Defina no servidor:
   ```bash
   OPENHUD_DOWNLOAD_URL=https://github.com/SEU-USUARIO/SEU-REPO/releases/download/v5.0.0/OpenHUD-AI-Setup.exe
   ```
4. Recarregue `/download`: o botão aparece, com o tamanho e o SHA-256 reais.

### Opção B — arquivo local (VPS)

1. Copie `OpenHUD-AI-Setup.exe` para `installer/Output/` (ou `dist/`).
2. Defina `OPENHUD_SERVE_INSTALLER=1` para o servidor servir o arquivo em
   `/download/file`.
3. Não use esta opção em PaaS gratuito (arquivos grandes e disco efêmero).

### Calcular o SHA-256 (para divulgar junto do download)

Windows:
```bat
certutil -hashfile "OpenHUD-AI-Setup.exe" SHA256
```
Linux/macOS:
```bash
sha256sum OpenHUD-AI-Setup.exe
```

O `/api/site/release` retorna `sha256`, `size_human` e `filename` do artefato
real (quando presente), para conferência.

## 4. Site público

As páginas públicas são servidas pelo mesmo processo e não exigem login:

- `/` — início · `/features` · `/how-it-works` · `/pricing` · `/help`
- `/privacy` · `/download` · `/changelog` · `/version`

O app (SPA) fica em `/app` e nas rotas internas (`/chat`, `/settings`, …) e
**exige** sessão; sem login, redireciona para `/login`.

## 5. Checklist de publicação

- [ ] `OPENHUD_PASSWORD` forte definida.
- [ ] HTTPS ativo (WebSocket exige `wss://`).
- [ ] Banco: disco persistente **ou** `OPENHUD_DATABASE_URL`.
- [ ] `OPENHUD_DOWNLOAD_URL` apontando para o instalador real.
- [ ] `/health` e `/ready` respondendo.
- [ ] `/download` mostrando o botão (ou o aviso honesto de "não publicado").
- [ ] Backup configurado (veja os cards de backup/atualização no app).
