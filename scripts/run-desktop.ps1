# Starts the Study Terminal desktop app: native window + system tray. Closing the window keeps monitoring in the tray.
. "$PSScriptRoot\_common.ps1"
Assert-Venv
$Pyw = Join-Path $Venv "Scripts\pythonw.exe"
$exe = if (Test-Path $Pyw) { $Pyw } else { $Py }
Start-Process -FilePath $exe -ArgumentList "`"$(Join-Path $Root 'desktop\launcher.py')`"" -WorkingDirectory $Root
Write-Host "Study Terminal is starting (window + tray icon). Ctrl+Alt+S brings the window back." -ForegroundColor Green
