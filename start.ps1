param(
    [string]$ListenHost = "0.0.0.0",
    [int]$Port = 8015,
    [switch]$ForceInstall,
    [switch]$Reload
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$venv = Join-Path $backend ".venv"

Set-Location $backend

if (-not (Test-Path -LiteralPath $venv)) {
    python -m venv .venv
}

$python = Join-Path $venv "Scripts\\python.exe"
$pip = Join-Path $venv "Scripts\\pip.exe"
$tesseractExe = "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
$localTessData = Join-Path $backend "tessdata"
$requirementsPath = Join-Path $backend "requirements.txt"
$statePath = Join-Path $backend ".deps_state"

if (Test-Path -LiteralPath $tesseractExe) {
    $env:TESSERACT_CMD = $tesseractExe
}

if (Test-Path -LiteralPath $localTessData) {
    $env:TESSDATA_PREFIX = $localTessData
}

if (-not $env:OCR_LANG) {
    $env:OCR_LANG = "tur+eng"
}

$reqHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $requirementsPath).Hash
$needInstall = $true
if ((-not $ForceInstall) -and (Test-Path -LiteralPath $statePath)) {
    $saved = (Get-Content -LiteralPath $statePath -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($saved -eq $reqHash) {
        $needInstall = $false
    }
}

if ($needInstall) {
    & $python -m pip install --upgrade pip
    & $pip install -r requirements.txt
    Set-Content -LiteralPath $statePath -Value $reqHash -Encoding ascii
}

$uvicornArgs = @('-m', 'uvicorn', 'main:app', '--host', $ListenHost, '--port', "$Port")
if ($Reload) {
    $uvicornArgs += '--reload'
}

& $python @uvicornArgs
