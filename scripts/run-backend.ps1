# Starts the backend API on http://127.0.0.1:8765 (docs at /docs). Ctrl+C to stop.
. "$PSScriptRoot\_common.ps1"
Assert-Venv
Push-Location $Backend
try { & $Py -m uvicorn app.main:app --host 127.0.0.1 --port 8765 } finally { Pop-Location }
