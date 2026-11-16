# Runs the dictation app silently every time you sign in to Windows.
# Usage (PowerShell, no admin needed):   .\install_startup.ps1
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$py  = Join-Path $dir "Jarvis-v1\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { Write-Host "Run setup.ps1 first (see README): $py not found"; exit 1 }

$lnk = Join-Path ([Environment]::GetFolderPath("Startup")) "LocalVoiceDictation.lnk"
$ws  = New-Object -ComObject WScript.Shell
$s   = $ws.CreateShortcut($lnk)
$s.TargetPath       = $py
$s.Arguments        = '"' + (Join-Path $dir "app.py") + '"'
$s.WorkingDirectory = $dir
$s.WindowStyle      = 7
$s.Description      = "Local voice dictation"
$s.Save()
Write-Host "Installed: $lnk"
Write-Host "It will start at next sign-in. Start it now with:  & '$py' '$dir\app.py'"
