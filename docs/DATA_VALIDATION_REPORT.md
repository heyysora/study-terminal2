# Data validation report (0.16.0)

Written 2026-11-14. This covers the data-health engine, the FOMO investigation, TopstepX automatic validation, and pump.fun/Solana checks.

The aim of this system isn't to make Study Terminal say its data is trustworthy. It proves what it can, says what it can't, and stops trade ideas when the data isn't trusted.

## 1. What was built

| Piece | File | What it does |
|---|---|---|
| Checks | `backend/app/datahealth/checks.py` | Candle shape, volume, order and duplicates, timeframe, missing candles, sudden jumps, symbol identity, freshness, "still updating", reply format. |
| Comparison | `backend/app/datahealth/compare.py` | Compares the same instrument across sources. Never averages. Allows for spread and timing. |
| Probes | `backend/app/datahealth/probes.py` | One per source: Yahoo stocks, Yahoo futures, three crypto exchanges, DexScreener (against Jupiter, GeckoTerminal and the chain), Solana public RPC, pump.fun, FOMO. |
| Chart validator | `backend/app/datahealth/chartwatch.py` | Records every reading of your TopstepX chart and later compares its price with reference candles for the same minute. |
| Engine | `backend/app/datahealth/engine.py` | Runs probes in the background from start-up, classifies, stores evidence, tracks outages and recoveries, re-checks troubled sources every minute. |
| Safety controller | `backend/app/safety.py` | One gate in front of stock signals, futures signals and memecoin practice buys. Can only say no. |
| Screen | `frontend/src/pagesDataHealth.tsx` | "Data check" in the menu. Plain sentence first, detail underneath, full technical report as JSON. |
| API | `backend/app/api/routes_datahealth.py` | `/api/datahealth`, `/report`, `/run`, `/history/{source}`, `/chart`. |
| Evidence | tables `datahealth_records`, `datahealth_outages`, `chart_observations` | Timestamp, source, status, every finding, each source's own values, app version, checks version. Kept 45 days. No secrets are stored; none exist for these sources. |
| Windows drill | `backend/research/datahealth_drill.py` | Runs the installed Windows app against the real sources and checks the results are honest and survive a restart. |

Reused, not duplicated: the existing bar validator (`market_data/validation.py`) still cleans bars before use; the freshness tracker still labels each quote; the Visual Monitor still does the capturing and reading. The new engine sits above them.

## 2. Statuses and what each one allows

| Status | Meaning | Trade ideas |
|---|---|---|
| VERIFIED | Passes its checks and an independent source agrees on the price. | Allowed |
| HEALTHY | Passes its checks. Nothing independent exists to confirm it. | Allowed, marked as not independently confirmed |
| DELAYED | Passes its checks but is known to run behind. | Allowed, marked delayed |
| DEGRADED | A check is failing: bad candles, wrong symbol or timeframe, rate-limited, changed format. | No |
| STALE | Too old, or stopped updating while the market is open. | No |
| CONFLICTING | Independent sources disagree by more than venues normally differ. | No |
| UNVERIFIED | Not enough evidence. | No |
| OFFLINE | Can't be reached. | No |
| UNSUPPORTED | No legitimate way to connect. | Not used |

"Not confirmed" for a field is never counted as a pass. After a restart the previous result is shown but not trusted: ideas wait for a fresh check.

## 3. Live results against the real sources

Run from the build machine (Linux) on 2026-11-14, a Saturday. US stock and futures markets were closed, so freshness and "still updating" could not be judged for them and are recorded as not confirmed.

| Source | Status | Independently confirmed | Not confirmed |
|---|---|---|---|
| Crypto exchanges (Kraken, Coinbase, Bitstamp) | VERIFIED | Price: three exchanges agreed within 0.06–0.41% on BTC, ETH, SOL | Volume (each exchange reports only its own), liquidity (order books aren't collected) |
| Solana token data (DexScreener) | VERIFIED | Price: matched Jupiter and GeckoTerminal for the two reference tokens. Token identity: the chain's own record matched (decimals). | Liquidity (sources measure different things), volume, buy/sell counts, age, holders: one source each. Creator activity: unsupported. |
| Stock prices (Yahoo) | HEALTHY | Nothing | Price (no free second source). 7 of 10 fields pass. |
| Futures prices (Yahoo, delayed) | DELAYED | Nothing | Price. Mini and micro contracts agreed with each other (0.00%), but both come from Yahoo. 8 of 11 fields pass. |
| Solana public RPC | HEALTHY | Nothing | Block number advanced; read from one address only. |
| pump.fun (direct) | UNSUPPORTED | – | See section 6. |
| FOMO (fomo.family) | UNSUPPORTED | – | See section 5. |
| TopstepX chart (your screen) | UNVERIFIED | – | No TopstepX chart exists on the build machine. See section 4. |

The Windows results for the same checks, run by the installed app on GitHub's Windows machine, are in `docs/TEST_RESULTS.md` for this version.

No source was too unreliable to support ideas at the time of the run. That is one weekend observation, not a reliability record; the engine now keeps that record day by day (the technical report has a 7-day table per source).

## 4. TopstepX chart validation

How it works: every reading the Visual Monitor makes on your PC is saved (status, contract, timeframe, price, how the price was obtained). About 20 minutes later, when the delayed free data has caught up, the 1-minute reference candles around that reading's own time are fetched and the price has to fall inside their range, with 0.06% allowed either side. That compares the same contract at the same moment.

Per feature:

| Feature | Can it be verified automatically? |
|---|---|
| Price extraction | Yes. Counts as verified after 30 matches on 2 different days with at least 95% matching. |
| Contract (symbol) | Partly. A wrong contract puts the price far outside the reference range, so it follows price extraction. |
| Timeframe | No. It's read from the chart's own label and nothing independent can confirm it. Stays unverified. |
| Candle values | No. They're estimated from the picture. |
| Frozen chart, minimise/restore, covered or other tab, resize, contract or timeframe change, restart, Edge closed | Recorded when they happen on your PC, with whether the reader recovered. |
| Browser zoom, internet loss, session expiry | Can't be told apart by looking. Zoom would need keys sent to the page; internet loss looks like a frozen chart; a logged-out page looks like an unreadable chart. Listed as not testable. |

Not built, deliberately: Study Terminal doesn't resize, minimise, switch tabs or change anything in Edge to create these situations. Doing so on a trading platform's page, unattended, wasn't judged worth the risk, and changing zoom, timeframe or contract would mean typing or clicking in TopstepX, which the app never does.

Current status: UNVERIFIED everywhere. The logic is tested with simulated screens only. It needs your PC with TopstepX open and logged in; once the chart is connected under My chart, validation starts and continues by itself. One caveat: the reference is the front-month continuous contract. If your chart shows a later month, its price differs legitimately and readings will show as mismatches.

The chart reading never produces trade ideas by itself, whatever its status.

## 5. FOMO (fomo.family)

Platform: https://fomo.family, a social crypto trading app (web, iOS, Android) from FOMO Labs Inc. It lists memecoins, new tokens and top gainers, supports Solana among other chains, and has copy trading and perpetual futures.

What was checked on 2026-11-14:

- The official site has no developer, API or SDK page. Its links are product pages, a help centre, blog, terms and privacy.
- Third-party write-ups and unofficial tools all say the same: there is no public API. The unofficial routes are (a) a reverse-engineered copy of the web app's private API that needs your login token copied out of the browser, and (b) paid services reselling collected data.
- Terms of Service, section 16: no downloading or searching the services by unauthorised automated means (bots, crawlers, data-mining tools); no scrapers collecting pricing, transaction or account data; no third-party tools retrieving data unless Fomo authorises them; no sharing session tokens for that; no reverse engineering.
- robots.txt allows search engines on most public pages and disallows `/token`, `/coin`, `/profile` and similar.

Conclusion: there is no legitimate way for Study Terminal to read FOMO's data. Reading the public pages with a program is what section 16 forbids; the private API needs a copied login token and reverse engineering, which the Terms and this project's own rules both rule out; the paid resellers break the $0 budget and rest on the same collection.

So nothing was connected and nothing was fetched from FOMO by the app. Every capability is UNSUPPORTED:

| Capability | Status | Live test |
|---|---|---|
| Token name and mint, price, market cap, volume, liquidity, buys/sells, holders, age, creator, price history, trading pairs, risk indicators, token discovery | UNSUPPORTED | None run. No permitted endpoint exists to test. |

What still works: a token you see on FOMO is an ordinary Solana token. Paste its address into Memecoins and Study Terminal checks it through DexScreener, Jupiter, GeckoTerminal and the chain.

What would change this: Fomo Labs publishing an API, or giving written permission (support@fomo.family). No credentials are needed from you now, and none should be given to any unofficial tool.

The automated tests for FOMO are simulated only: they check that the app reports it as unsupported and never as passing.

## 6. pump.fun and Solana

- pump.fun documents its on-chain programs (for sending transactions). It runs no documented data service, and the addresses its own website calls are undocumented, so they aren't used. Direct integration: UNSUPPORTED.
- pump.fun tokens are covered indirectly. Discovery, price, pool size and trade counts come from DexScreener. Stage (still on the starting curve, or graduated to PumpSwap) comes from which exchange DexScreener lists the token on. Mint and freeze authority and Token-2022 rules come from the chain.
- Bonding-curve progress as a percentage isn't shown: reading the curve account from the chain is possible in principle but isn't built, and public write-ups disagree on the graduation threshold.
- Before every memecoin practice buy the token's price is now cross-checked against Jupiter and GeckoTerminal. If they disagree by more than 3%, or DexScreener's reply is malformed or for another token, the buy is refused with the reason. If no second source answers, the buy is allowed with a warning that the price is unconfirmed.

## 7. Signal protection

- Stocks: `signals/service.py` asks the safety controller before every evaluation. If it says no, the signal engine receives a closed gate and returns NO TRADE with "Data check: …" as the reason.
- Futures: `futures/service.py` asks after the strategy has run. If the controller says no, whatever the strategy said becomes NO TRADE, the reason is added, and the suppressed action is recorded.
- Memecoins: preview and buy both go through the controller and the per-token cross-check.
- Crypto: watch-only, no ideas either way.
- Open practice trades whose data has gone bad are listed on the Data check screen with a warning that their stop, target and profit figures may be wrong until the data recovers.
- The controller also closes every market when Stop everything is on or the app is in recovery mode. One bad market doesn't close a healthy one.
- A test reads the source to confirm each of the three paths calls the controller and that the controller has no override.

## 8. Tests

All counts are for this release. Simulated tests prove the software reacts correctly to good and bad data. They prove nothing about any live source.

| Kind | Where | What | Result |
|---|---|---|---|
| Automated unit tests (simulated data) | Linux, Python 3.11 and 3.13 | 34 new test cases in `tests/test_datahealth.py` (23 test functions): 12 kinds of corrupted candle, wrong timeframe, stale, future-dated, stopped feed, changed format, comparison rules, status rules, each probe on fake sources | See TEST_RESULTS.md |
| Integration tests (simulated sources) | Linux | Bad stock data closes the gate through the running app and reopens after a passing check; futures idea turned into NO TRADE; conflicted token can't be bought | See TEST_RESULTS.md |
| Simulated failure tests | Linux | Outage, rate limit, reconnection, crash inside a check, restart with stored history, conflicting exchanges, token identity mismatch | See TEST_RESULTS.md |
| Live external-source tests | Linux build machine, real sources | Section 3 above | Passed as described |
| Real Windows environment | GitHub Windows Server 2025, installed app | 15-check data-health drill against real sources, evidence across a restart | See TEST_RESULTS.md |
| Impossible without your access | – | TopstepX chart on your PC; anything on your network | Not run |

## 9. Free sources: limits and terms

| Source | Cost | Account | Known limits | Notes |
|---|---|---|---|---|
| Yahoo Finance (via yfinance) | Free | No | Unofficial; undocumented limits; futures delayed 10–15 min | Personal use. Not licensed as a real-time feed. |
| Kraken, Coinbase Exchange, Bitstamp public tickers (via ccxt) | Free | No | Public rate limits; the app asks about once a minute for checks | ccxt is locked to public prices. |
| DexScreener | Free | No | Documented per-minute limits per endpoint | Attribution appreciated by the provider; data can lag. |
| Jupiter lite price endpoint | Free | No | Rate-limited; verified by calling it on 2026-11-14 | Used only as a cross-check. |
| GeckoTerminal public API | Free | No | Low per-minute limit; returned one 429 during testing from the shared build address, then answered | Used only as a cross-check. If it and Jupiter are both silent, prices are "not confirmed". |
| Solana public RPC | Free | No | Often refuses holder queries | A private free-tier address can be set in Settings. |

Features that can't be delivered reliably for free: independent confirmation of stock and futures prices, real-time futures data, creator-wallet history, order-book liquidity.

## 10. What needs your environment

1. TopstepX chart validation: your PC, Edge, a logged-in TopstepX chart connected under My chart. Nothing else to do; it runs by itself and reports on the Data check screen.
2. The Windows results come from GitHub's machine. Your PC's network may treat the sources differently; the Data check screen shows what your PC actually gets.
