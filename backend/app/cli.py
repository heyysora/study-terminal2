"""Command-line checks. No accounts or keys needed. Run from backend/ with the venv active:

  python -m app.cli check                   provider reachability, market session, sample quotes with labels
  python -m app.cli bars TSLA --timeframe 5Min --days 2
  python -m app.cli stream SPY AAPL --seconds 30
  python -m app.cli stream BTC-USD --seconds 20    crypto trades 24/7: proves streaming works on weekends
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from .config import get_settings
from .core.market_clock import ET, MarketClock
from .market_data.freshness import FreshnessTracker
from .market_data.providers.base import ProviderError, StreamState
from .market_data.providers.registry import create_provider
from .market_data.types import Tick, Timeframe

OK, WARN, FAIL = "[ OK ]", "[WARN]", "[FAIL]"


async def cmd_check(symbols: list[str]) -> int:
    s = get_settings()
    provider = create_provider(s)
    info = provider.info
    print(f"{OK} Provider: {info.display_name}  (API key required: {'yes' if info.requires_api_key else 'no'}; "
          f"guaranteed real-time: {'yes' if info.guaranteed_realtime else 'no'})")
    print(f"{OK} No brokerage account or credentials are used. Orders go to the local paper simulator only.")
    clock = MarketClock()
    si = clock.session_at()
    print(f"{OK} Market session: {si.session.value.upper()} (ET {si.now_et:%a %Y-%m-%d %H:%M}); calendar: {si.calendar_source}")
    if si.next_regular_open_et:
        print(f"       Next regular open: {si.next_regular_open_et:%a %Y-%m-%d %H:%M} ET")

    tracker = FreshnessTracker(provider=info, poll_interval_s=s.poll_interval_seconds, streaming_enabled=False)
    rc = 0
    try:
        data = await provider.get_recent_bars(symbols)
        tracker.poll_succeeded()
    except ProviderError as e:
        print(f"{FAIL} Could not reach {info.display_name}: {e}")
        return 1
    now = datetime.now(timezone.utc)
    for sym in symbols:
        bars = data.get(sym)
        if not bars:
            print(f"{WARN} {sym}: no recent bars returned (unknown symbol, or nothing traded today yet)")
            continue
        b = bars[-1]
        tracker.on_tick(Tick(symbol=sym, price=b.close, ts=min(b.ts + timedelta(seconds=60), now), received_at=now,
                             provider=info.name, source=b.source))
        try:
            tracker.set_feed_info(await provider.get_feed_info(sym))
        except ProviderError:
            pass
        lab = tracker.label(sym, si.session)
        fi = tracker.feed_info(sym)
        print(f"{OK} {sym:6} ${b.close:,.2f}  bar {b.ts.astimezone(ET):%m-%d %H:%M} ET  ->  {lab.status.value.upper()}: {lab.reason}")
        if fi and fi.note:
            print(f"       feed: {fi.note}")
    await provider.aclose()
    print("\nDone." if rc == 0 else "\nSome checks failed.")
    return rc


async def cmd_bars(symbol: str, timeframe: str, days: int) -> int:
    provider = create_provider(get_settings())
    try:
        bars, notes = await provider.get_bars(symbol, Timeframe(timeframe), datetime.now(timezone.utc) - timedelta(days=days))
    except ProviderError as e:
        print(f"{FAIL} {e}")
        return 1
    print(f"{symbol} {timeframe} from {provider.info.display_name}: {len(bars)} bars (HISTORICAL)")
    for n in notes:
        print(f"  note: {n}")
    for b in bars[-15:]:
        print(f"  {b.ts.astimezone(ET):%Y-%m-%d %H:%M} ET  O {b.open:>9.2f} H {b.high:>9.2f} L {b.low:>9.2f} "
              f"C {b.close:>9.2f} V {b.volume:>12,.0f}")
    return 0


async def cmd_stream(symbols: list[str], seconds: int) -> int:
    provider = create_provider(get_settings())
    if not provider.info.supports_streaming:
        print(f"{FAIL} {provider.info.display_name} has no streaming feed")
        return 1
    n = {"ticks": 0}
    states: list[StreamState] = []

    def on_tick(t):
        n["ticks"] += 1
        lag = (t.received_at - t.ts).total_seconds()
        print(f"  {t.symbol:8} ${t.price:,.4f}  source time {t.ts.astimezone(ET):%H:%M:%S} ET  "
              f"(arrived {lag:.1f}s later, session flag: {t.market_hours})")

    def on_state(st, why):
        states.append(st)
        print(f"[stream] {st.value}: {why}")

    stream = provider.create_stream(on_tick, on_state)
    await stream.set_symbols(symbols)
    print(f"Streaming {', '.join(symbols)} for {seconds}s. Yahoo only sends an update when a price changes.")
    task = asyncio.create_task(stream.run())
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=seconds)
    except asyncio.TimeoutError:
        pass
    finally:
        await stream.stop()
        await task
    print(f"\nReceived {n['ticks']} updates. Label for this data: NEAR_REALTIME at best (unofficial, not guaranteed).")
    if StreamState.CONNECTED not in states:
        print(f"{FAIL} Could not connect to the streaming socket.")
        return 1
    if n["ticks"] == 0:
        print(f"{WARN} Connected, but no updates. Normal when the market is closed; try BTC-USD to test on a weekend.")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING)
    p = argparse.ArgumentParser(prog="python -m app.cli", description="Study Terminal checks (no accounts needed)")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="Provider reachability, market session, labeled quotes")
    c.add_argument("symbols", nargs="*", default=["SPY", "AAPL"])
    b = sub.add_parser("bars", help="Historical bars")
    b.add_argument("symbol")
    b.add_argument("--timeframe", default="5Min", choices=[t.value for t in Timeframe])
    b.add_argument("--days", type=int, default=2)
    st = sub.add_parser("stream", help="Print the streaming feed for a few seconds")
    st.add_argument("symbols", nargs="*", default=["SPY"])
    st.add_argument("--seconds", type=int, default=30)
    a = p.parse_args(argv)
    if a.cmd == "check":
        return asyncio.run(cmd_check([x.upper() for x in a.symbols]))
    if a.cmd == "bars":
        return asyncio.run(cmd_bars(a.symbol.upper(), a.timeframe, a.days))
    return asyncio.run(cmd_stream([x.upper() for x in a.symbols], a.seconds))


if __name__ == "__main__":
    raise SystemExit(main())
