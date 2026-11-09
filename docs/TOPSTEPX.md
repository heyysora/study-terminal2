# TopstepX and futures (0.7.0)

Study Terminal now supports two independent setups that share the mentor, alerts, journal, learning and
infrastructure:

| | Stocks | Futures |
|---|---|---|
| Platform on screen | TradingView (or any chart) | TopstepX (or futures on TradingView) |
| Market data | Yahoo stream + polling | Yahoo (delayed) by default; TopstepX API optional |
| Analysis | equity feature frame, 10 setups | futures sessions and levels, 5 setups |
| Risk | % of equity, stock simulator limits | prop-firm rules (Topstep presets) + your own limits |
| Simulator | stock paper account | separate futures paper account, plus replay |

Switch with the **Stocks / Futures** buttons at the top left. In futures mode the app opens on the **Automation Center**
([AUTOMATION_GUIDE.md](AUTOMATION_GUIDE.md)); **Futures (TopstepX)** has the chart, ticket, rules, replay and evidence.
TopstepX is the default futures platform, and NQ, MNQ, ES and MES are the products monitored by default.

**Topstep is the prop firm; TopstepX is its trading platform.** Study Terminal treats them separately: the
TopstepX adapter reads the platform's screen, and the Topstep presets describe the firm's account rules.

**What Study Terminal will not do:** place, change or cancel orders on TopstepX or any broker; log in to
your Topstep account; reverse-engineer private TopstepX endpoints; or claim to enforce Topstep's rules on
your real account. Prop-firm limits are applied to Study Terminal's own simulator only, and every warning
says so.

---

## 1. Contracts (`backend/app/futures/contracts.py`)

Built-in products, checked against CME Group contract-spec pages on 2026-11-07 (the source URL is stored
with each spec and shown in the API):

| Root | Exchange | Point value | Tick | Tick value | Months | Last trade | Roll (front-month switch) |
|---|---|---|---|---|---|---|---|
| ES | CME | $50 | 0.25 | $12.50 | H M U Z | 3rd Friday, 8:30 CT (previous business day if a holiday) | Monday before the 3rd Friday (CME's roll-date page) |
| MES | CME | $5 | 0.25 | $1.25 | H M U Z | same | same |
| NQ | CME | $20 | 0.25 | $5.00 | H M U Z | same | same |
| MNQ | CME | $2 | 0.25 | $0.50 | H M U Z | same | same |
| YM | CBOT | $5 | 1 | $5.00 | H M U Z | same | same |
| MYM | CBOT | $0.50 | 1 | $0.50 | H M U Z | same | same |
| RTY | CME | $50 | 0.10 | $5.00 | H M U Z | same | same |
| M2K | CME | $5 | 0.10 | $0.50 | H M U Z | same | same |
| CL | NYMEX | $1,000 | 0.01 | $10.00 | every month | 3 business days before the 25th of the prior month (4 if the 25th isn't a business day) | 3 business days before last trade (**convention**, editable) |
| GC | COMEX | $100 | 0.10 | $10.00 | G J M Q V Z | 3rd-last business day of the month, 12:30 CT | COMEX First Position Date: 2 business days before the month's first business day |

- All prices go through exact Decimal tick rounding. P&L is ticks × tick value × contracts.
- Micros count 1/10 of a mini against prop-firm position limits.
- Symbols are read the way platforms show them: `ESZ6`, `ESZ26`, `ESZ2026`, `/ES`, `/MNQZ6`, `ES1!`, `ES=F`,
  `ESZ26.CME`, `CME_MINI:ESZ2026`, and ProjectX IDs like `CON.F.US.ENQ.Z25`. A bare `ES` is accepted when you type
  it into Study Terminal, never when read from a screen (ES is also a stock ticker).
- **Adding products:** create `futures_products.json` in your data folder (`%LOCALAPPDATA%\StudyTerminal`) with
  a list of objects using the same fields as the table. Added or overridden products are always flagged
  "user defined", never "verified".
- Business days for expirations use the NYSE holiday list from exchange_calendars, which matches CME settlement
  holidays closely but not perfectly. Check CME's product calendar before relying on an exact last-trade date.

## 2. Sessions (`sessions.py`)

- Times are exchange time (America/Chicago); daylight saving is handled by zoneinfo.
- A trade date starts at the Globex open the evening before (17:00 CT) and ends at 16:00 CT. Bars at
  18:00 CT Tuesday belong to Wednesday. The daily 16:00-17:00 CT break, weekends and holidays are "closed".
- RTH is configurable per product. Defaults: index futures 8:30-15:00 CT (cash-market hours), CL 8:00-13:30 CT,
  GC 7:20-12:30 CT (CME's reference session). These are conventions and are labeled as such.
- Holidays and early halts come from exchange_calendars' CMES/CBOT/NYMEX/COMEX calendars, covering about a
  year ahead. Holiday halt times there can differ by minutes from CME's published holiday schedule (for example
  the Friday after Thanksgiving); the session panel says so on early-close days.

## 3. Levels, structure and setups (`features.py`, `setups.py`)

Computed bar by bar so every value only uses data up to that bar (a test recomputes on truncated history to
prove it):

- Session VWAP (from the Globex open) with ±1σ bands, RTH VWAP
- Previous day high/low/close (previous trade date's RTH) and previous Globex session high/low
- Overnight high/low, pre-RTH hour high/low
- Opening range (15 min) and initial balance (60 min), shown only once complete
- Volume profile for the prior RTH session and today: POC, value area (70%), high- and low-volume nodes
  (approximate: built from bar volume, not ticks)
- Swing highs/lows, break of structure and change of character, unfilled fair value gaps, liquidity sweeps
- ATR and recent average volume

Five fixed setups (no parameters fitted to data): **liquidity sweep and reclaim** of PDH/PDL/ONH/ONL/IB,
**opening-range breakout retest**, **VWAP reclaim/loss with a break of structure**, **first close outside the
initial balance on above-average volume**, and **trend pullback into a fresh FVG**. Every plan is tick-rounded
with entry range, stop, a 2R target, next level beyond it, invalidation and the conditions that triggered it.

Anti-chase rules: no entry more than 0.5 ATR past the trigger level; nothing after a 1.5-ATR move in three
bars; no stops inside 0.4 ATR (noise); no entries in the last 20 minutes before the flat-by time; no setup if
a key level sits within 0.75R in the path to the target.

## 4. Signals (`signals.py`)

LONG / SHORT / HOLD / EXIT / NO TRADE. In order:

1. **Data must be live and complete.** Stale, historical, cached or unavailable data, or a hole of 20+ minutes in
   today's bars: NO TRADE with the reason. Delayed data (Yahoo) still gets the levels and the setups, labeled
   "Delayed data: for study only, not a signal".
2. An open simulator position in that contract gets **HOLD** or **EXIT** (flat-by time within 10 minutes, a
   change of character against the position, no stop).
3. A high-impact release (CPI, FOMC, jobs, GDP, PCE) within 15 minutes: watch-only.
4. **LONG/SHORT only when the futures backtest for that setup and direction is "reliable"**, the same evidence
   rule stocks use. Otherwise the setup is shown as watch-only and the answer is NO TRADE.
5. The plan must also pass your risk checks. Suggested size is the smallest of: your per-trade dollar risk
   (including slippage and fees), the position limit, and what fits inside the Maximum Loss Limit, the Daily
   Loss Limit and your own daily limit.

Each signal carries the contract, market-data timestamp, timeframe, entry range, stop (and ticks), target,
dollar risk per contract, suggested contracts, R:R, conditions, nearby levels, invalidation, evidence tier and
status.

## 5. Topstep rules and your own limits (`risk.py`, `prop_presets.json`)

Two layers that are never merged:

- **Official (prop firm):** presets for Topstep Trading Combine and Express Funded 50K/100K/150K, plus "Custom".
  Each preset starts **unconfirmed**; you check the numbers against your Topstep dashboard and press confirm.
  Every field is editable: starting balance, Maximum Loss Limit and its type (end-of-day trailing, intraday
  trailing or static) and lock level, Daily Loss Limit, profit target, consistency %, max contracts, micro
  ratio, flat-by time and no-new-entries time.
- **Personal:** max risk per trade, max daily loss, max contracts, losses in a row before a break, stop-for-the-day
  profit, minimum R:R, max open risk, stop required, RTH only, no-trade windows.

Preset values and where they came from (checked 2026-11-07):

| Rule | 50K / 100K / 150K | Source |
|---|---|---|
| Maximum Loss Limit | $2,000 / $3,000 / $4,500; end-of-day trailing, watched in real time including unrealized P&L; locks at the starting balance (Combine) or $0 (Express Funded, which starts at $0) | help.topstep.com "What is the Maximum Loss Limit?"; topstep.com blog "Static vs. Trailing Drawdown" |
| Profit target (Combine) | $3,000 / $6,000 / $9,000 | Topstep Combine parameters, as summarized by several third-party guides; confirm on your dashboard |
| Consistency (Combine) | best day ≤ 50% of the profit target | same |
| Position limit (Combine) | 5 / 10 / 15 minis or 50 / 100 / 150 micros | same; Topstep's TopstepX page confirms the 10:1 ratio |
| Daily Loss Limit | optional at checkout ($1,000 / $2,000 / $3,000); off in the presets | help.topstep.com DLL article; Live Funded Account rules describe the soft breach (flatten, locked until 5:00 PM CT) |
| Flat by | 3:10:00 PM CT; Topstep starts flattening at 3:08; trading resumes 5:00 PM CT | help.topstep.com "When and what products can I trade?" |
| Express Funded position size | Scaling Plan (tiers not included: enter your current tier) | help.topstep.com |
| News | allowed at your own risk; maximum size into major news is prohibited conduct | help.topstep.com "What are economic releases?" |

A CPI-window restriction described by some third-party sites could not be confirmed on an official Topstep
page, so it isn't enforced; the economic calendar still warns before CPI.

What the simulator does with them: shows balance, day P&L, the trailing floor and the room above it, Daily
Loss Limit left, your own daily limit left, open risk, max/remaining contracts, profit-target progress,
consistency and minutes to the flat-by time. It warns at 50% / 75% / 90% of each loss limit and 20 minutes
before the flat time. When a limit is hit it blocks new paper entries:

- Maximum Loss Limit: positions are flattened (simulated liquidation) and the account stays locked until you
  reset it, as it would end a real account.
- Daily limits and the flat window: locked until the next session at 5:00 PM CT.
- Losses in a row: locked until you write a review note (at least a sentence) or the next session.

## 6. Futures simulator and replay (`paper.py`)

Separate from the stock simulator. Market, limit and stop orders, brackets with a protective stop and
targets, per-contract round-turn fees (TopstepX's published totals: ES/NQ $3.78, MES/MNQ $1.22, GC $4.32;
RTY/M2K derived; YM, MYM and CL have no verified number yet, so only the commission is charged and every fill
says so), tick slippage on market and stop orders, partial fills capped at 10% of each bar's volume, stop
assumed first when a bar touches both stop and target, auto-flatten at the flat-by time, end-of-day trailing
floor updated when the trade date closes.

- No credentials or Topstep account are needed.
- It only fills on live data. With the default Yahoo feed (delayed) you can either turn on **delayed practice**
  (fills are labeled and won't match the live market) or use **Replay**: load any of the last ~59 days, step
  through it bar by bar, and trade it in a separate replay account.

## 7. Screen copilot with TopstepX

- Pick the platform on the Live copilot page (or Settings): Detect automatically, TradingView, TopstepX or Other.
  Detection checks TopstepX first because its tab hosts a TradingView chart.
- TopstepX's charts are built-in TradingView charts, so the same local OCR reads the legend, timeframe, price
  axis and price tag. On a TopstepX screen only futures symbols are accepted; it never falls back to a stock
  ticker.
- Cross-checks: the contract is resolved (a root like `/MES` assumes the front month and says so); the visible
  price must be on the contract's tick grid (otherwise it was probably misread); the visible price is compared
  with futures market data. With delayed Yahoo data a gap is expected, so the check only flags large mismatches
  (over 1%: wrong month or misread) and says why. With the TopstepX API the tolerance is 0.3%.
- Account and position panels are read only if you turn on "Read account/position panels on screen" (off by
  default), and are always marked unverified and never used in calculations.
- All existing privacy controls apply unchanged: explicit consent, one chosen window, pause/stop, frames kept in
  memory only, login screens skipped, non-chart browser tabs not captured.

## 8. Futures data sources

| Source | Real-time? | Coverage | Streaming | Needs | Cost | Limits | In Study Terminal |
|---|---|---|---|---|---|---|---|
| Yahoo Finance (default) | No: Yahoo reports a 10-minute delay on CME futures (checked 2026-11-07 for ES, MES, NQ, CL, GC) | Specific contracts (ESZ26.CME) and continuous front month (ES=F) | No | Nothing | Free | Unofficial; 1-min ≈ 7 days, 5-min ≈ 60 days | DELAYED: levels and study only; no signals, no live fills |
| TopstepX API (ProjectX Gateway) | Yes (included with the subscription) | Products tradable on TopstepX | SignalR hubs; Study Terminal polls REST bars | Topstep account, ProjectX API Access subscription, API key | $29/month, $14.50 with code "topstep" | retrieveBars 50 / 30 s; others 200 / 60 s; 20,000 bars per request | Optional, read-only, POLLING when fresh |
| Databento | Yes | Full CME Globex | Yes | Account + CME license | From $32.65/month non-pro license + usage, or $199/month plan | Usage-based | Not integrated (paid); the provider interface is ready |
| Your screen | As fast as your screen | What's visible | Capture | Screen monitoring on | Free | OCR can misread | Cross-check only, never a price for signals or fills |

**Setting up the TopstepX API (optional).** Subscribe on the ProjectX dashboard, link it in TopstepX >
Settings > API, generate a key, then add to `%LOCALAPPDATA%\StudyTerminal\.env` (never in the UI):

```
STUDY_PROJECTX_USERNAME=your_topstepx_username
STUDY_PROJECTX_API_KEY=your_key
```

Restart, choose "TopstepX API" under Futures > Data & simulator. A TopstepX API key can place real orders;
Study Terminal's client can only call login, contract search, historical bars and (only if you turn it on)
account balances. Any other path is refused before a request is made, and a test checks that. Keep the key
private: it's redacted from logs like other secrets.

## 9. Futures research (`backtest.py`, `research.py`)

Same fill rules as the simulator, one contract, fees and 1 tick slippage per side on market and stop orders, flat time
respected. Walk-forward over development folds with a parameter grid chosen only on earlier folds, then a final
chronological holdout. Full report: [BACKTEST_RESULTS_FUTURES.md](BACKTEST_RESULTS_FUTURES.md). Summary of the run bundled with
0.7.0 (Yahoo continuous 5-minute bars, 2026-08-31 to 2026-11-06, holdout 2026-10-27 to 2026-11-06):

| Product | OOS trades | OOS avg R (95% interval) | Holdout | Tier |
|---|---|---|---|---|
| NQ | 50 | +0.29 (−0.24 to +0.84) | 17 trades, +0.39R | inconclusive |
| MNQ | 42 | +0.42 (−0.07 to +0.86) | 17 trades, +0.39R | inconclusive |
| ES | 68 | −0.07 (−0.35 to +0.22) | 14 trades, −0.12R | losing |
| MES | 81 | −0.03 (−0.27 to +0.21) | 20 trades, −0.10R | losing |

**No strategy is validated**, so automated paper trading approves nothing and every futures setup stays watch-only.
The Nasdaq results are worth re-testing as data accumulates; with 17 holdout trades they can't be told apart from luck.

## 10. What could not be tested against a real TopstepX environment

These parts were built from documentation and tested with synthetic or recorded data only:

1. **Screen recognition of real TopstepX screenshots.** No TopstepX account or screenshots were available. The
   TopstepX adapter was tested on synthetic chart images in TradingView's layout with futures legends
   (`MESZ6`, `ESZ2026`, `/MNQ`). TopstepX's exact window title, legend format, colors, DOM and order-panel layout
   are unverified. To validate: save screenshots named `topstepx_MESZ26_5_7402.25.png` and run
   `scripts/screen-eval.ps1` as for TradingView.
2. **Account/position panel reading on TopstepX.** The label words used ("Position", "P&L", "Qty", "Avg") may
   not match TopstepX's panels. It's off by default and never used in calculations.
3. **The TopstepX API client.** Written from the ProjectX Gateway docs (login, contract search, retrieve bars,
   account search, rate limits) and tested against a mock server. Not run against the real API. Unknowns: whether
   `live: true` or `false` is right for your subscription (a setting), exact timestamp formats, and contract names
   for every product (looked up by name, never guessed).
4. **Topstep's rules on a live account.** The presets come from Topstep's help center and third-party summaries.
   How Topstep computes the end-of-day balance at the exact moment of the 3:10 PM flat, holiday trade-date merges,
   and the Express Funded Scaling Plan tiers were not verified against a real account.
5. **TopstepX fees for YM, MYM, CL** (not in the fee table that was readable), and whether fees differ by
   account type.
6. **Live futures signals and live paper fills.** With only Yahoo's delayed data available, the live path was
   tested with recorded bars and a fake live label, not a live feed.
7. **Holiday hours** come from exchange_calendars and were not checked against CME's holiday notices.
8. **Windows.** The desktop build has not been run on Windows by this build process.
9. **Automation against live data.** Mode B and the sandbox were tested with recorded bars, replay and injected clocks; they have
   not run against a live fillable feed (that needs the TopstepX API subscription).
10. **Screen-reading accuracy on TopstepX.** The calibration tool (Screen page) measures it on your own screenshots; no accuracy
    figure is claimed until real TopstepX samples have been scored.

## 11. TopstepX API: what exists, what Study Terminal uses

Sources checked 2026-11-08: ProjectX Gateway docs (gateway.docs.projectx.com) and Topstep's help article "TopstepX API Access".

| Area | Documented by ProjectX | Used by Study Terminal |
|---|---|---|
| Authentication | `POST /api/Auth/loginKey` (username + API key → session token) | Yes |
| Contracts | `POST /api/Contract/search` | Yes (contract ids are looked up by name, never guessed) |
| History | `POST /api/History/retrieveBars` (max 20,000 bars; 50 requests / 30 s) | Yes |
| Accounts | `POST /api/Account/search` | Only if you turn on account reading; display only |
| Orders | `POST /api/Order/place`, cancel, modify, search (limit, market, stop, trailing stop, join bid/ask; brackets only in Auto OCO mode) | **No.** Not implemented. The client refuses any path outside the four above before a request is made, and a test checks this. |
| Positions / trades | search and close endpoints | No |
| Real-time | SignalR user and market hubs (quotes, trades, depth) | No (REST polling only; labelled POLLING) |

Topstep's rules for API use (as published): custom bots are allowed through the API, no high-frequency trading;
VPS, VPNs and remote servers may not be used for trading; **Live Funded accounts may not trade through the API**; there is no
sandbox (Topstep suggests a Practice account); the subscription costs $29/month ($14.50 with code "topstep").
An older TopstepX FAQ still says bots aren't supported. Because of that conflict, and because order behaviour has never been
tested on a Practice account, live execution stays locked. See the checklist in the Automation Center.

