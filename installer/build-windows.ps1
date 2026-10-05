# OpenHUD AI — build do instalador oficial (Windows).
#
# Uso (PowerShell, na raiz do repositório):
#     powershell -ExecutionPolicy Bypass -File installer\build-windows.ps1
#
# Requisitos: Python 3.11+, Inno Setup 6 (iscc no PATH).
# Gera:
#     dist\OpenHUD AI.exe
#     dist\openhud-agent.exe
#     installer\Output\OpenHUD-AI-Setup.exe
#     installer\Output\release.json   (tamanho + SHA-256 reais)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "== OpenHUD AI — build do instalador ==" -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python não encontrado no PATH."
}

Write-Host "`n[1/5] Instalando dependências de build..." -ForegroundColor Yellow
python -m pip install -r requirements-desktop.txt

Write-Host "`n[2/5] Gerando o aplicativo (PyInstaller)..." -ForegroundColor Yellow
python -m openhud.desktop.build

Write-Host "`n[3/5] Gerando o agente (PyInstaller)..." -ForegroundColor Yellow
python -m openhud.agent.build_exe

Write-Host "`n[4/5] Compilando o instalador (Inno Setup)..." -ForegroundColor Yellow
if (-not (Get-Command iscc -ErrorAction SilentlyContinue)) {
    throw "iscc (Inno Setup 6) não encontrado no PATH. Instale em https://jrsoftware.org/isdl.php"
}
$version = (python -c "import openhud; print(openhud.__version__)").Trim()
Write-Host "Versão do produto: $version" -ForegroundColor DarkGray
iscc "/DMyAppVersion=$version" installer\openhud.iss

Write-Host "`n[5/5] Gerando o manifesto de release (tamanho + SHA-256)..." -ForegroundColor Yellow
python tools\make_release.py

$setup = Join-Path $root "installer\Output\OpenHUD-AI-Setup.exe"
if (Test-Path $setup) {
    $hash = (Get-FileHash $setup -Algorithm SHA256).Hash
    Write-Host "`nPronto: $setup" -ForegroundColor Green
    Write-Host "SHA-256: $hash" -ForegroundColor Green
    Write-Host "`nPublique o arquivo (ex.: GitHub Releases) e defina OPENHUD_DOWNLOAD_URL no servidor." -ForegroundColor Cyan
} else {
    throw "O instalador não foi gerado. Verifique a saída do iscc acima."
}
