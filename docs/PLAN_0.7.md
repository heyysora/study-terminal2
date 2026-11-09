# 0.7.0 implementation plan (dependency order)

Each phase leaves the app working and the full test suite passing before the next begins. Results of each phase
are recorded at the bottom of this file.

```
P1 correctness fixes ──► P2 data reliability ──► P3 risk service + decision pipeline ──► P4 automation engine
                                                         │                                    │
                                                         ▼                                    ▼
                                              P5 strategy research ──────────────► (eligibility feeds P3/P4)
P1 ──► P6 evaluation practice      P1/P2 ──► P7 replay      P2 ──► P8 screen calibration
P3/P4 ──► P9 journal, mentor, events ──► P10 Automation Center UI + mobile-ready API ──► P11 desktop, docs, delivery
```

| Phase | What changes | Main files | Risk to existing features | Depends on |
|---|---|---|---|---|
| P1 Correctness | Fix C1-C3, H1-H4, H6, M8. Restart replays missed bars; fills only on fillable data; flat time = earlier of the firm's flat time and the session's (holiday) close; EOD floor at the close; rule edits drop confirmation; account-size change requires reset; idempotent orders; fills stored in their own table. | futures/paper.py, futures/risk.py, futures/service.py, db/models.py | Simulator behaviour changes (intended). Existing futures tests must still pass. | — |
| P2 Data reliability | Futures feed monitor: per-contract status (REAL-TIME, DELAYED, HISTORICAL, REPLAY, CACHED, STALE, UNAVAILABLE), last update, bar validation (dupes, order, OHLC, future timestamps), missing-candle counts, backoff, sleep/downtime gaps. TopstepX default platform in futures mode, persistent; screen vs provider origin labels. | futures/data.py, new futures/feed.py, screen/* | Labels change wording; equity monitor untouched. | P1 |
| P3 Risk + pipeline | One risk-control service every simulated futures order passes through (adds max trades/session, max slippage, data freshness, event windows). 13-step deterministic decision pipeline with outcomes APPROVED / WATCH ONLY / WAIT FOR CONFIRMATION / REJECTED / INVALIDATED / NO TRADE, stored with full reasoning. Signal states and development status; regime; 15-minute confirmation. | new futures/pipeline.py, futures/risk.py, futures/signals.py, db/models.py | Signal JSON gains fields; UI must keep working. | P1, P2 |
| P4 Automation | Modes A (assisted), B (automated paper), C (live, LOCKED, no order code). Background monitor for NQ/MNQ/ES/MES with start/pause/resume/stop/emergency stop, downtime reporting, restart recovery. Mode B enters only pipeline-APPROVED trades; trade management per strategy (partials, breakeven, trailing, invalidation exit, max hold). Research sandbox account for experimental strategies, never mixed with validated ones. | new futures/automation.py, futures/paper.py, api routes | New background task; must not block the event loop or the stock monitor. | P3 |
| P5 Strategy research | Walk-forward with an untouched final holdout, full metrics (PF, max DD, avg win/loss, expectancy, CIs after costs), diagnostics by regime/session/trend/volume/entry lateness, cost sensitivity. Strategy registry: validated vs experimental, feeding the pipeline. Updated backtest report on real data. | futures/backtest.py, new futures/research.py | Evidence format grows; old evidence still readable. | P3 |
| P6 Evaluation practice | Trading days, evaluation status, multiple saved account profiles (Combine / Express Funded), clear official-vs-personal display. | futures/risk.py, futures/service.py | — | P1 |
| P7 Replay | Persistent replay sessions and trades (separate from live paper), timeframe choice, play/pause/speed, automated strategy in replay, review stats. | futures/service.py → futures/replay.py | Replay API changes shape; UI updated together. | P1, P2, P4 |
| P8 Screen calibration | Labeled screenshot workflow (stored only when you choose), accuracy report per field with confidence and failure cases, for TopstepX and TradingView. | screen/*, new screen/calibration.py | — | P2 |
| P9 Journal, mentor, events | Decisions in the journal; automated vs manual comparison; futures mistake analysis; mentor answers (contracts that fit, why rejected, nearest support, late entry); events with actual/previous where an official source publishes them, configurable warning lead time, event restrictions in risk. | journal/*, ai/assistant.py, news/* | Mentor answers for stocks must not change. | P3, P4 |
| P10 UI + mobile-ready API | Automation Center as the central futures screen; token-authenticated, read-mostly API for a future companion (status, signals, positions, P&L, risk, alerts, journal summary, mentor, pause/stop), localhost by default, documented. | frontend/*, api/routes_mobile.py, api/security.py | Navigation changes. | P4, P9 |
| P11 Delivery | Desktop: monitoring starts with the app; Windows verification attempt; guides (automation, paper, replay, evaluation, data, API); full tests on 3.11/3.13; frozen self-test; zip. | docs/*, desktop/*, installer/* | — | all |

## Phase log

### P1 Correctness (done)
Changed: futures/paper.py (fills only on fillable data; "reconcile" bars after downtime; pending flatten on the next fillable
bar; flat time = earlier of the firm's time and the session close; session equity recorded for the EOD floor; idempotent
signal orders; entries-per-session count), futures/risk.py (holiday-aware flat window, reset lock, flat-violation warning,
max trades per session, max slippage, event window, data-age setting), futures/service.py (restart reconciliation, rule edits
drop confirmation, account-size change re-bases a fresh account or requires reset, fills table, calendar into risk),
db/models.py (futures_fills).
Tests: 11 regression tests in tests/test_futures_p1_regressions.py (one per finding); full suite 275 passed (3.11).
Not verified: holiday close times still come from exchange_calendars, not CME notices.

### P2 Data reliability (done)
Changed: new futures/feed.py (bar validation: duplicates, order, impossible OHLC, future timestamps, off-tick and spike flags,
missing candles per session; source health with exponential backoff; downtime tracker), futures/data.py (validation on every
fetch, failures serve the last good copy labeled CACHED and blocking, UNAVAILABLE when there's none, TopstepX API failure falls
back to Yahoo only with an explicit DELAYED label and note, cache key includes lookback), futures/service.py (downtime gaps
logged and alerted; screen fusion lists the origin of every value), screen/service.py + settings (platform kept per mode,
TopstepX default in futures mode), frontend platform selector writes the per-mode key; REPLAY label.
Tests: 8 in tests/test_futures_p2_data.py; full suite 283 passed.
Not verified: behaviour against a real TopstepX API outage (mock only).

### P3 Risk service and decision pipeline (done)
Changed: new futures/pipeline.py (13 steps, outcomes APPROVED / WATCH_ONLY / WAIT / REJECTED / INVALIDATED / NO_TRADE, development
status, deterministic decision id), futures/features.py (regime: structure trend, VWAP side, ATR percentile volatility, day type),
futures/signals.py (UI signal = pipeline outcome; actions LONG, SHORT, HOLD, EXIT, WATCH ONLY, WAIT FOR CONFIRMATION,
INVALIDATED, NO TRADE), futures/service.py (evaluate_contract with a completed-bars-only 15-minute frame and the live 1-minute
price; decisions stored once per bar in futures_decisions; invalidation of the previous plan), futures/paper.py (data-age check in
the order path; order origin), api /futures/decisions, UI pipeline steps and regime.
Every simulated futures order still passes through one place: FuturesPaperEngine.preview -> RiskEngine.check_entry.
Tests: 15 in tests/test_futures_pipeline.py; full suite passes.

### P4 Automation engine (done)
Changed: new futures/automation.py (modes A assisted / B automated paper / C live LOCKED with a verification checklist and no
order-routing code; start/pause/resume/stop/emergency stop with a required review note to clear; monitor loop over NQ, MNQ, ES,
MES front contracts; one order per decision id, never acting on an old bar, no entry while a position or entry is working;
per-strategy management rules: partial at +1R, break-even, ATR trailing stop, max holding time, invalidation exit, entry
validity window; research sandbox account for strategies that pass everything except validation), futures/paper.py (modify_stop
records every stop change and only tightens by default), futures/service.py (sandbox engine persisted, both engines fed and
reconciled, automation state persisted, monitoring resumes after restart and autostarts with the app unless the emergency stop is
active), api /futures/automation*, /futures/sandbox.
Tests: 12 in tests/test_futures_automation.py; full suite 310 passed.
Not verified: a full trading session of automated paper trading on live data (only Yahoo delayed data is available here, and no
strategy is validated, so mode B currently approves nothing; the sandbox is where experimental strategies run).

### P5 Strategy research (done)
Changed: futures/backtest.py split into scan (setups per bar) and simulate (fills/costs), trades now carry regime, structure,
time of day, volume, VWAP side, entry lateness, MFE/MAE; new futures/research.py (walk-forward over development folds with a 4-set
parameter grid chosen only on earlier folds, one pass over a chronological holdout, metrics: win rate, avg winner/loser, expectancy,
avg R with CI, profit factor, max drawdown, costs; diagnostics; cost sensitivity; registry validated vs experimental),
futures/service.py (research endpoint; nothing is tradable until research validates it; bundled dated results on first run),
research/futures_report.py -> docs/BACKTEST_RESULTS_FUTURES.md, UI Evidence panel.
Real-data result (NQ, MNQ, ES, MES, 2026-08-31 to 2026-11-06): no strategy validated. NQ/MNQ positive OOS and on the holdout but
intervals include zero; ES/MES slightly negative. Mode B therefore approves nothing; the sandbox is where these run.
Tests: 4 in tests/test_futures_research.py.
Not verified: results beyond Yahoo's ~59-day window (no longer history is available without a paid source).

### P6 Evaluation practice + P7 Replay (done)
P6: evaluation status (in progress / target reached / target reached but consistency or trading days missing / failed), trading
days completed, winning-day progress for Express Funded payout paths ($150, 5 days, labeled "confirm"), optional minimum trading
days, saved account profiles (rules + personal limits) with reset when the account changes.
P7: new futures/replay.py: sessions persist across restarts (bars, orders, positions), 1- or 5-minute source bars, signals from
completed 5-minute bars only, 15-minute confirmation, optional automation on approved (and opt-in experimental) decisions with one
order per decision, review stats with automated vs manual replay trades; new futures/journal.py shared by practice, sandbox and
replay (round trips, automated vs manual comparison, futures mistake checks); fills record their origin.
Regression found and fixed: P1's holiday-aware flat time used the calendar date, so overnight bars (after 17:00 CT) were treated as
past the flat time and flattened. The flat time now belongs to the trade date; test added.
UI: replay play/pause/speed, timeframe, automation toggles, results; Rules tab shows evaluation status and profiles.
Tests: 7 in tests/test_futures_p6_p7.py + 1 regression; full suite 322 passed.

### P8 + P9 — screen calibration; mentor, published values, event warnings (done 2026-11-08)
- **Calibration** (`app/screen/calibration.py`, Screen page > "Calibrate screen reading"): upload your own screenshot, type contract/timeframe/last price,
  and the live monitor's reader is scored per field (ticker, timeframe, price within N ticks, price axis). Report per platform with sample count,
  95% Wilson range, ticker confidence when right vs wrong, and failure cases. Under 20 real samples a field is marked "not yet meaningful".
  Synthetic charts are scored but never counted. Images are stored only with the "keep" box ticked; results can be kept out of the report too;
  login screens are refused and nothing from them is kept; delete one or all. "Re-score" re-reads kept images after an update.
  **No accuracy figure is claimed for TopstepX: no real TopstepX screenshots were available in this build.** The only samples scored in tests are synthetic.
- **Published values** (`app/news/econ_data.py`): actual and previous for CPI, core CPI, PPI final demand, payrolls and unemployment from the BLS
  public API, one request per 6 hours, last good copy kept on refusal, optional `STUDY_BLS_API_KEY` (v2). Shown in the economic calendar with
  period and the BLS "preliminary" flag. Forecast column says "not available": no official free source. Relevance label per event kind.
  All five series were later checked live through the running app (P11): CPI and PPI for September 2026, jobs data for October 2026.
- **Event warnings**: one alert per high-impact release `events.warn_minutes` (default 30, 0 = off) before it, in the futures event log too.
- **Futures mentor**: new direct answers for "how many contracts fit" (risk engine's number, limits applied, can't be raised by the mentor),
  nearest support/resistance (levels from completed bars with tick distance), why a decision was rejected (failed pipeline steps + recent decisions),
  mistakes (futures journal), best strategies (research run, OOS and holdout, registry), late entry (distance as share of the stop), R:R.
  Context now carries recent decisions, the futures journal and the research run.
- Not covered: retail sales (Census) values, geopolitical events. Tests: `tests/test_p8_p9.py` (17). Full suite 339 passed (3.11).

### P10 — Automation Center and mobile API (done 2026-11-08)
- **Automation Center** (`frontend/src/pages5.tsx`, default page in futures mode): mode A/B buttons with C shown locked; start / pause / resume /
  stop / evaluate now / emergency stop (confirmation) and clearing with a written review note; monitored contracts and research sandbox toggles;
  per-contract table (data status, regime, decision, reason, last check); recent decisions expandable to all pipeline steps; automation log;
  practice account (balance, equity, day P&L, room to MLL and DLL, open risk, trades today, blocks, warnings, unconfirmed-rules notice);
  positions and working orders (managed vs manual); automated vs manual comparison; sandbox summary; live checklist; mobile access panel.
- **Mobile API** (`app/api/routes_mobile.py`, `docs/MOBILE_API.md`): off by default; bearer token shown once, stored as SHA-256; brake-only
  controls (pause, resume, emergency stop); no orders, mode, rule changes or clearing an e-stop; bad-token lockout; the app still listens on
  127.0.0.1 only; an optional private host name (STUDY_MOBILE_ALLOWED_HOSTS) is accepted for /api/mobile/* only. Mobile tokens can't be read
  or set through /api/settings. Not tested with a real phone or tunnel.
- Fix found while testing: `resume` during an emergency stop silently did nothing; it now refuses with an explanation.
- Tests: `tests/test_p10_mobile.py` (7). Full suite 346 passed (3.11).

### P11 — desktop, docs, version, verification (done 2026-11-08)
- Monitoring starts with the app (autostart) and the desktop `--self-test` now also checks that automation loaded with live execution locked.
- New docs: AUTOMATION_GUIDE, PAPER_TRADING_GUIDE, REPLAY_GUIDE, EVALUATION_GUIDE, MOBILE_API, LIMITATIONS, TEST_RESULTS; README, FEATURES,
  USER_GUIDE, ARCHITECTURE, DATA_PROVIDERS and TOPSTEPX (incl. §11 TopstepX API endpoints and Topstep's automation rules) updated.
- Version 0.7.0 (config, pyproject, installer, extension manifest).
- Live checks: app run against real Yahoo data (all futures DELAYED → NO TRADE, as designed); BLS values for all five series fetched.
- Bug found during live checks and fixed: futures messages formatted prices with `:g` (6 significant digits), so NQ prices like
  26952.25 printed as 26952.2. Replaced with an exact formatter in every futures module and the mentor; regression test added.
- Tests: 348 passed on Python 3.11 and 3.13; frontend build passed; PyInstaller bundle built and self-tested on Linux. Not run on Windows.
