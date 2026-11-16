# Changelog

## 0.19.2 (2026-11-16)

Two things about alerts arriving in time to be worth anything, and a page that shows you where the time goes.

**An entry alert that arrives after the price has gone is not sent**
- Reading your chart from pictures always costs a moment. Usually under a second; in a fast market, sometimes long enough that the price has already left the entry behind. Taking the trade then is a different trade from the one that was worked out: the same stop, now much further away, so a bigger loss if it goes wrong and less reward for the risk than the alert claimed.
- If the price has run more than a quarter of the way from the planned entry towards the stop, it is no longer sent as a trade. You get a quiet "missed" note instead, saying how far past it went. The setup may well have been right — the point is that entering there isn't the same bet.
- A price that moved *against* the entry gives you a better fill than planned. That is not late and is unaffected.
- Exits are never held back for being late. Getting out late still beats not knowing.

**Health > Speed**
- Every stage of one pass, timed: taking the picture, spotting that something changed, the price box, reading the words, turning it into prices and candles, deciding, alerting. Typical, slow (95th percentile) and worst, with the slowest stage highlighted.
- How often a pass actually happens, how many found nothing changed, how many ran late, and what the app is using in memory and CPU.
- What a screenshot cannot show — how long the market took to reach your screen — is named as not measurable rather than folded into a total.

## 0.19.1 (2026-11-16)

An exit no longer waits for the next full chart read.

- Study Terminal reads the price box about twice a second and the whole chart every couple of seconds. Until now a fresh price changed the number on screen and nothing else, so if your stop was hit a moment after a full read, you were told at the next one. For getting out of a trade, that gap is the whole point.
- A fresh price is now re-checked against the two things a price alone can decide: whether a trade being tracked has reached its stop or its final target, and whether a setup that was only ever "potential" has gone through the level where it stops being valid. Both are comparisons against levels worked out earlier by the normal rules from a full reading, so nothing is being judged more loosely — just sooner.
- **It can never open a trade.** A price box shows a number and nothing else: no candles, no indicators, no market structure, no session, no risk checks. Price moving is not a reason to trade, so there is no path from a price update to a BUY or a SHORT — those still wait for a full read. Ten tests hold that line, including one that throws prices from 1 to 99,999 at it and insists nothing is ever opened.
- The alert says where each half came from: the price off the price box, the level it was compared against from the last full reading.

## 0.19.0 (2026-11-16)

Two things: a test you can run on your own PC that proves whether the chart pipeline really works, and a chart read that is three and a half times faster.

**Prove it on your own machine**
- `scripts\acceptance-test.ps1` (or `StudyTerminal.exe --acceptance`) checks twelve things in order: which build this is, which libraries it's using, the text reader on known text, every part of the app doing real work, the engine, saving and reloading your chart settings, finding your actual Edge TopstepX window, capturing it, reading it, checking what it read, stamping it, and the live timings.
- The reading is checked against something independent: the price it reads off the pixels is compared with the price TopstepX itself puts in the tab's name. Two different routes to the same number. If they disagree, it fails and says by how much.
- A stage that can't run says so and why. It never counts as a pass, and the final verdict only says your chart works when all five chart stages earned it. The report is timestamped, keeps the evidence, and saves the picture it actually read.
- Then it walks you through the things only you can do: resizing the browser, switching tabs, minimising, changing instrument and timeframe, pulling the network, restarting, and leaving it in the background.

**A chart read is 3.5x faster**
- Measured first, at your capture size: a full read took 2,208 ms, and 97% of that was reading text. So that is what got fixed, and nothing else was touched on a hunch.
- The text reader was being handed shapes that made it slow. It resizes what it's given, so a wide short strip gets scaled up while a whole picture gets scaled down -- reading just the chart's header band cost *more* than reading the entire chart. Padding a strip towards square first: header band 2,146 ms to 664 ms, same words out.
- The chart's name line was re-read on every single tick, because TopstepX prints the live open/high/low/close into it, so its pixels always change. It now re-reads when the contract in the tab's name changes (noticed immediately), when the layout moves, or on an 8-second timer.
- Result: **2,208 ms to 638 ms** for a full read. The fast path that notices a price tick runs in 63 ms.
- A part of this was sitting in my working folder and had never actually been put into the app. That is why your copy was re-reading every word on the chart every time. It's in now.

**You can see where the time goes**
- Every stage is timed -- capture, change detection, price box, text, parsing, deciding, alerting -- with median, 95th and 99th percentile, and the slowest stage named automatically. Waiting for the next turn is counted separately from doing work, because one is a setting and the other is code.
- What a screenshot cannot see -- how long the market took to reach your screen -- is reported as not measurable, never folded into a total.

## 0.18.3 (2026-11-16)

Small follow-up to 0.18.2, from watching its own release checks.

- The packaged app reported every library version as "unknown", because the records those versions are read from weren't being included in the build. They are now. When there is still nothing to read, the check names the layout it found instead, which is the thing actually worth knowing: whether you have the version of the text reader that loads its parts by a name made up while running, or the one that doesn't.
- Nothing else changed. If 0.18.2 is working for you, this only makes Health more informative.

## 0.18.2 (2026-11-16)

The screen-text reader has never worked in any installed copy of Study Terminal. It does now.

**What was wrong**
- The reader loads three of its own parts by a name it reads out of a settings file while running. The tool that packages Study Terminal into an .exe works out what to include by reading the source code, so a name that only exists while the program is running is invisible to it, and those three parts were never put in the installer. The folders were there -- their settings files had been copied -- but with no code inside, so Python imported empty folders and the first thing asked of them failed: `AttributeError: module 'ch_ppocr_v3_det' has no attribute 'TextDetector'`.
- This could only ever happen in the installed app. In the source code every file is present, so all 629 tests passed and every build went out green while the installed app could not read a single character off your chart.
- Your second error -- `Unexpected token ',', "Internal S"... is not valid JSON` on the chart setup screen -- was the same fault. Test read called the dead reader, the engine answered with the plain words "Internal Server Error", and the page tried to read those words as data.

**The fix**
- Moved to a version of the reader that imports its parts normally, and pinned it. There is a catch, and it turned out to be the reason this happened at all: that version is only published for Python 3.12 and below, while the build was using Python 3.13 -- even though the build was written to ask for 3.12. It picked whichever Python it found first. So on 3.13 the only installable version of the reader was the one with the problem, and nothing ever said so. The build now uses the Python it asks for, and the pin follows the interpreter.
- The packaging list now also carries the reader's own code, so the version with the problem works too -- which matters if you run Study Terminal from source on Python 3.13.
- A failure of the reader is now its own thing, with its own words. It used to be reported as "I can't read your chart right now -- make sure nothing is covering the chart", which was useless advice for a problem that has nothing to do with your screen.

**The app now checks itself, inside the copy you installed**
- **Health > Screen text reader** runs the real thing on demand: the library, the parts it loads by name, the model files, starting the engine, and reading known text out of a picture. It prints every step and tells you the fix.
- **Health > This build** does the same for ten parts of the app -- fitting a model, opening a database, building a market calendar, decoding an image, constructing the crypto price client -- each doing a small piece of real work rather than just importing a name.
- Both run inside the packaged .exe during the release checks, and a release is now blocked if any of them fail. That gate is the thing that was missing: it is the only kind of test that could have caught this.

**Errors you can act on**
- A crash inside the engine now answers in a form the page can read, naming the fault and the line it came from, with the full detail in the log file. The page no longer turns a backend fault into a parsing error.
- The page tells apart: the engine not answering, a request taking too long, a crash, a refused request, and an answer it couldn't read.

## 0.18.1 (2026-11-16)

Your TopstepX chart reads now. Three separate faults were stopping it, and the app was telling you almost nothing about any of them.

**The timeframe is read off your chart**
- Your chart's label reads `NQZ26 · Nasdaq · 1`, and the picture-reader ran the timeframe into the open price next to it ("1O027,688"), so the `1` never survived. It is now pulled back off the front of that number, and the whole label is recognised wherever it sits on the picture -- not only in the top strip of the captured area.
- That label is the only shape accepted: contract, then exchange, then the timeframe. A loose number somewhere else on the chart can't be mistaken for it.
- If the captured area genuinely doesn't include the label, the timeframe you set yourself in **Set up a chart** is now used. It was being recorded but never counted, so setting it changed nothing -- every reading still ended as "timeframe uncertain". The chart showing a *different* timeframe than you set still blocks trade ideas, as before.

**A missing timeframe no longer blacks out the whole chart**
- Overall confidence was the lowest of five figures, and the timeframe was one of them. No timeframe meant 0.00, which meant "I can't read your chart right now" -- while the price, the axis, the market and 219 candles were all being read perfectly.
- The timeframe is a label on your screen, not a measurement off it, so it no longer drags that figure down. Your price and candles show; trade ideas still wait for a confirmed timeframe.

**Errors say what broke**
- "Internal error while reading the chart (AttributeError)" named the kind of fault and nothing else -- not the message, not where it happened. It now reads like `AttributeError: 'NoneType' has no attribute 'price' (visual_recommend.py:88)`, and the newest fault is kept in the chart status. No file paths, nothing from your screen.

**Sticking to the window you picked**
- Your Edge tab renames itself every time the price ticks ("NQZ26 $27,686.00 ... and 1 more page"). The app now stays on the window you picked when it renames, instead of letting go and hunting for it again, and it re-checks every ten seconds that the window id still belongs to the same program.
- A window that is *not* a browser can no longer be taken for your TopstepX chart. 0.17.0 matched any window titled like a contract -- a text file called `NQZ26 $27,686.00` would have been captured. TopstepX is a web page, so only a browser qualifies.

## 0.18.0 (2026-11-15)

The two things you said yes to: the app places practice trades by itself, and it re-tests its strategies every week.

**Practice trades without being asked**
- Automated practice trading (mode B) is now the default. When a strategy has passed testing, Study Terminal starts and manages its practice trades on its own, inside your risk limits, with pretend money. It was already built; it just had to be switched on by hand.
- If you had never picked a mode yourself, your app switches to it on this update. If you had picked one, your choice is kept. You can switch back any time in the Automation Center, and that choice then sticks.
- Nothing changes about real money. There is no order-routing code in Study Terminal and no setting that adds any.
- **Today this does nothing visible**, because no strategy has passed testing yet (NQ and MNQ inconclusive, ES and MES losing out of sample). The app will say so on screen, and will start trading by itself the day a strategy passes.

**Weekly strategy testing**
- Every contract is re-tested 7 days after its last test, with the same documented procedure on newer market data. It waits for that market to be closed so it stays out of the way, and runs anyway if it falls more than 11 days behind. One contract at a time; each takes a few minutes of your PC's time.
- It never changes a strategy, a parameter or a threshold. A strategy that stops meeting the bar stops trading on the next cycle; one that starts meeting it starts trading. Both are written to the automation log and sent as an alert.
- Every run is kept for good, so a later test can't hide an earlier poor result. The Automation Center has a new "Weekly strategy testing" panel with the schedule, the history and a "Test now" button.
- Switch it off with research.weekly in Settings.

**"Can I trust it?"**
- A new box at the top lists what fills in without you: chart checks, weekly strategy testing, and automatic practice trades, each with its current state.

## 0.17.0 (2026-11-15)

Faster start, every TopstepX window read, and "Can I trust it?" that fills in by itself. Also includes the 0.16.1 fix, which never shipped because a Windows check failed.

**It couldn't find your TopstepX chart (fix from 0.16.1)**
- The app looked for a tab with "TopstepX" in its name. The real tab is named after the contract and price, like "NQZ26 $27,927.25 ▼ -1.61%". It's now recognised when finding the window, in the window list, and by the privacy check. Bank, mail and other tabs are still refused.
- The contract is taken from the tab name when the chart header can't be read.

**Every TopstepX window**
- If you have more than one TopstepX chart open, each one is now read, not only the first. A browser only draws the tab in front, so each chart needs its own Edge window (drag the tab out of the window). Up to six.

**Faster**
- The window opens at once with a loading screen while the engine starts behind it, instead of nothing appearing until everything was ready.
- The first screens' data is fetched before you click, so Home and Charts open without waiting on a download.
- Start-up no longer waits for the futures monitor to catch up on market data.
- The market calendar loads about 100 times faster; a heavy library (scikit-learn) only loads when it's needed.
- The background data checks start a few seconds after launch, use fewer requests, and save their results off the main path.
- Unused fonts removed.

**"Can I trust it?" fills in by itself**
- Price, contract, timeframe and candle readings are now checked automatically while your chart is open: price against reference candles for the same minute, contract against the browser tab's name, timeframe and candles by comparing what's read from the picture with reference candles at every possible timeframe. These count the same as samples labelled by hand, so the first level (Visual validation) can be reached with no input from you.
- What it can't do: the later levels need strategy evidence and a record of practice trades. Right now no strategy has reliable out-of-sample results, so those levels stay open however long the app runs. They aren't faked.

**Windows checks**
- The recovery drill compared times to the second and could miss a rescue that finished in the same second it was asked for; fixed in the drill.
- The upgrade check now treats the app's own data-check records as expected changes.

## 0.16.1 (2026-11-14)

Fix: Study Terminal couldn't find or read the TopstepX chart in Edge.

- Cause: the app looked for a browser tab with "TopstepX" in its name. The real TopstepX tab is named after the contract and its price, for example "NQZ26 $27,927.25 ▼ -1.61%", with no "TopstepX" in it. So the window was never found, and a privacy check that only lets chart-looking tabs through would have refused it as well. Earlier tests used a made-up tab name.
- Now a tab named as a known futures contract followed by a dollar price is recognised as TopstepX: when finding the window, in the window list (marked with a star), and in the privacy check. Bank, mail and other tabs are still refused.
- The contract is taken from the tab name when the chart header can't be read, and a mismatch between the two is flagged.
- Tested with the exact tab name reported from a real PC. Not yet confirmed on that PC with this version.

## 0.16.0 (2026-11-14)

Study Terminal now checks its own data, by itself, all the time, and stops trade ideas when the data can't be trusted.

**Data check (new screen)**
- Every data source is checked in the background from the moment the app starts: is it reachable, fresh, still updating, the right symbol and timeframe, well-formed, and has its reply format changed.
- Where a second independent source exists, prices are compared. Crypto is compared across Kraken, Coinbase and Bitstamp. Solana token prices from DexScreener are compared with Jupiter and GeckoTerminal, and token identity with the Solana chain itself. Prices are never averaged: if two sources disagree, neither is trusted.
- Each source gets a status: Verified, Healthy, Delayed, Degraded, Stale, Conflicting, Unverified, Offline or Not supported. "Answering" is not the same as "right". Stock and futures prices can only reach Healthy or Delayed because no free second source exists for them.
- Results, outages and recoveries are saved on your PC for 45 days, with the app and check versions.
- A red banner appears on every screen when a source has a real problem.

**One safety check in front of every market**
- Stock ideas, futures ideas and memecoin practice buys all pass through one controller. It pauses a market when its data isn't Verified, Healthy or Delayed, when Stop everything is on, or in recovery mode. It can only pause; it can't place or change anything. One bad market doesn't pause a healthy one.
- After a restart, ideas wait for a fresh check instead of trusting the last result.
- Before a memecoin practice buy, that token's price is cross-checked. A conflict blocks the buy and says why.
- Open practice trades whose data has gone bad are flagged.

**TopstepX chart: automatic validation**
- Once your chart is connected, every reading is saved and later compared with reference candles for the same minute. No screenshots or manual comparing. Price reading counts as verified after 30 matches on two different days.
- Minimise/restore, covered tab, resize, frozen chart, contract or timeframe changes and restarts are recorded when they happen. Study Terminal still never clicks or types in TopstepX.
- Until your PC has real readings it shows as Unverified.

**FOMO and pump.fun**
- FOMO (fomo.family) has no developer API, and its Terms of Service forbid bots, scrapers and third-party tools from collecting its data. Nothing was connected. It shows as Not supported, with the reason. Tokens you find there can be pasted into Memecoins.
- pump.fun direct access shows as Not supported for the same kind of reason; its tokens are still covered through DexScreener and the chain.

**Not in this release**
- The iPhone app, crypto paper trading, the unified opportunity feed and background start with Windows. See docs/RELEASE_CANDIDATE_STATUS.md for the full plan and the release gates.

## 0.15.0 (2026-11-14)

New dark look, live crypto prices from exchanges, and more memecoin practice tools.

**Look**
- The app now opens in a dark exchange style: near-black background with a green glow, charcoal cards, one green accent, green pills for the active tab and the main button. The lavender aurora design is still there as the light theme (the sun/moon button at the top switches).
- Charts has a Markets column on the left: a card per coin with price, 24-hour change, a small trend line and the 24-hour high and low. Your stock list sits under it.

**Live crypto prices (ccxt)**
- Bitcoin, Ethereum, Solana, XRP, Dogecoin, Cardano, Chainlink and Litecoin prices now come from public exchange data (Kraken first, then Coinbase, then Bitstamp), a few seconds old instead of about a minute. Free, no account.
- The library used for this (ccxt) can place orders when it's given exchange keys. Study Terminal gives it none, has no setting that could, and switches off every order and account function. Health shows "Crypto prices: Read-only", and the installer's self-test fails if that lock is ever missing.
- Crypto is still watch only. If no exchange answers, the cards say so instead of showing old numbers as live.

**Memecoin practice**
- Exit plan: at your target you can sell only part (a quarter, half, three quarters) and keep the rest. The stop for the rest moves up to your buy price. An optional trailing stop follows the price up and never moves down.
- Sell half button on open positions.
- Practice journal: every finished memecoin practice trade with what it made or lost, how long you held it and how it ended. "Why I bought" and "What I learned" are only ever what you type; the app doesn't guess them.
- Hide amounts: hides dollar figures and keeps percentages, for sharing your screen.
- Rug-risk check has two new lines: whether the token lists any website or social links, and (for pump.fun tokens) whether it's still on pump.fun's starting curve or has graduated to a trading pool.

**Looked at and left out**
- Buying or selling real memecoins, wallets, token launches (pumpfun-agent-skill): real money and private keys, which stay outside the app. See docs/MEMECOIN_REAL_TRADING.md.
- Reading a real wallet's positions (pumpfun-utilities): the app's practice account has no wallet. Its journal idea and hide-amounts idea are what was used.
- From claude-trading-skills: exit strategies and pump.fun stages were used. Paid data services (Birdeye, Helius and others), prediction markets, tax tools and execution skills were not.

## 0.14.1 (2026-11-14)

New look, nothing else changed.

- Lavender background with a soft aurora glow at the top, white cards that float on a light shadow instead of borders, rounded pill buttons.
- One main button per screen in dark navy; active tabs and chips in a soft magenta. Font is now Inter.
- Green and red are only used for price moves, gains/losses and danger (darker shades so they're easy to read). The accent no longer flips colour with the market.
- Practice badge and Stop everything stay easy to spot. Dark mode follows the same style.
- No changes to trading rules, risk limits, data or safety checks.

## 0.14.0 (2026-11-14)

New: memecoin practice, an odds check for any plan, and a plain read of the last candle. Still practice only; real orders remain
impossible from Study Terminal.

- **Memecoins (Solana), practice only.** Watch new tokens with live prices from DexScreener (free), run a rug-risk check in
  plain words (can someone create more tokens or freeze yours, special token rules, pool size, age, selling pressure, biggest
  holders), and practise with a separate pretend-money account. Costs are modelled: price impact from the pool size, a 1% fee
  and a $0.05 network fee (editable). Every practice buy needs a stop; stops are checked about every 20 seconds and fill at the
  price seen then, so fast drops fill below the stop. Token names with slurs are hidden. The lists are labelled for what they
  are: tokens that paid DexScreener for a profile or a boost, not "trending". Study Terminal never holds a wallet or a key; a
  new safety test checks that no memecoin code can sign or send a transaction.
- **Real memecoin trading is kept outside the app.** `docs/MEMECOIN_REAL_TRADING.md` walks through pumpfun-cli in WSL with a
  separate small wallet, a dry run before every trade, and why the auto-sniper and AI-wallet tools were left out.
- **Check the odds** on any practice plan (Home, Charts, and the order ticket once a stop and target are set): how often the
  target came first, the stop came first, or neither by the close, on each of the last ~60 days and in 10,000 simulated
  sessions built from them, with a plain verdict ("close to a coin flip") and the break-even win rate. A simulation, not a
  prediction; costs aren't included. Idea from the day-trader skill pack (jakeschincariol/day-trader-skill).
- **Stock practice day-trading rules:** a warning from your 4th trade of the day (the journal's limit) and after 3:30 PM; set
  a limit in Settings to make either a hard stop. A reminder at 3:45 PM if practice trades are still open before the 3:55 PM
  flat time.
- **Last closed candle** card on Charts: the candle in words, its pattern, the market mood (trending up/down, sideways,
  jumpy), and how many of five checks point up or down (a count, not a win chance). **Copy for an AI** puts the same data as
  JSON on the clipboard to paste into Claude or any AI. Closed candles only, so it never changes after the fact. Idea adapted
  from AI Agent Lens (roan-maverick/tradingview-indicator-for-ai-agents), without its paid TradingView webhook or public tunnel.
- Fixed: crypto charts and analysis were cut down to stock-market hours; they now keep every hour.
- Faster start: screens load when first opened (initial download 695 KB -> 497 KB).
- Looked at and not added: Point72 csp (a C++ streaming engine; not needed at Study Terminal's data rates), Goldman Sachs
  gs-quant (needs institutional client credentials), Man Group ArcticDB (production use needs a paid licence), QuantOrb (a
  Solana memecoin holder scanner; its checks overlap the new rug-risk check), solana-sniper-mcp and pumpclaw (real-money
  wallet tools; see the guide).

## 0.13.6 (2026-11-14)

Prices that keep moving where the market really is moving, and honest "closed" screens where it isn't. No trading changes.

- **Each market by its own hours.** Stocks follow the stock exchange; futures follow CME Globex (Sunday 6 PM to Friday 5 PM ET,
  so they now count as open on weekday evenings); crypto is open 24/7. Before, everything used stock-market hours, so Bitcoin
  was labelled "Market closed" on weekends even though its price was current.
- **Watch something live at the weekend.** Charts has **Bitcoin** and **Ethereum** chips ("Open 24/7"). Their prices stream
  live from Yahoo's free feed (unofficial, can lag a little), the big price and the line update as it goes, and 1D means the
  last 24 hours. Crypto is watch-only: no practice trades or setups for it.
- **Whatever is on the Charts page updates live**, even if it isn't on your watchlist (it's followed while it's on screen).
- **Closed markets say so plainly.** Charts shows the official close, the after-hours price on its own line, and a live
  countdown to the open. My chart (TopstepX) shows "Futures closed for the weekend, opens Sun 6:00 PM ET" with a countdown
  instead of looking frozen. Home says the market is closed, gives Friday's real result (from daily bars) and the opening time.
- Prices are never invented: when a market is closed its last real price stays on screen, marked with when it was.

## 0.13.5 (2026-11-13)

Finishes recovery and reliability so ordinary problems can be fixed from inside the app. No trading changes.

- **Backups you can trust.** Every backup records each file's size and fingerprint and is marked finished only at the end; it
  is read back straight away and re-checked daily (or with **Check my backups**). Backups that didn't finish, are missing
  files or are damaged are shown in red and can't be restored. The newest usable backup is never deleted automatically, even
  if newer ones are bad. Settings and Health show the last good backup and whether the newest one passed, and the app warns
  when there's no usable backup.
- **Safer restore.** The new data file is built and checked before your current one is touched; if anything fails after
  that, your original is put back exactly. A backup that turns out damaged at restart changes nothing and is flagged.
- **Recovery screens explain themselves**: what went wrong, whether your data is safe, and for each option what it does,
  whether you could lose anything, and what happens next.
- **Health page**: app, data file, backups, chart monitor, Chrome extension, last good start, recent errors, whether a
  restart would help (with a Restart button), a recovery check you can run on your own computer, and a complete help file.
- **Chrome extension finds the app by itself** when it isn't on port 8765 (checks 8765-8804 and remembers the answer). A
  **Find Study Terminal** button, plus connection status and repair steps in Settings and Health.
- Fixed: after a quick restart the app could move to another port for no reason (Linux kept the old port briefly reserved).
- Fixed: the extension could wait forever when another program held its port without answering.

## 0.13.4 (2026-11-13)

Makes the problems found in the audit fixable from inside the app. No trading changes.

- **Recovery mode.** If your data file is damaged or the data folder can't be written, Study Terminal opens a plain Recovery
  screen instead of crashing: use the newest backup (shows when it was made and what's in it), rescue whatever can still be
  read, start with empty data, or save a help file. It restarts itself to do it. The damaged file is kept in `damaged\`.
- **Backups you can see and use.** Daily backups (newest 7 kept), **Back up now**, and **Restore** in Settings > Your data. A
  restore backs up your current data first. **Open my data folder** and **Open backups folder** buttons.
- **Help file.** One click saves a zip with logs, Chart check results and pictures, and app status to your Downloads folder.
  Passwords and keys are blanked out; `.env` is never included. Chart check has **Save my results to send**.
- If port 8765 is taken by another program, Study Terminal moves to the next free one by itself.
- If it can't start at all, it says so in plain words and saves a help file automatically.
- Home warns when the disk is nearly full.
- Trust & Validation accuracy is counted by session (screenshots from one session aren't independent) and needs samples from
  at least 3 different days to pass. The in-sample cost table no longer shows "promising" labels.
- Windows reliability now also checks Recovery mode, a restore on Windows, and starting with the port taken: 19 of 19 passed.

## 0.13.3 (2026-11-13)

Fixes from the post-feature audit (`docs/POST_FEATURE_AUDIT.md`, `docs/STUDY_TERMINAL_READINESS_REPORT.md`). No new features.

- **Fixed: a chart showing the wrong market could be reported as "Working".** The OCR version in the Windows app reads the "·" in
  a TopstepX chart title as ":", so the market name wasn't found and the chart's own setup was assumed instead. The title is now
  read correctly with either OCR version, and a clock time like "10:15" is never taken for a timeframe.
- **Stricter: if the chart's market or timeframe can't be read, no trade ideas.** Before, the setup's own values were trusted at
  high enough confidence to allow ideas. Now the watchdog shows "I can't see the market name on the chart" and ideas stop.
- **Releases are only published when every test passes on Windows and the Windows reliability checks pass.** 0.13.2 was
  published even though one Windows test failed (the bug above).
- The Windows upgrade check lists the build marker and Yahoo's cache as expected changes instead of failing on them; every other
  file must still be unchanged.

## 0.13.2 (2026-11-13)

- **Reliability watchdog**: one plain status per chart (Working, Working with problems, Frozen, Can't read, Not connected, Check
  chart settings, Off), restarts a stopped reading loop, warns once per change, notices if the app didn't close normally, and
  stops trade ideas when the chart can't be trusted or doesn't match its setup.
- **Chart check** (Phase 2 test tool): compare what Study Terminal reads with what your real TopstepX chart shows, and test
  resizing, zooming, switching tabs, minimizing, a frozen chart and restarting. Results and pictures are saved in your data
  folder. See `docs/REAL_CHART_TESTING.md`.
- Safety audit tests (`tests/test_safety_audit.py`) and an automatic Windows reliability run on every build (install, upgrade
  with data, backup, restore, uninstall, installer rollback, damaged database).
- Uninstalling without questions (silent) now keeps your data.
- **Known problem, fixed in 0.13.3**: a wrong-market chart could show as "Working" with the OCR version Windows uses.

## 0.13.1 (2026-11-13)

- **Charts (Simple mode) redesigned** like Home: big price, change today versus yesterday's close, a clean line chart with
  1D / 5D / 1M / 3M / 1Y and a Candles view, hover for the price at any time, quick-switch chips for your watchlist, and plain
  cards for "Should I practice a trade or wait?" (5-minute chart, the day-trading view), key prices, what's happening and news.
  The full trader page with every indicator is unchanged in Advanced mode.
- Chart time axes show dates at day boundaries instead of repeating "09:30".
- Home (stocks) leads with the actual move ("The stock market is down 0.39% today"); it no longer says "leaning up" while the
  S&P 500 is down.
- Simple mode shows only urgent pop-ups, one at a time; the rest go to Messages.
- More WAIT reasons in plain words.

## 0.13.0 (2026-11-13)

Release of the 0.12.0 preview work, for day trading practice. Everything below under "0.12.0 preview 2" and "0.12.0 preview 1" is
included: the live price read from your TopstepX chart about twice a second with a live line chart, light and dark themes, Home
with five plain answers and a setup guide, the safety bar (practice badge, health light, Stop everything), plain-language WAIT
explanations, Simple and Advanced modes, and an automatic data backup the first time a new version starts.

Practice trading, risk calculations, permissions and the practice-only lock are unchanged. 450 tests pass on Python 3.11, 3.13
and on Windows. Accuracy on your real TopstepX charts still needs checking (see docs/LIMITATIONS.md).

## 0.12.0 preview 2: live price and a cleaner look (2026-11-13)

Display and reading changes only. Practice trading, risk calculations, permissions and the practice-only lock are unchanged.

### Added
- **Live price from your TopstepX chart.** About twice a second Study Terminal reads only the price box on the chart's price scale
  (about 25 ms per read). A price is used only if it sits on the contract's price steps, matches where it sits on the price scale
  (fitted by the full chart read), and isn't a sudden jump of more than 40 ticks that the next read fails to confirm. Anything
  else is rejected and a full chart read is done instead. The full read (candles, indicators, analysis) still runs every few seconds.
- **Live price header and chart** on Home and My chart: big price, change since the session opened at 6:00 PM New York time (or
  since watching started), a line chart of accepted prices with 5 min / 1 hour / 4 hours / Today ranges, hover to see the price at
  any moment, and a Candles view (candles are estimated from the picture). Gaps in the line are times the chart couldn't be read;
  nothing is filled in. "How accurate is this?" shows how many prices were accepted and rejected.
- Prices are saved per day in `<data>\live_prices\` (two weeks kept) so today's chart survives a restart. Test and demo sources
  are never saved.
- **Light and dark themes**, following the Windows setting by default (button in the top bar). New typography, rounded cards,
  pill buttons, and one accent color that turns green or red with the day's move.
- API: `GET /api/visual/live` and `GET /api/visual/live/{profile}` (`range=live|1h|4h|day`); pushed `visual_price` messages.
  Chart profiles gain `live_seconds` (default 0.5; older saved profiles get the default).

### Not changed
- Practice trading (stocks and futures) works exactly as before.
- The live price is labeled as read from your screen, never as an exchange feed.

## 0.12.0 preview 1: interface foundation (2026-11-10)

First part of 0.12.0. It changes what is shown and adds a backup. It does not change trading logic, risk calculations, permissions,
stored data or the practice-only lock, and adds no dependency, service or cost.

### Added
- **Safety bar on every screen**: a permanent PRACTICE MODE badge; one health light (Working / Not watching / Needs attention /
  Not working) with a sentence and what to do; a **Stop everything** button with an in-app confirmation; a banner when the
  interface can't reach the engine; an always-visible risk line in plain words (practice money, today so far, most you can still
  lose today, at risk right now, new practice trades allowed or stopped).
- **Home**: five answers (Is Study Terminal working? What is the market doing? Should I practice a trade or wait? How much could I
  lose? What should I do next?), a getting-started guide whose ticks reflect real state, the last three decisions as sentences, and
  a "start again" box after a stop.
- **Plain-language layer** (`backend/app/plain.py`, mirrored in `frontend/src/plain.json`): every "don't trade" outcome reads WAIT
  with a headline, what to do, and the original reason under "More detail"; status words (Working / Old prices (delayed) / Chart
  isn't updating / Can't read the chart / Can't find the chart); everyday names and hover explanations for trading terms; "Practice"
  instead of paper/sim/simulator on labels; confidence shown as High / Medium / Low with "not the chance of winning".
- **Simple and Advanced modes** (Simple is the default). Advanced shows every screen and the original terms.
- **Automatic backup** of existing data the first time a new build starts (`<data>\backups\`), before the database is opened.
- API: `GET /api/home` (read-only), `POST /api/stop-everything` (needs `confirm: true`), `POST /api/start-again`, `GET /api/plain`,
  `POST /api/plain/explain`. Settings: `ui.mode`, `ui.setup_dismissed`, `ui.trades_chosen`.

### Changed
- The app opens on Home (the old stock dashboard is "Stock overview" in Advanced).
- Automation Center: the mode buttons read "I place practice trades myself" / "The app places practice trades for me"; the disabled
  "C - Live (locked)" button is replaced by one sentence saying real-money trading isn't part of Study Terminal. The lock itself is
  unchanged in the backend and still reported by the API.
- Recommendation card (Visual Monitor): leads with the plain reason; plan numbers use everyday labels in Simple mode.
- Error messages and alerts pass through the word list in Simple mode.

### Not changed (checked by tests)
- Risk limits, risk status, automation rules and the live lock are identical in Simple and Advanced.
- Data status values used by trading rules; delayed data is never labelled as working or live.
- Database layout. Existing journals, practice accounts, settings, limits, chart profiles and validation evidence load unchanged.

### Still to verify on Windows
See the list at the end of the delivery notes and `docs/TEST_RESULTS.md`.
