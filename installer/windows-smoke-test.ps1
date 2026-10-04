<#
.SYNOPSIS
    Automated Windows smoke test for OpenHUD AI.

.DESCRIPTION
    Runs the steps from WINDOWS_TEST.md automatically on a real Windows machine
    and writes a machine-readable report (windows-test-report.json) plus a
    human summary. It never marks a step as passed without observing the real
    result: every section records the actual command output / exit code.

    Sections:
      0. System info (OS, arch, CPU, RAM, GPU via CIM)
      1. Python environment (venv + requirements-desktop)
      2. Automated test suite (pytest)
      3. Agent selfcheck (--json)  -> PASS/WARNING/FAIL/NOT INSTALLED/NOT PERMITTED
      4. Build executables (optional, -Build)
      5. Build installer (optional, -Installer, needs Inno Setup iscc)
      6. Registry audit: no Run key, no service installed

.PARAMETER Build
    Also build dist\OpenHUD AI.exe and dist\openhud-agent.exe (needs pyinstaller).

.PARAMETER Installer
    Also compile installer\Output\OpenHUD-AI-Setup.exe (needs Inno Setup 6 / iscc).

.PARAMETER SkipTests
    Skip the pytest step (useful when only building).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\windows-smoke-test.ps1
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\windows-smoke-test.ps1 -Build -Installer
#>
[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$Installer,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$script:results = [ordered]@{}
$script:steps   = New-Object System.Collections.Generic.List[object]
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Add-Step {
    param([string]$Name, [string]$Status, [string]$Detail = "")
    $script:steps.Add([pscustomobject]@{ name = $Name; status = $Status; detail = $Detail })
    $color = switch ($Status) {
        "PASS"  { "Green" }
        "WARN"  { "Yellow" }
        "FAIL"  { "Red" }
        "SKIP"  { "DarkGray" }
        default { "Gray" }
    }
    Write-Host ("[{0,-5}] {1}" -f $Status, $Name) -ForegroundColor $color
    if ($Detail) { Write-Host ("        " + $Detail) -ForegroundColor DarkGray }
}

function Section([string]$title) {
    Write-Host ""
    Write-Host ("=== " + $title + " ===") -ForegroundColor Cyan
}

# ---------------------------------------------------------------------------
Section "0. Sistema"
# ---------------------------------------------------------------------------
$isWindows = $true
if ($PSVersionTable.PSVersion.Major -ge 6) { $isWindows = $IsWindows }
if (-not $isWindows) {
    Add-Step "Plataforma" "FAIL" "Este script deve ser executado no Windows."
    Write-Host "Abortando: ambiente nao e Windows." -ForegroundColor Red
    exit 2
}
Add-Step "Plataforma" "PASS" "Windows detectado."

try {
    $os = Get-CimInstance Win32_OperatingSystem
    $cs = Get-CimInstance Win32_ComputerSystem
    $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
    $script:results.system = [ordered]@{
        os        = $os.Caption
        version   = $os.Version
        arch      = $os.OSArchitecture
        cpu       = $cpu.Name
        cores     = $cpu.NumberOfCores
        ram_gb    = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
    }
    Add-Step "OS" "PASS" ("{0} ({1})" -f $os.Caption, $os.Version)
    Add-Step "CPU/RAM" "PASS" ("{0} · {1} GB" -f $cpu.Name, $script:results.system.ram_gb)
} catch {
    Add-Step "Info do sistema" "WARN" $_.Exception.Message
}

# GPU (multi-vendor, via CIM)
try {
    $gpus = Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM, DriverVersion
    $script:results.gpus = @($gpus | ForEach-Object { $_.Name })
    if ($gpus) {
        Add-Step "GPU" "PASS" (($gpus | ForEach-Object { $_.Name }) -join " | ")
    } else {
        Add-Step "GPU" "WARN" "Nenhuma GPU reportada pelo CIM (pode ser normal em VM)."
    }
} catch {
    Add-Step "GPU" "WARN" $_.Exception.Message
}

# ---------------------------------------------------------------------------
Section "1. Ambiente Python"
# ---------------------------------------------------------------------------
$py = $null
foreach ($cand in @("py -3", "python", "python3")) {
    try {
        $parts = $cand.Split(" ")
        $exe = $parts[0]; $pre = @(); if ($parts.Length -gt 1) { $pre = $parts[1..($parts.Length-1)] }
        $ver = & $exe @pre --version 2>&1
        if ($LASTEXITCODE -eq 0) { $py = @{ exe = $exe; pre = $pre; version = $ver }; break }
    } catch { }
}
if (-not $py) {
    Add-Step "Python" "FAIL" "Python nao encontrado. Instale Python 3.11+ e marque 'Add to PATH'."
    $script:results.python = $null
} else {
    Add-Step "Python" "PASS" ("{0} ({1})" -f $py.version, $py.exe)
    $script:results.python = $py.version
}

$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if ($py -and -not (Test-Path $venvPy)) {
    Write-Host "Criando venv..." -ForegroundColor DarkGray
    & $py.exe @($py.pre) -m venv .venv | Out-Null
}
if (Test-Path $venvPy) {
    Add-Step "venv" "PASS" $venvPy
    $req = Join-Path $root "requirements-desktop.txt"
    if (Test-Path $req) {
        Write-Host "Instalando dependencias (requirements-desktop.txt)..." -ForegroundColor DarkGray
        & $venvPy -m pip install --upgrade pip *> $null
        & $venvPy -m pip install -r $req *> $null
        if ($LASTEXITCODE -eq 0) {
            Add-Step "Dependencias" "PASS" "requirements-desktop.txt instalado."
        } else {
            Add-Step "Dependencias" "FAIL" "pip install falhou (codigo $LASTEXITCODE)."
        }
    }
    $venvPytest = Join-Path $root ".venv\Scripts\pytest.exe"
    if (-not (Test-Path $venvPytest)) { & $venvPy -m pip install pytest *> $null }
} else {
    Add-Step "venv" "FAIL" "Nao foi possivel criar .venv."
}

# ---------------------------------------------------------------------------
Section "2. Suite de testes"
# ---------------------------------------------------------------------------
if ($SkipTests) {
    Add-Step "pytest" "SKIP" "Ignorado por -SkipTests."
} elseif (Test-Path $venvPy) {
    Write-Host "Rodando pytest..." -ForegroundColor DarkGray
    $testOut = & $venvPy -m pytest -q 2>&1
    $testOut | Write-Host -ForegroundColor DarkGray
    $line = ($testOut | Select-String -Pattern "passed|failed|error" | Select-Object -Last 1)
    if ($LASTEXITCODE -eq 0) {
        Add-Step "pytest" "PASS" ("$line")
    } else {
        Add-Step "pytest" "FAIL" ("$line (exit $LASTEXITCODE)")
    }
    $script:results.pytest = "$line"
} else {
    Add-Step "pytest" "SKIP" "Sem venv."
}

# ---------------------------------------------------------------------------
Section "3. Diagnostico do agente (selfcheck)"
# ---------------------------------------------------------------------------
if (Test-Path $venvPy) {
    $scJson = Join-Path $root "windows-selfcheck.json"
    & $venvPy -m openhud.agent.selfcheck --json *> $scJson
    if (Test-Path $scJson) {
        try {
            $sc = Get-Content $scJson -Raw | ConvertFrom-Json
            $script:results.selfcheck = $sc.summary
            $summary = "PASS={0} WARNING={1} FAIL={2} NOT INSTALLED={3} NOT PERMITTED={4}" -f `
                $sc.summary.PASS, $sc.summary.WARNING, $sc.summary.FAIL, `
                $sc.summary.'NOT INSTALLED', $sc.summary.'NOT PERMITTED'
            $status = if ($sc.summary.FAIL -gt 0) { "FAIL" } else { "PASS" }
            Add-Step "selfcheck" $status $summary
            Write-Host ("Relatorio: " + $scJson) -ForegroundColor DarkGray
        } catch {
            Add-Step "selfcheck" "WARN" ("Nao foi possivel ler o JSON: " + $_.Exception.Message)
        }
    } else {
        Add-Step "selfcheck" "FAIL" "selfcheck nao produziu saida."
    }
} else {
    Add-Step "selfcheck" "SKIP" "Sem venv."
}

# ---------------------------------------------------------------------------
Section "4. Build dos executaveis"
# ---------------------------------------------------------------------------
if (-not $Build) {
    Add-Step "build exe" "SKIP" "Use -Build para compilar."
} elseif (Test-Path $venvPy) {
    & $venvPy -m pip install pyinstaller *> $null
    $exe1 = Join-Path $root "dist\OpenHUD AI.exe"
    $exe2 = Join-Path $root "dist\openhud-agent.exe"
    Write-Host "Compilando app desktop..." -ForegroundColor DarkGray
    & $venvPy -m openhud.desktop.build 2>&1 | Write-Host -ForegroundColor DarkGray
    $ok1 = Test-Path $exe1
    Write-Host "Compilando agente..." -ForegroundColor DarkGray
    & $venvPy -m openhud.agent.build_exe 2>&1 | Write-Host -ForegroundColor DarkGray
    $ok2 = Test-Path $exe2
    if ($ok1) { Add-Step "dist\OpenHUD AI.exe" "PASS" $exe1 } else { Add-Step "dist\OpenHUD AI.exe" "FAIL" "nao gerado" }
    if ($ok2) { Add-Step "dist\openhud-agent.exe" "PASS" $exe2 } else { Add-Step "dist\openhud-agent.exe" "FAIL" "nao gerado" }
    $script:results.executables = [ordered]@{ desktop = $ok1; agent = $ok2 }
} else {
    Add-Step "build exe" "SKIP" "Sem venv."
}

# ---------------------------------------------------------------------------
Section "5. Instalador (Inno Setup)"
# ---------------------------------------------------------------------------
if (-not $Installer) {
    Add-Step "instalador" "SKIP" "Use -Installer para compilar (precisa Inno Setup 6)."
} else {
    $iscc = Get-Command iscc -ErrorAction SilentlyContinue
    if (-not $iscc) {
        foreach ($p in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
                         "$env:ProgramFiles\Inno Setup 6\ISCC.exe")) {
            if (Test-Path $p) { $iscc = Get-Command $p }
        }
    }
    if (-not $iscc) {
        Add-Step "instalador" "FAIL" "ISCC.exe nao encontrado. Instale Inno Setup 6."
    } else {
        & $iscc.Source "installer\openhud.iss" 2>&1 | Write-Host -ForegroundColor DarkGray
        $setup = Join-Path $root "installer\Output\OpenHUD-AI-Setup.exe"
        if (Test-Path $setup) {
            $size = [math]::Round((Get-Item $setup).Length / 1MB, 1)
            Add-Step "instalador" "PASS" ("{0} ({1} MB)" -f $setup, $size)
            $script:results.installer = [ordered]@{ path = $setup; size_mb = $size }
        } else {
            Add-Step "instalador" "FAIL" "OpenHUD-AI-Setup.exe nao gerado."
        }
    }
}

# ---------------------------------------------------------------------------
Section "6. Auditoria de registro (nada e ativado sozinho)"
# ---------------------------------------------------------------------------
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
try {
    $run = Get-ItemProperty -Path $runKey -ErrorAction SilentlyContinue
    $entries = @()
    if ($run) { $entries = $run.PSObject.Properties | Where-Object { $_.Name -like "*OpenHUD*" } }
    if ($entries.Count -eq 0) {
        Add-Step "Run key" "PASS" "Nenhuma entrada OpenHUD em HKCU Run."
    } else {
        Add-Step "Run key" "WARN" ("Entradas: " + (($entries | ForEach-Object { $_.Name }) -join ", "))
    }
    $script:results.autostart_entries = @($entries | ForEach-Object { $_.Name })
} catch {
    Add-Step "Run key" "WARN" $_.Exception.Message
}

try {
    $svc = Get-Service | Where-Object { $_.Name -like "*OpenHUD*" -or $_.DisplayName -like "*OpenHUD*" }
    if (-not $svc) {
        Add-Step "Servicos" "PASS" "Nenhum servico OpenHUD instalado."
    } else {
        Add-Step "Servicos" "WARN" ("Servicos: " + (($svc | ForEach-Object { $_.Name }) -join ", "))
    }
    $script:results.services = @($svc | ForEach-Object { $_.Name })
} catch {
    Add-Step "Servicos" "WARN" $_.Exception.Message
}

# ---------------------------------------------------------------------------
Section "Resumo"
# ---------------------------------------------------------------------------
$pass = ($script:steps | Where-Object { $_.status -eq "PASS" }).Count
$warn = ($script:steps | Where-Object { $_.status -eq "WARN" }).Count
$fail = ($script:steps | Where-Object { $_.status -eq "FAIL" }).Count
$skip = ($script:steps | Where-Object { $_.status -eq "SKIP" }).Count
Write-Host ("PASS={0} WARN={1} FAIL={2} SKIP={3}" -f $pass, $warn, $fail, $skip)

$script:results.steps = $script:steps
$script:results.totals = [ordered]@{ pass = $pass; warn = $warn; fail = $fail; skip = $skip }
$script:results.generated_at = (Get-Date).ToUniversalTime().ToString("o")

$reportPath = Join-Path $root "windows-test-report.json"
$script:results | ConvertTo-Json -Depth 6 | Set-Content -Path $reportPath -Encoding UTF8
Write-Host ("Relatorio salvo em: " + $reportPath) -ForegroundColor Cyan

if ($fail -gt 0) { exit 1 } else { exit 0 }
