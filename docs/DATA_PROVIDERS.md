# Market data: what Study Terminal receives, and what else exists

Last researched: 2026-11-07. Prices and plan contents change often. Check the vendor's own
pricing page before you pay for anything. Nothing in this app requires a paid plan or an API key.

## 1. What the app actually uses today (Yahoo Finance, unofficial)

Yahoo has no official, documented API. The app talks to it in three ways, and labels each one separately:

| Path | Code | What it is | Label in the app |
|---|---|---|---|
| Streaming socket | `providers/yahoo_stream.py` | `wss://streamer.finance.yahoo.com`, protobuf `PricingData` messages. Pushes a new price only when one changes. | **Near real-time** (never "Real-time") |
| 1-minute poll | `providers/yahoo.py` → `yf.download(interval="1m")` | Every 30 s by default. The newest 1-minute bar is still forming, so a polled price can lag up to about 90 s. | **Polling** |
| History | `providers/yahoo.py` → `Ticker.history()` | Bars for charts, indicators, signals and backtests. Only fully closed bars are used. | **Historical**, or **Cached copy** if a refresh failed |

What was measured, not assumed:
- `Ticker.info["quoteSourceName"]` is "Nasdaq Real Time Price" for US stocks. That is **Nasdaq Last Sale**:
  the real-time price of trades on Nasdaq venues (plus FINRA TRF prints Nasdaq reports). It is not the
  consolidated tape. Volume is partial, and Yahoo itself lists consolidated exchange data as delayed 15 minutes
  (`exchangeDataDelayedBy`). The app reads both fields per symbol and shows them (`feed:` in `cli check`).
- Streaming was verified on crypto (BTC-USD, ETH-USD) with ticks arriving 4–6 s behind the source timestamp.
  **US stocks during market hours have not been observed from the build environment.** Run
  `.\scripts\check.ps1 SPY` during market hours to confirm on your machine.
- Extended-hours bars have zero volume from Yahoo. The app uses them only for premarket high/low.

Rules the app enforces:
- `REALTIME` is reserved for a provider that contractually guarantees real-time consolidated data. Yahoo never gets it.
- Signals run only on Near real-time or Polling data, and on polled data only on 5-minute or slower timeframes.
- Stale (no update within 2 min while the market is open), Cached, Delayed, Historical and Unavailable data never produce
  new signals. Open positions on stale data raise an alert.
- Every bar is validated (impossible bars dropped, rounding repaired, one-bar spikes flagged, missing regular-session
  candles counted). Results show under each chart.
- The stream reconnects automatically with backoff and resubscribes; while it's down, polling covers and the label says so.
  A disconnection longer than 60 s raises an alert, and so does a recovery.
- Yahoo's rate limits are undocumented. The app throttles itself to 60 requests/minute, backs off on HTTP 429,
  and shows "rate-limited" instead of retrying in a tight loop.

Risks: Yahoo can change or block these endpoints without notice, and its terms restrict use to personal,
non-commercial purposes. If it breaks, the app shows Unavailable and turns signals off. It does not invent prices.

## 2. Other providers (none required; all would plug into `MarketDataProvider`)

"Real-time" from a free source almost always means **one venue** (IEX, Nasdaq, or a broker's own blend), not the
consolidated tape. The table states which.

| Provider | Free tier | Real-time US stocks | Streaming | Key needed | Paid entry point | Notes |
|---|---|---|---|---|---|---|
| **Yahoo (current)** | Yes, unofficial | Nasdaq Last Sale price; partial volume | Yes (unofficial socket) | No | n/a | Can break without notice; personal use only |
| **Finnhub** | 60 REST calls/min, free WebSocket | Free trade stream for US stocks; Finnhub doesn't document which venues feed it | Yes, free (symbol limits apply) | Yes (free signup) | Plans from about $50/mo | Best free streaming option to add next. Treat as Near real-time until checked against a reference |
| **Tiingo** | 50 req/hour, 1,000/day, 500 symbols/month | IEX only (~2–3% of volume); free "reference price" or IEX TOPS with an IEX agreement | Yes (IEX socket) | Yes (free signup) | Power $30/mo (individual, internal use) | IEX quotes lag on illiquid names |
| **Twelve Data** | 8 credits/min, 800/day | "Real-time" default feed covers ~5% of US volume (their FAQ) | Trial symbols only on free tier; full WebSocket from Pro | Yes | Grow $29/mo; WebSocket from Pro (~$229/mo) | Good indicator endpoints; volume is partial |
| **Alpha Vantage** | 25 requests/day | No. Real-time is premium (exchange-licensed, Nasdaq vendor) | No (REST only) | Yes | $49.99/mo (15-min delayed); real-time from $99.99/mo | Entitlement paperwork through their portal |
| **Massive (formerly Polygon.io)** | 5 calls/min, end-of-day / delayed | Only on Stocks Advanced | Yes (paid; delayed socket on Starter) | Yes | Starter $29/mo (15-min delayed); real-time $199/mo | Consolidated SIP data on Advanced; exchange agreements required |
| **Databento** | Historical pay-as-you-go credits | US Equities Mini (blended BBO, no exchange fees) | Yes | Yes | Standard $199/mo | Professional-grade; overkill for one person |
| **Broker APIs** (Schwab, IBKR, Tradier, Alpaca) | Free with an account | Yes (varies) | Yes | Account + key | $0 with a funded account | Excluded by your requirement: no brokerage account |

Sources: vendor pricing and documentation pages (finnhub.io, api.tiingo.com/products/iex-api,
twelvedata.com/pricing and support FAQ, alphavantage.co/premium and realtime_data_policy, massive.com pricing
and knowledge base, databento.com/pricing), checked 2026-11-07 via web search. Third-party summaries were
used only where they agreed with the vendor's page.

## 3. Recommendation

1. Keep Yahoo as the zero-setup default. It's honest about what it is, and the app already labels it.
2. If you want a second, independent live source **for free**, add Finnhub's WebSocket as an optional provider
   (free key, no brokerage). It would let the app cross-check Yahoo prices and fail over when one feed is down.
   Not built in this release: it can't be verified without a key and live market hours, and an unverified
   second feed is worse than none.
3. If you ever trade size or need full volume and NBBO, the cheapest consolidated real-time option without a
   brokerage is Massive Stocks Advanced ($199/mo). Not worth it while the strategies show no edge.

## 4. Adding a provider

Implement `market_data/providers/base.py: MarketDataProvider`:

- `info` (name, `requires_api_key`, `guaranteed_realtime`)
- `get_bars(symbol, timeframe, start, end) -> (bars, notes)`
- `get_recent_bars(symbols)` for polling
- `get_feed_info(symbols)` describing each symbol's source and delay
- `get_movers(kind, count)` (optional) for the scanner
- `create_stream()` (optional) returning a `TickStream`

Register it in `providers/registry.py` and set `MARKET_DATA_PROVIDER=<name>` in `.env`. Validation, freshness
labels, caching, the signal gate and the UI work unchanged. `guaranteed_realtime=True` is the only way to get
the REALTIME label. Set it only if the vendor contractually provides consolidated real-time data.

## 5. Futures

Futures use a separate data layer (`backend/app/futures/data.py`). Yahoo serves CME futures but reports them as
delayed (10 minutes when checked on 2026-11-07), so futures bars from Yahoo are labeled DELAYED and never produce
signals. The optional, paid TopstepX API (ProjectX Gateway) is the documented way to get real-time TopstepX data;
Databento is the main paid alternative. Comparison table and setup steps: [TOPSTEPX.md](TOPSTEPX.md) §8.

Labels on every futures quote and chart (0.7.0): **REAL-TIME / NEAR REAL-TIME / POLLING** (fillable), **DELAYED**, **HISTORICAL**,
**REPLAY**, **CACHED** (fetch failed, last good copy shown with its age), **STALE**, **UNAVAILABLE**. Each label carries the source, bar time,
fetch time and validation counts (impossible and future-dated bars dropped, duplicates removed, out-of-order bars re-sorted, off-tick prices and missing candles counted).
If TopstepX REST fails (stream off), bars come from Yahoo **labelled DELAYED with a note saying why**. With the 0.8.0 stream on,
status comes only from the stream: LIVE while connected and receiving data, otherwise STALE or DISCONNECTED; nothing is substituted
under a live label ([LIVE_MARKET_DATA.md](LIVE_MARKET_DATA.md)). A failing source backs off from 30 s up to 10 minutes. Downtime (sleep, shutdown, stalls) is detected and the
missed bars are replayed in order (labelled `reconcile`) before any decision.

## 6. Economic data

Event dates and times: Federal Reserve (FOMC) and BEA pages, read live; BLS schedule bundled with its source URLs.
Published values (actual and previous) for CPI, core CPI, PPI final demand, payrolls and unemployment come from the BLS public
data API (`api.bls.gov`, free, about 25 requests/day without a key; one request every 6 hours; optional free key in
`STUDY_BLS_API_KEY`). Consensus forecasts are not shown: no official free source publishes them.
