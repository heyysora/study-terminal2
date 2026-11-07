# Feature Status

✅ built and tested here · 🟡 built, needs verification on your Windows PC or during market hours · ⬜ not built

## Stage 1 + migration: foundation and market data ✅
No brokerage and no keys. Yahoo provider (history, polling, streaming) behind a swappable provider interface. Honest freshness labels. Local NYSE calendar. Watchlists, SQLite, WebSocket push. Details in [docs/MIGRATION_FROM_ALPACA.md](docs/MIGRATION_FROM_ALPACA.md).

## Stage 2: technical analysis ✅
| Feature | Status |
|---|---|
| EMA 9/21/50/200, SMA 20/50/200 | ✅ |
| RSI (Wilder, TradingView-matching), MACD, stochastic, ROC, relative strength vs SPY via multi-timeframe and market context | ✅ |
| VWAP (session), time-of-day relative volume, volume profile (POC/VAH/VAL), OBV, volume spikes, buying/selling pressure estimate | ✅ |
| ATR, Bollinger Bands, historical volatility, intraday range | ✅ |
| Candles: engulfing, doji, hammer, shooting star, pin bars, inside bar, breakout candles | ✅ |
| Structure: swing highs/lows, HH/HL/LH/LL, support/resistance clustering, previous-day high/low/close, premarket high/low, opening range, liquidity sweeps, consolidation, RSI divergences | ✅ |
| Timeframes 1m–1D (4h built locally from hourly), user-selectable, alignment summary | ✅ |
| Every feature is causal (no look-ahead); enforced by tests | ✅ |

## Stage 3: scanner ✅
Universe from your watchlists plus Yahoo's market-wide lists (gainers, losers, most active, small-cap gainers). Filters: price, % move, average volume, dollar liquidity, market cap, RVOL, volatility, premarket move, setup quality. Transparent ranking. Automatic every 3 minutes in premarket and regular hours, or on demand. Verified against live Yahoo lists.

## Stage 4: signal engine ✅
| Feature | Status |
|---|---|
| Actions: STRONG BUY, BUY, POTENTIAL BUY, WAIT FOR CONFIRMATION, SHORT, POTENTIAL SHORT, NO TRADE; for positions: HOLD, TAKE PARTIAL PROFITS, SELL, EXIT POSITION, COVER SHORT | ✅ |
| 10 setups: VWAP reclaim/rejection, opening-range breakout/breakdown, level breakout/breakdown, trend pullback long/short, failed breakdown/breakout | ✅ |
| All 20 required signal fields, including position size, invalidation, confirmation, risks, and the beginner explanation | ✅ |
| Lifecycle: developing → approaching → confirmed → extended (don't chase) / invalidated / expired | ✅ |
| Confidence kept as three separate things: out-of-sample history, model estimate, checklist score. Plus "certainty: not knowable". | ✅ |
| STRONG BUY requires positive out-of-sample history; setups that lost money out-of-sample are capped at POTENTIAL | ✅ |
| Signals disabled on delayed/stale/closed data; polled data limited to 5-minute+ setups | ✅ |
| Market regime context from SPY, including high-risk conditions | ✅ |

## Stage 5: interface ✅ / 🟡
Dashboard, chart workspace (candles, volume, VWAP/EMA overlays, key levels, entry/stop/target lines, NY time axis), live copilot, scanner, paper trading, backtest/ML, learning center, alerts, settings. Always-visible status strip. Verified by rendering real-data screenshots in headless Chrome. 🟡 Not yet viewed inside the Windows WebView2 window.

## Stage 6: screen intelligence ✅ / 🟡
| Feature | Status |
|---|---|
| Window/monitor picker, consent gate, pause/resume/stop, frames never saved | ✅ |
| Ticker (window title + OCR, confirmed against market data), timeframe, visible price, price-axis reading | ✅ 18/18 rendered test charts |
| Drawn horizontal lines → prices, recent candle colors, visible indicators, on-screen position text (unverified) | ✅ on rendered charts |
| Login/password screen detection | ✅ |
| Fusion: screen vs market price discrepancy, frozen-screen detection, signals for the on-screen symbol and timeframe | ✅ |
| Change-driven processing, optional AI vision on material changes only | ✅ |
| Windows window capture (PrintWindow, mss fallback) | 🟡 written for Windows, not executable here |
| Real TradingView/Webull/thinkorswim/IBKR screenshots | 🟡 tested on rendered charts only; real platforms will need tuning |

## Stage 7: always-on copilot ✅ / 🟡
| Feature | Status |
|---|---|
| Alert engine: entry/position/market/system categories, severity, material-change detection, duplicate suppression, history | ✅ |
| In-app toasts with a link to the chart | ✅ |
| Sleep/wake detection; pause/resume monitoring with honest labels | ✅ |
| Windows toast notifications (win11toast), sound (winsound) | 🟡 |
| Desktop window (pywebview/WebView2), tray icon with status, close-to-tray, Ctrl+Alt+S, start on login, keep-awake option | 🟡 |

## Stage 8: AI mentor and education ✅
Provider choice (built-in / Claude / Ollama), never required. Grounded Q&A for every question in the spec; refuses to invent news or guess a symbol. Explain This Chart adapts to your level and the terms you've already learned. 18 lessons (17 core + a separate options module), quizzes graded server-side, 70+ glossary terms, real-chart "spot the setup" exercises, progress, recommendations. 🟡 Claude/Ollama paths are written but untested here (no key or local model).

## Stage 9: risk management ✅
Settings editable live and persisted. Per-trade risk, daily loss limit, max positions, min reward:risk, required stop, consecutive-loss pause, max exposure, buying power, weekly P&L, position size calculator. Short-sale warnings (borrow, fees, restrictions and unlimited loss).

## Stage 10: backtesting and ML ✅
Bar replay with the paper simulator's own fill rules and costs, flat at the close, no look-ahead (tested). Metrics: win rate, average win/loss, profit factor, drawdown, expectancy ($ and R, before and after costs), Sharpe, total return, trades, holding time. Breakdown by setup, regime and symbol. Optimization grid, walk-forward, chronological split. Calibration store feeds signals. ML: logistic baseline, random forest, gradient boosting (XGBoost if installed), chronological validation, Brier skill, AUC, precision/recall, calibration table, permutation importance, versioning, PSI drift. Deploys only if it beats the base rate.

## Not built (later stages in the original spec)
| Stage | Status |
|---|---|
| 11: trading journal, mistake analysis, performance dashboard | ⬜ (paper fills and backtest trades are already stored for it) |
| 12: Windows installer packaging | ⬜ |
| News and catalyst monitoring | ⬜ (no free news feed wired; the assistant says so instead of guessing) |
| Chrome extension | ⬜ (optional in the spec; screen capture covers browser charts) |
