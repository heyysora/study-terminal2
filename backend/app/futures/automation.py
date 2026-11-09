"""Automation engine for futures. Three modes:

  A  assisted     monitors, evaluates, alerts and explains. You decide and place every paper order.
  B  paper_auto   additionally enters and manages SIMULATED trades on its own, but only for decisions the pipeline marks
                  APPROVED (validated strategy, every risk check passed). It never bypasses the risk engine.
  C  live         LOCKED. There is no order-routing code in Study Terminal. See LIVE_CHECKLIST for what would have to be
                  verified, and by whom, before anything like it could be built.

Experimental (unvalidated) strategies can run only in the separate research sandbox account, never in the practice account.

Safety rules enforced here:
  * one decision -> at most one order (decision id = order idempotency key, stored in the database);
  * an APPROVED decision is only acted on while its bar is the newest one; after a restart old decisions are never replayed;
  * no new entry while the contract already has a position or a working entry;
  * every management action (break-even, trailing stop, partial exit, time exit, invalidation exit) is recorded with its reason;
  * emergency stop cancels automation orders, flattens automation positions (or queues them for the first fillable price)
    and stays stopped until you clear it.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from . import contracts as fc
from .contracts import fmt_num

log = logging.getLogger(__name__)

MODES = {"assisted": "A: assisted", "paper_auto": "B: automated paper trading", "live": "C: live execution (locked)"}

LIVE_CHECKLIST = [
    {"item": "Topstep allows automated trading through the TopstepX (ProjectX) API", "status": "documented",
     "detail": "help.topstep.com 'TopstepX API Access' (checked 2026-11-08): custom bots allowed via the API, no HFT. An older TopstepX FAQ "
               "still says bots aren't supported; ask Topstep to confirm in writing."},
    {"item": "Your account type may trade through the API", "status": "partly documented",
     "detail": "Live Funded Accounts may NOT trade through the API. The article doesn't address Trading Combine or Express Funded explicitly."},
    {"item": "Execution only from your own computer", "status": "documented",
     "detail": "VPS, VPNs and remote servers are prohibited for trading. Study Terminal runs locally, but the mobile companion must never place orders."},
    {"item": "Order endpoints and behaviour verified on a Practice account", "status": "not done",
     "detail": "ProjectX documents /api/Order/place (limit, market, stop, trailing stop; brackets only in Auto OCO mode). Nothing has been tested."},
    {"item": "A validated strategy with reliable out-of-sample evidence", "status": "not met",
     "detail": "No futures strategy is validated today (docs/BACKTEST_RESULTS_FUTURES.md)."},
    {"item": "Your explicit written authorization in the app", "status": "not given", "detail": "Required even after everything above."},
]


@dataclass
class ManagementRules:
    target_r: float = 2.0
    partial_at_r: float | None = 1.0          # take part of the position off at this R (None = no partial)
    partial_pct: float = 50.0
    breakeven_at_r: float | None = 1.0        # move the stop to entry once price reaches this R
    trail_activate_r: float | None = 1.5      # start trailing at this R
    trail_atr_mult: float = 1.5
    max_hold_minutes: int | None = 120
    exit_on_invalidation: bool = True
    entry_type: str = "limit"                 # limit at the planned entry, or market
    entry_valid_bars: int = 2                 # cancel an unfilled entry after this many bars

    @classmethod
    def from_dict(cls, d: dict | None) -> "ManagementRules":
        names = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in (d or {}).items() if k in names})


@dataclass
class AutomationState:
    mode: str = "assisted"
    status: str = "stopped"                  # stopped | running | paused | emergency_stopped
    roots: list[str] = field(default_factory=lambda: ["NQ", "MNQ", "ES", "MES"])
    interval_seconds: float = 60.0
    sandbox_enabled: bool = False
    rules: dict = field(default_factory=dict)             # strategy key or "default" -> ManagementRules dict
    started_at: str | None = None
    last_cycle_at: str | None = None
    cycles: int = 0
    per_contract: dict = field(default_factory=dict)      # contract -> {last_eval, outcome, action, data_status, error}
    managed: dict = field(default_factory=dict)           # contract -> {decision_id, entry, stop0, risk_points, opened, rules, done:[...]}
    log: list = field(default_factory=list)
    emergency: dict | None = None
    live_authorized: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "AutomationState":
        names = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in (d or {}).items() if k in names})


class AutomationEngine:
    def __init__(self, svc, state: AutomationState | None = None,
                 evaluate: Callable[..., Awaitable[dict]] | None = None, now: Callable[[], datetime] | None = None):
        self.svc = svc                     # FuturesService (engine, sandbox engine, persistence, alerts)
        self.state = state or AutomationState()
        self._evaluate = evaluate          # tests inject; default uses svc.evaluate_contract
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    # ---------------- control ----------------

    def _log(self, level: str, text: str, **data) -> None:
        self.state.log = (self.state.log + [{"at": self._now().isoformat(), "level": level, "text": text, **data}])[-500:]
        if level in ("high", "critical") and self.svc.alerts:
            self.svc.alerts.emit("system" if level == "critical" else "position", "high", "Futures automation", text,
                                 key=f"auto:{text[:40]}", fingerprint=text[:80])

    def save(self) -> None:
        self.svc.save_automation(self.state.to_dict())

    def set_mode(self, mode: str) -> dict:
        if mode == "live":
            raise PermissionError("Live execution is locked. Study Terminal has no order-routing code; see the checklist.")
        if mode not in MODES:
            raise ValueError(f"Unknown mode {mode}")
        self.state.mode = mode
        self._log("info", f"Mode set to {MODES[mode]}.")
        self.save()
        return self.status()

    def configure(self, d: dict) -> dict:
        if "roots" in d:
            roots = [r.upper() for r in d["roots"]]
            for r in roots:
                fc.get(r)
            self.state.roots = roots
        if "interval_seconds" in d:
            self.state.interval_seconds = max(20.0, float(d["interval_seconds"]))
        if "sandbox_enabled" in d:
            self.state.sandbox_enabled = bool(d["sandbox_enabled"])
        if "rules" in d:
            self.state.rules = {k: asdict(ManagementRules.from_dict(v)) for k, v in d["rules"].items()}
        self.save()
        return self.status()

    async def start(self) -> dict:
        if self.state.status == "emergency_stopped":
            raise PermissionError("Emergency stop is active. Review what happened, then clear it before starting again.")
        self.state.status = "running"
        self.state.started_at = self.state.started_at or self._now().isoformat()
        self._log("info", f"Monitoring started ({MODES[self.state.mode]}) for {', '.join(self.state.roots)}.")
        self._spawn()
        self.save()
        return self.status()

    def _spawn(self) -> None:
        if self._task is None or self._task.done():
            try:
                self._task = asyncio.get_running_loop().create_task(self._loop())
            except RuntimeError:
                self._task = None

    def pause(self) -> dict:
        if self.state.status == "running":
            self.state.status = "paused"
            self._log("info", "Monitoring paused by you. No evaluations or automated actions until you resume.")
            self.save()
        return self.status()

    async def resume(self) -> dict:
        if self.state.status == "emergency_stopped":
            raise PermissionError("Emergency stop is active. Review what happened, then clear it on the computer before resuming.")
        if self.state.status == "paused":
            return await self.start()
        return self.status()

    async def stop(self) -> dict:
        if self.state.status != "emergency_stopped":
            self.state.status = "stopped"
        self.state.started_at = None
        self._log("info", "Monitoring stopped.")
        if self._task:
            self._task.cancel()
            self._task = None
        self.save()
        return self.status()

    async def emergency_stop(self, reason: str = "Emergency stop pressed") -> dict:
        now = self._now()
        canceled, flattened, queued = 0, 0, 0
        for eng, acct in self.engines():
            for o in list(eng.orders.values()):
                if o.active and o.origin in ("automation", "sandbox"):
                    eng.cancel(o.id, now, f"Emergency stop: {reason}")
                    canceled += 1
            for c, p in list(eng.positions.items()):
                if p.qty and c in self.state.managed and self.state.managed[c].get("account") == acct:
                    if p.mark_status in ("realtime", "near_realtime", "polling", "replay") or (p.mark_status == "delayed" and eng.cfg.allow_delayed_practice):
                        eng.flatten(c, now, f"Emergency stop: {reason}", price=p.mark, ts_basis=f"last {p.mark_status} price")
                        flattened += 1
                    else:
                        eng.pending_flatten[c] = f"Emergency stop: {reason} (data wasn't fillable; flattened at the first fillable price)"
                        queued += 1
        self.state.status = "emergency_stopped"
        self.state.emergency = {"at": now.isoformat(), "reason": reason, "orders_canceled": canceled, "positions_flattened": flattened,
                                "positions_queued": queued}
        self._log("critical", f"EMERGENCY STOP: {reason}. Canceled {canceled} automation orders, flattened {flattened} positions"
                  + (f", {queued} queued for the first fillable price" if queued else "") + ".")
        if self._task:
            self._task.cancel()
            self._task = None
        self.svc.save()
        self.save()
        return self.status()

    def clear_emergency(self, note: str) -> dict:
        if self.state.status != "emergency_stopped":
            return self.status()
        if not note or len(note.strip()) < 10:
            raise ValueError("Write at least a sentence about what happened before clearing the emergency stop.")
        self.state.status, self.state.emergency = "stopped", None
        self._log("info", f"Emergency stop cleared: {note.strip()}")
        self.save()
        return self.status()

    def engines(self):
        out = [(self.svc.engine, "practice")]
        if self.svc.sandbox is not None:
            out.append((self.svc.sandbox, "sandbox"))
        return out

    def status(self) -> dict:
        s = self.state
        return {"mode": s.mode, "mode_label": MODES.get(s.mode), "status": s.status, "roots": s.roots, "interval_seconds": s.interval_seconds,
                "sandbox_enabled": s.sandbox_enabled, "started_at": s.started_at, "last_cycle_at": s.last_cycle_at, "cycles": s.cycles,
                "per_contract": s.per_contract, "managed": s.managed, "log": s.log[-100:][::-1], "emergency": s.emergency,
                "live": {"locked": True, "checklist": LIVE_CHECKLIST,
                         "note": "Live execution is locked and not implemented. No code in Study Terminal can send an order to TopstepX."},
                "rules": {k: v for k, v in (s.rules or {}).items()} or {"default": asdict(ManagementRules())},
                "running_task": bool(self._task and not self._task.done())}

    def rules_for(self, key: str) -> ManagementRules:
        r = self.state.rules or {}
        return ManagementRules.from_dict(r.get(key) or r.get("default"))

    # ---------------- loop ----------------

    async def _loop(self) -> None:
        while True:
            if self.state.status == "running":
                try:
                    await self.cycle()
                except Exception:  # noqa: BLE001
                    log.exception("automation cycle failed")
                    self._log("high", "An automation cycle failed; see the log file. Monitoring continues.")
            await asyncio.sleep(self.state.interval_seconds)

    async def cycle(self) -> list[dict]:
        """One pass over every monitored contract. Returns what it did (for tests and the UI)."""
        async with self._lock:
            now = self._now()
            actions: list[dict] = []
            gap = self.svc.downtime.tick(now) if hasattr(self.svc, "downtime") else None
            if gap:
                self._log("high", f"Monitoring was interrupted for {gap['seconds'] // 60} min; missed bars are reconciled before any decision.")
            for root in self.state.roots:
                contract = fc.front_contract(root, now.astimezone(fc.CT).date())
                try:
                    sig = await (self._evaluate or self._default_eval)(contract, self.state.mode)
                except Exception as e:  # noqa: BLE001 - one bad contract mustn't stop the others
                    self.state.per_contract[contract.code] = {"last_eval": now.isoformat(), "error": f"{type(e).__name__}: {str(e)[:160]}"}
                    continue
                dec = sig.get("decision") or {}
                prev = self.state.per_contract.get(contract.code, {})
                self.state.per_contract[contract.code] = {
                    "last_eval": now.isoformat(), "outcome": dec.get("outcome"), "action": sig.get("action"), "reason": (sig.get("reasons") or [""])[0],
                    "data_status": (sig.get("data") or {}).get("status"), "data_time": (sig.get("data") or {}).get("data_time"),
                    "decision_id": dec.get("id"), "development": sig.get("development"), "regime": (sig.get("regime") or {}).get("label")}
                if dec.get("outcome") and dec.get("outcome") != prev.get("outcome") and dec.get("outcome") in ("APPROVED", "INVALIDATED"):
                    self._log("medium", f"{contract.code}: {dec['outcome']}: {dec.get('reason')}", decision_id=dec.get("id"))
                actions += self._manage(contract, sig, now)
                if self.state.mode == "paper_auto" and dec.get("outcome") == "APPROVED":
                    a = self._enter(contract, dec, now, self.svc.engine, "practice", "automation")
                    if a:
                        actions.append(a)
                if self.state.sandbox_enabled and self.svc.sandbox is not None and self._sandbox_eligible(dec):
                    a = self._enter(contract, dec, now, self.svc.sandbox, "sandbox", "sandbox")
                    if a:
                        actions.append(a)
                self._expire_entries(contract, now)
            self.state.cycles += 1
            self.state.last_cycle_at = now.isoformat()
            self.svc.save()
            self.save()
            return actions

    async def _default_eval(self, contract: fc.Contract, mode: str) -> dict:
        sig, *_ = await self.svc.evaluate_contract(contract, mode=mode)
        return sig

    @staticmethod
    def _sandbox_eligible(dec: dict) -> bool:
        """Experimental: every step passed except strategy validation (step 7)."""
        if dec.get("outcome") != "WATCH_ONLY":
            return False
        fails = [s for s in dec.get("steps", []) if s.get("passed") is False]
        return len(fails) == 1 and fails[0]["n"] == 7

    def _enter(self, contract: fc.Contract, dec: dict, now: datetime, eng, account: str, origin: str) -> dict | None:
        plan = dec.get("plan") or {}
        did = dec["id"] if account == "practice" else f"sbx-{dec['id']}"
        latest = (self.state.per_contract.get(contract.code) or {}).get("data_time")
        if dec.get("bar_time") and latest and dec["bar_time"] < latest:
            return None                                                    # stale decision: never act on an old bar
        if any(o.signal_id == did for o in eng.orders.values()):
            return None                                                    # already acted (also survives restarts)
        if (eng.positions.get(contract.code) and eng.positions[contract.code].qty) or any(
                o.active and o.contract == contract.code and o.role == "entry" for o in eng.orders.values()):
            self._log("info", f"{contract.code}: approved idea skipped, already in a position or an entry is working.", decision_id=dec["id"])
            return None
        key = f"{plan.get('setup')}|{plan.get('direction')}"
        rules = self.rules_for(key)
        d = 1 if plan.get("direction") == "long" else -1
        qty = int(plan.get("suggested_contracts") or 0) if account == "practice" else 1
        if qty < 1:
            return None
        risk_pts = abs(plan["entry"] - plan["stop"])
        spec = contract.spec
        targets = []
        if rules.partial_at_r and qty >= 2:
            pq = max(1, int(qty * rules.partial_pct / 100))
            targets.append({"price": fc.round_to_tick(plan["entry"] + d * rules.partial_at_r * risk_pts, spec), "qty": pq})
            targets.append({"price": fc.round_to_tick(plan["entry"] + d * rules.target_r * risk_pts, spec), "qty": qty - pq})
        else:
            targets.append({"price": fc.round_to_tick(plan["entry"] + d * rules.target_r * risk_pts, spec), "qty": qty})
        clk = self.svc.clock(contract.root)
        status = (self.state.per_contract.get(contract.code) or {}).get("data_status")
        o, pv = eng.submit(contract.code, d, qty, rules.entry_type, plan["entry"] if rules.entry_type == "limit" else None, None,
                           {"stop": plan["stop"], "targets": targets}, plan["entry"], now, clk, status, signal_id=did, origin=origin)
        if not o:
            self._log("medium", f"{contract.code}: {account} entry refused by the risk engine: {'; '.join(pv.get('problems', [])[:2])}",
                      decision_id=dec["id"])
            return {"action": "entry_refused", "contract": contract.code, "account": account, "problems": pv.get("problems")}
        self.state.managed[contract.code] = {"account": account, "decision_id": dec["id"], "order_id": o.id, "entry": plan["entry"],
                                             "stop0": plan["stop"], "risk_points": risk_pts, "direction": d, "submitted": now.isoformat(),
                                             "opened": None, "rules": asdict(rules), "done": [], "setup": plan.get("setup"),
                                             "experimental": account == "sandbox"}
        if account == "practice":
            self.svc.mark_acted(dec["id"], o.id)
        self._log("high", f"{contract.code}: {'SANDBOX (experimental) ' if account == 'sandbox' else ''}paper {plan['direction']} {qty} at "
                  f"{fmt_num(plan['entry'])}, stop {fmt_num(plan['stop'])}, targets {', '.join(fmt_num(t['price']) for t in targets)}. Simulated only.",
                  decision_id=dec["id"], order_id=o.id)
        return {"action": "entered", "contract": contract.code, "account": account, "order_id": o.id, "qty": qty}

    def _expire_entries(self, contract: fc.Contract, now: datetime) -> None:
        m = self.state.managed.get(contract.code)
        if not m or m.get("opened"):
            return
        eng = self.svc.engine if m["account"] == "practice" else self.svc.sandbox
        o = eng.orders.get(m["order_id"]) if eng else None
        if o and o.filled_qty:
            m["opened"] = o.updated_at
            return
        limit = timedelta(minutes=5 * ManagementRules.from_dict(m["rules"]).entry_valid_bars)
        if o and o.active and now - datetime.fromisoformat(m["submitted"]) > limit:
            eng.cancel(o.id, now, "Entry not filled within its validity window (automation rule)")
            self._log("info", f"{contract.code}: unfilled entry canceled after {limit.seconds // 60} min.")
            self.state.managed.pop(contract.code, None)
        elif o and not o.active and not o.filled_qty:
            self.state.managed.pop(contract.code, None)

    def _manage(self, contract: fc.Contract, sig: dict, now: datetime) -> list[dict]:
        m = self.state.managed.get(contract.code)
        if not m:
            return []
        eng = self.svc.engine if m["account"] == "practice" else self.svc.sandbox
        if eng is None:
            return []
        pos = eng.positions.get(contract.code)
        if not pos or not pos.qty:
            if m.get("opened"):
                self._log("info", f"{contract.code}: automated trade closed.", decision_id=m["decision_id"])
                self.state.managed.pop(contract.code, None)
            return []
        m["opened"] = m.get("opened") or now.isoformat()
        rules = ManagementRules.from_dict(m["rules"])
        price = pos.mark
        if price is None:
            return []
        d, R = m["direction"], m["risk_points"] or 1
        r_now = (price - m["entry"]) * d / R
        out = []
        tick = float(contract.spec.tick)
        if rules.breakeven_at_r is not None and r_now >= rules.breakeven_at_r and "breakeven" not in m["done"]:
            ch = eng.modify_stop(contract.code, m["entry"] + d * tick, now, f"break-even rule at +{rules.breakeven_at_r}R (price {fmt_num(price)})")
            m["done"].append("breakeven")
            if ch:
                out.append({"action": "breakeven", **ch})
        atr = (sig.get("regime") or {}).get("atr") or next((st.get("data", {}).get("atr") for st in (sig.get("decision") or {}).get("steps", [])
                                                           if st.get("data")), None)
        if rules.trail_activate_r is not None and r_now >= rules.trail_activate_r:
            dist = rules.trail_atr_mult * (atr or R)
            ch = eng.modify_stop(contract.code, price - d * dist, now, f"trailing stop {rules.trail_atr_mult}x{'ATR' if atr else 'R'} at +{r_now:.2f}R")
            if ch:
                out.append({"action": "trail", **ch})
        if rules.max_hold_minutes and m.get("opened") and now - datetime.fromisoformat(m["opened"]) > timedelta(minutes=rules.max_hold_minutes):
            f = eng.flatten(contract.code, now, f"Maximum holding time ({rules.max_hold_minutes} min) reached (automation rule)", price=price,
                            ts_basis=f"last {pos.mark_status} price") if pos.mark_status in ("realtime", "near_realtime", "polling", "replay") else []
            if f:
                out.append({"action": "time_exit", "contract": contract.code})
                self._log("medium", f"{contract.code}: flattened after the maximum holding time.")
        elif rules.exit_on_invalidation and sig.get("action") == "EXIT":
            f = eng.flatten(contract.code, now, "Invalidation: " + "; ".join(sig.get("reasons", [])[:2]), price=price,
                            ts_basis=f"last {pos.mark_status} price") if pos.mark_status in ("realtime", "near_realtime", "polling", "replay") else []
            if f:
                out.append({"action": "invalidation_exit", "contract": contract.code})
                self._log("medium", f"{contract.code}: exited on invalidation: {'; '.join(sig.get('reasons', [])[:2])}")
        return out
