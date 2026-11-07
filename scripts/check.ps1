# Checks against the free market data provider (no accounts or keys needed).
#   .\scripts\check.ps1                          provider, market session, labeled quotes for SPY and AAPL
#   .\scripts\check.ps1 check TSLA NVDA          same, for other symbols
#   .\scripts\check.ps1 bars TSLA --timeframe 5Min --days 2
#   .\scripts\check.ps1 stream SPY AAPL --seconds 30
#   .\scripts\check.ps1 stream BTC-USD --seconds 20    crypto trades 24/7, so this proves streaming on weekends
. "$PSScriptRoot\_common.ps1"
Assert-Venv
$cliArgs = if ($args.Count -gt 0) { $args } else { @("check") }
Push-Location $Backend
try { & $Py -m app.cli @cliArgs } finally { Pop-Location }
