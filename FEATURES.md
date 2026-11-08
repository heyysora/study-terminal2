# Features and limitations (0.6.0)

✅ built and tested here · 🟡 built, not yet verified where it matters (Windows, market hours, your platform) · ⬜ not built

## Completed

| Area | Feature | Status |
|---|---|---|
| Market data | Yahoo stream + 1-min polling, no keys, swappable provider interface | ✅ |
| | Status per quote and chart: Near real-time / Polling / Delayed / Historical / **Cached** / Stale / Unavailable, with source, price time and age | ✅ |
| | Bar validation (impossible bars dropped, rounding repaired, one-bar spikes flagged, missing regular-session candles counted) | ✅ |
| | Feed-health alerts (stream down > 60 s, provider failing, stale price on an open position) and recovery alerts; automatic reconnect with backoff | ✅ |
| | Rate limiting (60/min, back-off on 429), exchange calendar incl. holidays and **early closes** everywhere | ✅ |
| | Provider research and how to add one ([docs/DATA_PROVIDERS.md](docs/DATA_PROVIDERS.md)) | ✅ |
| | US stocks streamed during market hours | 🟡 never observed from the build environment (weekend); crypto streaming verified |
| Signals | 10 setups, full plans, lifecycle, position sizing | ✅ |
| | Evidence tiers from out-of-sample results with day-clustered 95% intervals; BUY/SHORT only on "reliable" evidence; clearly losing setups = NO TRADE; STRONG needs regime record too | ✅ |
| | Watch-only for 15 min around FOMC/CPI/jobs/GDP/PCE; earnings and post-earnings notes | ✅ |
| Backtesting | Walk-forward (optimized and fixed-rules), per-direction/regime calibration, diagnostics across 17 dimensions, MFE/MAE, stop/target/entry mechanics, costs | ✅ |
| | Real-data studies: 5-min, 15-min, 1-hour, 20 symbols ([docs/BACKTEST_RESULTS.md](docs/BACKTEST_RESULTS.md)) | ✅ |
| Journal (Stage 11) | Automatic trade and signal records, conditions at entry, confidence components, plan checks, notes, tags | ✅ |
| | Mistake detection (8 patterns) with cost vs clean trades; performance dashboard with filters | ✅ |
| News | Yahoo headlines with reported/unconfirmed/opinion and relevance labels, earnings dates and surprises, analyst actions, FOMC (live), BEA (live), BLS (bundled) | ✅ verified live against Yahoo, the Fed and BEA |
| | Scanner catalyst tags; signal event gate; news alerts | ✅ |
| Screen copilot | Ticker, timeframe, price, axis from pixels and window title; cross-check against market data; price-confirmed OCR tickers | ✅ on 60 real TradingView screenshots (blind set: 0 wrong answers) |
| | Windows window/monitor capture | 🟡 Windows only |
| | Webull, thinkorswim, IBKR | 🟡 untested (no screenshots available); harness ready: `scripts\screen-eval.ps1` |
| AI mentor | Labelled answers from analysis, signals, evidence, journal, news, signal log; 18 intents | ✅ |
| | Claude / Ollama wording | 🟡 written, untested (no key or local model here) |
| Desktop (Stage 12) | Installer (Inno Setup), Start menu, desktop shortcut, icon, uninstall with keep-data choice, data folder separate from program | 🟡 written; the PyInstaller bundle was built and self-tested on Linux, the Windows build and installer were not run |
| | Single instance, clean shutdown, error message boxes, logs folder from tray and Settings, start-on-login (off by default) | 🟡 Windows behaviour unverified; clean shutdown verified on Linux |
| | Tray, toasts, sound, hotkey, WebView2 window | 🟡 run `scripts\verify-windows.ps1` |
| Chrome extension | Optional, token-paired, TradingView tabs only, title + address only | ✅ end-to-end in real Chrome with a real TradingView tab |
| Futures / TopstepX (0.6.0) | Contract registry (ES, MES, NQ, MNQ, YM, MYM, RTY, M2K, CL, GC; add your own), exact tick math, expirations and roll dates, symbol parsing for platform formats | ✅ checked against CME spec pages |
| | Globex sessions in exchange time: trade dates from 17:00 CT, RTH per product, holidays/early halts, daylight saving | ✅ (holiday minutes from exchange_calendars, not CME notices) |
| | VWAP ±1σ, previous day/session, overnight, pre-RTH, opening range, initial balance, volume profile (POC/VAH/VAL/HVN/LVN), BOS/CHoCH, FVGs, sweeps | ✅ causal, tested on real ES bars |
| | Five fixed futures setups; LONG/SHORT/HOLD/EXIT/NO TRADE with the same evidence gate as stocks; no signals on delayed/stale/incomplete data | ✅ |
| | Topstep presets (Combine and Express Funded 50K/100K/150K) with sources, unconfirmed until you confirm; personal limits kept separate; warnings and blocking in the simulator | ✅ simulator only; can't enforce anything on a real account |
| | Futures simulator: market/limit/stop, brackets, per-contract fees, tick slippage, partial fills, end-of-day trailing drawdown, flat-by time; replay of past sessions | ✅ |
| | TopstepX screen adapter and platform selector; futures cross-checks (tick grid, contract month, delayed-feed tolerance) | 🟡 tested on synthetic charts only; no real TopstepX screenshots |
| | Optional read-only TopstepX API (ProjectX) data source | 🟡 tested against a mock server only |
| | Futures backtest (ES, MES, NQ, CL, GC) | ✅ no setup reliable; all watch-only ([docs/TOPSTEPX.md](docs/TOPSTEPX.md) §9) |
| Earlier stages | Analysis, scanner, paper trading, risk limits, alerts, learning centre | ✅ (see previous releases) |

## Remaining limitations

- **No demonstrated edge.** The built-in setups lose slightly or break even out-of-sample. The app will mostly say NO TRADE.
- **Free data is partial.** Yahoo's price is Nasdaq Last Sale (real-time price, partial volume); its endpoints are
  unofficial and can change or break. Nothing is ever labelled REALTIME.
- **Intraday history is short**: ~60 days for 5- and 15-minute bars, ~2 years for hourly. Walk-forward on 5/15-minute
  covers 21 out-of-sample trading days, one market period.
- **Survivorship bias**: the test universe is today's large caps.
- **Windows-specific parts are unverified on Windows** (see [docs/WINDOWS_VERIFICATION.md](docs/WINDOWS_VERIFICATION.md)).
- **Screen reading** measured on TradingView only; logged-in layouts and other platforms will need tuning.
- **News**: Yahoo's feed only; no FDA calendar, no real-time wires; labels are keyword rules.
- **Chrome extension**: TradingView doesn't always put the interval in the address; then your default timeframe is used.
- Alert de-duplication resets on restart (M9 in the audit). Quitting within a second of launch logs a harmless library error (L6).
- **Futures data is delayed by default** (Yahoo reports 10 minutes). Without the optional TopstepX API there are no live
  futures signals or live simulator fills; use replay or delayed practice. Everything not tested against a real TopstepX
  environment is listed in [docs/TOPSTEPX.md](docs/TOPSTEPX.md) §10.
- Not built: real-money execution (by design), Webull/ToS/IBKR-specific readers, code signing for the installer.
