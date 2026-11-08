# Audit of Study Terminal 0.6.0 (before 0.7.0 work)

Date: 2026-11-08. Scope: the whole codebase, read against the "Master Development Directive" (automation,
TopstepX-first futures, production readiness). Every Critical and High item below was reproduced with a probe
script (`/tmp/audit/probes.py` during the audit; each one became a regression test when fixed).

Test baseline: 264 tests pass on Python 3.11 and 3.13. Passing tests did not catch the bugs below, which is the
point of this audit.

## 1. Defects

### Critical (wrong money, wrong risk, or unsafe behaviour in the simulator)

| ID | Problem | Reproduced how | Effect |
|---|---|---|---|
| C1 | **Restart loses stop-outs.** After a restart the futures simulator only looks at the newest bar, so a stop or target crossed while the app was closed or asleep is never processed. | Position with stop 5990; feed 8 bars after "restart", one with low 5980: position still open. | Simulated account shows a live position that should have been stopped out; P&L and drawdown wrong; automation would manage a trade that no longer exists. |
| C2 | **Fills on data that isn't fillable.** Auto-flatten at the flat time and Maximum-Loss-Limit liquidation fill at the last price even when the data is delayed or historical and practice mode is off. | Delayed data, practice off: flatten filled "at last price". | Simulated exits at prices that are 10+ minutes old, presented like normal fills. |
| C3 | **Holiday early closes ignored by the flat-by rule.** The flat time is a fixed 15:10 CT. On Thanksgiving the session halts at 12:00 CT, so the position is carried through the halt and no warning appears. | Thanksgiving 2026, position at 11:59 CT: still open, "195 minutes to flat", no warning. | Breaks Topstep's "flat before the product's close" rule in practice; overnight risk in the simulator. |

### High

| ID | Problem | Effect |
|---|---|---|
| H1 | End-of-day trailing floor uses the account value when the app first notices the new trade date (e.g. 17:10 CT at the reopen), not the value at the session close. | Floor can be wrong in either direction when positions are held into the close (auto-flatten off or app asleep). Reproduced: floor stayed $48,000 instead of $49,998. |
| H2 | Editing prop-firm rule values keeps them marked "confirmed" (the UI sends the old `confirmed: true`). Switching to a different account size keeps the old balance and floor. | The app can say your rules are confirmed when they no longer match what you confirmed; a 150K preset runs on a 50K account's numbers. |
| H3 | No duplicate-entry protection: the same signal can be submitted twice. | Automation (or a double click) can double a position. |
| H4 | Futures fills are persisted only as the last 2,000 inside one JSON blob. | Journal and performance lose older trades in long automated runs. |
| H5 | Futures signals and alerts are only computed when the page polls; there is no background futures monitor. | Nothing watches NQ/ES when the UI is closed; "monitoring" is not real for futures. |
| H6 | Economic-event gate is applied to displayed signals but not to simulator order checks. | A paper entry can be placed inside the CPI/FOMC window the app itself warns about. |
| H7 | Every decision's reasoning is discarded after the response (rejected setups, risk failures). | No audit trail for "why was this rejected"; mentor can't answer it later. |

### Medium

| ID | Problem |
|---|---|
| M1 | Futures data cache key ignores the lookback length (two requests with different `days` share one cache entry). |
| M2 | Futures feed has no bar validation (duplicates, out-of-order, impossible OHLC, future timestamps) and no missing-candle count across the whole loaded window; only today's largest gap is checked. |
| M3 | No sleep/downtime detection for futures; the equity monitor has it, futures doesn't. |
| M4 | Futures backtest reports no profit factor, maximum drawdown, average winner/loser; folds are consistency checks only and the rules were never validated on a held-out period. |
| M5 | Replay state lives only in memory; replay trades vanish on restart and aren't in any journal. No timeframe choice, no play/pause/speed. |
| M6 | Screen platform defaults to "auto" even in futures mode; screen-derived values and provider values aren't labeled by origin in every response. |
| M7 | Evaluation practice lacks trading-days count and an explicit status (in progress / target reached / failed). |
| M8 | Consecutive-loss lock cleanup in `on_clock` is convoluted (keeps then pops the same key). |
| M9 | Futures signal states are only NO TRADE/LONG/SHORT/HOLD/EXIT; no WATCH ONLY / WAIT FOR CONFIRMATION / INVALIDATED and no market regime or multi-timeframe check. |
| M10 | Economic calendar shows scheduled time and source only; no actual/previous values. Forecasts aren't available from any free official source. |

### Low

| ID | Problem |
|---|---|
| L1 | Futures events list and review log trimmed silently on save. |
| L2 | `futures_ok` variable in the desktop self-test is assigned but only used indirectly. |
| L3 | Frontend bundle is 544 kB (single chunk). |

### Security
No new problems found. The local API still requires the `X-Study-Terminal` header for state changes and rejects
foreign Host headers; the optional TopstepX client refuses non-read-only paths; secrets are redacted from logs.
A future remote/mobile interface does not exist yet and must not be added without authentication (Phase 10).

## 2. What already exists vs the directive

✅ done and tested · ◐ partly done · ✗ missing

| Directive area | Status | Notes |
|---|---|---|
| Stock environment, TradingView, journal, mentor, alerts, news | ✅ | 0.5.0 work, unchanged |
| Futures contract registry (10 products, ticks, expirations, roll, sessions, DST, holidays) | ✅ | C3 is a flat-time bug, not a session bug |
| Futures levels (VWAP, PDH/PDL, ON, OR, IB, profile, FVG, BOS/CHoCH, sweeps) | ✅ | anchored VWAP from arbitrary anchors ◐ (session/RTH only) |
| Regime classification, multi-timeframe confluence, volatility state for futures | ✗ | M9 |
| Futures signals | ◐ | 5 states; needs the 8 decision states and full pipeline |
| Strategy validation | ◐ | fixed-rule backtest; needs walk-forward with holdout and full metrics (M4) |
| Automation modes A/B/C | ✗ | |
| Background monitoring service for futures | ✗ | H5 |
| Deterministic decision pipeline with stored reasoning | ✗ | H7 |
| Automated trade management (partials, breakeven, trailing, invalidation exit, max hold) | ◐ | brackets with partial targets exist; rest missing |
| Topstep evaluation practice | ◐ | MLL/DLL/target/consistency/limits done; trading days and status missing (M7) |
| Futures simulator | ◐ | needs C1, C2, H1, H3, H4 |
| Replay | ◐ | M5 |
| TopstepX screen copilot | ◐ | synthetic-only validation; calibration workflow missing |
| TopstepX API (read-only data) | ◐ | client written, mock-tested; no streaming |
| Data reliability for futures | ◐ | M1-M3 |
| Centralized risk-control service | ◐ | futures risk engine exists; needs max trades/session, max slippage, freshness and event checks in one place |
| Automation Center UI | ✗ | |
| Mobile-ready API | ✗ | |
| Windows | ◐ | never run on Windows by this build process |

## 3. TopstepX API facts used for the plan (checked 2026-11-08)

- Topstep's API article: custom automated strategies and bots are allowed via the TopstepX/ProjectX API,
  subject to platform rules and the ban on high-frequency trading. VPS, VPNs and remote servers are prohibited
  for trading ("your server can watch and record, but it cannot trade"). **Live Funded accounts cannot trade
  through the API.** There is no sandbox; Topstep suggests a Practice account for testing. Cost $29/month
  ($14.50 with code "topstep"), billed by ProjectX.
- The ProjectX Gateway documents order placement (`POST /api/Order/place`: limit, market, stop, trailing
  stop, join bid/ask; bracket orders only in "Auto OCO Brackets" mode), plus account, contract, history, trade
  and realtime hubs (quotes, trades, depth).
- An older TopstepX FAQ page still says bots "are not currently supported"; the newer API article supersedes
  it, but the conflict is a reason to keep live execution locked until you verify it with Topstep yourself.

Study Terminal will keep using only read-only endpoints. Live execution (Mode C) stays locked; Phase 4 builds
the lock, the checklist and the interface boundary, with no order-placement code.
