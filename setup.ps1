# One-shot setup: creates the Jarvis-v1 virtual environment, installs the requirements and
# downloads the speech-to-text model (~600 MB) and the Piper voice set in config.py.
# Usage (PowerShell, no admin needed):   .\setup.ps1
# If scripts are blocked:                powershell -ExecutionPolicy Bypass -File .\setup.ps1
# Safe to re-run: every step skips what is already there.
$ErrorActionPreference = "Stop"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $dir
$venv = Join-Path $dir "Jarvis-v1"
$py   = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "Creating virtual environment: $venv"
    python -m venv $venv
    if ($LASTEXITCODE -ne 0) { Write-Host "Could not create the venv - is Python installed and on PATH?"; exit 1 }
}

Write-Host "Installing requirements..."
& $py -m pip install --upgrade pip
& $py -m pip install -r (Join-Path $dir "requirements.txt")
if ($LASTEXITCODE -ne 0) { Write-Host "pip install failed - see the messages above."; exit 1 }

Write-Host "Downloading the speech-to-text model..."
& $py (Join-Path $dir "download_model.py")
if ($LASTEXITCODE -ne 0) { Write-Host "Speech model download failed - see the messages above."; exit 1 }

Write-Host "Downloading the Piper voice..."
& $py (Join-Path $dir "download_voice.py")
if ($LASTEXITCODE -ne 0) { Write-Host "Voice download failed - dictation still works; read-aloud needs the voice (or set TTS_ENGINE = `"sapi`" in config.py)." }

Write-Host ""
Write-Host "Setup finished. Start it with:  & '$py' '$dir\app.py'"
