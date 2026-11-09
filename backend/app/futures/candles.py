"""Candles from live trades, and session-aligned aggregation for every chart timeframe.

Rules (each one is tested):
  * Bars are built from TRADES (price, size, exchange timestamp), never from quotes. The exchange timestamp decides the bar.
  * Prices are snapped to the contract's tick grid to remove float noise. A price that is genuinely off the grid (more than a
    millionth of a tick away) is a corrupt print: it's dropped and counted, never "fixed".
  * Exact duplicates (same exchange time, price, size and side) are dropped and counted. Two genuine identical prints at the same
    microsecond would also be dropped; the count makes that visible.
  * A late trade for a bar that's still inside the revision window (10 minutes) updates that bar (high/low/volume; open or close
    only if it's earlier/later than what the bar already has) and the bar is marked revised. Older trades are counted as too late.
  * A bar closes on the clock: once its minute has ended plus a 2-second grace for in-flight prints.
  * Trades outside the trading session (daily break, weekend) are dropped and counted, except prints up to 5 seconds after the
    session close, which belong to the last minute.
  * Aggregation is anchored to the Globex open of each trade date (17:00 CT for CME equity index futures), so 1h/4h buckets never
    straddle two sessions; the daily bar is the whole trade date and is stamped 00:00 UTC of that date.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .contracts import ProductSpec
from .sessions import FuturesClock

TF_SECONDS = {"1Min": 60, "5Min": 300, "15Min": 900, "30Min": 1800, "1Hour": 3600, "4Hour": 14400, "1Day": 86400}
GRACE = timedelta(seconds=2)
CLOSE_PRINT_GRACE = timedelta(seconds=5)


def snap(price: float, spec: ProductSpec) -> tuple[float | None, bool]:
    """(price on the tick grid, was it on the grid). Off-grid prices return (None, False)."""
    tick = Decimal(spec.tick_size)
    p = Decimal(str(price))
    n = (p / tick).to_integral_value()
    snapped = n * tick
    if abs(p - snapped) > tick * Decimal("0.000001"):
        return None, False
    return float(snapped), True


def minute_start(ts: datetime) -> datetime:
    return ts.astimezone(timezone.utc).replace(second=0, microsecond=0)


@dataclass
class LiveBar:
    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    trades: int = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    closed: bool = False
    revised: int = 0
    source: str = "stream"           # stream | backfill

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ts"] = d.pop("start")
        return d


@dataclass
class BuilderStats:
    received: int = 0
    applied: int = 0
    duplicates: int = 0
    too_late: int = 0
    off_tick: int = 0
    outside_session: int = 0
    revisions: int = 0
    backfilled: int = 0
    last_trade_exchange_ts: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CandleBuilder:
    spec: ProductSpec
    clock: FuturesClock
    late_window: timedelta = timedelta(minutes=10)
    keep: int = 60 * 24 * 7                       # 1-minute bars kept in memory (a week)
    dedupe_size: int = 5000
    bars: "OrderedDict[datetime, LiveBar]" = field(default_factory=OrderedDict)
    stats: BuilderStats = field(default_factory=BuilderStats)

    def __post_init__(self):
        self._seen: set = set()
        self._seen_q: deque = deque()

    # ---------------- trades ----------------

    def _session_minute(self, ts: datetime) -> datetime | None:
        if self.clock.window_at(ts) is not None:
            return minute_start(ts)
        w = self.clock.window_at(ts - CLOSE_PRINT_GRACE)
        if w is not None and ts >= w.close:              # settlement/close print a moment after the close
            return minute_start(w.close - timedelta(seconds=1))
        return None

    def add_trade(self, price: float, volume: float, ts: datetime, side: int | None = None) -> dict:
        """Apply one trade. Returns {"kind": new|update|revised|duplicate|too_late|off_tick|outside_session, "bar": dict|None}."""
        self.stats.received += 1
        ts = ts.astimezone(timezone.utc)
        key = (ts.isoformat(), float(price), float(volume), side)
        if key in self._seen:
            self.stats.duplicates += 1
            return {"kind": "duplicate", "bar": None}
        self._seen.add(key)
        self._seen_q.append(key)
        if len(self._seen_q) > self.dedupe_size:
            self._seen.discard(self._seen_q.popleft())
        px, ok = snap(price, self.spec)
        if not ok:
            self.stats.off_tick += 1
            return {"kind": "off_tick", "bar": None}
        m = self._session_minute(ts)
        if m is None:
            self.stats.outside_session += 1
            return {"kind": "outside_session", "bar": None}
        newest = next(reversed(self.bars)) if self.bars else None
        if newest is not None and m < newest - self.late_window:
            self.stats.too_late += 1
            return {"kind": "too_late", "bar": None}
        b = self.bars.get(m)
        vol = float(volume)
        if b is None:
            b = LiveBar(start=m, open=px, high=px, low=px, close=px, first_ts=ts, last_ts=ts)
            self._insert(b)
            kind = "new"
        else:
            kind = "revised" if b.closed else "update"
            b.high, b.low = max(b.high, px), min(b.low, px)
            if b.first_ts is None or ts < b.first_ts:
                b.open, b.first_ts = px, ts
            if b.last_ts is None or ts >= b.last_ts:
                b.close, b.last_ts = px, ts
            if b.closed:
                b.revised += 1
                self.stats.revisions += 1
        b.volume += vol
        b.trades += 1
        if side == 0:
            b.buy_volume += vol
        elif side == 1:
            b.sell_volume += vol
        self.stats.applied += 1
        if self.stats.last_trade_exchange_ts is None or ts.isoformat() > self.stats.last_trade_exchange_ts:
            self.stats.last_trade_exchange_ts = ts.isoformat()
        return {"kind": kind, "bar": b.to_dict()}

    def _insert(self, b: LiveBar) -> None:
        out_of_order = bool(self.bars) and b.start < next(reversed(self.bars))
        self.bars[b.start] = b
        if out_of_order:                                   # a late trade opened an earlier minute: keep time order
            self.bars = OrderedDict(sorted(self.bars.items()))
        while len(self.bars) > self.keep:
            self.bars.popitem(last=False)

    # ---------------- clock ----------------

    def close_due(self, now: datetime) -> list[dict]:
        """Mark bars whose minute (plus grace) has ended as closed. Returns the newly closed bars, oldest first."""
        out = []
        for b in self.bars.values():
            if not b.closed and b.start + timedelta(minutes=1) + GRACE <= now:
                b.closed = True
                out.append(b.to_dict())
        return out

    # ---------------- history ----------------

    def merge_history(self, hist: list[dict], now: datetime) -> dict:
        """Merge REST 1-minute bars (backfill after start or reconnect). For minutes that have ended, the REST bar is
        authoritative and replaces whatever the stream built (the stream may have missed trades while disconnected).
        The minute still forming keeps the stream's version. Returns counts."""
        added = replaced = 0
        for h in hist:
            start = minute_start(h["ts"])
            if start + timedelta(minutes=1) > now:          # still forming: the stream owns it
                continue
            o, hi, lo, c = (snap(float(h[k]), self.spec)[0] for k in ("open", "high", "low", "close"))
            if None in (o, hi, lo, c):
                continue
            nb = LiveBar(start=start, open=o, high=hi, low=lo, close=c, volume=float(h.get("volume") or 0), closed=True, source="backfill")
            if start in self.bars:
                replaced += 1
            else:
                added += 1
            self.bars[start] = nb
        if added or replaced:
            self.bars = OrderedDict(sorted(self.bars.items()))
            while len(self.bars) > self.keep:
                self.bars.popitem(last=False)
        self.stats.backfilled += added + replaced
        return {"added": added, "replaced": replaced}

    def missing_minutes(self, since: datetime, until: datetime) -> list[datetime]:
        """Session minutes between `since` and `until` with no bar at all. Quiet minutes with no trades also show up here;
        backfill tells the two apart (REST returns nothing for a minute nobody traded)."""
        out = []
        m = minute_start(since)
        while m < minute_start(until):
            if m not in self.bars and self.clock.window_at(m) is not None:
                out.append(m)
            m += timedelta(minutes=1)
        return out

    def bars_list(self) -> list[dict]:
        return [b.to_dict() for b in self.bars.values()]


def bucket_start(ts: datetime, tf_seconds: int, clock: FuturesClock) -> tuple[datetime, datetime] | None:
    """(bucket start, bucket end) for a bar starting at ts, anchored to its session's Globex open. None outside sessions."""
    w = clock.window_at(ts)
    if w is None:
        return None
    if tf_seconds >= 86400:
        d = datetime(w.trade_date.year, w.trade_date.month, w.trade_date.day, tzinfo=timezone.utc)
        return d, w.close
    off = int((ts - w.open).total_seconds() // tf_seconds) * tf_seconds
    start = w.open + timedelta(seconds=off)
    return start.astimezone(timezone.utc), min(start + timedelta(seconds=tf_seconds), w.close).astimezone(timezone.utc)


def aggregate(bars: list[dict], tf_seconds: int, clock: FuturesClock, now: datetime | None = None) -> list[dict]:
    """Session-aligned aggregation of smaller bars (sorted or not). Volume is summed; open = first, close = last by time.
    Each output bar has `closed` = its bucket has ended (when `now` is given)."""
    out: dict[datetime, dict] = {}
    for b in sorted(bars, key=lambda x: x["ts"]):
        k = bucket_start(b["ts"], tf_seconds, clock)
        if k is None:
            continue
        start, end = k
        a = out.get(start)
        if a is None:
            out[start] = {"ts": start, "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"],
                          "volume": float(b.get("volume") or 0), "end": end, "revised": int(b.get("revised") or 0)}
        else:
            a["high"], a["low"], a["close"] = max(a["high"], b["high"]), min(a["low"], b["low"]), b["close"]
            a["volume"] += float(b.get("volume") or 0)
            a["revised"] += int(b.get("revised") or 0)
    res = list(out.values())
    for a in res:
        a["closed"] = bool(now and a["end"] <= now)
    return res
