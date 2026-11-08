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
