# Removes the start-at-sign-in shortcut.
$lnk = Join-Path ([Environment]::GetFolderPath("Startup")) "LocalVoiceDictation.lnk"
if (Test-Path $lnk) { Remove-Item $lnk; Write-Host "Removed $lnk" } else { Write-Host "Nothing to remove." }
