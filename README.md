# Study Terminal 0.5.0

A trading research and paper-trading environment for Windows that you use alongside your charts. It watches
the market, reads your chart window (with your permission), finds setups, tells you honestly how those setups
have performed on data they never saw, records every trade and signal in a journal, and teaches as it goes.

**No brokerage account, no API keys, no paid services. Paper trading only: it never touches real money.**

> Read this first: in walk-forward testing on 20 liquid US stocks, **none of the 10 built-in setups has a
> reliable edge** ([docs/BACKTEST_RESULTS.md](docs/BACKTEST_RESULTS.md)). The app is built to say so: most of the
> time its answer is **NO TRADE**, with setup ideas shown as *watch only*. Use it to study, practice and measure
> yourself, not as a source of trade calls.

| Area | What it does |
|---|---|
| Market data | Yahoo stream + 1-minute polling, labelled Near real-time / Polling / Delayed / Historical / Cached / Stale / Unavailable with source and timestamp on every quote and chart. Bad bars dropped, spikes flagged, missing candles counted, feed drop-outs alerted. Exchange calendar (holidays, early closes). |
| Analysis | Moving averages, RSI, MACD, stochastic, VWAP, relative volume, volume profile, ATR, Bollinger, candles, structure, levels, divergences, multiple timeframes |
| Scanner | Market-wide candidates (Yahoo lists + watchlists), filters, transparent ranking, catalyst tags |
| Signals | 10 setups with full trade plans. Actions are gated by out-of-sample evidence with 95% intervals; only "reliable" evidence allows BUY/SHORT |
| News | Yahoo headlines (labelled reported / unconfirmed / opinion), earnings dates and surprises, analyst actions, FOMC/CPI/jobs/GDP/PCE calendar |
| Paper trading | Market/limit/stop/bracket orders, shorts, conservative fills, costs, risk limits |
| Journal | Every trade and signal recorded; plan-followed checks; mistake detection with cost; performance dashboard with filters |
| Screen copilot | Reads ticker, timeframe and price from your chart window and cross-checks against market data. Measured on real TradingView screenshots |
| Chrome extension | Optional: follows your TradingView tab using only its title and address |
| AI mentor | Answers from the app's own data, labelled observed / interpretation / evidence / uncertainty / scenario. Works offline; Claude or Ollama optional |
| Backtesting | Walk-forward testing, diagnostics by strategy, ticker, regime, time of day and more, ML with a deployment gate |
| Learning | 18 lessons, quizzes, glossary, real-chart exercises |

Docs: [User guide](docs/USER_GUIDE.md) · [Features and limits](FEATURES.md) · [Backtest results](docs/BACKTEST_RESULTS.md) ·
[Market data sources](docs/DATA_PROVIDERS.md) · [Screen validation](docs/SCREEN_VALIDATION.md) ·
[Windows verification](docs/WINDOWS_VERIFICATION.md) · [Architecture](docs/ARCHITECTURE.md) · [Audit](docs/AUDIT.md)

---

## Option A: install like a normal Windows app

You build the installer once on your PC (it can't be built on Linux, and an unsigned download would trigger
SmartScreen warnings anyway):

```powershell
cd C:\Users\<you>\dev\study-terminal
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1            # Python environment (once)
winget install JRSoftware.InnoSetup                                    # free installer compiler (once)
powershell -ExecutionPolicy Bypass -File .\scripts\build-installer.ps1  # ~5 minutes
.\dist-installer\StudyTerminal-Setup-0.5.0.exe
```

The installer:
- installs per-user (no admin rights) to `%LOCALAPPDATA%\Programs\Study Terminal`;
- adds a Start menu entry and, optionally, a desktop shortcut and start-on-login (off by default);
- uses the app icon and shows up in Windows Settings > Apps for uninstalling. Uninstall asks whether to keep your data.

**Your data** (journal, paper account, settings, backtests, logs) lives in `%LOCALAPPDATA%\StudyTerminal`,
separate from the program. **Updating** = build or download the new installer and run it: program files are
replaced, data is kept. Settings > About and files shows every location and opens the logs folder.

## Option B: run from source (for development)

1. Install **Python 3.11+** from python.org and tick "Add python.exe to PATH".
2. Unzip this folder, then in PowerShell:

```powershell
cd C:\Users\<you>\dev\study-terminal
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1        # install
powershell -ExecutionPolicy Bypass -File .\scripts\test.ps1         # run the test suite (no internet needed)
powershell -ExecutionPolicy Bypass -File .\scripts\run-desktop.ps1  # desktop window + tray
powershell -ExecutionPolicy Bypass -File .\scripts\run-backend.ps1  # or: browser at http://127.0.0.1:8765
```

## PowerShell commands

| Command | What it does |
|---|---|
| `.\scripts\setup.ps1` | Creates the Python environment and installs everything |
| `.\scripts\test.ps1` | Full test suite. Extra pytest arguments pass through, e.g. `.\scripts\test.ps1 -k journal -x` |
| `.\scripts\run-desktop.ps1` | Desktop app (window + tray). Closing hides to tray; Ctrl+Alt+S reopens; Tray > Quit exits |
| `.\scripts\run-backend.ps1` | Backend only; open http://127.0.0.1:8765 (API docs at /docs) |
| `.\scripts\check.ps1 SPY AAPL` | Live data check: source, delay, freshness per symbol |
| `.\scripts\check.ps1 stream BTC-USD --seconds 20` | Proves streaming works (crypto trades 24/7) |
| `.\scripts\verify-windows.ps1` | Checks capture, notifications, sound, tray, hotkey, WebView2, single instance, clean shutdown |
| `.\scripts\screen-eval.ps1 C:\shots` | Measures screen-reading accuracy on your own screenshots |
| `.\scripts\build-installer.ps1` | Builds `dist-installer\StudyTerminal-Setup-<version>.exe` |

Prefix each with `powershell -ExecutionPolicy Bypass -File` if script execution is disabled on your PC.

Re-run the backtest studies behind `docs/BACKTEST_RESULTS.md` (takes ~20 minutes, needs internet):
```powershell
cd backend; .\.venv\Scripts\python.exe -m research.run_walkforward 5Min 58 --fixed
```

## First session
1. **Dashboard**: add symbols. Every price shows its source and age.
2. **Backtest**: run a walk-forward test on your symbols. This is what signals use as evidence; until then every
   idea is "untested" and watch-only.
3. **Chart**: analysis, signal card with its evidence tier, catalysts, and the paper order ticket.
   "Load into paper order ticket" links the trade to the signal for the journal.
4. **Live copilot**: pick your chart window, consent, start. Or install the Chrome extension for TradingView.
5. **Journal**: after a few paper trades, see what you did versus the plan and what your mistakes cost.
6. **Settings**: risk limits, alerts, AI provider, learning level, extension pairing, data folders.

## Optional AI model
The built-in mentor needs nothing. For more natural wording:
- **Claude** (paid per use): put `ANTHROPIC_API_KEY=...` in `%LOCALAPPDATA%\StudyTerminal\.env` (or `.env` in this
  folder when running from source) and choose Claude in Settings.
- **Ollama** (free, local): install from ollama.com, `ollama pull llama3.1`, choose Ollama in Settings.
Both only reword the app's own data. Neither was tested here (no key, no local model in the build environment).

## Troubleshooting

| Symptom | Fix |
|---|---|
| Everything says "Market closed" / NO TRADE | Nights, weekends, holidays: signals pause by design. During market hours, NO TRADE usually means no setup has a proven edge. |
| Meters show "Polling" | The stream dropped; prices can lag 1–2 minutes, so only 5-minute+ setups are evaluated. It reconnects by itself. |
| "Yahoo is rate-limiting" | It backs off automatically. Lower `MAX_LIVE_SYMBOLS` or raise `POLL_INTERVAL_SECONDS` in the `.env`. |
| Screen copilot can't read the ticker | Make the symbol visible, or use TradingView in Chrome (the symbol is in the window title), or the Chrome extension. |
| No Windows notifications | Settings > Alerts > Send test alert; check Windows Settings > Notifications. Run `verify-windows.ps1`. |
| App won't start | A message box names the reason. Logs: `%LOCALAPPDATA%\StudyTerminal\logs` (`study_terminal.log`, `desktop.log`). |
| Port 8765 in use | Add `PORT=8766` to `%LOCALAPPDATA%\StudyTerminal\.env`. |
