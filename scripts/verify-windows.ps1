# Checks the Windows-only parts of Study Terminal on this PC (capture, notifications, sound, tray, hotkey,
# WebView2, single instance, clean shutdown) and saves a report to %LOCALAPPDATA%\StudyTerminal\logs\windows-check.json
. "$PSScriptRoot\_common.ps1"
Assert-Venv
& $Py (Join-Path $Root "desktop\verify_windows.py")
