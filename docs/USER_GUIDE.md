# Using Study Terminal

Study Terminal is a research and paper-trading environment. It watches the market, looks for a fixed set of
setups, tells you how those setups have actually performed out-of-sample, and records everything you do so you
can learn from it. **It never trades real money and never places an order you didn't confirm.**

The one thing to understand first: in testing, none of the built-in setups has a reliable edge yet (see
`docs/BACKTEST_RESULTS.md`). So most of the time the honest answer you'll see is **NO TRADE**, with ideas listed
as **watch only**. That's the app working as designed, not a bug.

## The status strip (top of every page)
- **Market data meter**: how live prices are. Near real-time (Yahoo stream) > Polling (lags up to ~90 s) >
  Delayed / Historical / Cached / Stale > Unavailable. Hover for the reason. New signals need Near real-time or Polling.
- **Screen**: whether the screen copilot is watching (it never runs without your OK).
- **Paper equity, day P&L**: the simulated account.

Every quote shows where it came from and when ("Yahoo stream, price time 14:32:05 ET, 3s old"). Every chart shows
its bar source, when it was fetched, the newest closed bar, and data-quality checks (bad bars removed, spikes
flagged, missing candles counted).

## Scanner
Finds candidates from your watchlists plus Yahoo's gainers, losers and most-active lists. It runs every 3 minutes in
premarket and market hours, or when you press Run.

- **Filters**: price, % move, average volume, dollar liquidity, market cap, relative volume, volatility, setup quality.
- **Score**: a weighted mix of setup checklist, relative volume, move size, trend clarity and liquidity. The
  weights are judgment calls, shown next to every row ("Why it ranks here"). A setup with losing out-of-sample
  history is penalized; a fresh confirmed catalyst adds +5 (the direction of the news is never assumed).
- **Watch** next to a signal means the setup has no reliable edge.

## Signals
Each setup idea shows: entry range, stop, invalidation, targets, size for your risk setting, reward:risk, and a
plain-language explanation. The action comes from two things:

1. **Where the setup is**: developing → approaching → confirmed, or extended (don't chase) / invalidated / expired.
2. **How the setup has done out-of-sample** (from walk-forward tests you run on the Backtest page):

| Evidence tier | Meaning | What the app does |
|---|---|---|
| Untested / Too few trades | Fewer than 30 out-of-sample trades | Watch only |
| Lost money in testing / No proven edge | Average below zero, or the 95% interval includes zero | Watch only |
| Clearly lost money | The whole 95% interval is below zero | **NO TRADE** (study only) |
| Positive, not yet reliable | Interval above zero but < 100 trades, < 30 days, or inconsistent across test windows | Watch only |
| **Reliable** | Interval above zero, 100+ trades over 30+ days, positive in most test windows | **BUY / SHORT** allowed |

**STRONG BUY / STRONG SHORT** additionally need a high checklist score *and* a non-negative record in the current
market regime. A high checklist alone never makes a signal strong.

Signals also go watch-only from 15 minutes before to 15 minutes after a major scheduled release (FOMC, CPI, jobs,
GDP, PCE), and on stale, delayed, cached or closed-market data.

## News and catalysts (chart page, dashboard)
- **Headlines** from Yahoo Finance with source, time, link, and the app's labels: **Reported** (stated as fact by the
  publisher), **Unconfirmed** (rumour, "reportedly", "in talks"), **Opinion** (commentary, "stocks to buy"). Relevance
  (high/medium/low) says whether it's really about this symbol. These labels are keyword rules, not AI, and they're
  marked that way. The publisher's own summary is shown as theirs.
- **Earnings**: next date and time (and whether the company has confirmed it), EPS estimate, last reports with surprise %.
- **Analyst actions** (last 45 days): firm, old → new rating, price-target change.
- **Economic calendar**: FOMC (Federal Reserve site), GDP/PCE/trade (BEA site), CPI/jobs/PPI (BLS schedule bundled
  with the app, through Dec 2027).
- Not covered: FDA decision dates (no reliable free calendar), real-time newswires.

## Screen copilot (Live copilot page)
1. Pick a window or a monitor. Nothing is captured until you start it, and a red dot shows while it runs.
2. It reads the ticker, timeframe and visible price, checks them against market data, and runs the signal engine
   for that symbol and timeframe.
3. If the screen and the market data disagree by more than 0.5%, it tells you and uses market data.
4. Login screens and non-chart browser tabs are skipped. Frames are never saved. Pause/Stop from the page or the tray.
5. You can also upload a screenshot for a one-off read.

Measured accuracy on real TradingView screenshots: `docs/SCREEN_VALIDATION.md`. Webull, thinkorswim and IBKR
are untested; use `scripts\screen-eval.ps1` on your own screenshots to measure them.

**Optional Chrome extension**: follows your active TradingView tab using only its title and address (no screen
capture at all). See `extension/README.md`.

## Paper trading
- Order ticket: market, limit, stop (breakout entry) or stop-limit, with an optional protective stop and target
  (they become a one-cancels-other pair when the entry fills). **Preview first, then confirm.**
- **Load into paper order ticket** on a signal fills the plan in and links the trade to that signal, so the journal
  can compare what you did with the plan.
- Fills are conservative: slippage of max(1 bp, 1¢), stops that gap fill at the worse price, limits need price to
  trade through, stop first when one bar hits both.
- Risk limits (Settings): % risk per trade, daily loss limit, max positions, minimum reward:risk, required stop,
  pause after N losing trades in a row, max exposure. Orders that break a limit are rejected with the reason.

## Journal
Every paper trade and every signal is recorded automatically.

- **Trades**: entry, exit, stop, target, size, risk, P&L (realized and open), R-multiple, strategy, the conditions
  when you entered (market, data status, trend, regime, how stretched price was), the signal's confidence at that
  moment, and **whether you followed the plan** (each check listed: stop set, stop kept, entry inside the range,
  stop where planned, risk within your limit, exit at stop or target). You can override the verdict, add notes and tags.
- **Mistakes** detected from the records: late entry, chasing an extended move, exiting a winner early, holding a loser
  past the plan, no stop or removed stop, unfavorable conditions, too many trades (or a trade within 10 minutes of a
  loss), repeating a setup that's losing. Each shows its evidence and what it has cost you compared with your clean trades.
- **Performance**: win rate, average winner and loser, profit factor, expectancy, max drawdown, total R, average R,
  best and worst strategy, by ticker, time of day and regime. Filters for dates, ticker, strategy, direction, mistake
  and plan-followed.
- Closed trades are kept even if you reset the paper account.

## Backtest
Run **walk-forward** tests: parameters are chosen on one window and scored on the *next* window they never saw. Only
those out-of-sample results calibrate signals. The results page shows the evidence tier with 95% intervals, the
trade mechanics (how often trades reach +1R or +2R, how many are stopped within 2 bars, how many stopped trades later hit
the target, cost per trade), and results by strategy, ticker, timeframe, direction, regime, time of day, volatility,
streak and checklist score.

Treat the "results by…" tables as a microscope, not a tuner: picking filters from them and re-testing on the same
trades is curve-fitting.

## AI mentor
Ask in plain English: "Should I buy this?", "Where's my stop?", "What would invalidate this?", "Is this breakout
confirmed?", "Am I chasing?", "Why did this signal appear / get invalidated?", "What's the risk/reward?", "Why is it
moving?", "Which of my strategies has done best?", "What mistakes am I repeating?"

Every answer is built from the app's own data and split into labelled parts: **Observed** (facts from data),
**Interpretation** (the app's reading), **Historical evidence** (backtest and journal numbers), **Uncertainty** (what
isn't known), **If you…** (scenarios). It works offline. Claude or Ollama are optional: they rewrite the same
grounded data in friendlier language and are told never to invent prices, news or statistics.

## Learning
18 lessons with quizzes, a glossary, and "spot the setup" exercises on real charts. The mentor adapts explanations to
your level and the terms you've learned.

## Home, Simple mode and the top bar (0.12)
Study Terminal opens on **Home**, which answers five questions in plain words and shows a getting-started guide until setup is done.
The top bar is on every screen: **PRACTICE MODE** (always: there is no real-money mode), a health light (Working / Not watching /
Needs attention / Not working) and **Stop everything**. Stop everything stops chart watching, market checking and anything the app
was practicing by itself; to start again you write one sentence about why you stopped. **Simple / Advanced** changes only what is
shown. Advanced has every screen and the trading terms; your limits and safety rules are the same in both.

## Your data: backups, restore and help (0.13.4)

Settings > **Your data**. A backup is made every day you use Study Terminal and before every update; **Back up now** makes one
whenever you like. Each backup says when it was made and what's in it (journal trades, practice orders). **Restore** goes back
to one: Study Terminal backs up your current data first, restarts, and shows what it did. **Save a help file** puts a zip of the
logs, Chart check results and app status in your Downloads folder to send when something's wrong (no passwords or keys).

If the data file is ever damaged, Study Terminal opens a **Recovery** screen instead of the usual app: use the newest backup,
rescue what can still be read, or start with empty data. Whatever you pick, the damaged file is kept in a folder called
`damaged`. If another program is using Study Terminal's usual port, it quietly uses the next free one.

## Memecoins (0.14.0, practice only)

**Memecoins** in the menu. Paste a Solana token address (or search a name) to see its live price and a rug-risk check in plain
words. **Practice a trade** buys with pretend money: choose an amount, a stop (required) and, if you like, a take-profit. The
preview shows the estimated price impact, fees and what you'd lose at the stop. The practice account shows what each position
would fetch if sold now. Settings > Memecoins changes the starting amount and the cost assumptions, and takes an optional free
Solana RPC address that makes the "biggest holders" check work. Real memecoin trading is done outside the app; see
`docs/MEMECOIN_REAL_TRADING.md`.

## Check the odds and the last candle (0.14.0)

On any practice plan, **Check the odds** shows how often that exact stop and target worked out recently (past days and 10,000
simulated sessions). On Charts, **Last closed candle** describes the newest finished candle and has **Copy for an AI**.

## Weekends and closed markets (0.13.6)

Stocks and futures don't trade at the weekend (futures: Friday 5 PM to Sunday 6 PM ET), so their prices stay at the last real
price, with a countdown to the open. Bitcoin and Ethereum trade around the clock: tap them on Charts to watch prices move live
any time. Crypto is for watching only; practice trading covers stocks and futures.

## Health (0.13.5)

**Health** in the menu shows whether Study Terminal itself is OK: the app, your data file, backups (last good one and whether
the newest passed its check), the chart monitor, the Chrome extension, the last good start, recent errors and whether a restart
would help (with a **Restart** button). **Run the recovery check** tests backup, restore, rescue and a failed restore putting
everything back, on a scratch copy on your own computer; your real data is only read. **Save a complete help file** puts
everything needed to look into a problem in your Downloads folder.

Every backup is read back when it's made and checked again daily. A backup that didn't finish, is missing files or doesn't
match what was saved is shown in red and can't be restored. The newest usable backup is never deleted automatically.

## Trust & Validation
Menu > Trust & Validation shows nine validation statuses and the overall readiness level, with exactly what's still missing for the
next level. It only counts real recorded evidence. To add visual evidence, use Live copilot > Calibrate: upload a real TopstepX
screenshot, pick your Visual Monitor profile and type what the chart shows (price, contract, timeframe, last completed candle O/H/L/C,
VWAP and EMA values). Details: [TRUST_VALIDATION.md](TRUST_VALIDATION.md).

## Visual Monitor (your TopstepX chart as the input)
Menu > **Visual Monitor**. Set up each chart once (window, region, colors), then start monitoring. Full steps, labels and limits:
[VISUAL_MONITOR.md](VISUAL_MONITOR.md).

## Futures and TopstepX
Click **Futures** at the top left. The **Automation Center** opens: monitoring status and mode, controls including the
emergency stop, the latest decision per contract, recent decisions with every pipeline step, the practice account,
positions, automated vs manual results, and the locked live-execution checklist ([AUTOMATION_GUIDE.md](AUTOMATION_GUIDE.md)).
**Futures (TopstepX)** in the menu has the chart and ticket. **Live Market** has live-updating charts for NQ, MNQ, ES and MES from
1 minute to daily, with indicator and overlay toggles and a data-integrity panel ([LIVE_MARKET_DATA.md](LIVE_MARKET_DATA.md)). The status strip switches to the futures
simulator: balance, day P&L, room above the Maximum Loss Limit, which rules are active and whether entries are allowed.

- **Live**: pick a product (ES, NQ, CL, GC, MES, MNQ, or type a contract such as MNQZ26). You get the chart with
  session levels, the signal, the account and limits panel, a paper order ticket and the levels table. The data
  label matters: Yahoo's futures prices are delayed, so you'll see setups marked "for study only" and no signals.
- **Rules**: load a Topstep preset, check every number against your Topstep dashboard, then press confirm. Your own
  limits sit next to it and are kept separate.
- **Replay**: load a past session (last ~59 days), play or step through it, optionally with automation, in a separate
  account ([REPLAY_GUIDE.md](REPLAY_GUIDE.md)).
- **Evidence**: the bundled research run, or run walk-forward research for a product. Until a strategy is validated it
  stays watch-only and automation won't trade it.
- **Data & simulator**: data source (Yahoo or your TopstepX API subscription), slippage, partial-fill share,
  auto-flatten, delayed practice, and fees per product.

On the Live copilot page, set **Platform** to TopstepX (or leave it on automatic) and watch your TopstepX window as
you would TradingView. Study Terminal reads the chart, checks the contract and price against futures data, and
shows the futures signal. It can't place, change or cancel anything on your Topstep account. Use **Calibrate screen
reading** on that page to measure how well it reads your own TopstepX screenshots before relying on it.

The economic calendar shows each release's relevance and, for BLS releases, the last published actual and previous values.
You get an alert 30 minutes before each high-impact release (setting `events.warn_minutes`, 0 = off).
