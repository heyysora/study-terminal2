# Study Terminal

An AI day-trading copilot for Windows that you use alongside your charts. It watches the market, watches your chart window (with your permission), finds setups, explains them in plain language, alerts you, and lets you practice in a built-in paper trading simulator.

**No brokerage account, no API keys, no paid services required.**

What's in it:

| Area | What it does |
|---|---|
| Market monitoring | Watchlists and open positions via Yahoo's streaming feed plus 1-minute polling. Every price is labeled with how fresh it really is. |
| Technical analysis | EMAs/SMAs, RSI, MACD, stochastic, ROC, VWAP, relative volume, volume profile, OBV, ATR, Bollinger, volatility, candlestick patterns, market structure, key levels, divergences, multiple timeframes |
| Scanner | Finds candidates market-wide (Yahoo's gainers/losers/most-active lists plus your watchlists), filters them, and ranks them with the reasons shown |
| Signals | 10 setups with entry range, stop, three targets, reward:risk, position size, invalidation, confirmation, risks, and a beginner explanation. Each setup is tracked as developing → approaching → confirmed → invalid. NO TRADE is the default. |
| Paper trading | A local simulator: market/limit/stop/bracket orders, shorts, slippage, commissions, P&L, and risk limits |
| Screen copilot | Watches the trading window you choose, reads its ticker, timeframe, price and drawn lines, and cross-checks them against market data |
| Alerts | Windows notifications, sounds, in-app alerts, duplicate suppression, history |
| AI mentor | Answers your questions and explains charts using the app's own data. Works offline; Claude or a local Ollama model are optional. |
| Learning | 18 lessons with quizzes, a glossary, real-chart exercises, progress tracking |
| Backtesting | Same rules as live trading, costs included, walk-forward testing, optimization, regime breakdown, and ML that only deploys if it beats the base rate on unseen data |

Status of every feature: [FEATURES.md](FEATURES.md). Design and limitations: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Install (Windows, PowerShell)

1. Install **Python 3.11 or newer** from https://www.python.org/downloads/ and check **"Add python.exe to PATH"**.
2. Unzip this folder, for example to `C:\Users\<you>\dev\study-terminal`.
3. In PowerShell:

```powershell
cd C:\Users\<you>\dev\study-terminal
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\test.ps1
```

`setup.ps1` installs everything, including the Windows window, tray and notification packages. The UI is already built, so you don't need Node.js unless you want to change it. `test.ps1` should report all tests passing; the tests need no internet.

## Run

Desktop app (window plus system-tray icon):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-desktop.ps1
```

- Closing the window keeps monitoring running in the tray. **Ctrl+Alt+S** brings the window back.
- The tray icon shows status: green = live stream, amber = polling only, gray = paused, red = a problem. A red dot means screen capture is on.
- Use **Quit** in the tray menu to stop everything.

Or run it in your browser:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-backend.ps1
```

Then open http://127.0.0.1:8765. API docs are at http://127.0.0.1:8765/docs.

Quick data checks:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1 stream BTC-USD --seconds 20
```

The second check proves streaming works even on a weekend, because crypto trades all the time.

## First session checklist

1. **Dashboard:** add symbols to your watchlist. Each price has a small signal meter; five bars means live.
2. **Backtest:** run a walk-forward test on your symbols. This calibrates signal confidence. Until you do, signals say they have no history instead of inventing a confidence number.
3. **Live copilot:** pick your TradingView or broker window, tick the consent box, and click Start watching. The app reads the chart and cross-checks it against market data.
4. **Chart:** open any symbol to see the full analysis, the signal card, and the paper order ticket.
5. **Settings:** risk limits, which setups to watch, alert preferences, AI provider, your learning level.

## Optional: AI model

The built-in mentor answers everything from the app's own data. For more natural explanations, either:

- **Claude** (paid per use): add `ANTHROPIC_API_KEY=...` to a `.env` file in this folder, then choose Claude in Settings.
- **Ollama** (free, runs on your PC): install it from https://ollama.com, run `ollama pull llama3.1`, then choose Ollama in Settings.

The AI only explains numbers the app calculated. It never sets prices or places orders.

## Changing the UI (optional)

Requires Node.js 20+:

```powershell
cd frontend; npm install; npm run build
```

Or use `npm run dev` for live editing; it proxies to a running backend.

## Where things are stored

Database, logs, and ML models live in `%LOCALAPPDATA%\StudyTerminal\`. Screen frames are never stored.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Everything says "Market closed" | Nights, weekends and holidays. Signals pause by design. |
| Meters show 3 bars ("Polling") | The stream dropped or is off. Data can lag 1–2 minutes, so only 5-minute+ setups are evaluated. |
| "Yahoo is rate-limiting" | The app backs off automatically. Lower `MAX_LIVE_SYMBOLS` or raise `POLL_INTERVAL_SECONDS` in `.env`. |
| Screen copilot can't read the ticker | Make the symbol visible in the chart header, or use TradingView, which puts the symbol in the window title. |
| No Windows notifications | Settings → Alerts → Send test alert. Also check Windows Settings → Notifications for Python. |
