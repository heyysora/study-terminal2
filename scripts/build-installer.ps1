# Builds the Windows installer:  dist-installer\StudyTerminal-Setup-<version>.exe
#   1. installs PyInstaller into the project's Python environment
#   2. builds the web UI (if Node.js is installed; otherwise uses the prebuilt frontend\dist)
#   3. packages the app with PyInstaller into dist\StudyTerminal\
#   4. runs the packaged app's self-test (starts the backend, checks health, shuts down cleanly)
#   5. compiles the installer with Inno Setup 6 (free). If it's missing:  winget install JRSoftware.InnoSetup
. "$PSScriptRoot\_common.ps1"
Assert-Venv
$version = (Select-String -Path (Join-Path $Backend "app\config.py") -Pattern '^VERSION = "(.+)"').Matches[0].Groups[1].Value
Write-Host "Building Study Terminal $version" -ForegroundColor Cyan

Write-Host "[1/5] PyInstaller" -ForegroundColor Cyan
& $Py -m pip install --quiet "pyinstaller>=6.10,<7"; Assert-Ok "pip install pyinstaller"

Write-Host "[2/5] Web UI" -ForegroundColor Cyan
$frontend = Join-Path $Root "frontend"
if (Get-Command npm -ErrorAction SilentlyContinue) {
    Push-Location $frontend
    try { npm ci --no-audit --no-fund; Assert-Ok "npm ci"; npm run build; Assert-Ok "npm run build" } finally { Pop-Location }
} elseif (Test-Path (Join-Path $frontend "dist\index.html")) {
    Write-Host "  Node.js not found: using the prebuilt frontend\dist" -ForegroundColor Yellow
} else { throw "frontend\dist is missing and Node.js isn't installed (winget install OpenJS.NodeJS.LTS)" }

Write-Host "[3/5] Packaging (a few minutes)" -ForegroundColor Cyan
Push-Location $Root
try {
    & $Py -m PyInstaller --noconfirm --clean --distpath (Join-Path $Root "dist") --workpath (Join-Path $Root "build") `
        (Join-Path $Root "installer\StudyTerminal.spec")
    Assert-Ok "PyInstaller"
} finally { Pop-Location }
$exe = Join-Path $Root "dist\StudyTerminal\StudyTerminal.exe"
if (-not (Test-Path $exe)) { throw "PyInstaller did not produce $exe" }

Write-Host "[4/5] Self-test of the packaged app" -ForegroundColor Cyan
$env:STUDY_TERMINAL_DATA_DIR = Join-Path $env:TEMP "StudyTerminal-selftest"
$env:PORT = "8799"
$env:STUDY_TERMINAL_NO_ENV_FILE = "1"   # the test run never reads your real .env (settings, credentials)
$p = Start-Process -FilePath $exe -ArgumentList "--self-test" -Wait -PassThru -NoNewWindow
Remove-Item Env:STUDY_TERMINAL_DATA_DIR, Env:PORT, Env:STUDY_TERMINAL_NO_ENV_FILE
if ($p.ExitCode -ne 0) { throw "Packaged app self-test failed (exit $($p.ExitCode)). See $env:TEMP\StudyTerminal-selftest\logs" }
Write-Host "  self-test passed" -ForegroundColor Green

Write-Host "[5/5] Installer" -ForegroundColor Cyan
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found. Install it (free):  winget install JRSoftware.InnoSetup   then run this again." }
& $iscc "/DAppVersion=$version" (Join-Path $Root "installer\StudyTerminal.iss"); Assert-Ok "Inno Setup"
$out = Join-Path $Root "dist-installer\StudyTerminal-Setup-$version.exe"
Write-Host "Done: $out" -ForegroundColor Green
