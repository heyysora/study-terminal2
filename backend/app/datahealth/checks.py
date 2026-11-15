"""Checks on the data itself. Pure functions: no network, no clock unless `now` is passed. Each returns a Finding.

A Finding is {"check", "ok" (True / False / None = couldn't be judged), "detail"}. None never counts as a pass.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from statistics import median

TEST_VERSION = "dh-1"


def finding(check: str, ok: bool | None, detail: str, **extra) -> dict:
    return {"check": check, "ok": ok, "detail": detail, **extra}


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _ts(c) -> datetime | None:
    t = c.get("ts") if isinstance(c, dict) else getattr(c, "ts", None)
    if isinstance(t, (int, float)) and math.isfinite(t):
        try:
            return datetime.fromtimestamp(t / 1000 if t > 1e11 else t, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(t, datetime):
        return t if t.tzinfo else None                      # a time without a zone can't be placed; treated as invalid
    return None


def _f(c, k):
    return c.get(k) if isinstance(c, dict) else getattr(c, k, None)


def candle_shape(candles: list) -> dict:
    """Open, high, low, close present, finite, positive, and high/low actually bound the candle."""
    bad = []
    for i, c in enumerate(candles):
        o, h, lo, cl = (_f(c, k) for k in ("open", "high", "low", "close"))
        if not all(_num(x) and x > 0 for x in (o, h, lo, cl)):
            bad.append((i, "a price is missing, not a number, or not above zero"))
        elif h < lo or h < max(o, cl) or lo > min(o, cl):
            bad.append((i, "high/low don't contain the open and close"))
    if not candles:
        return finding("candle_shape", None, "No candles to check.")
    return finding("candle_shape", not bad, f"All {len(candles)} candles are well-formed." if not bad
                   else f"{len(bad)} of {len(candles)} candles are malformed (first: #{bad[0][0]}, {bad[0][1]}).", bad=len(bad))


def volume_valid(candles: list, expect_some: bool = True) -> dict:
    vols = [_f(c, "volume") for c in candles]
    if not candles:
        return finding("volume", None, "No candles to check.")
    wrong = [v for v in vols if not _num(v) or v < 0]
    if wrong:
        return finding("volume", False, f"{len(wrong)} candles have a missing or negative volume.")
    if expect_some and len(vols) >= 5 and not any(v > 0 for v in vols):
        return finding("volume", False, "Every candle reports zero volume, which a traded market wouldn't.")
    return finding("volume", True, "Volume values are valid numbers.")


def order_and_duplicates(candles: list) -> dict:
    ts = [_ts(c) for c in candles]
    if not candles:
        return finding("order", None, "No candles to check.")
    if any(t is None for t in ts):
        return finding("order", False, f"{sum(t is None for t in ts)} candles have an invalid time.")
    dup = len(ts) - len(set(ts))
    back = sum(1 for a, b in zip(ts, ts[1:], strict=False) if b < a)
    if dup or back:
        return finding("order", False, f"{dup} duplicate candle time(s) and {back} out-of-order candle(s).", duplicates=dup, out_of_order=back)
    return finding("order", True, "Candle times are unique and in order.")


def timeframe_matches(candles: list, expected_seconds: int) -> dict:
    """The gap between neighbouring candles should be the timeframe that was asked for (closed periods make some gaps bigger,
    never smaller, so the most common gap is what's compared)."""
    ts = [t for t in (_ts(c) for c in candles) if t]
    if len(ts) < 4:
        return finding("timeframe", None, "Too few candles to tell the timeframe.")
    gaps = [(b - a).total_seconds() for a, b in zip(ts, ts[1:], strict=False) if b > a]
    if not gaps:
        return finding("timeframe", False, "Candle times don't advance.")
    m = median(gaps)
    ok = abs(m - expected_seconds) <= expected_seconds * 0.02
    return finding("timeframe", ok, f"Candles are {m:g} s apart; {expected_seconds} s was asked for." if not ok
                   else f"Candles are {expected_seconds} s apart, as asked.", seen_seconds=m)


def missing_candles(candles: list, expected_seconds: int, max_ratio: float = 0.05, session_gap_seconds: int = 3600) -> dict:
    """Holes inside a trading period. Gaps of an hour or more are treated as the market being closed, not as missing data."""
    ts = [t for t in (_ts(c) for c in candles) if t]
    if len(ts) < 4:
        return finding("missing", None, "Too few candles to look for holes.")
    missing = 0
    for a, b in zip(ts, ts[1:], strict=False):
        g = (b - a).total_seconds()
        if expected_seconds * 1.5 < g < max(session_gap_seconds, expected_seconds * 3):
            missing += round(g / expected_seconds) - 1
    ratio = missing / (len(ts) + missing)
    return finding("missing", ratio <= max_ratio, f"{missing} candle(s) missing inside trading periods ({ratio:.1%})." if missing
                   else "No candles missing inside trading periods.", missing=missing)


def symbol_matches(requested: str, returned: list[str | None]) -> dict:
    got = {str(x).upper() for x in returned if x}
    want = requested.upper()
    if not got:
        return finding("symbol", None, "The source didn't say which symbol it returned.")
    ok = got == {want}
    return finding("symbol", ok, f"Asked for {want} and got {want}." if ok else f"Asked for {want} but the data is labelled {', '.join(sorted(got))}.")


def fresh(last: datetime | None, now: datetime, max_age_seconds: float, market_open: bool | None = True) -> dict:
    if last is None:
        return finding("fresh", False, "No time on the newest data, so its age is unknown.")
    age = (now - last).total_seconds()
    if age < -120:
        return finding("fresh", False, f"The newest data is dated {-age:.0f} s in the future.", age_seconds=age)
    if market_open is False:
        return finding("fresh", None, f"Market closed. The newest data is from {last:%a %b %d %H:%M} UTC; it can't go stale while closed.", age_seconds=age)
    ok = age <= max_age_seconds
    return finding("fresh", ok, f"Newest data is {age:.0f} s old (limit {max_age_seconds:.0f} s).", age_seconds=age)


def advancing(prev_last: datetime | None, last: datetime | None, seconds_between_checks: float, expected_seconds: int,
              market_open: bool | None = True) -> dict:
    """Between two checks made while the market is open, the newest candle should have moved on."""
    if market_open is False:
        return finding("advancing", None, "Market closed; no new data is expected.")
    if prev_last is None or last is None:
        return finding("advancing", None, "First check: nothing to compare with yet.")
    if last < prev_last:
        return finding("advancing", False, "The newest data is older than last time: time went backwards.")
    if last == prev_last and seconds_between_checks > expected_seconds * 3:
        return finding("advancing", False, f"No new data for {seconds_between_checks:.0f} s while the market is open: the feed has stopped updating.")
    return finding("advancing", True, "Data is moving forward.")


def price_reasonable(price, reference: float | None = None, max_jump: float = 0.5) -> dict:
    if not _num(price) or price <= 0:
        return finding("price_range", False, "The price is missing, not a number, or not above zero.")
    if reference and _num(reference) and reference > 0:
        ch = abs(price - reference) / reference
        if ch > max_jump:
            return finding("price_range", False, f"The price moved {ch:.0%} from the last known value in one step, which looks like bad data.")
    return finding("price_range", True, "The price is a plausible number.")


def sudden_move(candles: list, max_step: float = 0.2) -> dict:
    closes = [_f(c, "close") for c in candles if _num(_f(c, "close")) and _f(c, "close") > 0]
    worst = max((abs(b - a) / a for a, b in zip(closes, closes[1:], strict=False)), default=0.0)
    return finding("continuity", worst <= max_step, f"Largest candle-to-candle move is {worst:.1%}." if worst <= max_step
                   else f"A {worst:.0%} jump between neighbouring candles: either extreme news or bad data, so it's treated as suspect.", worst=worst)


def shape(obj, required: dict[str, type | tuple], where: str) -> dict:
    """Has the source changed its reply format? `required` maps field name -> expected type(s)."""
    if not isinstance(obj, dict):
        return finding("format", False, f"{where}: expected an object and got {type(obj).__name__}. The source may have changed its format.")
    missing = [k for k in required if k not in obj or obj[k] is None]
    wrong = [k for k, t in required.items() if k in obj and obj[k] is not None and not isinstance(obj[k], t)]
    if missing or wrong:
        return finding("format", False, f"{where}: " + "; ".join(x for x in (f"missing {', '.join(missing)}" if missing else "",
                                                                         f"wrong type for {', '.join(wrong)}" if wrong else "") if x)
                       + ". The source may have changed its format.", missing=missing, wrong=wrong)
    return finding("format", True, f"{where}: the reply has the expected fields.")


def candle_checks(candles: list, expected_seconds: int, requested: str, now: datetime, max_age_seconds: float,
                  market_open: bool | None, expect_volume: bool = True) -> list[dict]:
    last = max((t for t in (_ts(c) for c in candles) if t), default=None)
    return [symbol_matches(requested, [_f(c, "symbol") for c in candles[-50:]]), candle_shape(candles), volume_valid(candles, expect_volume),
            order_and_duplicates(candles), timeframe_matches(candles, expected_seconds), missing_candles(candles, expected_seconds),
            sudden_move(candles), fresh(last, now, max_age_seconds, market_open)]
