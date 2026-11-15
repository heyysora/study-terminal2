"""The data-health engine: runs every probe on a schedule, classifies each source, keeps the evidence, tracks outages and
recoveries, and tells the safety controller which markets may produce ideas.

Statuses (per source):
  VERIFIED     every check passes AND the price was confirmed by an independent source
  HEALTHY      every check passes, but nothing independent exists to confirm the price
  DELAYED      every check passes, but the source is known to run behind (free futures data); ideas allowed, labelled delayed
  DEGRADED     a check is failing (bad candles, wrong symbol or timeframe, rate-limited, changed format)
  STALE        the data is too old, or has stopped updating while the market is open
  CONFLICTING  independent sources disagree by more than venues normally differ
  UNVERIFIED   there isn't enough evidence yet
  OFFLINE      the source can't be reached
  UNSUPPORTED  there is no legitimate way to connect to it
Ideas are allowed only on VERIFIED, HEALTHY or DELAYED. A failed check is never turned into a pass by falling back to something else.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from ..config import VERSION
from ..db.models import DataHealthOutage, DataHealthRecord
from .checks import TEST_VERSION

log = logging.getLogger(__name__)
GOOD = ("VERIFIED", "HEALTHY", "DELAYED")
DOWN = ("OFFLINE", "DEGRADED", "STALE")
CRITICAL = {"symbol identity", "candles", "order and duplicates", "timeframe", "freshness", "still updating", "price continuity",
            "reply format", "pair identity", "token identity", "reachability", "consistency", "price"}
MARKET_SOURCES = {"stocks": ["yahoo_stocks"], "futures": ["yahoo_futures"], "crypto": ["crypto_exchanges"], "memecoins": ["memecoin_data"]}
KEEP_DAYS = 45
WORDS = {"VERIFIED": "Verified", "HEALTHY": "Healthy", "DELAYED": "Delayed", "DEGRADED": "Degraded", "STALE": "Stale",
         "CONFLICTING": "Conflicting", "UNVERIFIED": "Unverified", "OFFLINE": "Offline", "UNSUPPORTED": "Not supported"}


def classify(res: dict) -> tuple[str, str]:
    """(status, why) from one probe result."""
    if res.get("unsupported"):
        return "UNSUPPORTED", "There's no legitimate way to connect to this source."
    if not res.get("reachable", True):
        return "OFFLINE", next((f["detail"] for f in res.get("findings", []) if f.get("ok") is False), "The source didn't answer.")
    feats = res.get("features") or {}
    failing = [(k, f) for k, f in feats.items() if f["state"] == "fail" and k in CRITICAL]
    if failing:
        only_age = all(k in ("freshness", "still updating") for k, _f in failing)
        return ("STALE" if only_age else "DEGRADED"), f"{failing[0][0].capitalize()}: {failing[0][1]['detail']}"
    if res.get("rate_limited"):
        return "DEGRADED", "The source is limiting how often it can be asked, so its data may be incomplete."
    quest = [(k, f) for k, f in feats.items() if f["state"] == "questionable"]
    if quest:
        return "CONFLICTING", quest[0][1]["detail"]
    if not feats:
        return "UNVERIFIED", "Nothing could be checked."
    price = feats.get("price") or feats.get("price extraction")
    others = [f for k, f in feats.items() if k in CRITICAL and k not in ("price",)]
    if price and price["state"] == "pass" and price.get("independent"):
        return "VERIFIED", price["detail"]
    if others and all(f["state"] in ("pass", "unknown") for f in others) and any(f["state"] == "pass" for f in others):
        if res.get("delayed"):
            return "DELAYED", f"Passing its automatic checks, but this source runs about {res['delayed']} behind and nothing independent confirms it."
        return "HEALTHY", "Passing its automatic checks. No independent source is available to confirm it."
    return "UNVERIFIED", (price or {}).get("detail") or "Not enough evidence yet."


def coverage(res: dict) -> dict:
    feats = res.get("features") or {}
    n = len(feats)
    by = {s: sorted(k for k, f in feats.items() if f["state"] == s) for s in ("pass", "fail", "questionable", "unknown", "unsupported")}
    indep = sorted(k for k, f in feats.items() if f["state"] == "pass" and f.get("independent"))
    return {"fields": n, "passing": len(by["pass"]), "independently_confirmed": indep, "by_state": by,
            "text": f"{len(by['pass'])} of {n} fields pass their checks; {len(indep)} confirmed by an independent source." if n else "Nothing checked."}


class DataHealth:
    def __init__(self, db, probes: list, chartwatch=None, positions_fn=lambda: [], kind: str = "live", start_delay: float = 4.0):
        self.start_delay = start_delay
        self.db, self.probes, self.chartwatch, self.positions_fn, self.kind = db, list(probes), chartwatch, positions_fn, kind
        self.state: dict[str, dict] = {}
        self.enforcing = False
        self._due: dict[str, float] = {}
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self.started_at = datetime.now(timezone.utc)
        self.token_flags: dict[str, dict] = {}
        self._pruned = 0.0
        self._settled = 0.0
        self._restore()

    # ---------------- persistence ----------------
    def _restore(self) -> None:
        """Show the last known result for each source after a restart, clearly marked as not yet re-checked."""
        with self.db.session() as s:
            for p in self.probes:
                r = s.scalars(select(DataHealthRecord).where(DataHealthRecord.source == p.source, DataHealthRecord.kind == self.kind)
                              .order_by(DataHealthRecord.id.desc()).limit(1)).first()
                if r:
                    d = json.loads(r.detail or "{}")
                    self.state[p.source] = {**d, "status": r.status, "checked_at": r.ts.isoformat(), "from_previous_run": True,
                                            "signals_permitted": False}

    def _save(self, entry: dict) -> None:
        with self.db.session() as s:
            s.add(DataHealthRecord(ts=datetime.fromisoformat(entry["checked_at"]), source=entry["source"], status=entry["status"],
                                   signals_permitted=int(entry["signals_permitted"]), kind=self.kind, app_version=VERSION,
                                   test_version=TEST_VERSION, detail=json.dumps({k: v for k, v in entry.items() if k not in ("from_previous_run",)}, default=str)))
            if time.monotonic() - self._pruned > 3600:   # old evidence is cleared once an hour, not on every write
                self._pruned = time.monotonic()
                s.execute(delete(DataHealthRecord).where(DataHealthRecord.ts < datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)))

    def _outage(self, source: str, was: str | None, now_status: str, why: str, at: datetime) -> None:
        bad_now, bad_before = now_status in DOWN, was in DOWN
        with self.db.session() as s:
            open_ = s.scalars(select(DataHealthOutage).where(DataHealthOutage.source == source, DataHealthOutage.ended_at.is_(None))).first()
            if bad_now and not open_:
                s.add(DataHealthOutage(source=source, started_at=at, status=now_status, reason=why[:400]))
            elif not bad_now and open_:
                open_.ended_at = at
            elif bad_now and open_ and not bad_before:
                open_.reason = why[:400]

    # ---------------- running ----------------
    async def run_probe(self, p, now: datetime | None = None) -> dict:
        at = now or datetime.now(timezone.utc)
        try:
            res = await asyncio.wait_for(p.run(), timeout=60)
        except asyncio.TimeoutError:
            res = {"source": p.source, "name": p.name, "market": p.market, "reachable": False, "features": {}, "symbols": {},
                   "findings": [{"check": "reachable", "ok": False, "detail": "The check took longer than 60 seconds and was stopped."}]}
        except Exception as e:  # noqa: BLE001 - a broken probe must show as a failure, never as silence
            log.exception("data-health probe %s crashed", p.source)
            res = {"source": p.source, "name": p.name, "market": p.market, "reachable": False, "features": {}, "symbols": {},
                   "findings": [{"check": "probe", "ok": False, "detail": f"The check itself failed: {type(e).__name__}"}]}
        status, why = classify(res)
        prev = self.state.get(p.source)
        entry = {**res, "status": status, "word": WORDS[status], "why": why, "checked_at": at.isoformat(), "coverage": coverage(res),
                 "signals_permitted": status in GOOD, "kind": self.kind,
                 "last_good_at": at.isoformat() if status in GOOD else (prev or {}).get("last_good_at")}
        was = (prev or {}).get("status") if prev and not prev.get("from_previous_run") else None
        entry["recovered"] = bool(was is not None and was not in GOOD and was != "UNSUPPORTED" and status in GOOD)
        self.state[p.source] = entry
        if p.source == "memecoin_data":
            self.token_flags = {m: d for m, d in (res.get("symbols") or {}).items()}
        try:                                         # written off the main loop so a slow disk never stalls the app's pages
            await asyncio.to_thread(self._save, entry)
            await asyncio.to_thread(self._outage, p.source, was, status, why, at)
        except Exception:  # noqa: BLE001 - evidence storage failing must not stop the checks
            log.exception("could not store data-health evidence")
        return entry

    async def run_all(self) -> dict:
        async with self._lock:
            for p in self.probes:
                await self.run_probe(p)
            if self.chartwatch:
                self.chartwatch.observe()
                await self.chartwatch.settle()
        return self.summary()

    async def _loop(self) -> None:
        await asyncio.sleep(self.start_delay)        # let the first screens load before the checks start using the network
        while True:
            try:
                async with self._lock:
                    for p in self.probes:
                        if time.monotonic() >= self._due.get(p.source, 0):
                            await self.run_probe(p)
                            st = self.state[p.source]["status"]
                            # a source in trouble is re-checked sooner, so recovery is noticed without anyone restarting anything
                            self._due[p.source] = time.monotonic() + (p.every if st in GOOD or st == "UNSUPPORTED" else min(p.every, 60))
                    if self.chartwatch:
                        self.chartwatch.observe()
                        if time.monotonic() - self._settled > 300:       # reference candles are fetched at most every 5 minutes
                            self._settled = time.monotonic()
                            await self.chartwatch.settle()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("data-health loop error")
            await asyncio.sleep(15)

    async def start(self) -> None:
        self.enforcing = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    # ---------------- the gate ----------------
    def permit(self, market: str, symbol: str | None = None) -> tuple[bool, str]:
        if not self.enforcing:
            return True, "Data checks aren't running in this session."
        for src in MARKET_SOURCES.get(market, []):
            st = self.state.get(src)
            if not st or st.get("from_previous_run"):
                return False, "Data checks haven't finished yet since Study Terminal started. Waiting for the first result."
            if st["status"] not in GOOD:
                return False, f"{st['name']} is {WORDS[st['status']].lower()}: {st['why']}"
            if symbol:
                per = (st.get("symbols") or {}).get(symbol) or (st.get("symbols") or {}).get(symbol.upper())
                if per and per.get("ok") is False:
                    return False, f"The data for {symbol} failed a check: {per.get('why')}"
        return True, "Data checks are passing."

    async def check_token(self, mint: str) -> dict:
        """Cross-check one memecoin's price right now (used before a practice buy)."""
        probe = next((p for p in self.probes if p.source == "memecoin_data"), None)
        if not probe:
            return {"ok": None, "why": "Token cross-checks aren't available."}
        try:
            per, _f, _r = await probe.check_tokens([mint])
        except Exception as e:  # noqa: BLE001
            return {"ok": None, "why": f"The cross-check couldn't run ({type(e).__name__})."}
        d = per.get(mint) or {"ok": None, "why": "No data for this token."}
        self.token_flags[mint] = d
        return d

    # ---------------- reporting ----------------
    def outages(self, limit: int = 50) -> list[dict]:
        with self.db.session() as s:
            rows = s.scalars(select(DataHealthOutage).order_by(DataHealthOutage.id.desc()).limit(limit)).all()
            return [{"source": o.source, "started_at": o.started_at.isoformat(), "ended_at": o.ended_at.isoformat() if o.ended_at else None,
                     "minutes": round((o.ended_at - o.started_at).total_seconds() / 60, 1) if o.ended_at else None,
                     "status": o.status, "reason": o.reason} for o in rows]

    def history(self, source: str, limit: int = 200) -> list[dict]:
        with self.db.session() as s:
            rows = s.scalars(select(DataHealthRecord).where(DataHealthRecord.source == source, DataHealthRecord.kind == self.kind)
                             .order_by(DataHealthRecord.id.desc()).limit(limit)).all()
            return [{"at": r.ts.isoformat(), "status": r.status, "signals_permitted": bool(r.signals_permitted), "app_version": r.app_version,
                     "test_version": r.test_version} for r in rows]

    def reliability(self, days: int = 7) -> dict:
        """Share of checks in which each source was good, per day: is it getting better or worse?"""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        out: dict[str, dict] = {}
        with self.db.session() as s:
            for r in s.scalars(select(DataHealthRecord).where(DataHealthRecord.ts >= since, DataHealthRecord.kind == self.kind)).all():
                d = out.setdefault(r.source, {}).setdefault(r.ts.date().isoformat(), [0, 0])
                d[0] += 1
                d[1] += 1 if r.status in GOOD else 0
        return {src: [{"day": day, "checks": n, "good_pct": round(g / n * 100)} for day, (n, g) in sorted(days_.items())] for src, days_ in out.items()}

    def flagged_positions(self) -> list[dict]:
        out = []
        for pos in self.positions_fn():
            ok, why = self.permit(pos["market"], pos.get("symbol"))
            if not ok:
                out.append({**pos, "warning": f"The data behind this open practice trade isn't trusted right now ({why}) "
                                              "Its stop, target and profit figures may be wrong until the data recovers."})
        return out

    def chart_source(self) -> dict | None:
        if not self.chartwatch:
            return None
        cw = self.chartwatch.summary()
        res = {"source": "topstepx_chart", "name": "TopstepX chart reading (your screen)", "market": "futures", "reachable": True,
               "features": cw["features"], "findings": [], "symbols": {}}
        c = cw["counts"]
        if not c["real_readings"]:
            status, why = "UNVERIFIED", cw["features"]["chart capture"]["detail"]
        else:
            status, why = classify(res)
            if status == "HEALTHY":
                status, why = "UNVERIFIED", cw["features"]["price extraction"]["detail"]      # for a screen reader, unconfirmed prices aren't "healthy"
        return {**res, "status": status, "word": WORDS[status], "why": why, "coverage": coverage(res), "signals_permitted": False,
                "checked_at": (cw["last"] or {}).get("at"), "chart": cw,
                "explain": "Your TopstepX chart is read from the screen. It's shown for studying and is never used on its own to give trade ideas."}

    def summary(self) -> dict:
        srcs = [self.state[p.source] if p.source in self.state else
                {"source": p.source, "name": p.name, "market": p.market, "status": "UNVERIFIED", "word": WORDS["UNVERIFIED"],
                 "why": "Not checked yet.", "signals_permitted": False, "features": {}, "coverage": coverage({}), "checked_at": None}
                for p in self.probes]
        ch = self.chart_source()
        if ch:
            srcs.append(ch)
        active = [s for s in srcs if s["status"] != "UNSUPPORTED" and s["source"] != "topstepx_chart"]
        bad = [s for s in active if s["status"] not in GOOD]
        stale = [s for s in active if s.get("from_previous_run")]
        if not self.enforcing:
            overall, tone = "Data checks aren't running in this session.", "idle"
        elif stale or any(s.get("checked_at") is None for s in active):
            overall, tone = "Checking your data sources. Trade ideas wait until the first check finishes.", "attention"
        elif not bad:
            ver = sum(1 for x in active if x["status"] == "VERIFIED")
            overall = (f"All {len(active)} connected data sources are passing their checks. {ver} of them are also confirmed by an independent source; "
                       "the rest have no free second source to compare with.")
            tone = "ok"
        else:
            b = bad[0]
            overall = b.get("explain") or f"{b['name']} is {WORDS[b['status']].lower()}. Study Terminal has paused new ideas that depend on it."
            if len(bad) > 1:
                overall += f" ({len(bad) - 1} other source{'s' if len(bad) > 2 else ''} also need attention.)"
            tone = "bad" if any(s["status"] in DOWN for s in bad) else "attention"
        return {"overall": overall, "tone": tone, "enforcing": self.enforcing, "sources": srcs, "outages": self.outages(20),
                "flagged_positions": self.flagged_positions(), "app_version": VERSION, "test_version": TEST_VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "legend": {"VERIFIED": ["Passed its checks and an independent source agrees.", "Trade ideas allowed."],
                           "HEALTHY": ["Passing its checks; nothing independent to confirm it.", "Trade ideas allowed, marked as not independently confirmed."],
                           "DELAYED": ["Passing its checks but known to run behind.", "Trade ideas allowed, marked as delayed."],
                           "DEGRADED": ["Some checks are failing.", "No trade ideas."], "STALE": ["Too old, or stopped updating.", "No trade ideas."],
                           "CONFLICTING": ["Independent sources disagree.", "No trade ideas."], "UNVERIFIED": ["Not enough evidence.", "No trade ideas."],
                           "OFFLINE": ["Can't be reached.", "No trade ideas."], "UNSUPPORTED": ["No legitimate way to connect.", "Not used."]},
                "note": "A source answering is not the same as its data being right. Only Verified, Healthy and Delayed sources may produce trade ideas."}

    def report(self) -> dict:
        """The full technical report."""
        return {**self.summary(), "reliability_7d": self.reliability(7), "history": {p.source: self.history(p.source, 50) for p in self.probes},
                "all_outages": self.outages(200), "thresholds": {"crypto price tolerance": "0.5% + 3x widest quoted spread",
                                                                 "memecoin price tolerance": "3%", "futures same-provider consistency": "0.2%",
                                                                 "stocks freshness limit (market open)": "20 minutes", "futures freshness limit (market open)": "30 minutes"}}
