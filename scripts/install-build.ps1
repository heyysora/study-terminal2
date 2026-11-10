# Build half of the one-click install (run by install-app.ps1, which logs everything this prints).
# Checks dependencies, installs only the ones that are missing, then builds and self-tests the app.
# Touches only this project folder (backend\.venv, build\, dist\, dist-installer\, frontend\) and, if they're
# missing, installs Python / Inno Setup with winget. It never touches your data in %LOCALAPPDATA%\StudyTerminal
# or the installed program.
$ErrorActionPreference = "Stop"
$env:ST_ONE_CLICK = "1"

function Update-PathFromRegistry {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

function Install-WithWinget($id, $label) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "$label is missing and winget isn't available to install it. Install $label yourself, then run the installer again."
    }
    Write-Host "  $label not found. Installing it with winget (package $id; winget checks the download's hash)..."
    $ErrorActionPreference = "Continue"
    winget install -e --id $id --silent --accept-package-agreements --accept-source-agreements
    $code = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    Write-Host "  winget exit code: $code"
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
        if ($LASTEXITCODE -eq 0 -and $v -and [int]("$v".Trim()) -ge 311) { Write-Host "  Python found: $exe $rest ($v)"; return $true }
    }
    return $false
}

function Find-InnoSetup {
    @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
}

try {
    Write-Host "`n[1/5] Checking Python and Inno Setup"
    if (-not (Test-Python)) {
        Install-WithWinget "Python.Python.3.12" "Python 3.12"
        if (-not (Test-Python)) { throw "Python was installed but Windows hasn't picked it up yet. Restart your PC, then run the installer again." }
    }
    $iscc = Find-InnoSetup
    if (-not $iscc) {
        Install-WithWinget "JRSoftware.InnoSetup" "Inno Setup 6"
        $iscc = Find-InnoSetup
        if (-not $iscc) { throw "Inno Setup didn't install. Run 'winget install JRSoftware.InnoSetup' yourself, then try again." }
    }
    Write-Host "  Inno Setup found: $iscc"

    Write-Host "`n[2/5] Python packages (only missing or outdated ones are downloaded)"
    & (Join-Path $PSScriptRoot "setup.ps1")

    Write-Host "`n[3/5] Building the app and its installer, then self-testing it (the longest step)"
    & (Join-Path $PSScriptRoot "build-installer.ps1")
    exit 0
} catch {
    Write-Host "BUILD FAILED: $($_.Exception.Message)"
    Write-Host "Nothing was installed and your existing Study Terminal (if any) was not touched."
    exit 1
}
