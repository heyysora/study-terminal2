# Study Terminal — real-PC acceptance test.
#
# Answers one question that no build machine and no saved screenshot can: does the Study Terminal installed on THIS
# computer read YOUR TopstepX chart in Microsoft Edge, right now, correctly?
#
# Run it from anywhere:   powershell -ExecutionPolicy Bypass -File scripts\acceptance-test.ps1
# Or, if you only have the installed app:   & "$env:LOCALAPPDATA\Programs\StudyTerminal\StudyTerminal.exe" --acceptance
#
# What it does NOT do: it never clicks, types into, or sends anything to TopstepX. It reads pixels. Nothing here can
# place, change or cancel an order, and the app has no code that could.
#
# Part 1 runs on its own and needs nothing from you.
# Part 2 asks you to change something on screen (resize, switch tab, change timeframe...) and checks that Study
# Terminal notices. Press Enter when you have done each one; type s to skip one, or q to stop.
param(
    [switch]$SkipScenarios,          # part 1 only
    [string]$Exe                     # path to StudyTerminal.exe, if it isn't where it usually is
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Find-Exe {
    if ($Exe -and (Test-Path $Exe)) { return $Exe }
    $guesses = @(
        "$env:LOCALAPPDATA\Programs\StudyTerminal\StudyTerminal.exe",
        "$env:ProgramFiles\StudyTerminal\StudyTerminal.exe",
        "${env:ProgramFiles(x86)}\StudyTerminal\StudyTerminal.exe"
    )
    foreach ($g in $guesses) { if (Test-Path $g) { return $g } }
    $lnk = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Study Terminal.lnk"
    if (Test-Path $lnk) {
        $sh = New-Object -ComObject WScript.Shell
        $t = $sh.CreateShortcut($lnk).TargetPath
        if ($t -and (Test-Path $t)) { return $t }
    }
    return $null
}

$exePath = Find-Exe
if (-not $exePath) {
    Write-Host "Couldn't find StudyTerminal.exe." -ForegroundColor Red
    Write-Host "Install Study Terminal first, or pass the path:  -Exe 'C:\path\to\StudyTerminal.exe'"
    exit 2
}
Write-Host "Study Terminal: $exePath" -ForegroundColor Cyan

# --- is it running? the test talks to the running app, it does not start a second copy -------------------------------
$running = Get-Process -Name "StudyTerminal" -ErrorAction SilentlyContinue
if (-not $running) {
    Write-Host ""
    Write-Host "Study Terminal isn't running. Start it, wait for the window, then run this again." -ForegroundColor Yellow
    Write-Host "(The test checks the app as you actually use it, so it needs the real one running.)"
    exit 2
}

Write-Host ""
Write-Host "Before part 1, please make sure:" -ForegroundColor Cyan
Write-Host "  * Microsoft Edge is open with your TopstepX chart, on the chart's own tab (not minimised)."
Write-Host "  * You have set up a chart in Study Terminal (My chart > Set up a chart)."
Write-Host "  * Monitoring is running, if you want the live timing numbers too."
Write-Host ""
Read-Host "Press Enter when that's true"

# --- part 1: the twelve checks ---------------------------------------------------------------------------------------
Write-Host ""
Write-Host "=== PART 1: the pipeline, end to end ===" -ForegroundColor Green
Write-Host ""
& $exePath --acceptance
$code = $LASTEXITCODE
$reportDir = Join-Path $env:LOCALAPPDATA "StudyTerminal\acceptance"
Write-Host ""
if ($code -eq 0) {
    Write-Host "PART 1 PASSED: your real chart was read and what it read checks out." -ForegroundColor Green
} else {
    Write-Host "PART 1 DID NOT PASS. The report says which stage and why." -ForegroundColor Yellow
}
Write-Host "Reports: $reportDir"

if ($SkipScenarios) { exit $code }

# --- part 2: the things only you can do -------------------------------------------------------------------------------
$scenarios = @(
    @{ n = "Chart visible, nothing touched"; do = "Leave everything as it is."; expect = "My chart keeps reading: a price that moves and a recent time." }
    @{ n = "Resize the browser"; do  = "Drag the Edge window to a clearly different size, then wait ~10 seconds."; expect = "Study Terminal should say the layout changed and ask you to set the region again, OR carry on reading correctly. It must not keep reporting prices from the old layout as if nothing happened." }
    @{ n = "Switch to another tab"; do = "Click a different tab in the same Edge window, wait ~10 seconds."; expect = "It should say the browser is showing a different tab and stop reading. Nothing else on your screen is captured." }
    @{ n = "Back to the chart tab"; do = "Click back onto the TopstepX tab, wait ~10 seconds."; expect = "Reading resumes by itself. You should not have to press anything." }
    @{ n = "Minimise and restore"; do = "Minimise Edge, wait ~10 seconds, then restore it."; expect = "While minimised it should say so (a minimised window cannot be captured). After restoring, reading resumes." }
    @{ n = "Change the timeframe"; do = "Change the chart's timeframe in TopstepX (1 minute to 5, say), wait ~15 seconds."; expect = "Within about 8 seconds it should pick up the new timeframe, or say the chart no longer matches its setup. It must NOT keep showing the old timeframe indefinitely." }
    @{ n = "Change the instrument"; do = "Switch the chart to a different contract (NQ to ES, say), wait ~10 seconds."; expect = "It should notice almost immediately (the tab's name carries the contract) and either follow it or say the chart doesn't match its setup. It must never label one market's prices as another's." }
    @{ n = "Pull the network"; do = "Turn Wi-Fi off for ~20 seconds, then back on. (TopstepX will stop updating.)"; expect = "Study Terminal should notice the chart has stopped moving and say so, rather than quietly showing the last price as if it were current." }
    @{ n = "Restart Study Terminal"; do = "Close Study Terminal from the tray and start it again. Wait for it to settle."; expect = "Your chart setup, history and practice money are all still there, and monitoring picks up again." }
    @{ n = "Leave it in the background"; do = "Close the Study Terminal window to the tray, use your PC normally for a few minutes, then reopen it."; expect = "It kept reading the whole time: the history has entries from while it was hidden, with no gap it doesn't explain." }
)

Write-Host ""
Write-Host "=== PART 2: the things only you can do ===" -ForegroundColor Green
Write-Host "For each one: do the thing, watch Study Terminal's My chart page, then say whether it did what it should."
Write-Host "Enter = it behaved as expected · n = it did not · s = skip · q = stop here"
Write-Host ""

$results = @()
foreach ($s in $scenarios) {
    Write-Host ("-" * 78)
    Write-Host $s.n -ForegroundColor Cyan
    Write-Host "  Do this:    $($s.do)"
    Write-Host "  Expect:     $($s.expect)"
    $a = Read-Host "  Result [Enter=ok / n=not ok / s=skip / q=quit]"
    switch ($a.ToLower()) {
        ""  { $results += @{ scenario = $s.n; result = "PASS"; note = "" } }
        "n" {
            $why = Read-Host "  What did it do instead?"
            $results += @{ scenario = $s.n; result = "FAIL"; note = $why }
        }
        "s" { $results += @{ scenario = $s.n; result = "SKIPPED"; note = "" } }
        "q" { break }
        default { $results += @{ scenario = $s.n; result = "PASS"; note = $a } }
    }
}

# --- write part 2 alongside part 1's report ---------------------------------------------------------------------------
New-Item -ItemType Directory -Force $reportDir | Out-Null
$stamp = Get-Date -Format "yyyyMMddTHHmmss"
$out = Join-Path $reportDir "scenarios-$stamp.md"
$lines = @("# Real-PC scenarios — $(Get-Date -Format 'yyyy-MM-dd HH:mm')", "",
    "Machine: $env:COMPUTERNAME · Windows $([Environment]::OSVersion.Version)", "",
    "| Scenario | Result | Note |", "|---|---|---|")
foreach ($r in $results) { $lines += "| $($r.scenario) | **$($r.result)** | $($r.note -replace '\|', '/') |" }
$fails = @($results | Where-Object { $_.result -eq "FAIL" }).Count
$lines += @("", "$fails of $($results.Count) scenarios failed.")
if ($fails -gt 0) {
    $lines += @("", "Send this file and the newest acceptance-*.md in the same folder; the failures above are what to fix next.")
}
$lines -join "`n" | Set-Content $out -Encoding UTF8

Write-Host ""
Write-Host ("=" * 78)
Write-Host "Part 1: $(if ($code -eq 0) { 'PASSED' } else { 'did not pass' })"
Write-Host "Part 2: $($results.Count) scenarios run, $fails failed"
Write-Host "Reports in: $reportDir"
Write-Host "  - acceptance-*.md   (part 1, with the evidence)"
Write-Host "  - scenarios-$stamp.md (part 2)"
Write-Host "  - capture.png       (the picture it actually read)"
if ($code -ne 0 -or $fails -gt 0) { exit 1 }
exit 0
