# Changelog

Todas as mudanças relevantes do OpenHUD AI. O formato segue
[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o versionamento
segue [SemVer](https://semver.org/lang/pt-BR/).

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
- 150 testes automatizados passando.

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
