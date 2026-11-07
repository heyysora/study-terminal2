# Shared helpers for Study Terminal scripts.
$ErrorActionPreference = "Stop"
$Root    = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Venv    = Join-Path $Backend ".venv"
$Py      = Join-Path $Venv "Scripts\python.exe"

function Assert-Ok($what) {
    # PowerShell doesn't stop on failing native commands by itself
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)" }
}

function Assert-Venv {
    if (-not (Test-Path $Py)) { throw "Python environment not found. Run .\scripts\setup.ps1 first." }
}
