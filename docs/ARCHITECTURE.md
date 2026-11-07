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
        |  hosts
 FastAPI backend (127.0.0.1:8765)  ── serves the React UI (frontend/dist) + REST + WebSocket
   market_data/   provider interface -> Yahoo (history, polling, stream) ; MarketMonitor ; FreshnessTracker
   analysis/      causal feature frame (indicators, levels, structure, candles) -> snapshot / MTF
   signals/       setups (vectorized, causal) -> trade plan -> lifecycle -> action ; position management
   scanner/       Yahoo market-wide lists + watchlists -> filters -> deep scan -> transparent rank
   paper/         local simulator (orders, fills, P&L, risk limits) + SQLite persistence
   backtest/      bar replay with the simulator's own fill rules ; walk-forward ; optimization ; calibration
   ml/            setup-outcome classifier, chronological validation, deploy gate, drift (PSI)
   screen/        window capture -> change detection -> OCR (RapidOCR) + OpenCV -> fusion with market data
   alerts/        dedupe, history, Windows toasts/sound, in-app push
   ai/            provider choice (built-in / Claude / Ollama) ; grounded assistant ; Explain This Chart
   education/     lessons, quizzes, glossary, progress, real-chart exercises
   settings/      live-editable settings persisted in SQLite
```

Design rules:
- **One feature frame for everything.** Live analysis, signals, the scanner and the backtester all consume the same causal per-bar features. Tests recompute on truncated data to prove there's no look-ahead.
- **Freshness gates everything.** Signals and paper fills only use REALTIME, NEAR_REALTIME or POLLING data (polling: 5-minute+ setups only).
- **Confidence is never invented.** A signal shows three separate things: out-of-sample backtest history (walk-forward only), a model probability (only if the model beat the base rate on unseen data), and a checklist score that is labeled as not a probability. STRONG BUY needs positive out-of-sample history.
- **The LLM explains; it doesn't calculate.** It receives the computed JSON with strict no-invention rules. Without an LLM, built-in templates answer.
- **No broker code exists.** Orders go only to the local simulator, and each needs `confirm: true`.
- **Screen frames never touch disk.** Capture is off until you consent and select a target. Login screens are skipped.

Why pywebview instead of Tauri: Tauri needs Rust plus Visual Studio Build Tools (several GB) and a separate sidecar process for Python. pywebview uses the WebView2 runtime already in Windows 11 and installs with pip, so the whole app is one Python process. The UI is a standard React build, so moving to Tauri later only changes the shell.

## 3. Folder structure

```
study-terminal/
├─ README.md · FEATURES.md · .env.example (optional)
├─ docs/        ARCHITECTURE.md · MIGRATION_FROM_ALPACA.md
├─ scripts/     setup.ps1 · test.ps1 · check.ps1 · run-backend.ps1 · run-desktop.ps1
├─ desktop/     launcher.py (window, tray, hotkey)
├─ frontend/    React + TypeScript + Vite + lightweight-charts (dist/ prebuilt)
└─ backend/
   ├─ app/      main.py config.py cli.py | core/ db/ market_data/ analysis/ signals/ scanner/ paper/
   │            backtest/ ml/ screen/ alerts/ ai/ education/ settings/ api/
   └─ tests/    unit + integration tests (synthetic data, fake provider, fake Yahoo socket, rendered chart screenshots)
```

## 3b. What the backtests found (Nov 7, 2026)

Walk-forward test, 6 large caps (SPY, QQQ, AAPL, TSLA, NVDA, AMD), 5-minute bars, about 58 days: **274 out-of-sample trades, -0.11R per trade after costs, -0.03R before costs.** The setups as written show no demonstrated edge on this sample. A few were positive out-of-sample (support breakdown +0.24R over 32 trades, short trend pullback +0.27R over 37), but these are small samples from one market period, too few to tell skill from luck. The app acts on this automatically: setups that lost money out-of-sample are capped at POTENTIAL, and STRONG BUY is impossible without positive out-of-sample history. Re-run walk-forward regularly; results will change with market conditions.

## 4. Free data sources investigated

| Source | Real-time? | Key needed? | Verdict |
|---|---|---|---|
| **Yahoo Finance (yfinance)** | Price real-time when from Nasdaq Last Sale, else delayed. Unofficial push socket. | No | **Default.** Covers history, polling, and the stream. |
| Finnhub free tier | Free WebSocket for trades; ~60 REST calls/min | Free data key (not a brokerage) | **Best candidate for a second, optional provider.** Would plug into `registry.py`. Not added, since you asked for no key requirements. |
| Twelve Data free | Mostly delayed; 800 requests/day | Free key | Too limited for monitoring |
| Polygon/Massive free | End-of-day only, 5 calls/min | Free key | History only |
| Alpha Vantage free | Delayed, 25 requests/day | Free key | Too limited |
| Nasdaq.com / CNBC unofficial endpoints | Varies | No | Not used: undocumented, and scraping them is fragile |

Paid upgrade path, should you ever want true real-time: any licensed provider can be added as a new `MarketDataProvider` with `guaranteed_realtime=True`. Only then will the app show REALTIME.

## 5. Runs entirely on your PC
Indicators, structure, setups, risk, sizing, the paper simulator, the market calendar, backtests on cached data, ML, screen capture and OCR/CV, the journal, analytics, lessons, notifications, and the database.

## 6. Needs internet
Market data (Yahoo), news (later), and the optional cloud LLM.

## 7. Needs payment
Nothing. Optional: Claude API usage for AI explanations (Stage 8, can stay off), or a licensed data provider if you ever want guaranteed real-time data.

## 8. Screen + market fusion (Stage 6)
Screen OCR identifies the ticker and timeframe → the monitor focuses that symbol (stream + bars) → the visible price is compared with the latest labeled tick (mismatch = stale screen or wrong symbol) → analysis runs on market data only → signals are allowed only if the symbol's label permits them for that timeframe.

## 9. Teaching style
Explanations assume no prior knowledge: every term is defined at first use, one idea at a time, with dollar examples before formulas.
