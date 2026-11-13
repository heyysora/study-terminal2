# One-click install. Started by "Install Study Terminal.cmd" in the project folder.
# 1-3. Builds and self-tests the app (scripts\install-build.ps1). Nothing is installed if that fails.
# 4.   Backs up the currently installed program files, runs the installer, and puts the backup back if it fails.
# 5.   Opens the app.
# Your data (%LOCALAPPDATA%\StudyTerminal: journal, paper account, settings, validation evidence, .env) is never
# read, moved or written by this script or the installer. Every line of output goes to install-log.txt.
param(
    # Testing only: skip the build and run this setup program instead (used by the Windows reliability test to prove rollback).
    [string]$SetupExe = ""
)
$ErrorActionPreference = "Stop"
if (-not $env:LOCALAPPDATA -or -not (Test-Path $env:LOCALAPPDATA)) { Write-Host "LOCALAPPDATA isn't set; stopping before doing anything." -ForegroundColor Red; exit 1 }
$Root = Split-Path -Parent $PSScriptRoot
$logPath = Join-Path $Root "install-log.txt"
$setupLogPath = Join-Path $Root "install-setup-log.txt"
$appDir = Join-Path $env:LOCALAPPDATA "Programs\Study Terminal"
$backupDir = Join-Path $env:LOCALAPPDATA "Programs\Study Terminal (previous version backup)"
$dataDir = Join-Path $env:LOCALAPPDATA "StudyTerminal"

$log = New-Object System.IO.StreamWriter($logPath, $false, (New-Object System.Text.UTF8Encoding($false)))  # replaces the previous log
$log.AutoFlush = $true
function Say($msg, $color = "Gray") { Write-Host $msg -ForegroundColor $color; $log.WriteLine($msg) }

$failed = $false
$backedUp = $false
try {
    Say "Study Terminal one-click install - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" "Green"
    Say "Project folder: $Root"
    Say "Program folder: $appDir"
    Say "Your data:      $dataDir (not touched by this script or the installer)"
    Say "Windows: $([Environment]::OSVersion.VersionString); PowerShell $($PSVersionTable.PSVersion)"
    Say "This takes about 5-10 minutes the first time. Leave this window open."

    # ---- steps 1-3: build in a child process so all of its output (pip, PyInstaller, npm, winget) is captured
    if ($SetupExe) { Say "Test run: skipping the build and using $SetupExe" "Yellow" }
    $ErrorActionPreference = "Continue"
    if (-not $SetupExe) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "install-build.ps1") 2>&1 | ForEach-Object {
        $line = "$_"
        Write-Host $line
        $log.WriteLine($line)
    }
    $buildExit = $LASTEXITCODE
    } else { $buildExit = 0 }
    $ErrorActionPreference = "Stop"
    if ($buildExit -ne 0) { throw "The build failed (exit code $buildExit). Nothing was installed." }

    $version = (Select-String -Path (Join-Path $Root "backend\app\config.py") -Pattern '^VERSION = "(.+)"').Matches[0].Groups[1].Value
    $setupExe = if ($SetupExe) { $SetupExe } else { Join-Path $Root "dist-installer\StudyTerminal-Setup-$version.exe" }
    if (-not (Test-Path $setupExe)) { throw "The build finished but $setupExe is missing. Nothing was installed." }

    # ---- step 4: install, with a backup of the current program files
    Say "`n[4/5] Installing Study Terminal $version" "Cyan"
    while (Get-Process -Name "StudyTerminal" -ErrorAction SilentlyContinue) {
        Say "  Study Terminal is open. Quit it from the tray icon (right-click > Quit), then press Enter here." "Yellow"
        [void](Read-Host)
    }
    if (Test-Path (Join-Path $appDir "StudyTerminal.exe")) {
        Say "  Backing up the installed program files to: $backupDir"
        & robocopy.exe $appDir $backupDir /MIR /R:1 /W:1 /NP /NFL /NDL /NJH /NJS | ForEach-Object { $log.WriteLine("  robocopy: $_") }
        if ($LASTEXITCODE -ge 8) { throw "Couldn't back up the current program files (robocopy exit $LASTEXITCODE). Nothing was installed." }
        $backedUp = $true
    } else {
        Say "  No existing installation found (fresh install)."
    }
    Say "  Running $setupExe (silent; its own log: $setupLogPath)"
    $p = Start-Process -FilePath $setupExe -Wait -PassThru -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
        '/MERGETASKS="desktopicon"', "/LOG=`"$setupLogPath`""
    if (Test-Path $setupLogPath) { Get-Content $setupLogPath | ForEach-Object { $log.WriteLine("  setup: $_") } }
    $app = Join-Path $appDir "StudyTerminal.exe"
    if ($p.ExitCode -ne 0) { throw "The installer exited with code $($p.ExitCode)." }
    if (-not (Test-Path $app)) { throw "The installer finished but $app is missing." }
    if ($backedUp) {
        Remove-Item -LiteralPath $backupDir -Recurse -Force -ErrorAction SilentlyContinue
        Say "  Installed. Removed the program-files backup (your data was never part of it)."
    }

    # ---- step 5
    Say "`n[5/5] Opening Study Terminal" "Cyan"
    Start-Process -FilePath $app
    Say "`nDone. Study Terminal $version is installed." "Green"
    Say "Open it any time from the desktop shortcut or the Start menu (type 'Study Terminal')."
    Say "To reinstall without rebuilding, keep: $setupExe"
} catch {
    $failed = $true
    Say "`nInstall stopped: $($_.Exception.Message)" "Red"
    if ($backedUp) {
        Say "  Restoring the previous program files from the backup..." "Yellow"
        & robocopy.exe $backupDir $appDir /MIR /R:2 /W:2 /NP /NFL /NDL /NJH /NJS | ForEach-Object { $log.WriteLine("  robocopy: $_") }
        if ($LASTEXITCODE -lt 8) {
            Say "  Previous version restored. The backup is kept at $backupDir until the next successful install." "Yellow"
        } else {
            Say "  Restore failed (robocopy exit $LASTEXITCODE). Your previous program files are still in $backupDir." "Red"
        }
    }
    Say "Your data in $dataDir was not touched."
    Say "The full log is in $logPath"
} finally {
    $log.Close()
}
if ($failed) { exit 1 } else { exit 0 }
