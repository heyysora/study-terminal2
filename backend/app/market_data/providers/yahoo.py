"""Yahoo Finance provider (via yfinance). No account, no API key.

What Yahoo actually provides (verified Nov 2026):
- Historical bars: 1m (recent days only), 2m-30m (~60 days), 60m (~730 days), daily (decades).
- US stock prices: Yahoo says US quotes are real-time for NASDAQ, NYSE and NYSE American
  *when available from Nasdaq Last Sale*, otherwise delayed from the consolidated tape.
  Nasdaq Last Sale covers only part of US volume, so volume from Yahoo is approximate.
- Extended-hours 1-minute bars are returned with volume 0.
- A streaming socket (wss://streamer.finance.yahoo.com) that yfinance can decode. It is
  undocumented and unofficial, so its data is labeled NEAR_REALTIME at best, never REALTIME.
- Yahoo rate-limits aggressive clients. All requests here go through one throttle.

yfinance is an unofficial library and Yahoo's terms restrict data to personal use.
"""
from __future__ import annotations

import asyncio
import logging
import time as _time
from collections import deque
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from ...core.market_clock import ET, regular_close_minute
from ..types import Bar, ProviderInfo, SymbolFeedInfo, Timeframe
from .base import MarketDataProvider, ProviderError, ProviderRateLimited, StateHandler, SymbolNotFound, TickHandler, TickStream

log = logging.getLogger(__name__)

INTERVALS = {
    Timeframe.M1: "1m", Timeframe.M2: "2m", Timeframe.M5: "5m", Timeframe.M15: "15m",
    Timeframe.M30: "30m", Timeframe.H1: "60m", Timeframe.H4: "60m", Timeframe.D1: "1d",
}
# How far back Yahoo serves each interval (kept slightly inside Yahoo's real limits).
MAX_LOOKBACK = {
    Timeframe.M1: timedelta(days=7), Timeframe.M2: timedelta(days=59), Timeframe.M5: timedelta(days=59),
    Timeframe.M15: timedelta(days=59), Timeframe.M30: timedelta(days=59), Timeframe.H1: timedelta(days=729),
    Timeframe.H4: timedelta(days=729), Timeframe.D1: timedelta(days=365 * 40),
}


class RateLimiter:
    """Sliding one-minute window shared by every Yahoo HTTP call in the app."""

    def __init__(self, per_minute: int):
        self.per_minute = max(1, per_minute)
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()
        self.blocked_until = 0.0

    async def acquire(self, n: int = 1) -> None:
        n = min(n, self.per_minute)
        async with self._lock:
            while True:
                now = _time.monotonic()
                if now < self.blocked_until:
                    await asyncio.sleep(self.blocked_until - now)
                    continue
                while self._calls and now - self._calls[0] > 60:
                    self._calls.popleft()
                if len(self._calls) + n <= self.per_minute:
                    self._calls.extend([now] * n)
                    return
                await asyncio.sleep(max(0.05, 60 - (now - self._calls[0])))

    def penalize(self, seconds: float) -> None:
        self.blocked_until = max(self.blocked_until, _time.monotonic() + seconds)


def _yf():
    import yfinance as yf

    return yf


def frame_to_bars(df, symbol: str, timeframe: Timeframe, source: str) -> list[Bar]:
    """Convert a yfinance OHLCV DataFrame to Bars (drops empty rows)."""
    if df is None or len(df) == 0:
        return []
    cols = {c.lower(): c for c in df.columns}
    need = ["open", "high", "low", "close", "volume"]
    if not all(k in cols for k in need):
        return []
    out = []
    for ts, row in df.iterrows():
        o, h, lo, c, v = (row[cols[k]] for k in need)
        if any(x != x for x in (o, h, lo, c)):  # NaN check without numpy import
            continue
        t = ts.to_pydatetime()
        if t.tzinfo is None:
            t = t.replace(tzinfo=ET)
        out.append(Bar(symbol=symbol, timeframe=timeframe.value, ts=t.astimezone(timezone.utc), open=float(o), high=float(h),
                       low=float(lo), close=float(c), volume=float(v if v == v else 0), provider="yahoo", source=source))
    return out


def aggregate_4h(bars_1h: list[Bar]) -> list[Bar]:
    """Build 4-hour bars from regular-session hourly bars, anchored at 09:30 ET
    (09:30-13:30 and 13:30-16:00), the same way TradingView anchors US stocks."""
    groups: dict[tuple, list[Bar]] = {}
    for b in bars_1h:
        t = b.ts.astimezone(ET)
        minutes = (t.hour * 60 + t.minute) - (9 * 60 + 30)
        if minutes < 0 or t.hour * 60 + t.minute >= regular_close_minute(t.date()):   # after the close (13:00 on early-close days)
            continue
        groups.setdefault((t.date(), minutes // 240), []).append(b)
    out = []
    for (_, _), g in sorted(groups.items()):
        g.sort(key=lambda b: b.ts)
        out.append(Bar(symbol=g[0].symbol, timeframe=Timeframe.H4.value, ts=g[0].ts, open=g[0].open,
                       high=max(b.high for b in g), low=min(b.low for b in g), close=g[-1].close,
                       volume=sum(b.volume for b in g), provider="yahoo", source="yahoo-history-aggregated"))
    return out


class YahooProvider(MarketDataProvider):
    info = ProviderInfo(
        name="yahoo",
        display_name="Yahoo Finance (via yfinance, unofficial)",
        requires_api_key=False,
        supports_history=True,
        supports_polling=True,
        supports_streaming=True,
        guaranteed_realtime=False,
        history_limits={k.value: f"~{v.days} days" for k, v in MAX_LOOKBACK.items()},
        notes=[
            "Unofficial: Yahoo can change or block access at any time; the app reports that instead of guessing.",
            "US prices are real-time only when Yahoo has them from Nasdaq Last Sale; otherwise delayed.",
            "Volume comes from a partial source and extended-hours 1-minute volume is reported as 0: volume metrics are approximate.",
            "Streaming socket is undocumented: data is labeled NEAR_REALTIME at best, never REALTIME.",
            "For personal use per Yahoo's terms.",
        ],
    )

    def __init__(self, requests_per_minute: int = 60, cache_dir: Path | None = None):
        self.limiter = RateLimiter(requests_per_minute)
        logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # it prints its own errors otherwise
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
            try:
                _yf().set_tz_cache_location(str(cache_dir))
            except Exception:
                log.debug("could not set yfinance cache dir", exc_info=True)

    async def _call(self, n: int, fn, *args, **kwargs):
        await self.limiter.acquire(n)
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except Exception as e:
            name = type(e).__name__
            if name == "YFRateLimitError" or "Too Many Requests" in str(e) or "429" in str(e):
                self.limiter.penalize(60)
                raise ProviderRateLimited("Yahoo is rate-limiting requests; backing off for 60s") from e
            raise ProviderError(f"Yahoo request failed: {name}: {str(e)[:200]}") from e

    # ---------------- history ----------------

    async def get_bars(self, symbol, timeframe, start, end=None):
        notes: list[str] = []
        now = datetime.now(timezone.utc)
        earliest = now - MAX_LOOKBACK[timeframe]
        if start < earliest:
            notes.append(f"Yahoo only serves {timeframe.value} bars for about the last {MAX_LOOKBACK[timeframe].days} days; "
                         f"start moved from {start:%Y-%m-%d} to {earliest:%Y-%m-%d}.")
            start = earliest
        interval = INTERVALS[timeframe]
        intraday = timeframe != Timeframe.D1
        prepost = intraday and timeframe != Timeframe.H4

        def fetch():
            t = _yf().Ticker(symbol)
            return t.history(start=start, end=end or now + timedelta(days=1), interval=interval, prepost=prepost,
                             auto_adjust=False, actions=False, raise_errors=True)

        try:
            df = await self._call(1, fetch)
        except ProviderError as e:
            if "delisted" in str(e).lower() or "no data" in str(e).lower() or "not found" in str(e).lower():
                raise SymbolNotFound(f"Yahoo has no data for {symbol}") from e
            raise
        bars = frame_to_bars(df, symbol, Timeframe.H1 if timeframe == Timeframe.H4 else timeframe, "yahoo-history")
        if timeframe == Timeframe.H4:
            bars = aggregate_4h(bars)
            notes.append("4-hour bars are built locally from Yahoo's hourly bars (regular session, anchored 09:30 ET).")
        if not bars:
            raise SymbolNotFound(f"Yahoo returned no {timeframe.value} bars for {symbol}")
        if intraday and prepost:
            notes.append("Yahoo reports extended-hours intraday volume as 0; premarket/after-hours volume is not usable.")
        notes.append("Prices are as traded (not dividend-adjusted).")
        return bars, notes

    # ---------------- polling ----------------

    async def get_recent_bars(self, symbols):
        if not symbols:
            return {}

        def fetch():
            return _yf().download(tickers=symbols, period="1d", interval="1m", prepost=True, group_by="ticker",
                                  auto_adjust=False, progress=False, threads=True, multi_level_index=True)

        df = await self._call(len(symbols), fetch)
        out: dict[str, list[Bar]] = {}
        if df is None or len(df) == 0:
            return out
        top = set(df.columns.get_level_values(0))
        for sym in symbols:
            if sym in top:
                out[sym] = frame_to_bars(df[sym], sym, Timeframe.M1, "yahoo-poll")
        return {k: v for k, v in out.items() if v}

    # ---------------- feed info ----------------

    async def get_feed_info(self, symbol):
        def fetch():
            return _yf().Ticker(symbol).info

        info = await self._call(3, fetch)  # .info makes several requests internally
        if not info or not (info.get("quoteType") or info.get("regularMarketPrice")):
            raise SymbolNotFound(f"Yahoo has no quote for {symbol}")
        src = info.get("quoteSourceName")
        delay = info.get("exchangeDataDelayedBy")
        realtime_price = bool(src and "real time" in src.lower())
        if realtime_price:
            note = f"Price from '{src}' (Nasdaq Last Sale: real-time price, partial-market volume)."
            if delay:
                note += f" Yahoo lists consolidated exchange data as delayed {delay} min."
        elif delay:
            note = f"Yahoo marks this symbol's quotes as delayed {delay} minutes."
        else:
            note = "Yahoo did not state whether this quote is real-time."
        return SymbolFeedInfo(
            symbol=symbol, provider="yahoo", realtime_price=realtime_price if src or delay is not None else None,
            price_source=src, delay_minutes=int(delay) if delay is not None else None, quote_type=info.get("quoteType"),
            exchange=info.get("fullExchangeName") or info.get("exchange"), name=info.get("shortName") or info.get("longName"),
            checked_at=datetime.now(timezone.utc), note=note,
        )

    # ---------------- market movers (scanner universe) ----------------

    movers_kinds = ("day_gainers", "day_losers", "most_actives", "small_cap_gainers", "aggressive_small_caps")

    async def get_movers(self, kind, count=25):
        if kind not in self.movers_kinds:
            raise ProviderError(f"Unknown movers list {kind!r}")

        def fetch():
            return _yf().screen(kind, count=count)

        res = await self._call(1, fetch)
        out = []
        for q in (res or {}).get("quotes", []):
            if q.get("quoteType") not in (None, "EQUITY", "ETF"):
                continue
            out.append({"symbol": q.get("symbol"), "name": q.get("shortName"), "price": q.get("regularMarketPrice"),
                        "change_pct": q.get("regularMarketChangePercent"), "volume": q.get("regularMarketVolume"),
                        "avg_volume": q.get("averageDailyVolume3Month") or q.get("averageDailyVolume10Day"),
                        "market_cap": q.get("marketCap"), "premarket_change_pct": q.get("preMarketChangePercent"),
                        "exchange": q.get("fullExchangeName") or q.get("exchange"), "source": f"yahoo:{kind}"})
        return [o for o in out if o["symbol"]]

    # ---------------- streaming ----------------

    def create_stream(self, on_tick: TickHandler, on_state: StateHandler) -> TickStream:
        from .yahoo_stream import YahooStream

        return YahooStream(on_tick=on_tick, on_state=on_state)
