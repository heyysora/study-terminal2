# Live futures market data and the Live Market screen (0.8.0)

**Status: built and tested against a local mock of the TopstepX market hub only. It has not been run against real TopstepX
market data**, because no TopstepX API credentials were available while building it. Until you run it with your own account,
treat "live" as unverified. The checklist at the end lists exactly what to check.

## What you need (entitlements)

| Requirement | Where | Notes |
|---|---|---|
| A Topstep account using TopstepX | topstep.com | |
| **ProjectX API Access subscription** | dashboard.projectx.com | Billed by ProjectX: $29/month, $14.50 with Topstep's code "topstep" (help.topstep.com, checked 2026-11-07). This is what unlocks the API and its real-time hubs. |
| Link TopstepX to ProjectX | TopstepX > Settings > API > *Add Link* | Without it the API answers "User lacks subscription". |
| API key | TopstepX > Settings > API | Goes in `%LOCALAPPDATA%\StudyTerminal\.env`, never in the app: `STUDY_PROJECTX_USERNAME=…` and `STUDY_PROJECTX_API_KEY=…` |
| CME market-data entitlement | ProjectX side | ProjectX's admin docs list CME subscriptions (`CME_TOB`, `CMEGROUP_TOB`, …). How these are granted to TopstepX API users isn't documented for end users. If subscribing is refused, the app shows the refusal (status DISCONNECTED with the server's message). |

Then in Study Terminal: **Futures > Data & simulator > data source: TopstepX API**. The stream starts by itself (setting
`futures.stream_enabled`, on by default) for NQ, MNQ, ES, MES and any other products automation monitors. Optional settings:
`futures.stream_stale_seconds` (30), `futures.projectx_live_data` (sends `live: true` to REST calls; the docs say `false` uses the
sim subscription). Optional `.env`: `STUDY_PROJECTX_RTC_URL` (default `https://rtc.topstepx.com`).

## What it uses from the official API (gateway.docs.projectx.com, checked 2026-11-08)

| Item | Documented as | Used for |
|---|---|---|
| `POST /api/Auth/loginKey` | session token, valid 24 h | REST calls and the hub's `?access_token=` (refreshed before expiry; re-login after a 401) |
| `POST /api/Contract/search` | contract `id`, `name` (e.g. `NQU5`), tick size/value | finding the front contract's id by name, never guessed |
| `POST /api/History/retrieveBars` | `unit` 2 = minute, 3 = hour; max 20,000 bars | chart history and **backfill after every (re)connect** |
| Market hub `https://rtc.topstepx.com/hubs/market` | SignalR over WebSockets, `skipNegotiation` | live connection |
| `SubscribeContractQuotes(contractId)` | → `GatewayQuote` (lastPrice, bestBid, bestAsk, timestamp, …) | last price, bid, ask |
| `SubscribeContractTrades(contractId)` | → `GatewayTrade` (price, volume, timestamp, type Buy/Sell) | candles and volume |

Not used: market depth, the user hub (accounts/orders/positions), and **every order endpoint**. The hub client can only send the two
subscribe calls above (a test checks that anything else is refused before it's sent). Unsubscribe methods aren't documented, so the
app never calls one: to change contracts (e.g. at the roll) it reconnects.

Unknowns the code handles defensively: `GatewayTrade` may carry one trade or a list (both accepted); quote events may omit fields
(previous values kept); the docs don't say whether a bar's `t` is its start (assumed start, as in the docs' example); whether the
server replays trades after a reconnect (duplicates are dropped).

## How the data flows

```
TopstepX market hub ──GatewayTrade──▶ candle engine (1-minute bars by exchange time) ─┐
                    ──GatewayQuote──▶ last / bid / ask                                │
TopstepX REST ──retrieveBars──▶ history + backfill after each reconnect ──────────────┼─▶ session-aligned 1m…daily bars
                                                                                     │      │
                                          status: LIVE / STALE / DISCONNECTED ◀──────┘      ├─▶ Live Market chart (WebSocket pushes, in-place updates)
                                                                                            ├─▶ decision pipeline (completed bars only)
                                                                                            └─▶ futures simulator (marks, fills)
```

- **Candles**: built from trades only. Exchange timestamp picks the minute. Prices snapped to the tick grid; genuinely off-grid prints
  dropped and counted. Duplicates dropped and counted. Late trades revise the right bar within 10 minutes; older ones are counted as
  too late. Bars close on the clock (minute end + 2 s). Prints up to 5 s after the session close belong to the last minute.
- **Timeframes**: 1m, 5m, 15m, 30m, 1h, 4h, daily, all anchored to the Globex open of each trade date (17:00 CT): 4h buckets are
  17:00, 21:00, 01:00, 05:00, 09:00, 13:00–16:00 CT; the daily bar is the whole trade date. Older 4h/daily history comes from TopstepX
  hourly bars, recent bars from minute bars and the stream.
- **Backfill**: after every connect, minute bars since the last bar the app had are requested. For minutes that have ended, the REST
  bar replaces what the stream built (it may have missed trades while disconnected); the forming minute stays the stream's. Each gap
  is recorded with how many minutes were added or corrected.
- **Rollover**: every minute the app checks the front contract (CME roll calendar); after the roll it switches, resubscribes and labels
  the chart with the new contract. Bars aren't back-adjusted.
- **Automation**: when a streamed 5-minute bar closes, automation (if running) re-evaluates right away instead of waiting for its timer.
  Same pipeline, same risk engine, same evidence gate; decisions use completed bars only.

## Data-integrity labels

Every update carries: source (`topstepx-stream`), exchange timestamp (quote and trade separately), local receipt time, contract, price.

| Label | Meaning | Signals / simulated fills |
|---|---|---|
| **LIVE** | Connected, subscribed, market data received within the last 30 s during the session | allowed (still subject to every risk check) |
| **STALE** | Connected but no market data for more than 30 s during the session | no |
| **DISCONNECTED** | Hub not connected, or the subscription was refused | no |
| **DELAYED** | Yahoo Finance data (about 10 minutes late on CME futures) | no |
| **CACHED** | A fetch failed; the last good copy is shown with its age | no |
| Historical | Market closed | no |

Yahoo data is never labelled live. If the TopstepX stream drops, the screen says DISCONNECTED, the chart is greyed out with
"NOT LIVE", and nothing is substituted under a live label.

## The Live Market screen

Menu > **Live Market**. Products NQ, MNQ, ES, MES; timeframes 1m–daily. The forming candle, its volume bar and the EMAs move as trades
arrive (in-place chart updates, no page refresh); indicators and overlays are recomputed by the server when a bar of the chart's
timeframe closes. Toggles: EMA 9/20/50/200, VWAP (intraday only; resets each session), volume, previous day high/low, overnight
high/low, Globex and RTH open, opening range, initial balance, BOS/CHoCH, swing highs/lows, fair value gaps, liquidity sweeps,
support/resistance, previous-RTH volume profile. Every overlay is a calculated price at a stated time (hover a marker); structure,
swings, FVGs and sweeps use completed bars of the chart's timeframe; levels use the 5-minute frame. Bid and ask come from quotes.

## Trying it without an account (mock server)

`backend/research/mock_topstepx.py` imitates the documented REST and hub shapes with **synthetic prices** so you can see the screen
update, go STALE (`POST /mock/pause`) and DISCONNECTED/reconnect (`POST /mock/drop`). Its data is fake and proves nothing about TopstepX.

## What still needs a real TopstepX account

1. Login and hub connection with your token (`?access_token=`), and that `skipNegotiation` WebSockets works as documented.
2. Subscriptions accepted for NQ, MNQ, ES, MES front contracts; contract names returned by `Contract/search` (`NQZ6` format).
3. Real `GatewayTrade` / `GatewayQuote` payloads: single object vs list, which fields arrive, timestamp format and time zone.
4. Candle accuracy: compare a few minutes of streamed 1-minute bars with TopstepX's own chart and with `retrieveBars` for the same minutes.
5. Whether bar `t` from `retrieveBars` is the bar start; whether `live: true/false` matters for your subscription.
6. Server keep-alive behaviour (pings) and the 30 s stale threshold during quiet overnight trading in MES/MNQ.
7. Reconnection after a real network drop, token expiry after 24 h, and a contract roll.
8. Volume parity with TopstepX (the app counts every trade print it receives).
9. Live simulated fills and automated paper entries on LIVE data (they've only run on recorded and mock data).
