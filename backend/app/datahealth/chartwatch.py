"""Automatic validation of the TopstepX chart reader, on the PC where the chart actually is.

It only LOOKS at what the existing Visual Monitor already captured. It never clicks, types, logs in, or touches the page.
Every reading is saved. Because free futures data is delayed, a reading isn't compared straight away: about 20 minutes later
the 1-minute reference candles around the reading's own time are fetched, and the price read from the screen has to fall inside
those candles' range (plus a small allowance). That compares the same instrument at the same time, not two different moments.

What this can and can't establish:
  price extraction      independently checkable (against delayed reference candles)
  symbol                independently checkable in part: an NQ chart read as ES would be thousands of points off the reference
  timeframe             read from the chart's own label only; no independent source, so it stays unverified
  candles               estimated from the picture; not validated here
Results from test or demo capture sources are stored but never counted as evidence.
"""
from __future__ import annotations

import json
import platform
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..backtest.odds import data_symbol
from ..config import VERSION
from ..db.models import ChartObservation
from ..market_data.types import Timeframe
from .compare import within_range

COMPARE_AFTER = timedelta(minutes=20)       # free futures data runs roughly 10-15 minutes behind
GIVE_UP_AFTER = timedelta(hours=6)
TOLERANCE = 0.0006                          # 0.06% either side of the reference candles (bid/ask, tick rounding, clock skew)
NEED_MATCHES, NEED_DAYS, NEED_RATE = 30, 2, 0.95
SCENARIOS = {"normal": "Normal visible chart", "minimized_restored": "Minimized, then restored", "hidden_recovered": "Covered or another tab, then back",
             "frozen": "Frozen chart detected", "resized": "Window resized", "symbol_changed": "Contract changed", "timeframe_changed": "Timeframe changed",
             "restart": "Kept working after Study Terminal restarted", "window_gone": "Edge or the TopstepX tab closed"}
NOT_OBSERVABLE = {"Browser zoom changes": "Zoom can't be told apart from a resize by looking, and changing it would mean sending keys to the page.",
                  "Temporary internet loss": "From the screen alone this looks the same as a frozen chart; it is recorded as 'frozen'.",
                  "TopstepX session expiration": "A logged-out page is recorded as 'chart not readable'; the reason can't be confirmed without reading account pages.",
                  "Switching timeframe or contract on purpose": "Study Terminal never clicks in TopstepX. These are recorded when YOU change them."}


class ChartWatch:
    def __init__(self, db, visual, monitor, real_fn=lambda: False, every: float = 15.0):
        self.db, self.visual, self.monitor, self.real_fn, self.every = db, visual, monitor, real_fn, every
        self.os = platform.platform()
        self._prev: dict[str, dict] = {}
        self._started = datetime.now(timezone.utc)
        self._first_good_done = False
        self.scenarios: dict[str, dict] = {}
        self._load_scenarios()

    # ---------------- observing ----------------
    def _load_scenarios(self) -> None:
        with self.db.session() as s:
            for o in s.scalars(select(ChartObservation).where(ChartObservation.outcome == "scenario")).all():
                d = json.loads(o.detail or "{}")
                k = d.get("scenario")
                if k and o.real_capture:
                    e = self.scenarios.setdefault(k, {"count": 0, "last": None, "handled": 0})
                    e["count"] += 1
                    e["handled"] += 1 if d.get("handled") else 0
                    e["last"] = o.ts.isoformat()

    def _scenario(self, key: str, handled: bool, note: str, now: datetime, real: bool) -> None:
        with self.db.session() as s:
            s.add(ChartObservation(ts=now, status="scenario", outcome="scenario", real_capture=int(real), app_version=VERSION, os_version=self.os,
                                   detail=json.dumps({"scenario": key, "handled": handled, "note": note})))
        if real:
            e = self.scenarios.setdefault(key, {"count": 0, "last": None, "handled": 0})
            e["count"] += 1
            e["handled"] += 1 if handled else 0
            e["last"] = now.isoformat()

    def observe(self, now: datetime | None = None) -> list[dict]:
        """Record what the Visual Monitor sees right now. Cheap; called every few seconds."""
        now = now or datetime.now(timezone.utc)
        real = bool(self.real_fn())
        out = []
        charts = (self.visual.status() or {}).get("charts", {}) if self.visual and getattr(self.visual, "state", "") == "running" else {}
        for pid, ch in charts.items():
            rd = ch.get("reading") or {}
            status = ch.get("status") or "unknown"
            reason = (ch.get("reason") or "")[:200]
            sym = ((rd.get("instrument") or {}).get("value") or "") if status == "screen_capture" else ""
            tf = ((rd.get("timeframe") or {}).get("value") or "") if status == "screen_capture" else ""
            px = (rd.get("price") or {}).get("value") if status == "screen_capture" else None
            cls = (rd.get("price") or {}).get("class") or ""
            size = tuple(rd.get("size") or ())
            cur = {"status": status, "symbol": str(sym), "timeframe": str(tf), "size": size, "reason": reason}
            prev = self._prev.get(pid)
            good = status == "screen_capture" and isinstance(px, (int, float)) and px > 0
            # scenarios, recognised from what changed since the last look
            if prev:
                was = prev["status"]
                if was == "disconnected" and good:
                    self._scenario("minimized_restored" if "minim" in prev["reason"].lower() else "window_gone", True, "came back and read a price", now, real)
                if was == "unreadable" and good:
                    self._scenario("hidden_recovered", True, "became readable again", now, real)
                if status == "stale" and was != "stale" and "frozen" in reason.lower():
                    self._scenario("frozen", True, reason, now, real)
                if good and was == "screen_capture":
                    if prev["size"] and size and prev["size"] != size:
                        self._scenario("resized", True, f"{prev['size']} -> {size}; still reading", now, real)
                    if prev["symbol"] and sym and prev["symbol"] != sym:
                        self._scenario("symbol_changed", True, f"{prev['symbol']} -> {sym}", now, real)
                    if prev["timeframe"] and tf and prev["timeframe"] != tf:
                        self._scenario("timeframe_changed", True, f"{prev['timeframe']} -> {tf}", now, real)
                if status == "disconnected" and was != "disconnected" and "minim" not in reason.lower():
                    self._scenario("window_gone", False, reason, now, real)
            if good and not self._first_good_done:
                self._first_good_done = True
                with self.db.session() as s:
                    had = s.scalar(select(ChartObservation.id).where(ChartObservation.ts < self._started, ChartObservation.outcome != "scenario").limit(1))
                self._scenario("restart" if had else "normal", True, "first good reading after starting", now, real)
            self._prev[pid] = cur
            # keep one reading a minute per chart (plus every change of state)
            last_at = (prev or {}).get("saved_at")
            if prev and prev["status"] == status and last_at and (now - last_at).total_seconds() < 60:
                cur["saved_at"] = last_at
                continue
            cur["saved_at"] = now
            row = ChartObservation(ts=now, status=status, symbol=str(sym)[:24], timeframe=str(tf)[:12], price=float(px) if good else None,
                                   price_class=str(cls)[:32], ref_symbol=data_symbol(str(sym)) if sym else "",
                                   outcome="pending" if good and sym else "not_readable", real_capture=int(real), app_version=VERSION,
                                   os_version=self.os, detail=json.dumps({"profile": pid, "reason": reason, "confidence": rd.get("confidence"),
                                                                          "capture_method": ch.get("capture_method")}))
            with self.db.session() as s:
                s.add(row)
            out.append({"profile": pid, "status": status, "symbol": sym, "price": px})
        return out

    # ---------------- comparing with reference data ----------------
    async def settle(self, now: datetime | None = None) -> int:
        """Compare readings that are old enough for the delayed reference data to have caught up."""
        now = now or datetime.now(timezone.utc)
        with self.db.session() as s:
            due = s.scalars(select(ChartObservation).where(ChartObservation.outcome == "pending", ChartObservation.ts <= now - COMPARE_AFTER)
                            .order_by(ChartObservation.ts).limit(40)).all()
            due = [(o.id, o.ts, o.price, o.ref_symbol) for o in due]
        if not due:
            return 0
        cache: dict[str, list] = {}
        done = 0
        for oid, ts, price, ref in due:
            outcome, lo, hi, diff, note = "no_reference", None, None, None, ""
            try:
                if ref not in cache:
                    first = min(t for _i, t, _p, r in due if r == ref)
                    cache[ref], _n = await self.monitor.provider.get_bars(ref, Timeframe.M1, first - timedelta(minutes=5), now)
                near = [b for b in cache[ref] if abs((b.ts - ts.replace(second=0, microsecond=0)).total_seconds()) <= 60]
                if near:
                    lo, hi = min(b.low for b in near), max(b.high for b in near)
                    w = within_range(price, lo, hi, TOLERANCE)
                    outcome, diff, note = ("match" if w["ok"] else "mismatch"), w["diff_pct"], w["detail"]
                elif now - ts < GIVE_UP_AFTER:
                    continue                                   # the reference hasn't reached that minute yet; try again later
                else:
                    note = "No reference candle exists for that minute (market closed, or the free data has a hole)."
            except Exception as e:  # noqa: BLE001
                if now - ts < GIVE_UP_AFTER:
                    continue
                note = f"Reference data couldn't be fetched: {type(e).__name__}"
            with self.db.session() as s:
                o = s.get(ChartObservation, oid)
                o.outcome, o.ref_low, o.ref_high, o.diff_pct, o.tolerance_pct = outcome, lo, hi, diff, TOLERANCE * 100
                o.detail = json.dumps({**json.loads(o.detail or "{}"), "comparison": note, "reference": "Yahoo 1-minute candles (delayed)"})
            done += 1
        return done

    # ---------------- reporting ----------------
    def summary(self) -> dict:
        with self.db.session() as s:
            rows = s.scalars(select(ChartObservation).where(ChartObservation.outcome != "scenario").order_by(ChartObservation.id.desc()).limit(5000)).all()
            rows = [(o.ts, o.status, o.symbol, o.timeframe, o.price, o.outcome, o.diff_pct, bool(o.real_capture), o.ref_low, o.ref_high, o.detail) for o in rows]
        real = [r for r in rows if r[7]]
        cmp = [r for r in real if r[5] in ("match", "mismatch")]
        match = [r for r in cmp if r[5] == "match"]
        days = {r[0].date() for r in match}
        rate = len(match) / len(cmp) if cmp else None
        readable = [r for r in real if r[1] == "screen_capture"]
        f = {}
        if not real:
            f["chart capture"] = ("unknown", "No real readings of your TopstepX chart have been recorded on this PC yet. Open TopstepX in Edge and "
                                             "connect it under My chart; validation then starts by itself.")
        else:
            share = len(readable) / len(real)
            f["chart capture"] = ("pass" if share >= 0.8 else "fail", f"{len(readable)} of {len(real)} recent looks at the chart produced a reading ({share:.0%}).")
        if not cmp:
            f["price extraction"] = ("unknown", f"No reading has been compared with reference data yet ({sum(1 for r in real if r[5] == 'pending')} waiting; "
                                                f"comparisons happen about 20 minutes after each reading, while the futures market is open).")
        elif len(match) >= NEED_MATCHES and len(days) >= NEED_DAYS and rate >= NEED_RATE:
            f["price extraction"] = ("pass", f"{len(match)} of {len(cmp)} readings matched independent reference candles ({rate:.0%}) over {len(days)} days.")
        elif rate < 0.8 and len(cmp) >= 10:
            f["price extraction"] = ("fail", f"Only {len(match)} of {len(cmp)} readings matched the reference candles ({rate:.0%}).")
        else:
            f["price extraction"] = ("unknown", f"{len(match)} of {len(cmp)} readings matched so far ({rate:.0%}) over {len(days)} day(s). "
                                                f"Needs {NEED_MATCHES} matches across {NEED_DAYS} days at {NEED_RATE:.0%} to count as verified.")
        st, det = f["price extraction"]
        f["symbol detection"] = (st, ("The contract read from the chart is consistent with the reference prices for that contract." if st == "pass"
                                      else "Follows price extraction: a wrong contract would put the price far outside the reference range. " + det))
        f["timeframe detection"] = ("unknown", "Read from the chart's own label. No independent source can confirm a chart's timeframe, so it stays unverified.")
        f["candle values"] = ("unknown", "Candles are estimated from the picture and aren't validated automatically.")
        f["frozen-chart detection"] = (("pass", f"Detected {self.scenarios['frozen']['count']} time(s) on this PC.") if self.scenarios.get("frozen")
                                       else ("unknown", "Not seen on this PC yet. Tested with simulated charts only."))
        f["recovery after minimize / hidden tab"] = (("pass", "Seen recovering on this PC.") if (self.scenarios.get("minimized_restored") or self.scenarios.get("hidden_recovered"))
                                                     else ("unknown", "Not seen on this PC yet. Tested with simulated charts only."))
        last = rows[0] if rows else None
        return {"features": {k: {"state": v[0], "detail": v[1], "independent": k in ("price extraction", "symbol detection") and v[0] == "pass"} for k, v in f.items()},
                "counts": {"real_readings": len(real), "compared": len(cmp), "matched": len(match), "mismatched": len(cmp) - len(match),
                           "waiting": sum(1 for r in real if r[5] == "pending"), "days_with_matches": len(days), "test_source_readings": len(rows) - len(real)},
                "last": last and {"at": last[0].isoformat(), "status": last[1], "symbol": last[2], "timeframe": last[3], "price": last[4], "outcome": last[5]},
                "scenarios": [{"key": k, "name": n, **(self.scenarios.get(k) or {"count": 0, "last": None, "handled": 0})} for k, n in SCENARIOS.items()],
                "cannot_observe": NOT_OBSERVABLE, "os": self.os,
                "recent": [{"at": r[0].isoformat(), "status": r[1], "symbol": r[2], "timeframe": r[3], "price": r[4], "outcome": r[5], "diff_pct": r[6],
                            "ref_low": r[8], "ref_high": r[9], "real": r[7]} for r in rows[:40]],
                "rules": f"Verified needs {NEED_MATCHES} matches on {NEED_DAYS} different days with at least {NEED_RATE:.0%} matching; "
                         f"allowance {TOLERANCE:.2%} either side of the 1-minute reference candles.",
                "note": "Reference: Yahoo continuous futures candles, delayed. If your chart shows a later contract month than the front month, "
                        "its price legitimately differs and readings will show as mismatches."}
