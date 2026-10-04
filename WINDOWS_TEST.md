# OpenHUD AI — Teste real no Windows (procedimento oficial)

Este documento é o roteiro para validar o OpenHUD em um Windows **real**. Ele
existe porque não é possível executar o aplicativo Windows nem o instalador
neste ambiente Linux de desenvolvimento — então este procedimento descreve os
passos exatos, o resultado esperado de cada um e o que registrar.

> Regra: não marque um passo como aprovado sem ter visto o resultado real.
> Se algo falhar, anote a mensagem de erro exata. O diagnóstico do agente foi
> feito para nunca inventar um resultado.

## Execução automatizada (recomendado)

Em vez de rodar os passos à mão, use o script que faz tudo e gera um relatório:

```powershell
powershell -ExecutionPolicy Bypass -File installer\windows-smoke-test.ps1
# incluir build dos executáveis e do instalador:
powershell -ExecutionPolicy Bypass -File installer\windows-smoke-test.ps1 -Build -Installer
```

Ele cobre: info do sistema (OS/CPU/RAM/GPU), ambiente Python + venv, suíte de
testes, `selfcheck --json`, build dos `.exe` (opcional), compilação do
instalador (opcional) e auditoria de registro (nenhuma entrada de inicialização
nem serviço). O resultado fica em `windows-test-report.json`, com os status
reais — nenhum passo é marcado como aprovado sem observação.

## 0. Requisitos

- Windows 10 ou 11, 64 bits.
- Python 3.11+ **somente** para rodar a partir do código-fonte (o instalador
  oficial não exige Python).
- Conta de usuário normal. Administrador é opcional (instalação para todos os
  usuários).

## 1. Diagnóstico do agente (sem instalar nada)

O jeito mais rápido de saber se a máquina está pronta:

```bat
python -m openhud.agent.selfcheck
```

Ou, se você já tem o agente instalado:

```bat
openhud-agent.exe --diagnose
```

Resultado esperado: uma tabela com cada item e um status entre **PASS**,
**WARNING**, **FAIL**, **NOT INSTALLED** e **NOT PERMITTED**. Itens como
"Captura de tela" devem aparecer como **NOT PERMITTED** até você conceder a
permissão no site — isso é o comportamento correto, não um erro.

Para guardar um relatório:

```bat
openhud-agent.exe --diagnose --diagnose-json > diagnostico.json
```

## 2. Rodar a partir do código-fonte (validação do servidor local)

```bat
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-desktop.txt
python -m openhud.desktop.app
```

Esperado:

- O console mostra `Iniciando em http://127.0.0.1:8000` e uma senha local.
- O navegador abre a página pública (site) em `/`.
- Em `/login`, a senha local entra e leva para `/app`.
- O ícone aparece na bandeja com o título **"OpenHUD conectado"** ou
  **"OpenHUD desconectado"** conforme o estado real.

Teste os recursos que dependem do Windows:

| Recurso | Como testar | Esperado |
| --- | --- | --- |
| Telemetria | Painel do PC | CPU, RAM, disco e GPU reais (ou "não detectada") |
| Captura de tela | Conceder "Tela" no site, pedir uma captura | Imagem real ou erro explícito |
| OCR | Pedir leitura de um texto na tela | Texto reconhecido ou "Tesseract não instalado" |
| Controle | Conceder "Controle", pedir para mover o mouse | O ponteiro se move |
| Voz | Conceder "Voz", falar | Transcrição ou aviso de microfone |

## 3. Gerar os executáveis

```bat
python -m openhud.desktop.build
python -m openhud.agent.build_exe
```

Esperado: `dist\OpenHUD AI.exe` e `dist\openhud-agent.exe`.

Teste o executável diretamente (sem instalar):

```bat
dist\OpenHUD AI.exe --permissions
dist\OpenHUD AI.exe --diagnose
```

## 4. Compilar o instalador

Instale o [Inno Setup 6](https://jrsoftware.org/isdl.php) e compile:

```bat
iscc installer\openhud.iss
```

Esperado: `installer\Output\OpenHUD-AI-Setup.exe`.

## 5. Testar a instalação

1. Execute `OpenHUD-AI-Setup.exe`.
2. Escolha a pasta (padrão: `C:\Program Files\OpenHUD AI` ou por usuário).
3. **Não** marque atalhos nem "iniciar com o Windows" para o primeiro teste.
4. Conclua e abra o app.

Verifique:

- [ ] O programa abre e o site público carrega.
- [ ] A bandeja mostra o status real.
- [ ] O assistente de primeira execução explica o produto e pede o pareamento.
- [ ] Nenhuma entrada de inicialização foi criada (verifique `msconfig` →
      Inicialização, ou `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`).
- [ ] Nenhum serviço foi instalado (`services.msc`).

## 6. Testar o pareamento de ponta a ponta

1. No site, abra **Painel do PC** e gere um código de 6 dígitos.
2. No app: `OpenHUD AI.exe --agent https://SEU-SERVIDOR --pair 123456`.
3. Esperado: o app conecta (WSS), o dispositivo aparece **online** no site e as
   permissões escolhidas aparecem marcadas.

## 7. Testar a desinstalação

1. Painel de Controle → Aplicativos → **OpenHUD AI** → Desinstalar.
2. Quando perguntar sobre os dados locais, teste as duas opções em execuções
   separadas.

Verifique:

- [ ] A pasta do programa foi removida.
- [ ] Escolhendo "Não", `%APPDATA%\OpenHUD` é preservado.
- [ ] Escolhendo "Sim", `%APPDATA%\OpenHUD` é removido.
- [ ] Nenhum atalho, entrada de inicialização ou serviço permanece.

## 8. Registrar os resultados

Preencha e anexe ao relatório da release:

```
Máquina:            (CPU / RAM / GPU / versão do Windows)
Data:               ____-__-__
Versão testada:     5.0.0
selfcheck:          PASS=__ WARNING=__ FAIL=__ NOT INSTALLED=__ NOT PERMITTED=__
Instalação:         OK / FALHOU  (detalhe)
Pareamento:         OK / FALHOU  (detalhe)
Tela / OCR:         OK / FALHOU  (detalhe)
Controle:           OK / FALHOU  (detalhe)
Voz:                OK / FALHOU  (detalhe)
Desinstalação:      OK / FALHOU  (detalhe)
Observações:
```

## O que NÃO pode ser validado aqui

Este ambiente de desenvolvimento é Linux e não tem Windows, PyInstaller para
Windows, Inno Setup nem GPU NVIDIA. Portanto:

- a compilação dos `.exe` e do instalador **precisa** ser feita no Windows;
- os testes de captura de tela, controle e voz dependem de permissões e
  hardware reais;
- o que este repositório entrega é o código, o script do instalador, os testes
  automatizados das partes portáveis e este procedimento.

Não há resultado de teste de Windows registrado aqui porque ele não foi
executado. Rode os passos acima na sua máquina e preencha a seção 8.
