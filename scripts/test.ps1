# Runs the automated test suite. No API keys or internet needed.
. "$PSScriptRoot\_common.ps1"
Assert-Venv
Push-Location $Backend
try { & $Py -m pytest @args; Assert-Ok "Tests" } finally { Pop-Location }
