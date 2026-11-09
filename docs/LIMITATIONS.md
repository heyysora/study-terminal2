# Known limitations (0.8.0)

Plain list of what Study Terminal can't do, what wasn't verified, and why. Each item says what would change it.

## Trading and evidence
- **No validated strategy.** Neither the 10 stock setups nor the futures setups show a reliable out-of-sample edge
  ([BACKTEST_RESULTS.md](BACKTEST_RESULTS.md), [BACKTEST_RESULTS_FUTURES.md](BACKTEST_RESULTS_FUTURES.md)). Automated paper trading
  (Mode B) therefore approves nothing. NQ/MNQ were positive but inconclusive (17 holdout trades each).
- **Short history.** Free 5-minute futures history covers about 60 days: one market period, roughly 25 out-of-sample trading days.
  Continuous series include a roll inside the window.
- **Live execution is locked** and not implemented. It needs your written authorization, written confirmation from Topstep that
  your account type may trade through the API, and order testing on a Practice account.

## Data
- **Futures data is delayed by default.** Yahoo reports about 10 minutes on CME futures. Without the paid TopstepX API there are no
  live futures signals, no automated entries and no live fills (replay and labelled delayed practice still work).
- **TopstepX live streaming (0.8.0) was tested only against a local mock hub.** It has never received real TopstepX market data. The
  list of what to verify with a real account is in [LIVE_MARKET_DATA.md](LIVE_MARKET_DATA.md#what-still-needs-a-real-topstepx-account).
  REST calls were also tested against mocks only. Market depth and the user hub aren't used.
- Candles are built from the trade prints the stream delivers; volume parity with TopstepX's own charts is unverified. Bars aren't
  back-adjusted across contract rolls.
- Yahoo endpoints are unofficial and can change or break.
- Holiday hours come from exchange_calendars, not CME's holiday notices.

## Economic calendar
- The calendar lists FOMC, BEA (GDP, PCE) and BLS (CPI, PPI, jobs) releases. **Retail sales (Census) and jobless claims (DOL) aren't
  on it.** Published values come from BLS only (CPI, core CPI, PPI, payrolls, unemployment); BEA releases show dates without
  figures. No consensus forecasts (no official free source).
- The BLS API allows about 25 requests a day without a key; Study Terminal uses one every 6 hours. If BLS refuses, the last good
  values are shown with the error.
- **Geopolitical events aren't covered.** Headlines come from Yahoo per symbol, with keyword labels.

## Topstep rules
- Presets come from Topstep's help center and third-party summaries (checked 2026-11-07) and must be confirmed against your
  dashboard. End-of-day balance timing at the flat moment, holiday trade-date merges and Express Funded Scaling Plan tiers
  weren't verified against a real account. Fees for YM, MYM and CL weren't in the readable fee table.
- Study Terminal applies these rules to its own simulator only. It can't see or enforce anything on your real account.

## Screen copilot
- Accuracy was measured on real TradingView screenshots (stocks). **No real TopstepX screenshots were available**: the TopstepX
  adapter was tested on synthetic charts, and no TopstepX accuracy figure is claimed. Use the calibration panel to measure it.
- Account/position panel reading is off by default and unverified on TopstepX.

## Mobile companion
- The API is built and tested in-process; it was **not tested from a real phone** over an SSH tunnel or Tailscale. There's no phone
  app. The phone can only read status and pause/resume/emergency-stop.

## Desktop and Windows
- **Nothing in 0.7.0 was run on Windows by this build process.** The PyInstaller bundle was built and self-tested on Linux only.
  Window capture, toasts, tray, hotkey, WebView2 and the installer need `scripts\verify-windows.ps1` on your PC
  ([WINDOWS_VERIFICATION.md](WINDOWS_VERIFICATION.md)).
- Monitoring runs only while the app runs and the PC is awake; sleep and shutdown gaps are detected and reconciled afterwards.

## AI
- Claude and Ollama wording were not tested (no key or local model in the build environment). The built-in mentor works offline.
