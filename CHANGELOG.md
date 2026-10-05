# Changelog

Todas as mudanças relevantes do OpenHUD AI. O formato segue
[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o versionamento
segue [SemVer](https://semver.org/lang/pt-BR/).

## 5.2.0 (2026-10-05)

- **Apoio via LivePix**: a área de apoio em `/pricing` agora mostra o QR Code
  oficial do LivePix (imagem fornecida, sem modificações) e o botão
  **APOIAR O PROJETO** aponta para <https://livepix.gg/supimpa2>. Inclui
  alternativa textual acessível (`Ou acesse: livepix.gg/supimpa2`) e layout
  responsivo (desktop e celular). O link é público (não é credencial) e pode
  ser trocado por `OPENHUD_DONATION_URL`; defina a variável como vazia para
  esconder o botão.
- **Aplicativo Windows real e instalável**: pipeline de build no Windows
  (PyInstaller + Inno Setup) via GitHub Actions em runner `windows-latest`,
  gerando `OpenHUD AI.exe`, `openhud-agent.exe` e o instalador
  `OpenHUD-AI-Setup.exe`. O workflow faz smoke test dos executáveis congelados
  (servidor embutido respondendo em `/health`) antes de publicar.
- **Download real**: a página `/download` passa a exibir o instalador real
  (versão, tamanho, SHA-256 e link) assim que `OPENHUD_DOWNLOAD_URL` aponta
  para o asset publicado; nunca mostra um link falso.
- Versão do produto elevada para 5.2.0.

## 5.1.1 (2026-10-04)

- **Cabeçalhos de segurança** em todas as respostas: `Content-Security-Policy`
  (mesma origem + fontes do Google usadas pelo site), `X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` e
  `Strict-Transport-Security` quando servido por HTTPS.
- **Verificador de deploy público** (`tools/verify_public_deploy.py`): checa
  páginas, endpoints, cabeçalhos e o fluxo real de conta contra uma URL pública.
- **Hospedagem pública permanente**: plataforma definida (Render free + Postgres
  no Neon) e documentada em `DEPLOY.md`; alternativas (Fly/Railway/VPS) no
  Apêndice A. `railway.json` corrigido para JSON válido.
- **Chaves de API persistentes em disco efêmero**: nova variável
  `OPENHUD_ENCRYPTION_KEY` (Fernet) para que os segredos cifrados continuem
  legíveis após um redeploy; gerada automaticamente pelo `render.yaml`.
- **Degradação honesta**: se a chave de criptografia estiver errada/rotacionada,
  `/api/secrets` informa o problema em vez de retornar HTTP 500, e
  `/api/health`, diagnóstico e busca continuam funcionando.
- **README** com badges, recursos e início rápido; contagem de testes atualizada.
- Testes: **230** automatizados, todos passando.

## 5.1.0 (2026-10-04)

- **Contas de usuário**: cadastro, login, logout, recuperação e redefinição de
  senha, verificação de e-mail, troca de senha e exclusão de conta (LGPD).
  Senhas com PBKDF2-SHA256 e política de senha forte; sessões guardadas apenas
  como hash, com listagem e revogação; proteção CSRF e limite de tentativas.
- **Páginas de conta** (`/register`, `/login`, `/forgot-password`,
  `/reset-password`, `/account`) e navegação do site ciente de sessão.
- **Dispositivos vinculados à conta**: cada PC pareado pertence ao usuário que
  o registrou; o app Windows entra com a mesma conta do site
  (`--login --email`) e guarda somente o token do dispositivo.
- **E-mail por ambiente** (`OPENHUD_SMTP_*`) que nunca finge ter enviado.
- **URL de doação** opcional (`OPENHUD_DONATION_URL`).
- Testes: **208** automatizados, todos passando.

## 5.0.0 (2026-10-04)

- Site público com páginas de início, recursos, como funciona, preços, ajuda,
  privacidade, download e changelog (sem login).
- Página de download que mostra tamanho e SHA-256 reais e só exibe o botão
  quando há um instalador publicado de verdade.
- Instalador oficial para Windows (Inno Setup): atalhos e início automático
  opcionais, desinstalação limpa com opção de manter os dados locais.
- Diagnóstico do agente (`selfcheck`) com status PASS / WARNING / FAIL /
  NOT INSTALLED / NOT PERMITTED — nunca inventa um resultado.
- Aplicativo desktop com assistente de primeira execução, bandeja com status
  de conexão real, configurações e diagnóstico.
- Permissão de voz adicionada às permissões do agente.
- Guias `WINDOWS_TEST.md` e `DEPLOY.md` e licença MIT.
- Pacote de código-fonte (`tools/make_source_zip.py`) e download real do ZIP na
  página `/download` (tamanho e SHA-256 reais).
- Detecção de GPU multi-vendor (NVIDIA via NVML; AMD/Intel via sysfs/CIM/lspci).
- Script de teste real no Windows (`installer/windows-smoke-test.ps1`) que gera
  relatório com os resultados observados.
- 175 testes automatizados passando.

## 4.0.0

- Módulos de inteligência de negócios, criação de conteúdo, análise de dados e
  automação administrativa.
- Barramento de ferramentas extensível e sistema de plugins.

## 3.0.0

- Memória de longo prazo, projetos e histórico de conversas.
- Múltiplos provedores de IA, incluindo provedores sem chave e modelo local.

## 2.0.0

- Ferramentas reais: terminal, arquivos, Python, busca na web, navegador, HTTP
  e análise de dados.
- Interface web com streaming por SSE.

## 1.0.0

- Núcleo do agente, laço de conversa e interface inicial.
