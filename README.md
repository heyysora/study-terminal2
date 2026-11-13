# Study Terminal 0.13.0

A trading research and paper-trading environment for Windows that you use alongside your charts. It watches
the market, reads your chart window (with your permission), finds setups, tells you honestly how those setups
have performed on data they never saw, records every trade and signal in a journal, and teaches as it goes.

**No brokerage account, no API keys, no paid services. Paper trading only: it never touches real money.**

> Read this first: in walk-forward testing on 20 liquid US stocks, **none of the 10 built-in setups has a
> reliable edge** ([docs/BACKTEST_RESULTS.md](docs/BACKTEST_RESULTS.md)), and **no futures strategy passed validation** on NQ, MNQ, ES
> or MES ([docs/BACKTEST_RESULTS_FUTURES.md](docs/BACKTEST_RESULTS_FUTURES.md)), so automated paper trading approves nothing. The app is built to say so: most of the
> time its answer is **NO TRADE**, with setup ideas shown as *watch only*. Use it to study, practice and measure
> yourself, not as a source of trade calls.

| Area | What it does |
|---|---|
| Market data | Yahoo stream + 1-minute polling, labelled Near real-time / Polling / Delayed / Historical / Cached / Stale / Unavailable with source and timestamp on every quote and chart. Bad bars dropped, spikes flagged, missing candles counted, feed drop-outs alerted. Exchange calendar (holidays, early closes). |
| Analysis | Moving averages, RSI, MACD, stochastic, VWAP, relative volume, volume profile, ATR, Bollinger, candles, structure, levels, divergences, multiple timeframes |
| Scanner | Market-wide candidates (Yahoo lists + watchlists), filters, transparent ranking, catalyst tags |
| Signals | 10 setups with full trade plans. Actions are gated by out-of-sample evidence with 95% intervals; only "reliable" evidence allows BUY/SHORT |
| News | Yahoo headlines (labelled reported / unconfirmed / opinion), earnings dates and surprises, analyst actions, FOMC/CPI/jobs/GDP/PCE calendar with BLS published values (actual/previous) and release warnings |
| Paper trading | Market/limit/stop/bracket orders, shorts, conservative fills, costs, risk limits |
| Journal | Every trade and signal recorded; plan-followed checks; mistake detection with cost; performance dashboard with filters |
| Screen copilot | Reads ticker, timeframe and price from your chart window and cross-checks against market data. Measured on real TradingView screenshots; calibration panel measures accuracy on your own TopstepX screenshots |
| Chrome extension | Optional: follows your TradingView tab using only its title and address |
| AI mentor | Answers from the app's own data, labelled observed / interpretation / evidence / uncertainty / scenario. Works offline; Claude or Ollama optional |
| Backtesting | Walk-forward testing, diagnostics by strategy, ticker, regime, time of day and more, ML with a deployment gate |
| Learning | 18 lessons, quizzes, glossary, real-chart exercises |
| Futures (TopstepX) | TopstepX is the default futures platform; NQ, MNQ, ES, MES monitored by default. CME contract specs, Globex sessions, regime and multi-timeframe analysis, a 13-step decision pipeline with every decision stored, Topstep evaluation practice, a persistent futures simulator, replay with automation, labelled data with fallback and downtime reconciliation. Never places orders on TopstepX. See [docs/TOPSTEPX.md](docs/TOPSTEPX.md) |
| Live price (0.12 preview 2) | The price from your TopstepX chart, read about twice a second and checked against the chart's price scale, shown as a big number with a live line chart (light or dark theme). Read from your screen, not an exchange feed |
| Home, Simple mode and the safety bar (0.12) | Home answers five questions in plain words (is it working, what is the market doing, practice or wait, how much could I lose, what next) with a first-time setup guide. Every screen shows PRACTICE MODE, one health light and a Stop everything button. Simple mode is the default; Advanced shows every tool and the trading terms. Display only: limits, calculations and the practice-only lock are identical in both. See [docs/CHANGELOG.md](docs/CHANGELOG.md) |
| Trust & Validation | Nine evidence-based validation statuses (visual capture, OCR/price, instrument/timeframe, candles/indicators, signals, historical performance, walk-forward, paper trading, risk) and a readiness level from EXPERIMENTAL to LIVE ELIGIBILITY REVIEW. Counts only recorded real evidence; unit tests and synthetic screenshots never count; live execution stays disabled. See [docs/TRUST_VALIDATION.md](docs/TRUST_VALIDATION.md) |
| Live Visual Monitor | Uses the TopstepX chart in Microsoft Edge (Windows Graphics Capture, with PrintWindow/screen fallbacks) as the market input, with no data subscription: reads instrument, timeframe, price, candles, volume, VWAP/EMAs from the chart (each value labelled read / calculated / estimated / unavailable, with confidence and capture time), runs the futures analysis and risk engine, and alerts you. Runs in the background. Never clicks or orders. Tested on synthetic screenshots so far. See [docs/VISUAL_MONITOR.md](docs/VISUAL_MONITOR.md) |
| Live Market | Live-updating futures charts (NQ, MNQ, ES, MES; 1m to daily) from the TopstepX market hub when you have a ProjectX API subscription, with EMAs, VWAP, session levels and structure overlays, and an honest LIVE / STALE / DISCONNECTED / DELAYED label. Without the subscription the charts use Yahoo, labelled DELAYED. Streaming is mock-tested only so far. See [docs/LIVE_MARKET_DATA.md](docs/LIVE_MARKET_DATA.md) |
| Automation Center | Mode A (assisted) and Mode B (automated paper trading, validated strategies only, inside a central risk service); Mode C live is locked with no order code. Start/pause/resume/stop, emergency stop with review, research sandbox, automated vs manual comparison. See [docs/AUTOMATION_GUIDE.md](docs/AUTOMATION_GUIDE.md) |
| Mobile companion | Optional, off by default: token-protected API to watch status and pause/resume/emergency-stop from a phone over a private encrypted channel. See [docs/MOBILE_API.md](docs/MOBILE_API.md) |

Docs: [Visual Monitor (start here for TopstepX)](docs/VISUAL_MONITOR.md) · [Trust & Validation](docs/TRUST_VALIDATION.md) · [User guide](docs/USER_GUIDE.md) · [TopstepX and futures](docs/TOPSTEPX.md) · [Live market data](docs/LIVE_MARKET_DATA.md) · [Automation](docs/AUTOMATION_GUIDE.md) ·
[Paper trading](docs/PAPER_TRADING_GUIDE.md) · [Replay](docs/REPLAY_GUIDE.md) · [Evaluation practice](docs/EVALUATION_GUIDE.md) ·
[Mobile API](docs/MOBILE_API.md) · [Features](FEATURES.md) · [Limitations](docs/LIMITATIONS.md) · [Test results](docs/TEST_RESULTS.md) ·
[Backtest results: stocks](docs/BACKTEST_RESULTS.md), [futures](docs/BACKTEST_RESULTS_FUTURES.md) · [Market data sources](docs/DATA_PROVIDERS.md) ·
[Screen validation](docs/SCREEN_VALIDATION.md) · [Windows verification](docs/WINDOWS_VERIFICATION.md) · [Architecture](docs/ARCHITECTURE.md) ·
[0.7 audit](docs/AUDIT_0.7.md) and [plan](docs/PLAN_0.7.md)

---

## Easiest: one double-click

1. Unzip the folder anywhere (for example `Documents\study-terminal`).
2. Double-click **`Install Study Terminal.cmd`**. If Windows shows "Windows protected your PC", click **More info > Run anyway**.
3. Wait 5-10 minutes. It installs Python and Inno Setup with winget if they're missing, builds the app, installs it and opens it.

After that, open Study Terminal from the desktop shortcut or the Start menu like any other app. To update, unzip the new
version and double-click the same file again.

Each new build also copies your existing data to `%LOCALAPPDATA%\StudyTerminal\backups\<date> before <build>` the first time
it starts, before opening the database (the last 10 are kept; `.env` and logs are never copied).

What it does and doesn't touch:
- Your data in `%LOCALAPPDATA%\StudyTerminal` (journal, paper accounts, settings, validation evidence, `.env`) is never read,
  moved or written by the installer scripts or the setup program.
- Nothing is installed unless the build and its self-test pass. The self-test uses a temporary data folder and ignores your `.env`.
- Before upgrading, the installed program files are copied to `%LOCALAPPDATA%\Programs\Study Terminal (previous version backup)`;
  if setup fails they're put back, and on success the copy is removed.
- Everything printed, including pip/PyInstaller/winget output, goes to `install-log.txt`; the setup program's own log is
  `install-setup-log.txt`.

## Get the installer without building on your PC (GitHub, free)

1. Create a free GitHub account and a new **private** repository, then upload this folder to it.
2. Every push to `main` builds the installer (or: **Actions** tab > **Build Windows installer** > **Run workflow**).
3. After about 15-20 minutes, open the repository's **Releases** page and download `StudyTerminal-Setup-<version>.exe`.
4. Run the `.exe` on your PC. It installs like any app; nothing else is needed.

The installer isn't code-signed, so Windows shows "Windows protected your PC" once: click **More info > Run anyway**.

## Option A: install like a normal Windows app (step by step)

You build the installer once on your PC (it can't be built on Linux, and an unsigned download would trigger
SmartScreen warnings anyway):

```powershell
cd C:\Users\<you>\dev\study-terminal
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1            # Python environment (once)
winget install JRSoftware.InnoSetup                                    # free installer compiler (once)
powershell -ExecutionPolicy Bypass -File .\scripts\build-installer.ps1  # ~5 minutes
.\dist-installer\StudyTerminal-Setup-0.13.0.exe
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
Futures research: Futures > Evidence > **Run research** in the app (per product; results are stored and shown there).
The report in `docs/BACKTEST_RESULTS_FUTURES.md` is generated from the bundled study's JSON:
`.\.venv\Scripts\python.exe -m research.futures_report research\out\futures_research.json`.

Developer commands (from `backend\`, any OS):
```powershell
.\.venv\Scripts\python.exe -m pytest tests            # full suite (no internet needed)
cd ..\frontend; npm ci; npm run build                  # rebuild the UI into frontend\dist (type-checks first)
```

## First session with your TopstepX chart (no data subscription)
Follow [docs/VISUAL_MONITOR.md](docs/VISUAL_MONITOR.md#windows-instructions): open your NQ/ES chart in TopstepX, then
**Live Visual Monitor > Set up a chart** (pick the Edge window, drag the region, Test read, Save) and **Monitor > Start monitoring**.

## First session (futures / TopstepX)
1. Switch to **Futures** (top left). The **Automation Center** opens and monitoring of NQ, MNQ, ES and MES starts in Mode A.
2. **Futures > Rules**: pick your Topstep preset, check every number against your dashboard, confirm. Set personal limits.
3. **Futures > Data & simulator**: Yahoo (delayed) works with no setup. For live data: ProjectX API Access subscription, key in `.env`,
   data source "TopstepX API" ([docs/LIVE_MARKET_DATA.md](docs/LIVE_MARKET_DATA.md)). Then open **Live Market**.
4. **Futures > Evidence**: see the bundled research or re-run it. Nothing is validated today, so ideas stay watch-only.
5. Practise in **Replay**, or live once you have a fillable feed. Check the **Journal** and the mentor ("why was this rejected?").
6. Optional: **Live copilot** for your TopstepX window (calibrate it first), and the **mobile companion**.

## First session (stocks)
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
