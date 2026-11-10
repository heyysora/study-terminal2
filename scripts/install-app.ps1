# One-click install. Started by "Install Study Terminal.cmd" in the project folder.
# Builds Study Terminal from this folder and installs it like a normal Windows app
# (Start menu entry, desktop shortcut, uninstall from Windows Settings > Apps).
# Run it again after unzipping a new version to update. Your data is kept.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$log = Join-Path $Root "install-log.txt"
try { Start-Transcript -Path $log -Force | Out-Null } catch { }
$env:ST_ONE_CLICK = "1"
$failed = $false

function Step($n, $text) { Write-Host "`n[$n/5] $text" -ForegroundColor Cyan }

function Update-PathFromRegistry {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

function Install-WithWinget($id, $label) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "$label is missing and winget isn't available to install it. Install $label yourself, then double-click the installer again."
    }
    Write-Host "  Installing $label (a few minutes)..."
    $ErrorActionPreference = "Continue"
    winget install -e --id $id --silent --accept-package-agreements --accept-source-agreements
    $ErrorActionPreference = "Stop"
    Update-PathFromRegistry
}

function Test-Python {
    # The Microsoft Store "python" shortcut exists but fails; it's skipped by the exit-code check.
    $ErrorActionPreference = "Continue"
    foreach ($cand in @(@("py", "-3.13"), @("py", "-3.12"), @("py", "-3.11"), @("python"))) {
        $exe = $cand[0]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $rest = @($cand | Select-Object -Skip 1)
        $v = $null
        try { $v = & $exe @rest -c "import sys; print(sys.version_info[0] * 100 + sys.version_info[1])" 2>$null } catch { continue }
        if ($LASTEXITCODE -eq 0 -and $v -and [int]("$v".Trim()) -ge 311) { return $true }
    }
    return $false
}

function Find-InnoSetup {
    @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
}

try {
    Write-Host "Study Terminal one-click install" -ForegroundColor Green
    Write-Host "This takes about 5-10 minutes the first time. Leave this window open."

    Step 1 "Checking Python and Inno Setup"
    if (-not (Test-Python)) {
        Install-WithWinget "Python.Python.3.12" "Python 3.12"
        if (-not (Test-Python)) { throw "Python was installed but Windows hasn't picked it up yet. Restart your PC, then double-click the installer again." }
    }
    Write-Host "  Python OK"
    if (-not (Find-InnoSetup)) {
        Install-WithWinget "JRSoftware.InnoSetup" "Inno Setup 6"
        if (-not (Find-InnoSetup)) { throw "Inno Setup didn't install. Run 'winget install JRSoftware.InnoSetup' yourself, then try again." }
    }
    Write-Host "  Inno Setup OK"

    Step 2 "Installing the app's Python packages"
    & (Join-Path $PSScriptRoot "setup.ps1")

    Step 3 "Building the app and its installer (the longest step)"
    & (Join-Path $PSScriptRoot "build-installer.ps1")
    $version = (Select-String -Path (Join-Path $Root "backend\app\config.py") -Pattern '^VERSION = "(.+)"').Matches[0].Groups[1].Value
    $setupExe = Join-Path $Root "dist-installer\StudyTerminal-Setup-$version.exe"
    if (-not (Test-Path $setupExe)) { throw "The build finished but $setupExe is missing." }

    Step 4 "Installing Study Terminal $version"
    while (Get-Process -Name "StudyTerminal" -ErrorAction SilentlyContinue) {
        Write-Host "  Study Terminal is open. Quit it from the tray icon (right-click > Quit), then press Enter here." -ForegroundColor Yellow
        [void](Read-Host)
    }
    $p = Start-Process -FilePath $setupExe -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", '/MERGETASKS="desktopicon"' -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "The installer exited with code $($p.ExitCode)." }

    Step 5 "Opening Study Terminal"
    $app = Join-Path $env:LOCALAPPDATA "Programs\Study Terminal\StudyTerminal.exe"
    if (-not (Test-Path $app)) { throw "Installed, but $app wasn't found." }
    Start-Process -FilePath $app
    Write-Host "`nDone. Study Terminal $version is installed." -ForegroundColor Green
    Write-Host "Open it any time from the desktop shortcut or the Start menu (type 'Study Terminal')."
    Write-Host "To share or reinstall without rebuilding, keep: $setupExe"
} catch {
    $failed = $true
    Write-Host "`nInstall stopped: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "The full log is in $log"
} finally {
    try { Stop-Transcript | Out-Null } catch { }
}
if ($failed) { exit 1 } else { exit 0 }
