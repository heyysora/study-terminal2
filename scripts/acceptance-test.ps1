# Does Study Terminal work on THIS PC, with THIS Edge window and THIS TopstepX chart?
#
#   1. Open your TopstepX chart in Microsoft Edge and leave that tab in front (don't minimise the window).
#   2. Start Study Terminal and leave it running.
#   3. Run this:   .\scripts\acceptance-test.ps1
#
# It reads your chart and times each stage. It never clicks, types, or touches a TopstepX control, and it never
# places an order -- Study Terminal has no code that can.
#
# The report lands in %LOCALAPPDATA%\StudyTerminal\logs\acceptance-<timestamp>.md (and .json), with a picture of
# what the app actually saw saved next to it.
param(
    [string]$Exe = "",          # the installed StudyTerminal.exe; found automatically if you don't pass it
    [switch]$FromSource         # run from this checkout instead of the installed app
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

if ($FromSource) {
    $py = Join-Path $Root "backend\.venv\Scripts\python.exe"
    if (-not (Test-Path $py)) { throw "No virtual environment yet. Run .\scripts\setup.ps1 first." }
    & $py (Join-Path $Root "desktop\acceptance.py")
    exit $LASTEXITCODE
}

if (-not $Exe) {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\StudyTerminal\StudyTerminal.exe"),
        (Join-Path $env:LOCALAPPDATA "StudyTerminal\StudyTerminal.exe"),
        (Join-Path ${env:ProgramFiles} "StudyTerminal\StudyTerminal.exe"),
        (Join-Path $Root "dist\StudyTerminal\StudyTerminal.exe")
    )
    $Exe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Exe) {
    Write-Host "Couldn't find StudyTerminal.exe. Pass it: .\scripts\acceptance-test.ps1 -Exe 'C:\path\to\StudyTerminal.exe'"
    Write-Host "Or test this source checkout instead:   .\scripts\acceptance-test.ps1 -FromSource"
    exit 2
}
Write-Host "Testing the installed app: $Exe`n"
& $Exe --acceptance
exit $LASTEXITCODE
