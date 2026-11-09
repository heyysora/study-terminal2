# Study Terminal 0.8.0: live futures charting and market data (plan)

## What exists in 0.7.0 (audited 2026-11-08)

| Piece | State |
|---|---|
| `futures/projectx.py` | Read-only REST client: `loginKey`, `Contract/search`, `History/retrieveBars` (minute bars only), `Account/search`. Path allow-list. Mock-tested only. |
| `futures/data.py` | Yahoo (labelled DELAYED) or TopstepX REST bars (labelled POLLING). REST failure falls back to Yahoo labelled DELAYED. Cache, validation, backoff. No streaming. 4h/daily not session-aligned. |
| Streaming | None for futures. The UI WebSocket (`/ws/market`) carries stock ticks and app events. |
| Charts | `CandleChart` (lightweight-charts v5) redraws everything on each poll; futures page polls every 20 s. No EMA, no bid/ask, no structure markers. |
| Analysis | Feature frame already computes VWAP, PDH/PDL, overnight, opening range, IB, swings, BOS/CHoCH, FVGs, sweeps, volume profile, trend. |
| Decision engine | Pipeline accepts `realtime / near_realtime / polling / replay` only; automation evaluates on a timer. |

## What the official ProjectX docs say about streaming (checked 2026-11-08)

Source: gateway.docs.projectx.com, "Real Time Data Overview", "Connection URLs", "Validate Session", "Retrieve Bars", "Search Contracts".

- SignalR over WebSocket. Market hub `https://rtc.topstepx.com/hubs/market?access_token=<JWT>`; the docs' client uses
  `skipNegotiation: true`, WebSockets transport, automatic reconnect, and re-subscribes in `onreconnected`.
- Market hub methods (from the docs' example): `SubscribeContractQuotes(contractId)`, `SubscribeContractTrades(contractId)`,
  `SubscribeContractMarketDepth(contractId)`. **Unsubscribe method names are not documented**, so Study Terminal never calls any:
  to change contracts it closes the connection and opens a new one.
- Events arrive as `(contractId, data)`: `GatewayQuote` (symbol, lastPrice, bestBid, bestAsk, change, open, high, low, volume,
  lastUpdated, timestamp), `GatewayTrade` (symbolId, price, timestamp, type 0=Buy/1=Sell, volume), `GatewayDepth` (not used).
- Token: JWT from `loginKey`, valid 24 hours. Contract ids come from `Contract/search` (names like `NQU5`).
- Entitlement: the ProjectX API Access subscription (billed by ProjectX) linked to TopstepX. The admin docs list CME market-data
  subscriptions (e.g. `CME_TOB`, `CMEGROUP_TOB`); how TopstepX maps these to an API user isn't documented for end users.

Not documented, so treated as unknowns and handled defensively: whether `GatewayTrade` data is one object or a list (both accepted);
whether bar `t` is the bar start (assumed start, as in the example); whether the server replays trades after a reconnect.

## Plan (dependency order)

1. **Candle engine** (`futures/candles.py`): trades → 1-minute bars with exchange timestamps; duplicates dropped and counted;
   late trades revise the right bar or are counted as too late; bars close on the wall clock; session-anchored aggregation to
   5m/15m/30m/1h/4h/daily (buckets start at the Globex open, daily = trade date); prices snapped to the tick grid, off-grid counted.
2. **Stream client** (`futures/stream.py`): minimal SignalR JSON-protocol client on the existing `websockets` dependency
   (handshake, invocations, pings, close), exactly the documented hub/methods/events; reconnect with backoff; token refresh.
   **LiveFeed** per contract: quote state (last/bid/ask), candle builder, status LIVE / STALE / DISCONNECTED, gap detection,
   REST backfill after every (re)connect, front-contract rollover check.
3. **Data integration**: when the stream is on, `FuturesData` serves REST history merged with streamed bars labelled
   `realtime` (shown as LIVE) only while connected and fresh; `stale` or new `disconnected` otherwise. Neither is tradable, so the
   decision pipeline and simulator stop. Yahoo stays DELAYED. Every update carries source, exchange time, receipt time, contract,
   price, status. 4h/daily are session-aligned aggregates. Automation re-evaluates when a 5-minute bar closes on the stream.
4. **Chart API**: `/api/futures/live/chart` (candles, volume, EMA 9/20/50/200, VWAP, levels, structure overlays with price and
   time, volume profile bins, status) and `/api/futures/live/status`; WebSocket `futures_live` pushes (throttled).
5. **Live Market screen**: NQ/MNQ/ES/MES, seven timeframes, incremental chart updates (`series.update`), indicator and overlay
   toggles, bid/ask, status banner; a disconnected/stale feed greys the chart and says so.
6. **Tests** (mocked streams, clearly labelled) and **docs**: entitlements, what still needs a real TopstepX account.

Nothing here touches order execution, the risk engine or the strategy-evidence gate.

## Phase log
