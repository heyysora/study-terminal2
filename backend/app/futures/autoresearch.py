"""Weekly strategy research, run by the app itself.

Why it exists: a strategy may only trade (even with pretend money) once walk-forward research marks it VALIDATED, and that
verdict goes stale as new market data arrives. Re-running it by hand is exactly the kind of chore the app should do.

What it does NOT do: it never changes a strategy, a parameter or a threshold. It re-runs the same documented procedure
(`research.walk_forward`) on newer bars and records the verdict. A strategy that stops meeting the bar stops trading on the
next cycle; a strategy that starts meeting it starts trading. Both are logged and alerted.

Every run is appended to a history that is never rewritten, so a later run cannot hide an earlier poor result.

When it runs: each product is due 7 days after its last run. To stay out of the way of live monitoring, a due run waits for
that product's market to be closed (weekend or the daily break). If it stays due for more than `FORCE_AFTER` days anyway, it
runs regardless, because an out-of-date verdict is worse than a busy minute. One product at a time.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

EVERY = timedelta(days=7)
FORCE_AFTER = timedelta(days=11)
GAP = timedelta(minutes=2)               # between two products in the same sweep
KEEP_RUNS = 200
CHECK_SECONDS = 600.0


def _summary(res: dict) -> dict:
    """The small, permanent record of one run. Numbers only; no parameters to tune from."""
    oos, hold = res.get("oos_metrics") or {}, res.get("holdout_metrics") or {}
    return {"product": res.get("product"), "at": res.get("run_at"), "validated": sorted(res.get("validated") or []),
            "data": res.get("data"), "method": res.get("method"),
            "oos": {k: oos.get(k) for k in ("trades", "avg_r", "profit_factor", "total_r", "tier", "tier_text")},
            "holdout": {k: hold.get(k) for k in ("trades", "avg_r", "profit_factor", "total_r")}}


class AutoResearch:
    """Owns the weekly schedule. `svc` is the FuturesService; `store` the settings store."""

    HISTORY_ID = 6

    def __init__(self, svc, store, now=None, every: timedelta = EVERY, check_seconds: float = CHECK_SECONDS):
        self.svc, self.store, self._now = svc, store, now or (lambda: datetime.now(timezone.utc))
        self.every, self.check_seconds = every, check_seconds
        self._task: asyncio.Task | None = None
        self.last_error: str | None = None
        self.running: str | None = None
        self.history: list[dict] = (svc._load(self.HISTORY_ID) or {}).get("runs", [])

    # ---------------- schedule ----------------
    @property
    def enabled(self) -> bool:
        return bool(self.store.get("research.weekly", True))

    def roots(self) -> list[str]:
        return [r for r in (self.svc.automation.state.roots or []) if r] or ["NQ", "MNQ", "ES", "MES"]

    def last_run(self, root: str) -> datetime | None:
        """When this product was last researched: from the evidence itself, so a run you started by hand counts too."""
        at = ((self.svc.evidence.get(root) or {}).get("run") or {}).get("at") or (self.svc.evidence.get(root) or {}).get("run_at")
        try:
            return datetime.fromisoformat(at) if at else None
        except (TypeError, ValueError):
            return None

    def market_closed(self, root: str, now: datetime) -> bool:
        try:
            return self.svc.clock(root).window_at(now) is None
        except Exception:  # noqa: BLE001 - if the calendar can't say, don't block the run
            return True

    def due(self, now: datetime | None = None) -> list[dict]:
        """Every product and why it is or isn't due, oldest first. Used by the schedule and shown in the UI."""
        now = now or self._now()
        out = []
        for root in self.roots():
            last = self.last_run(root)
            age = (now - last) if last else None
            overdue = age is None or age >= self.every
            forced = age is None or age >= FORCE_AFTER
            closed = self.market_closed(root, now)
            out.append({"root": root, "last_run": last.isoformat() if last else None,
                        "days_since": round(age.total_seconds() / 86400, 1) if age else None,
                        "due": overdue, "ready": overdue and (closed or forced), "market_closed": closed,
                        "next_due": (last + self.every).isoformat() if last else "now",
                        "why": ("never researched" if last is None else
                                f"researched {age.days} day(s) ago" if not overdue else
                                "due; waiting for the market to close" if not (closed or forced) else "due")})
        out.sort(key=lambda d: (d["last_run"] or ""))
        return out

    # ---------------- running ----------------
    async def run_root(self, root: str, reason: str = "weekly") -> dict:
        """Research one product and record the result. Returns the permanent summary."""
        before = set((self.svc.evidence.get(root) or {}).get("validated") or [])
        self.running = root
        try:
            res = await self.svc.research(root)
        finally:
            self.running = None
        after = set(res.get("validated") or [])
        rec = {**_summary(res), "reason": reason, "started_validated": sorted(before), "changed": sorted(after ^ before)}
        self.history = (self.history + [rec])[-KEEP_RUNS:]
        self.svc._save(self.HISTORY_ID, {"runs": self.history})
        self._announce(root, before, after, rec)
        return rec

    def _announce(self, root: str, before: set, after: set, rec: dict) -> None:
        a = self.svc.automation
        gained, lost = sorted(after - before), sorted(before - after)
        tier = (rec["oos"] or {}).get("tier_text") or (rec["oos"] or {}).get("tier")
        a._log("info", f"Weekly research on {root} finished: {rec['oos'].get('trades')} out-of-sample trades, "
                       f"average {rec['oos'].get('avg_r')}R, {tier}. Validated strategies: {len(after)}.")
        for key, text, level in ((lost, "no longer validated and will not trade", "high"), (gained, "validated and may now trade", "medium")):
            if key:
                a._log(level, f"{root}: {', '.join(key)} {text} (weekly research, {rec['at'][:10]}).")
        if (gained or lost) and self.svc.alerts:
            self.svc.alerts.emit("system", "medium" if gained and not lost else "high", f"{root}: validated strategies changed",
                                 (f"Now trading: {', '.join(gained)}. " if gained else "")
                                 + (f"Stopped: {', '.join(lost)}. " if lost else "")
                                 + "Weekly research re-ran the same tests on newer market data. Practice trading only.",
                                 key=f"research:{root}", fingerprint=f"{root}:{sorted(after)}")

    async def tick(self, now: datetime | None = None) -> dict | None:
        """One scheduler step: research the product that has waited longest, if any is ready. At most one per call."""
        if not self.enabled or self.running or self.svc._bt_running:
            return None
        ready = [d for d in self.due(now) if d["ready"]]
        if not ready:
            return None
        root = ready[0]["root"]
        try:
            return await self.run_root(root, reason="weekly")
        except Exception as e:  # noqa: BLE001 - a failed run is reported, never silent, and tried again next check
            self.last_error = f"{type(e).__name__}: {str(e)[:200]}"
            log.exception("weekly research on %s failed", root)
            self.svc.automation._log("medium", f"Weekly research on {root} couldn't run ({self.last_error}). It will try again later.")
            return None

    async def _loop(self) -> None:
        await asyncio.sleep(90)                     # let the app finish starting before any heavy work
        while True:
            try:
                await self.tick()
                if self.running is None and any(d["ready"] for d in self.due()):
                    await asyncio.sleep(GAP.total_seconds())
                    continue
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("weekly research scheduler error")
            await asyncio.sleep(self.check_seconds)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    # ---------------- reporting ----------------
    def status(self) -> dict:
        return {"enabled": self.enabled, "every_days": self.every.days, "running": self.running, "last_error": self.last_error,
                "products": self.due(), "history": self.history[::-1][:40],
                "note": "Research re-runs the same documented tests on newer market data. It never changes a strategy, a parameter "
                        "or a threshold. Results are kept for good, so a later run can't hide an earlier poor one.",
                "validated_now": {r: sorted((self.svc.evidence.get(r) or {}).get("validated") or []) for r in self.roots()}}
