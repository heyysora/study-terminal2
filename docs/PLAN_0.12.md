# Study Terminal 0.12.0: implementation and testing plan

0.12.0 is built in stages. The interface comes first (stages 1-3 of the product experience audit, `docs/UX_AUDIT.md`), then a full
test stop, then the new trading features, each added inside the simplified interface.

Permanent rules for every stage:

- The software does the complicated thinking; the user doesn't do complicated navigating. Simple mode is the default and must be
  understandable to someone who has never traded.
- Nothing is removed. Every existing screen stays reachable in Advanced mode.
- Trading logic, risk calculations, permissions and safety limits are not changed to make the interface simpler. The practice-only
  lock stays; there is no live order code.
- No paid service, account, API key or subscription is introduced.
- Existing user data (journal, practice accounts, settings, limits, chart profiles, validation evidence) is preserved.

## Part A. Interface foundation (this delivery)

### Data protection (before anything else)

| Item | What | How it is checked |
|---|---|---|
| A0.1 | No database layout change in this part. Three new settings keys only (`ui.mode`, `ui.setup_dismissed`, `ui.trades`). | Upgrade test 0.11.0 -> 0.12.0 on one data folder: files byte-identical, user-visible records identical. |
| A0.2 | Automatic backup: the first time a new build starts on an existing data folder, the database and data files are copied to `<data>\backups\<date> before <version>\` before the database is opened. The last 10 backups are kept. Backups are never deleted by anything else. | `test_backup.py` |
| A0.3 | A failed backup never blocks the app from starting and never touches the originals; it is logged and shown on Home. | `test_backup.py` |

### Stage 1. Safety and status bar

| Item | What | Existing code it uses | Risk |
|---|---|---|---|
| 1.1 | A permanent **PRACTICE MODE - no real money** badge on every screen. | health endpoint (`brokerage_connected`), automation `live.locked` | Low |
| 1.2 | One health light: **Working / Needs attention / Not working**, one sentence, one "what to do". It is the worst state of checks that already exist. | visual monitor status, market-data health, automation status, database check | Low |
| 1.3 | **Stop everything** on every screen. Runs the existing automation emergency stop, stops the Visual Monitor and stops screen watching. Asks for confirmation. | `automation.emergency_stop`, `visual.stop`, `screen.stop` | Low |
| 1.4 | "The engine isn't running" banner when the interface can't reach the backend. | WebSocket state + failed poll | Low |
| 1.5 | Always-visible risk line in plain words: practice money, today so far, most you can lose today, at risk right now, new practice trades allowed or stopped. | futures risk status / stock practice account | Low |

### Stage 2. Plain-language wording

| Item | What | Risk |
|---|---|---|
| 2.1 | One word list (`backend/app/plain.py`, exported to `frontend/src/plain.json`; a test fails if they drift). | Low |
| 2.2 | Every "don't trade" outcome is shown as **WAIT**, with a plain headline, the reason, and what to do. The original technical reason stays one click away. Stored decisions are not changed. | Low |
| 2.3 | Data status shown as Working / Slow / Chart isn't updating / Can't read the chart / Can't find the chart. The underlying status values are untouched (trading rules depend on them); delayed data is never called live. | Low |
| 2.4 | One word for pretend money: **Practice**. | Low |
| 2.5 | Technical terms that remain carry an everyday explanation (hover or tap). | Low |
| 2.6 | Simple / Advanced switch. Changes what is displayed only. | Low. `test_home.py` proves settings, limits and decisions are identical in both modes. |
| 2.7 | Scores and confidence shown as High / Medium / Low with "this is not the chance of winning". | Low |

### Stage 3. Home

| Item | What | Risk |
|---|---|---|
| 3.1 | Home answers five questions: Is Study Terminal working? What is the market doing? Should I practice a trade or wait? How much could I lose? What should I do next? Built by one read-only endpoint (`GET /api/home`) from existing services. | Low |
| 3.2 | "What should I do next?" comes from real state (no chart connected, chart not updating, limits not confirmed, stopped, and so on). | Low |
| 3.3 | First-time setup guide: choose what you trade, connect your chart, confirm your loss limits, start watching. Each step shows whether it is really done. | Low |
| 3.4 | Home is the start page in Simple mode. | Low |

### Test stop after stage 3

1. Backend unit and API tests on Python 3.11 and 3.13 (existing suite must stay green; new tests for backup, wording, Home, Stop everything, mode switch).
2. Frontend type-check and production build.
3. Screenshots of Home, the bar, a WAIT explanation and Advanced mode, checked by eye.
4. Upgrade test 0.11.0 -> 0.12.0 on one data folder.
5. Packaged self-test (PyInstaller, Linux) to prove the new modules are bundled.
6. Written list of what can only be checked on Windows.

## Part B. Remaining interface stages (after the test stop)

4. Five-section menu (Home, Charts, Practice, My Progress, Settings). 5. "Connect your chart" walkthrough. 6. One Settings
section and "My limits". 7. Practice and My Progress tidy-up. See `UX_AUDIT.md` section 9.

## Part C. 0.12.0 features (after Part A; each lands inside the simplified interface)

Order follows the brief's priorities: reliable observation first, then understanding, then decisions, then measurement.

| Stage | Feature | Already exists (to extend, not duplicate) |
|---|---|---|
| C1 | Reliability watchdog with HEALTHY / DEGRADED / STALE / UNREADABLE / DISCONNECTED / REQUIRES RECALIBRATION feeding the health light | Visual Monitor statuses, calibration-invalid detection, frozen detection, downtime tracker |
| C2 | Multi-timeframe analysis that only uses timeframes actually available | 5-minute + 15-minute check in the pipeline, session aggregation for all timeframes |
| C3 | NO TRADE engine as a named layer with plain reasons | 13-step decision pipeline, risk engine, event blocks |
| C4 | Trade quality score with visible factors, never shown as a probability | setup scoring, evidence tiers |
| C5 | Journal: plan snapshot, chart images, audit trail | futures journal, round trips, review log |
| C6 | Performance dashboard, with backtest / replay / practice kept separate | journal analytics, evidence, trust dashboard |
| C7 | Strategy lab | walk-forward research, holdout, registry |
| C8 | Session replay of recorded observations | futures replay |
| C9 | Economic calendar improvements | BLS schedule, event blocks |
| C10 | Order-flow investigation (report what is and isn't observable; UNAVAILABLE otherwise) | none |
| C11 | Optional local AI mentor | built-in assistant, Ollama provider |
| C12 | Trading profile | prop rules, personal limits, saved profiles |
| C13 | Desktop quality of life, backup/restore, export | tray app, hotkey, automatic backup (A0.2) |
| C14 | Trust & Validation categories for the new features; cost audit; changelog | trust dashboard |
