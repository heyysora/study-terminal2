# Windows reliability checks for a freshly built installer. Run by GitHub Actions on a clean Windows machine
# (.github/workflows/build-windows.yml, job "reliability"); can also be run by hand on a spare Windows PC.
# It installs and uninstalls Study Terminal for the current user and uses throwaway data folders under %TEMP%.
# Your real data folder (%LOCALAPPDATA%\StudyTerminal) is only touched by the uninstall check, which first proves the folder
# exists with a marker file and then checks it is still there afterwards. Don't run this on a PC whose real data you need.
param(
    [Parameter(Mandatory = $true)][string]$NewInstaller,
    [string]$Previous = "v0.13.1"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Out = Join-Path $Root "reliability-out"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$Prog = Join-Path $env:LOCALAPPDATA "Programs\Study Terminal"
$Exe = Join-Path $Prog "StudyTerminal.exe"
$Results = New-Object System.Collections.ArrayList

function Record($name, $outcome, $detail) {
    [void]$Results.Add([ordered]@{ check = $name; outcome = $outcome; detail = "$detail" })
    $color = @{ pass = "Green"; fail = "Red"; observed = "Yellow" }[$outcome]
    Write-Host ("[{0}] {1}: {2}" -f $outcome.ToUpper(), $name, $detail) -ForegroundColor $color
}

function Install($installer, $tag) {
    $log = Join-Path $Out "setup-$tag.log"
    $p = Start-Process -FilePath $installer -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=`"$log`"" -PassThru
    if (-not $p.WaitForExit(600000)) { $p.Kill(); return 999 }
    return $p.ExitCode
}

function SelfTest($dataDir, $tag, [hashtable]$extraEnv = @{}) {
    $env:STUDY_TERMINAL_DATA_DIR = $dataDir
    $env:STUDY_TERMINAL_NO_ENV_FILE = "1"
    $env:PORT = "8811"
    foreach ($k in $extraEnv.Keys) { Set-Item -Path "Env:$k" -Value $extraEnv[$k] }
    $so = Join-Path $Out "selftest-$tag.out.txt"; $se = Join-Path $Out "selftest-$tag.err.txt"
    $t = [Diagnostics.Stopwatch]::StartNew()
    $p = Start-Process -FilePath $Exe -ArgumentList "--self-test" -PassThru -NoNewWindow -RedirectStandardOutput $so -RedirectStandardError $se
    $done = $p.WaitForExit(240000)
    if (-not $done) { $p.Kill() }
    $t.Stop()
    foreach ($k in @("STUDY_TERMINAL_DATA_DIR", "STUDY_TERMINAL_NO_ENV_FILE", "PORT") + @($extraEnv.Keys)) { Remove-Item -Path "Env:$k" -ErrorAction SilentlyContinue }
    $text = (Get-Content $so -Raw -ErrorAction SilentlyContinue) + (Get-Content $se -Raw -ErrorAction SilentlyContinue)
    return @{ exit = $(if ($done) { $p.ExitCode } else { 999 }); seconds = [math]::Round($t.Elapsed.TotalSeconds, 1); text = "$text" }
}

$py = (Get-Command python).Source
function Py($cwd, [string[]]$pyArgs) {
    Push-Location $cwd
    try { $env:PYTHONPATH = $cwd; & $py @pyArgs 2>&1 | ForEach-Object { "$_" } ; return $LASTEXITCODE } finally { Pop-Location; Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
}

$version = (Select-String -Path (Join-Path $Root "backend\app\config.py") -Pattern '^VERSION = "(.+)"').Matches[0].Groups[1].Value
Write-Host "Windows reliability checks for Study Terminal $version on $([Environment]::OSVersion.VersionString)"

# ---------------------------------------------------------------- 1. fresh install
$code = Install $NewInstaller "fresh"
if ($code -eq 0 -and (Test-Path $Exe)) { Record "Fresh install" "pass" "Installed to $Prog (exit 0)." }
else { Record "Fresh install" "fail" "Setup exit code $code; StudyTerminal.exe present: $(Test-Path $Exe)" }

# ---------------------------------------------------------------- 2. startup, clean shutdown, logs, secrets
$fresh = Join-Path $env:TEMP "st-rel-fresh"
Remove-Item $fresh -Recurse -Force -ErrorAction SilentlyContinue
$planted = "PLANTED-SECRET-" + [guid]::NewGuid().ToString("N").Substring(0, 12)
$r = SelfTest $fresh "fresh" @{ STUDY_PROJECTX_API_KEY = $planted; ANTHROPIC_API_KEY = $planted }
$ok = $r.exit -eq 0 -and $r.text -match "clean shutdown yes" -and $r.text -match "live locked: True"
Record "Startup and clean shutdown" $(if ($ok) { "pass" } else { "fail" }) "Self-test exit $($r.exit) in $($r.seconds) s. $(($r.text -split "`n" | Select-String 'self-test:') -join ' ')"
$marker = Test-Path (Join-Path $fresh "running.marker")
Record "Clean exit is recorded" $(if (-not $marker) { "pass" } else { "fail" }) "running.marker left behind after a clean exit: $marker"
$logf = Join-Path $fresh "logs\study_terminal.log"
if (Test-Path $logf) {
    $log = Get-Content $logf -Raw
    $hasStart = $log -match "Study Terminal starting"; $hasStop = $log -match "Study Terminal stopped"
    Record "Log file written" $(if ($hasStart -and $hasStop) { "pass" } else { "fail" }) "$logf ($((Get-Item $logf).Length) bytes); start line: $hasStart; stop line: $hasStop"
    Record "No secrets in the log" $(if ($log -notmatch [regex]::Escape($planted)) { "pass" } else { "fail" }) "A planted fake API key was set for this run and searched for in the log."
    Copy-Item $logf (Join-Path $Out "fresh-study_terminal.log")
} else { Record "Log file written" "fail" "No log at $logf" }
$built = Get-Content (Join-Path $fresh "installed_build.txt") -ErrorAction SilentlyContinue
Record "Fresh data folder needs no backup" $(if (-not (Test-Path (Join-Path $fresh "backups"))) { "pass" } else { "fail" }) "installed_build.txt = '$built'"

# ---------------------------------------------------------------- 3. uninstall keeps your data
$realData = Join-Path $env:LOCALAPPDATA "StudyTerminal"
New-Item -ItemType Directory -Force -Path $realData | Out-Null
$keep = Join-Path $realData "reliability-keep-me.txt"; "keep" | Set-Content $keep
$unins = Join-Path $Prog "unins000.exe"
if (Test-Path $unins) {
    $p = Start-Process -FilePath $unins -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -PassThru
    $fin = $p.WaitForExit(180000); Start-Sleep -Seconds 5
    $gone = -not (Test-Path $Exe); $kept = Test-Path $keep
    Record "Uninstall removes the program" $(if ($fin -and $gone) { "pass" } else { "fail" }) "Finished: $fin; program removed: $gone"
    Record "Uninstall keeps your data" $(if ($kept) { "pass" } else { "fail" }) "Data folder marker still there after a silent uninstall: $kept"
} else { Record "Uninstall removes the program" "fail" "No uninstaller at $unins" }
Remove-Item $keep -ErrorAction SilentlyContinue

# ---------------------------------------------------------------- 4. upgrade from the previous release, with data
$up = Join-Path $env:TEMP "st-rel-upgrade"
Remove-Item $up -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $up | Out-Null
$prevDir = Join-Path $Root "prev-installer"
gh release download $Previous -R $env:GITHUB_REPOSITORY -p "*.exe" -D $prevDir --clobber 2>&1 | Out-Null
$prevExe = Get-ChildItem $prevDir -Filter *.exe -ErrorAction SilentlyContinue | Select-Object -First 1
$venvOk = $false
if ($prevExe) {
    $code = Install $prevExe.FullName "previous"
    Record "Install previous release ($Previous)" $(if ($code -eq 0 -and (Test-Path $Exe)) { "pass" } else { "fail" }) "exit $code"
    $r = SelfTest $up "previous"
    Record "Previous release starts" $(if ($r.exit -eq 0) { "pass" } else { "fail" }) "Self-test exit $($r.exit)"
    # seed realistic data with the PREVIOUS version's own code (journal note, practice trades, limits, settings, chart profile)
    git -C $Root worktree add -f (Join-Path $Root "prev-src") $Previous 2>&1 | Out-Null
    & $py -m pip install --quiet -r (Join-Path $Root "backend\requirements.txt") 2>&1 | Out-Null
    $venvOk = $LASTEXITCODE -eq 0
    $seedOut = Py (Join-Path $Root "prev-src\backend") @((Join-Path $Root "backend\research\upgrade_check.py"), "seed", $up, (Join-Path $Out "seed.json"))
    $seedOk = Test-Path (Join-Path $Out "seed.json")
    Record "Seed data with $Previous" $(if ($seedOk) { "pass" } else { "fail" }) (($seedOut | Select-Object -Last 3) -join " ")
    $code = Install $NewInstaller "upgrade"
    $r = SelfTest $up "upgraded"
    $newVer = ($r.text -match "version $([regex]::Escape($version))")
    Record "Upgrade installs over the previous version" $(if ($code -eq 0 -and $r.exit -eq 0 -and $newVer) { "pass" } else { "fail" }) "Setup exit $code; upgraded app self-test exit $($r.exit); reports version $version`: $newVer"
    $bk = Get-ChildItem (Join-Path $up "backups") -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
    Record "Automatic backup before the upgrade" $(if ($bk -and (Test-Path (Join-Path $bk.FullName "study_terminal.db"))) { "pass" } else { "fail" }) "$($bk.Name)"
    $verOut = Py (Join-Path $Root "backend") @((Join-Path $Root "backend\research\upgrade_check.py"), "verify", $up, (Join-Path $Out "verify.json"))
    $cmp = Py (Join-Path $Root "backend") @((Join-Path $Root "backend\research\upgrade_check.py"), "compare", (Join-Path $Out "seed.json"), (Join-Path $Out "verify.json"), $(if ($bk) { $bk.FullName } else { "" }), (Join-Path $Out "compare-upgrade.json"))
    $cmpJson = Get-Content (Join-Path $Out "compare-upgrade.json") -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
    Record "Journal, practice accounts, settings and limits survive the upgrade" $(if ($cmpJson.pass) { "pass" } else { "fail" }) ($cmp -join " ")
    # ------------------------------------------------------------ 5. restore from the automatic backup
    if ($bk) {
        $restored = Join-Path $env:TEMP "st-rel-restored"
        Remove-Item $restored -Recurse -Force -ErrorAction SilentlyContinue
        Copy-Item $bk.FullName $restored -Recurse
        Copy-Item (Join-Path $up "installed_build.txt") $restored
        $r = SelfTest $restored "restored"
        $null = Py (Join-Path $Root "backend") @((Join-Path $Root "backend\research\upgrade_check.py"), "verify", $restored, (Join-Path $Out "verify-restored.json"))
        $cmp2 = Py (Join-Path $Root "backend") @((Join-Path $Root "backend\research\upgrade_check.py"), "compare", (Join-Path $Out "seed.json"), (Join-Path $Out "verify-restored.json"), "", (Join-Path $Out "compare-restored.json"))
        $c2 = Get-Content (Join-Path $Out "compare-restored.json") -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
        Record "Restore from the backup" $(if ($r.exit -eq 0 -and $c2.all_views_same) { "pass" } else { "fail" }) "Restored copy starts (exit $($r.exit)); your data as before: $($c2.all_views_same)"
    }
} else { Record "Install previous release ($Previous)" "fail" "Couldn't download $Previous from the Releases page" }

# ---------------------------------------------------------------- 6. installer rollback after a failed setup
if (Test-Path $Exe) {
    $before = (Get-FileHash $Exe).Hash
    $cs = Join-Path $Out "FailingSetup.cs"
    @"
using System.IO;
class P { static int Main(string[] a) {
  string d = System.Environment.GetEnvironmentVariable("LOCALAPPDATA") + "\\Programs\\Study Terminal";
  File.WriteAllText(Path.Combine(d, "half-installed.tmp"), "partial");
  File.Delete(Path.Combine(d, "StudyTerminal.exe"));
  return 3; } }
"@ | Set-Content $cs
    $csc = Get-ChildItem "$env:WINDIR\Microsoft.NET\Framework64\v4*\csc.exe" | Select-Object -Last 1
    $fail = Join-Path $Out "FailingSetup.exe"
    & $csc.FullName /nologo /out:$fail $cs | Out-Null
    $p = Start-Process powershell.exe -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $Root "scripts\install-app.ps1"), "-SetupExe", $fail -PassThru -Wait -NoNewWindow
    $after = if (Test-Path $Exe) { (Get-FileHash $Exe).Hash } else { "missing" }
    $leftover = Test-Path (Join-Path $Prog "half-installed.tmp")
    $ok = $p.ExitCode -ne 0 -and $after -eq $before -and -not $leftover
    Record "Installer rollback after a failed setup" $(if ($ok) { "pass" } else { "fail" }) "Script exit $($p.ExitCode); program restored byte-for-byte: $($after -eq $before); half-installed file removed: $(-not $leftover)"
    Copy-Item (Join-Path $Root "install-log.txt") (Join-Path $Out "rollback-install-log.txt") -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------- 7. damaged data file: Recovery mode, then a restore
if (Test-Path $up) {
    $bad = Join-Path $env:TEMP "st-rel-damaged"
    Remove-Item $bad -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item $up $bad -Recurse
    $dbPath = Join-Path $bad "study_terminal.db"
    Remove-Item (Join-Path $bad "study_terminal.db-wal"), (Join-Path $bad "study_terminal.db-shm") -ErrorAction SilentlyContinue
    [IO.File]::WriteAllBytes($dbPath, [byte[]](1..4096 | ForEach-Object { 7 }))
    $badHash = (Get-FileHash $dbPath).Hash
    $r = SelfTest $bad "damaged"
    $untouched = (Test-Path $dbPath) -and ((Get-FileHash $dbPath).Hash -eq $badHash)
    $ok = $r.exit -eq 2 -and $r.text -match "recovery mode \(database" -and $untouched
    Record "Damaged data file opens Recovery mode" $(if ($ok) { "pass" } else { "fail" }) "Self-test exit $($r.exit) (2 = Recovery mode) after $($r.seconds) s; damaged file left exactly as it was: $untouched"

    # The Recovery screen's "Use this backup" writes this plan and restarts; here the installed app is started with it.
    $bk = Get-ChildItem (Join-Path $bad "backups") -Directory | Sort-Object Name -Descending | Select-Object -First 1
    if ($bk) {
        @{ action = "restore"; backup = $bk.Name; asked_at = (Get-Date -Format s) } | ConvertTo-Json | Set-Content (Join-Path $bad "pending_recovery.json") -Encoding UTF8
        $r = SelfTest $bad "restore"
        $last = Get-Content (Join-Path $bad "last_recovery.json") -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
        $kept = @(Get-ChildItem (Join-Path $bad "damaged") -Recurse -Filter "study_terminal.db" -ErrorAction SilentlyContinue | Where-Object { (Get-FileHash $_.FullName).Hash -eq $badHash }).Count -gt 0
        $verify = Join-Path $Out "verify-after-restore.json"
        $same = $false
        $chk = Join-Path $Root "backend\research\upgrade_check.py"
        if (Test-Path (Join-Path $Out "seed.json")) {
            [void](Py (Join-Path $Root "backend") @($chk, "verify", $bad, $verify))
            [void](Py (Join-Path $Root "backend") @($chk, "compare", (Join-Path $Out "seed.json"), $verify, "", (Join-Path $Out "compare-after-restore.json")))
            if (Test-Path (Join-Path $Out "compare-after-restore.json")) { $same = (Get-Content (Join-Path $Out "compare-after-restore.json") -Raw | ConvertFrom-Json).all_views_same }
        }
        $ok = $r.exit -eq 0 -and $last.ok -and $kept -and $same
        Record "Restore from Recovery mode" $(if ($ok) { "pass" } else { "fail" }) "Self-test exit $($r.exit); restore result: $($last.detail); damaged file kept in damaged\: $kept; your data views as before the damage: $same"
    } else {
        Record "Restore from Recovery mode" "fail" "No backup was found to restore from."
    }
}

# ---------------------------------------------------------------- 8. our port is taken by another program
$busy = Join-Path $env:TEMP "st-rel-port"
Remove-Item $busy -Recurse -Force -ErrorAction SilentlyContinue
$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 8811)
$listener.Start()
try { $r = SelfTest $busy "port-busy" } finally { $listener.Stop() }
$moved = Select-String -Path (Join-Path $busy "logs\desktop.log") -Pattern "port 8811 is used by another program; using (\d+)" -ErrorAction SilentlyContinue | Select-Object -First 1
$ok = $r.exit -eq 0 -and $moved
Record "Starts when its usual port is taken" $(if ($ok) { "pass" } else { "fail" }) "Self-test exit $($r.exit); $(if ($moved) { $moved.Line.Trim() } else { 'did not move to another port' })"

# ---------------------------------------------------------------- summary
$json = $Results | ConvertTo-Json -Depth 4
$json | Set-Content (Join-Path $Out "results.json")
$fails = @($Results | Where-Object { $_.outcome -eq "fail" }).Count
"# Windows reliability results ($version, $(Get-Date -Format 'yyyy-MM-dd HH:mm'))`n" + (($Results | ForEach-Object { "- **$($_.outcome.ToUpper())** $($_.check): $($_.detail)" }) -join "`n") |
    Set-Content (Join-Path $Out "results.md")
Write-Host "`n$($Results.Count) checks, $fails failed."
git -C $Root worktree remove --force (Join-Path $Root "prev-src") 2>&1 | Out-Null
if ($fails -gt 0) { exit 1 }
