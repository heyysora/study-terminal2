# Release-candidate operation: audit, status and continuation report

Last updated 2026-11-15, at Study Terminal 0.18.0. This is the working document for the whole operation. It is updated at every checkpoint so work can resume from it in a new session.

**Release-readiness decision today: not release-ready.** Five of ten gates are open (section 6). The Windows app is installable and tested on GitHub's Windows machine; the iPhone app doesn't exist yet; no strategy has enough evidence to be called profitable.

## 1. Briefs this operation follows

In the order they arrived on 2026-11-14:

1. Multi-market intelligence + native iOS companion (plan: `docs/PLAN_MULTI_MARKET_IOS.md`; its four questions are still open).
2. Autonomous data validation and self-testing.
3. Automated FOMO + TopstepX validation.
4. FOMO platform confirmed: https://fomo.family.
5. Complete product optimisation, hardening and release candidate (18 stages, gates A–J).
6. Final expansion: 30 capabilities, Global Trading Safety Controller.
7. A+ market monitor expansion (26 sections, phases A–G).

Brief 7 says to present the audit and plan before starting a large implementation; brief 5 says not to stop at an audit. Resolution used: the data-validation and safety-controller work was already under way when 5–7 arrived and is the first reliability item in all of them, so it was finished and released as 0.16.0. This document is the audit and plan. Nothing else large has been started.

## 2. What exists (audit)

About 26,700 lines of Python (FastAPI, SQLite via SQLAlchemy), 5,200 lines of React/TypeScript, 54 test files, 587 tests. Windows installer (PyInstaller + Inno Setup) built and checked on GitHub Windows Server 2025 on every release.

### Dependency map

```
desktop/launcher.py (window, tray, single-instance lock, restart, headless mode)
  └─ app/main.py (builds every service, one event loop)
       ├─ market_data  ── providers/yahoo(+stream) ─┐
       │    freshness, validation, hours, health    │
       │    exchanges (ccxt, read-only) ────────────┤ network
       ├─ memecoins ── sources (DexScreener, Solana RPC, Jupiter, GeckoTerminal) ─┘
       ├─ datahealth (checks, compare, probes, chartwatch, engine)  ← market_data, memecoins, screen
       ├─ safety (controller)                                       ← datahealth, futures.automation, recovery state
       ├─ analysis ← market_data          ├─ scanner ← analysis
       ├─ signals  ← analysis, paper, backtest, safety
       ├─ futures  ← provider, news, safety   (own contracts, sessions, setups, paper account, prop rules, replay, research)
       ├─ paper    ← market_data              ├─ journal ← paper, futures
       ├─ screen (capture, chart reader, visual monitor) → futures;  validation (chart check, trust);  watchdog
       ├─ alerts (Windows toasts, history)    ├─ news (calendars, BLS)   ├─ ai (optional local/own-key explanations)
       ├─ datacare, backup (backups, restore, recovery mode, help file)  ├─ settings (store)
       └─ api/* (routes), ws (live updates)  →  frontend (React)  ·  extension (Chrome, talks to the local app)
```

### Findings

| Area | Finding | Severity |
|---|---|---|
| Duplicate implementations | Two signal engines (stocks `signals/`, futures `futures/signals.py`) and three paper accounts (stocks, futures, memecoins) with their own fill models. They work and are tested; they share no record shape. | Medium: blocks a unified opportunity feed |
| Duplicate implementations | Two phone-facing designs: the existing `/api/mobile/*` (one shared token) and the planned companion API. | Low: old one folds into the new |
| Data structures | No single signal/opportunity record across markets; no opportunity lifecycle (watching → forming → confirmed …) outside futures decisions. | High for the monitor goals |
| Migrations | Tables are created on start; new tables are additive. There is no schema version number or migration history. Works so far because every change has been an added table. | Medium |
| Dependencies | `requirements.txt` uses version ranges, no lock file. Builds aren't reproducible byte for byte. | Medium |
| Update integrity | The installer isn't code-signed and the app doesn't verify updates (it doesn't self-update either; you install a new version yourself). | Medium; signing certificates cost money |
| Background operation | The app keeps running in the tray with the window closed and has a single-instance lock. There is no "start with Windows" option, no sleep/wake detection, no heartbeat gap report. | High for unattended monitoring |
| Monitoring status | Health line, watchdog, system health and now data health each report separately. No single RUNNING / PAUSED / … state. | Medium |
| Notifications | Windows toasts only. No phone delivery, quiet hours, per-category switches or delivery tracking. | High for the phone goal |
| Crypto | Watch-only. No crypto signals or paper account. | Medium |
| Memecoin engine | Lists what DexScreener promotes; rug check has 10 rules. No own scanner, snapshots over time, five-level risk scale, or liquidity-withdrawal watch. | Medium |
| Strategy evidence | Stocks and futures have walk-forward research and evidence tiers; untraded-signal tracking exists for futures decisions only. No maturity labels in the brief's wording, no drift monitoring. | High for gate E |
| Security | Local API bound to 127.0.0.1 with a header check; phone token hashed; secrets scrubbed from help files; ccxt locked. No formal threat model, no dependency vulnerability scan in CI. | Medium |
| Unused or abandoned code | None found that is dead. `docs/PLAN_0.7/0.8/0.12.md` are historical. | – |
| Features that look complete but aren't | "Can I trust it?" (Trust & Validation) depends on manual chart checks you haven't run; TopstepX automatic validation has no real readings yet; ML probability is "no model trained". All three say so on screen. | Disclosed |

Most important architectural weaknesses, in order: (1) no unified signal/opportunity record, (2) no single monitoring state with sleep/gap awareness, (3) no versioned migrations, (4) notifications tied to Windows toasts.

## 3. Completed in this operation

| Version | What | Verified |
|---|---|---|
| 0.15.0 | Dark exchange look; live crypto prices through ccxt locked to public data; memecoin exit plans, journal, hide amounts, stage and links checks | 552 tests on Linux (3.11, 3.13); Windows tests + 39 reliability checks on GitHub |
| 0.18.0 | Automated practice trading on by default (validated strategies only); weekly strategy re-testing with permanent history, alerts when the validated set changes; trust page shows what fills in by itself | 621 tests on Linux (3.11, 3.13); Windows checks |
| 0.17.0 | Real TopstepX tab title recognised; every TopstepX window read; window opens at once, first screens warmed, lighter start-up; automatic trust evidence (price, contract, timeframe, candles) | 611 tests on Linux (3.11, 3.13); 55 of 55 Windows checks on GitHub |
| 0.16.0 | Data-health engine, nine statuses, independent comparison, evidence store, outage history, Global Trading Safety Controller wired to stocks, futures and memecoins, per-token cross-check before practice buys, automatic TopstepX chart validator, FOMO and pump.fun classified, Data check screen, Windows data-health drill | See `docs/TEST_RESULTS.md` and `docs/DATA_VALIDATION_REPORT.md` |

## 4. Status against the A+ specification

Classes: 1 implemented and verified · 2 implemented, not adequately verified · 3 partial · 4 missing · 5 not feasible under the constraints · 6 not recommended.

| § | Area | Class | Notes |
|---|---|---|---|
| 1 | Market surveillance, cross-market, regime | 3 | Per-symbol regime exists (candle packet: trend up/down, range, high volatility); NQ/MNQ and ES/MES consistency checked in data health. Missing: breadth, correlation and breakdowns, regime history with reasons. Breadth for stocks needs many symbols from one free source; feasible only in a small form. |
| 2 | Opportunity detection and lifecycle | 3 | 10 stock setups and futures setups with developing/watch states; futures decisions are stored. Missing: one lifecycle (WATCHING → EXPIRED) with IDs, transition reasons and immutable history across markets. |
| 3 | Signal quality, separate confidences, disagreement, explanation | 3 | Evidence tiers, multi-timeframe summary, data gate, reasons. Missing: the five separate measures shown side by side; "reasons it may fail" and "what's missing" on every signal. |
| 4 | Microstructure | 5 / 3 | Order-book depth, aggressor side and real spread aren't in the free futures or stock data: not feasible. Crypto order books are available free through ccxt (not collected yet). VWAP and price impact for memecoins exist. Anything inferred from candles must be labelled as inferred. |
| 5 | Exit and position monitoring, protection limits | 3 | Stops, targets, trailing and part-sell (memecoins), daily loss, trade count, consecutive-loss pause, open-position cap, close reminder. Missing: thesis tracking, exit signals as first-class objects, correlated-exposure and duration limits, stop history. |
| 6 | Solana and memecoin surveillance | 3 | Mint as identity, 10 risk rules, stage, price cross-check. Missing: own discovery scanner, snapshots, lifecycle, five-level scale, duplicate-name detection. Wallet intelligence beyond largest holders: 5 on free data (needs transaction history the public RPC won't serve reliably). |
| 7 | Anomaly and event detection | 3 | Spike flags on bars, feed-interruption alerts, data-health findings. Missing: an anomaly record with severity, confirmed/suspected, resolution, and de-duplication. |
| 8 | Data quality, provenance, verification | 1 / 3 | Statuses, comparison, evidence, failure behaviour: built and tested in 0.16.0 (class 1 for the software, live-verified for crypto and Solana prices). Missing: per-value lineage from a displayed number back to its raw observation; expected vs actual update interval per source. |
| 9 | Unified ranking and categories | 4 | Scanner ranks stocks only. |
| 10 | Alert intelligence | 3 | Windows toasts, history, duplicate suppression by key. Missing: priorities per category, quiet hours, cooldown per asset, grouping, delivery status, phone delivery. |
| 11 | Sessions and calendar | 1 | Exchange calendar with holidays and early closes, futures sessions, crypto 24/7, countdown to next open. Maintenance window and rollover awareness exist for futures. |
| 12 | Economic and news awareness | 1 / 3 | Scheduled events (FOMC, CPI, jobs, GDP, PCE) from public calendars with watch-only windows; free news headlines with sources. Missing: crypto-protocol incident feed (no reliable free source identified yet). |
| 13 | Strategy performance and evidence | 3 | Walk-forward, out-of-sample, day-clustered intervals, evidence tiers that block BUY/SHORT without evidence. Missing: maturity labels as specified, preserved original results, drift monitoring with documented downgrade rules, performance by regime. |
| 14 | Paper-trading realism | 3 | Slippage, fees, tick sizes, point values, prop-firm rules, memecoin price impact. Missing: partial and missed fills, limit non-execution modelling, recorded assumptions per fill. |
| 15 | Observability and self-diagnostics | 3 | System health page, self-check, startup history, recent errors, watchdog for the chart monitor. Missing: CPU/memory/queue metrics, task-level watchdog with crash-loop protection. |
| 16 | Background operation | 3 | Tray, window can close, single instance, safe restart. Missing: start with Windows, sleep/wake detection, gap reporting, unified run state. |
| 17 | Security and privacy | 3 | See audit. Missing: written threat model, dependency scan. |
| 18 | UX | 2 | Simple mode, plain language, one question per card. Not verified with real users; scripted usability tests not written. |
| 19 | iPhone companion | 4 | Not started. Blocked on the notification decision. |
| 20 | User-controlled automation | 3 | Pause, Stop everything, per-setup switches, reset practice accounts. Missing: per-market and per-alert-category switches, device revoke (no devices yet). |
| 21 | Auditability and replay | 3 | Futures replay without look-ahead; decision log; alert history; data-health history. Missing: one event history across the system, replay of a whole monitoring period. |
| 22 | Release engineering | 3 | CI on Windows: tests, installer, fresh install, upgrade, recovery drill, data-health drill. Missing: dependency lock, uninstall test, long-duration runs, iOS build. |
| 23 | Advanced features to investigate | – | Evaluated in section 5; none added. |
| 24 | Global safety controller | 1 / 3 | Built and tested in 0.16.0: data reliability, Stop everything, recovery mode; per-market suppression; exits and monitoring left running. Missing inputs: strategy maturity, token risk level, application-health metrics; read-only safe mode as a named state. |

## 5. The 30 capabilities and the "investigate" list

| # | Capability | Status | Reason |
|---|---|---|---|
| 1 | Regime detection, adaptive selection | Partial / adaptive selection not recommended yet | Regime labels exist per symbol. Switching strategies by regime needs its own out-of-sample test first. |
| 2 | Multi-market confluence | Deferred | Needs the unified record (stage 7). |
| 3 | Signal conflict resolution | Partial | Multi-timeframe and data conflicts handled; cross-market not. |
| 4 | Correlation and anomaly detection | Partial | Same-index consistency and spike flags exist. |
| 5 | Opportunity ranking | Deferred | Stage 7. |
| 6 | Risk-adjusted setup scoring | Partial | Evidence tiers and reward/risk; no single transparent breakdown. |
| 7–9 | Execution realism, liquidity-aware fills, partial and missed fills | Partial | Slippage, fees, impact exist; partial/missed fills don't. |
| 10 | AI explanations grounded in data | Implemented and tested | Built-in explanations are assembled from computed facts; an optional model only rewords them. |
| 11 | Daily and weekly reports | Deferred | Cheap once the unified record exists. |
| 12 | Journal and mistake analysis | Implemented (stocks, futures, memecoins); not validated with real use | |
| 13 | Replay and guided learning | Implemented and tested (futures replay, lessons) | |
| 14–16 | Diagnostics, service recovery, backup monitoring | Implemented and tested on GitHub Windows | Self-check, restart, verified backups. |
| 17 | API schema-change detection | Implemented and tested (0.16.0) | Reply-format checks per source. |
| 18–19 | Notification prioritisation, delivery tracking | Deferred | Stage 13. |
| 20 | Global Trading Safety Controller | Implemented and tested (0.16.0) | Section 4, §24. |
| 21 | Safe mode, read-only diagnostic mode | Partial | Recovery mode is read-only and blocks ideas; not user-selectable. |
| 22 | Emergency shutdown | Implemented and tested | Stop everything survives restarts. |
| 23 | Version rollback, update verification | Partial / unsupported at $0 | Data is backed up before every upgrade and can be restored; installing the older version restores the app. Verified updates need a code-signing certificate (paid). |
| 24 | Demo mode with labelled simulated data | Deferred | Useful for first run; low priority. |
| 25 | Beginner and advanced modes | Implemented and tested | |
| 26 | Watchlists, customisable dashboards | Watchlists implemented; custom dashboards not worth implementing now | Adds clutter against the 10-year-old test. |
| 27 | CSV export, journal portability | Missing | No journal export exists. The whole data folder can be backed up and restored, and the help file can include it. Small to add; planned with stage 15. |
| 28 | Accessibility, multi-monitor | Partial | Keyboard focus and labels; contrast not audited; multi-monitor capture exists for the chart. |
| 29 | First-run onboarding | Implemented; not tested with real users | |
| 30 | Product documentation | Partial | 30+ documents; several guides in brief 5 §16 don't exist yet (iPhone pairing, notification troubleshooting). |

From the investigate list: natural-language summaries and daily/weekly reports belong in this release line (cheap, verifiable). Statistical anomaly detection and regime-transition detection in a simple, rule-based form: yes. Probability calibration: only once there are enough tracked signals; until then scores stay "setup quality". Lead/lag, Bayesian updates, similarity search, token relationship graphs, wallet clustering, liquidity forecasting, degradation forecasting: not now; each needs data the free sources don't give or a sample size that doesn't exist yet. Exchange-flow monitoring: needs paid data.

## 6. Release gates

| Gate | State | Evidence | What's missing |
|---|---|---|---|
| A Build integrity | **Windows: PASS. iOS: FAIL (not built)** | GitHub Windows build and installer per release | iOS project and build |
| B Regression integrity | **PASS** | 587 tests on Python 3.11 and 3.13; Windows suite | – |
| C Data integrity | **PASS for classification** | Every source has a status from real checks (`DATA_VALIDATION_REPORT.md`) | Stocks and futures prices have no independent confirmation; TopstepX chart has no real readings yet |
| D Trading safety | **PASS** | Controller tests; bad data → NO TRADE through the running app (simulated sources) | Not yet exercised by a real outage on Windows |
| E Strategy evidence | **FAIL** | Research and evidence tiers exist | No strategy has forward paper evidence in sufficient quantity; maturity labels and drift rules not built |
| F Windows reliability | **PARTIAL** | 55 of 55 checks on GitHub Windows for 0.17.0 (install, upgrade, recovery, data-check drill, real window start) | Start with Windows, sleep/wake, long-duration runs, uninstall test; nothing verified on your PC |
| G iPhone functionality | **FAIL** | – | Not started; needs the notification decision |
| H Security | **PARTIAL** | Safety audit tests, ccxt lock, no secrets in help files | Threat model, dependency scan, unsigned installer |
| I Recovery | **PASS on GitHub Windows** | Backup, restore, rescue, rollback drill | Not run on your PC |
| J Release usability | **PARTIAL** | Installer, user guide, in-app recovery guidance | Missing guides; no real-user test |

A failed or partial gate stays in this table until its evidence exists.

## 7. Remaining stages, in order

Order follows brief 5 §19, with two moves: the unified record comes before scanner improvements (everything else hangs off it), and background operation moves ahead of the iPhone app (the phone needs a dependable PC).

| # | Stage | Main work | Done when |
|---|---|---|---|
| 1 | Repository audit | This document | Done |
| 2 | Architecture cleanup | Schema version table and migration runner; dependency lock file; one config map | Old data files upgrade through numbered steps on GitHub Windows |
| 3–6 | Data integrity, FOMO, TopstepX validation, pump.fun/Solana | 0.16.0 | Done for the software. Open: real TopstepX readings on your PC |
| 7 | Unified opportunity record + lifecycle; monitor supervisor (one run state, heartbeat, sleep/gap report) | New tables; adapters from the three engines; nothing rewritten | Every idea from every market appears as one record with history |
| 8 | Scanner and signals | Crypto setups; exit signals; SELL vs SHORT rules; five separate confidence measures; ranking and categories | Tests; SHORT impossible where the venue has none |
| 9 | Memecoin engine | Own scanner, snapshots, five-level risk, liquidity-withdrawal watch | Tests on recorded real replies; a week of observations |
| 10 | Strategy evidence | Maturity labels, tracking of every signal, drift rules. Done in 0.18.0: results preserved run by run, automatic re-testing, automatic enable/disable of a strategy | Gate E has data to show, whatever it says |
| 11 | Background Windows operation | Start with Windows (opt-in), sleep/wake detection, task watchdog with crash-loop limit | Windows drill covers each |
| 12 | Security, database, performance | Threat model, dependency scan, uninstall test, profiling, long runs (1 h, 6 h, 24 h) | Reports with measured numbers |
| 13 | Notification hub + companion API + pairing | Categories, quiet hours, cooldowns, delivery log; encrypted LAN listener; QR pairing; revoke | Tests for every unauthenticated and revoked case |
| 14 | iPhone app | SwiftUI, five tabs, built on GitHub's Mac | Compiles; unit tests pass; you install and pair it |
| 15 | UI refinement, documentation, final audit | Missing guides; usability script; final gate table | Gates updated with evidence |

Each stage ships as its own Windows version with the full Windows checks.

## 8. Decisions needed from you

1. **Phone notifications:** free route (the free ntfy app delivers them; our app must be re-signed from your PC every 7 days) or Apple's Developer Program ($99 a year; our app receives them directly and stays installed for a year). A free Apple ID can't receive push in its own app at all. You can start free and switch.
2. **Away from home:** install Tailscale (free for personal use) so the app can reach your PC on cellular, or stay Wi-Fi-only.
3. **Crypto coverage:** start crypto ideas and paper trading with Bitcoin, Ethereum and Solana only?
4. **FOMO:** nothing can be connected within its rules. Do you want me to draft a short permission request to support@fomo.family for you to send?

If these stay unanswered I'll use: free route, Wi-Fi-only with Tailscale documented as optional, the three coins, and no request drafted.

## 9. What only you can do

- Open TopstepX in Edge, log in, and connect the chart under My chart once. Validation then runs by itself.
- Install each release on your PC (results so far are from GitHub's Windows machine).
- Later: install the iPhone build and scan the pairing code.

## 10. Exact next step

Stage 2 (schema version + migration runner + dependency lock), then stage 7. Start by reading `backend/app/db/session.py` and `backend/requirements.txt`; add `schema_migrations` with one row per applied step, convert the existing ad hoc `_migrate` into step 1, and extend `backend/research/upgrade_check.py` so the Windows upgrade test asserts the version table.
