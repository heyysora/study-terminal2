# Measure the screen copilot on your own screenshots (nothing is uploaded anywhere).
# Put screenshots in a folder, named  platform_SYMBOL_interval_price.png , e.g.
#   webull_AAPL_5m_342.37.png   thinkorswim_TSLA_15m_358.20.png   ibkr_SPY_1h_735.29.png   tradingview_NVDA_D_186.64.png
# (price = the real last price when you took it; leave it off if you don't know it). Then:
#   .\scripts\screen-eval.ps1 C:\path\to\folder
param([Parameter(Mandatory = $true)][string]$Folder)
. "$PSScriptRoot\_common.ps1"
Assert-Venv
if (-not (Test-Path $Folder)) { throw "Folder not found: $Folder" }
Push-Location $Backend
try { & $Py -m research.screen_eval $Folder --out (Join-Path $Folder "screen_eval_results.json"); Assert-Ok "Screen evaluation" }
finally { Pop-Location }
