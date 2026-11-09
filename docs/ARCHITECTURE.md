# Study Terminal: Architecture, Data Sources, and Limitations

Updated Nov 7, 2026 (Stages 2-10 built). The app uses no brokerage. See [MIGRATION_FROM_ALPACA.md](MIGRATION_FROM_ALPACA.md).

---

## 1. Constraints that shape the design

| # | Constraint | What the app does about it |
|---|---|---|
| 1 | **No free US stock feed is officially real-time across the whole market.** Exchange licensing makes full real-time data cost money. | Labels are honest. Nothing from a free provider is ever labeled REALTIME. The best a free source gets is NEAR_REALTIME (an unofficial stream with fresh timestamps) or POLLING. |
| 2 | **Yahoo's prices are real-time only sometimes.** Yahoo says US quotes are real-time for NASDAQ, NYSE and NYSE American *when available from Nasdaq Last Sale*. Otherwise they're delayed from the consolidated tape. | The app asks Yahoo per symbol (`quoteSourceName`, `exchangeDataDelayedBy`). Symbols Yahoo marks as delayed are labeled DELAYED, and signals are disabled for them. |
| 3 | **Yahoo's volume is partial**, and extended-hours 1-minute bars come back with **volume 0** (observed directly). | Every label carries a volume caveat. Premarket volume and relative-volume scanning from Yahoo will be marked approximate or unavailable, never presented as accurate. |
| 4 | **Yahoo's streaming socket is undocumented.** It works (tested: ticks arrived 4–6s after their source timestamps), but Yahoo can change or block it. | It's used as a best-effort stream with automatic reconnects. Polling of 1-minute bars always runs underneath it, so monitoring degrades to POLLING instead of stopping. |
| 5 | **Polling a history endpoint is not live data.** A polled 1-minute bar can be 60–90+ seconds behind. | Polled data is labeled POLLING, never "live". Signals on polled data are limited to 5-minute or slower setups. |
| 6 | **Yahoo rate-limits clients.** | One app-wide throttle (60 requests/min by default) with a 60s back-off on rate-limit errors. Monitoring is capped at 40 symbols. Open positions are always monitored first. |
| 7 | **Yahoo history limits:** 1-minute ≈ 7 days, 2–30-minute ≈ 60 days, hourly ≈ 2 years, daily = decades. No native 4-hour bars. | Requests are clamped and the clamping is reported in `notes`. 4-hour bars are built locally from hourly bars, anchored at 09:30 ET. Long intraday backtests will need a different data source (see §4). |
| 8 | **No broker means no borrow data.** Short availability, borrow fees, and short-sale restrictions can't be checked. | The simulator allows shorts with a configurable simulated borrow fee and warns on every short that these are not verified. |
| 9 | **yfinance is unofficial**, and Yahoo's terms limit data to personal use. | Fine for a personal tool. The provider interface means a licensed source can replace it without touching the rest of the app. |
| 10 | Reading charts from pixels is approximate (unchanged). | Screen intelligence identifies *what* you're viewing. All numbers come from market data. Anything detected visually is labeled a visual estimate. |
| 11 | "Always on" means while the PC is awake (unchanged). | Sleep is detected and labels go STALE. Optional keep-awake while monitoring (Stage 7). |

## 2. Architecture

One Python process on your PC (plus the WebView2 window it opens):

```
 desktop/launcher.py   native window (pywebview -> WebView2) + tray icon (pystray) + Ctrl+Alt+S + keep-awake
                       single-instance mutex, clean shutdown, error dialogs, --minimized, --self-test
 installer/            PyInstaller spec (one-folder bundle) + Inno Setup script (per-user installer)
 extension/            optional Chrome MV3 extension -> /api/extension (token-paired, TradingView tabs only)
        |  hosts
 FastAPI backend (127.0.0.1:8765)  ── serves the React UI (frontend/dist) + REST + WebSocket
   market_data/   provider interface -> Yahoo (history, polling, stream) ; MarketMonitor ; FreshnessTracker
                  validation (bad bars, spikes, missing candles) ; FeedHealthWatcher (drop-out/recovery alerts)
   analysis/      causal feature frame (indicators, levels, structure, candles) -> snapshot / MTF
   signals/       setups (vectorized, causal) -> trade plan -> lifecycle -> action ; position management
   scanner/       Yahoo market-wide lists + watchlists -> filters -> deep scan -> transparent rank
   paper/         local simulator (orders, fills, P&L, risk limits) + SQLite persistence
   backtest/      bar replay with the simulator's own fill rules ; walk-forward ; optimization ; calibration
                  stats (day-clustered bootstrap, Wilson, evidence tiers) ; diagnostics (17 slices, MFE/MAE, findings)
   journal/       round trips from paper fills -> trades, plan checks, mistakes, performance ; signal log
   news/          Yahoo news/earnings/analyst ; FOMC + BEA (live) + BLS (bundled) ; labels ; event gate
   ml/            setup-outcome classifier, chronological validation, deploy gate, drift (PSI)
   screen/        window capture -> change detection -> OCR (RapidOCR) + OpenCV -> fusion with market data
   alerts/        dedupe, history, Windows toasts/sound, in-app push
   ai/            provider choice (built-in / Claude / Ollama) ; grounded assistant ; Explain This Chart
   education/     lessons, quizzes, glossary, progress, real-chart exercises
   futures/       contracts (specs, ticks, expirations, roll) ; sessions (Globex, CT) ; data (Yahoo delayed / optional
                  read-only TopstepX API, labels, cache, fallback) ; feed (bar validation, source health, downtime) ;
                  features (levels, profile, structure, regime) ; setups ; pipeline (13-step decision, stored) ; signals ;
                  risk (central risk service: prop presets + personal limits) ; paper (futures simulator, persisted) ;
                  automation (modes A/B, C locked; monitoring loop; trade management; emergency stop; sandbox) ;
                  backtest (scan + simulate) ; research (walk-forward + holdout, strategy registry) ; replay ; journal ; service
   futures/stream.py      TopstepX SignalR market hub client (read-only, two subscribe calls), LiveStream: status, gaps, backfill, rollover
   futures/candles.py     trades -> 1-minute bars (dedupe, late prints, tick grid), session-aligned aggregation for every timeframe
   screen/calibration.py  labelled-screenshot scoring and per-platform accuracy report (images kept only with consent)
   news/econ_data.py      BLS published values (actual/previous) for CPI, PPI, payrolls, unemployment
   api/routes_mobile.py   token-protected, brake-only mobile companion API
   screen/platforms.py  platform adapters (TopstepX, TradingView, generic) feeding the shared OCR pipeline
   settings/      live-editable settings persisted in SQLite
```

Design rules:
- **One feature frame for everything.** Live analysis, signals, the scanner and the backtester all consume the same causal per-bar features. Tests recompute on truncated data to prove there's no look-ahead.
- **Freshness gates everything.** Signals and paper fills only use REALTIME, NEAR_REALTIME or POLLING data (polling: 5-minute+ setups only).
- **Confidence is never invented.** A signal shows three separate things: out-of-sample evidence (walk-forward only, with a 95% interval and a tier), a model probability (only if the model beat the base rate on unseen data with an interval above zero), and a checklist score labeled as not a probability. Only "reliable" evidence allows BUY/SHORT; STRONG also needs a non-negative record in the current regime.
- **Sessions come from the exchange calendar**, never from a fixed 09:30–16:00 (early-close days).
- **Every number shown has a source and a time** (quotes, charts, news, calendar entries).
- **The LLM explains; it doesn't calculate.** It receives the computed JSON with strict no-invention rules. Without an LLM, built-in templates answer.
- **No broker code exists.** Orders go only to the local simulator, and each needs `confirm: true` (stocks) or passes
  `FuturesPaperEngine.preview` -> `RiskEngine.check_entry` (futures; the same path for manual, automated, replay and sandbox orders).
  Live execution (Mode C) is locked and has no implementation.
- **Live means live.** Only the TopstepX stream can label data `realtime` (LIVE), and only while connected and receiving data.
  Stale/disconnected/delayed data can't reach the pipeline's or simulator's tradable set. Decisions drop a still-forming candle.
- **One decision pipeline.** Futures signals, assisted mode, automated paper mode, replay automation and the sandbox all use
  `pipeline.run`; every decision is stored with its steps, keyed by contract/setup/direction/bar time so it can't act twice.
- **Screen frames never touch disk.** Capture is off until you consent and select a target. Login screens are skipped.

Why pywebview instead of Tauri: Tauri needs Rust plus Visual Studio Build Tools (several GB) and a separate sidecar process for Python. pywebview uses the WebView2 runtime already in Windows 11 and installs with pip, so the whole app is one Python process. The UI is a standard React build, so moving to Tauri later only changes the shell.

## 3. Folder structure

```
study-terminal/
├─ README.md · FEATURES.md · .env.example (optional)
├─ docs/        USER_GUIDE · TOPSTEPX · AUTOMATION_GUIDE · PAPER_TRADING_GUIDE · REPLAY_GUIDE · EVALUATION_GUIDE · MOBILE_API ·
│               BACKTEST_RESULTS(_FUTURES) · DATA_PROVIDERS · SCREEN_VALIDATION · WINDOWS_VERIFICATION · TEST_RESULTS · LIMITATIONS ·
│               AUDIT(_0.7) · PLAN_0.7 · ARCHITECTURE · MIGRATION_FROM_ALPACA
├─ scripts/     setup · test · check · run-backend · run-desktop · verify-windows · screen-eval · build-installer (.ps1)
├─ desktop/     launcher.py (window, tray, hotkey) · verify_windows.py · make_icon.py · assets/
├─ installer/   StudyTerminal.spec (PyInstaller) · StudyTerminal.iss (Inno Setup)
├─ extension/   optional Chrome extension
├─ frontend/    React + TypeScript + Vite + lightweight-charts (dist/ prebuilt)
└─ backend/
   ├─ app/      main.py config.py cli.py | core/ db/ market_data/ analysis/ signals/ scanner/ paper/
   │            backtest/ ml/ screen/ alerts/ ai/ education/ settings/ journal/ news/ api/
   ├─ research/ run_walkforward.py · run_all.sh · screen_eval.py · out/ (study results, JSON)
   └─ tests/    unit + integration tests (synthetic data, fake provider, fake Yahoo socket, rendered charts,
                trimmed real Fed/BEA pages, recorded real ES bars, mocked BLS/ProjectX HTTP); count in docs/TEST_RESULTS.md
```

## 3b. What the backtests found

See [BACKTEST_RESULTS.md](BACKTEST_RESULTS.md): six walk-forward studies on 20 symbols (5-min, 15-min, 1-hour; fixed
and optimized). No setup has a reliable edge; the largest study (2,796 hourly trades over 21 months) averages
−0.027R with a 95% interval of −0.065 to +0.015R. The Stage 10 figure (−0.11R on 274 trades) is superseded.

## 4. Data sources

See [DATA_PROVIDERS.md](DATA_PROVIDERS.md) for what Yahoo actually provides, how it's labelled, and a priced
comparison of Finnhub, Tiingo, Twelve Data, Alpha Vantage, Massive (Polygon) and Databento.

## 5. Runs entirely on your PC
Indicators, structure, setups, risk, sizing, the paper simulator, the market calendar, backtests on cached data, ML, screen capture and OCR/CV, the journal, analytics, lessons, notifications, and the database.

## 6. Needs internet
Market data and news (Yahoo), the FOMC and BEA calendars (federalreserve.gov, bea.gov), and the optional cloud LLM.

## 7. Needs payment
Nothing. Optional: Claude API usage for AI explanations (Stage 8, can stay off), or a licensed data provider if you ever want guaranteed real-time data.

## 8. Screen + market fusion (Stage 6)
Screen OCR identifies the ticker and timeframe → the monitor focuses that symbol (stream + bars) → the visible price is compared with the latest labeled tick (mismatch = stale screen or wrong symbol) → analysis runs on market data only → signals are allowed only if the symbol's label permits them for that timeframe.

## 9. Teaching style
Explanations assume no prior knowledge: every term is defined at first use, one idea at a time, with dollar examples before formulas.
