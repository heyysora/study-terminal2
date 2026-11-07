# One-time setup: creates backend\.venv and installs dependencies. No accounts or API keys needed.
# Usage (from the project folder):  powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
. "$PSScriptRoot\_common.ps1"

function Find-Python {
    # Windows PowerShell 5.1 turns redirected stderr into terminating errors under "Stop",
    # and `py -3.13` writes to stderr when 3.13 isn't installed. Probe with "Continue".
    $ErrorActionPreference = "Continue"
    $candidates = @(@("py", "-3.13"), @("py", "-3.12"), @("py", "-3.11"), @("python"))
    foreach ($cand in $candidates) {
        $exe = $cand[0]
        $rest = @($cand | Select-Object -Skip 1)
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $v = $null
        try { $v = & $exe @rest -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null } catch { continue }
        if ($LASTEXITCODE -eq 0 -and $v) {
            $parts = "$v".Trim().Split(".")
            if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 11) { return ,$cand }
        }
    }
    throw "Python 3.11+ not found. Install it from https://www.python.org/downloads/ (check 'Add python.exe to PATH'), then reopen PowerShell."
}

$pyCmd = Find-Python
$exe = $pyCmd[0]; $rest = @($pyCmd | Select-Object -Skip 1)
Write-Host "Using Python: $exe $rest" -ForegroundColor Cyan

if (-not (Test-Path $Py)) {
    & $exe @rest -m venv $Venv; Assert-Ok "Creating virtual environment"
}
& $Py -m pip install --upgrade pip --quiet; Assert-Ok "pip upgrade"
& $Py -m pip install -r (Join-Path $Backend "requirements.txt") -r (Join-Path $Backend "requirements-dev.txt"); Assert-Ok "Installing dependencies"

# No .env is needed: every setting has a default and no keys or accounts are required.
$envFile = Join-Path $Root ".env"
if (Test-Path $envFile) {
    $old = Select-String -Path $envFile -Pattern "^\s*ALPACA_" -Quiet
    if ($old) {
        Write-Host "Your .env still contains ALPACA_ settings. They are ignored now; you can delete those lines." -ForegroundColor Yellow
    }
}
Write-Host "`nSetup complete. Next: .\scripts\test.ps1, then .\scripts\check.ps1, then .\scripts\run-backend.ps1" -ForegroundColor Green
