"""Recommendations from what's visible on the chart: LONG / SHORT / WAIT / EXIT / NO TRADE.

Order of checks:
  1. Capture quality gates (frozen, stale, obscured, uncertain instrument, unreadable price, too few/low-confidence candles,
     layout change). Any failure -> NO TRADE with the reason.
  2. The existing 13-step decision pipeline on the visual bars, with the existing risk engine and account snapshot, and with
     check_unvalidated=True so a setup that isn't a validated strategy still goes through entry quality, R:R, sizing, risk and costs.
  3. LONG / SHORT only when the pipeline APPROVES (that needs a walk-forward validated strategy, the same rule as live data).
     A complete setup that passes everything except the evidence rule is WAIT with "potential LONG/SHORT setup".
  4. EXIT when an active LONG/SHORT's stop or second target is reached by the price read from the chart text.
Nothing here can place or change an order anywhere.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..futures import contracts as fc
from ..futures import pipeline as fp

MIN_CANDLES = 30
MIN_CONF = 0.5


def _r(x, spec):
    return None if x is None else round(round(x / float(spec.tick_size)) * float(spec.tick_size), 6)


def no_trade(reason: str, *, contract=None, reading=None, timeframe=None, details: list[str] | None = None) -> dict:
    return {"action": "NO TRADE", "reason": reason, "details": details or [], "contract": contract, "timeframe": timeframe,
            "observed_price": (reading.price.value if reading is not None else None),
            "data_confidence": round(reading.confidence, 2) if reading is not None else 0.0,
            "captured_at": reading.captured_at if reading is not None else None, "potential": None}


def quality_gates(reading, status: str, status_reason: str, profile) -> str | None:
    if status != "screen_capture":
        return f"{status.upper()}: {status_reason}"
    if reading is None or not reading.ok:
        return "The chart couldn't be read: " + "; ".join((reading.problems if reading else []) or ["no reading"])
    if reading.instrument.value not in ("NQ", "MNQ", "ES", "MES") or reading.instrument.confidence < 0.6:
        return "Instrument uncertain: " + (reading.instrument.source or "not readable")
    if reading.timeframe.value is None or reading.timeframe.confidence < 0.6:
        return "Timeframe uncertain: " + (reading.timeframe.source or "not readable")
    if reading.price.value is None or reading.price.confidence < 0.6:
        return "Current price can't be read reliably: " + (reading.price.source or "not readable")
    if len(reading.candles) < MIN_CANDLES:
        return f"Only {len(reading.candles)} candles readable; {MIN_CANDLES} are needed. Zoom out or widen the capture region."
    if reading.candle_confidence < MIN_CONF:
        return f"Candle recognition confidence is low ({reading.candle_confidence:.2f})."
    recent = reading.candles[-20:]
    if sum(1 for c in recent if not c.body_known) > 2:
        return "Candle bodies of the recent candles aren't readable (zoom in or check the candle colors in the profile)."
    if reading.confidence < MIN_CONF:
        return f"Overall recognition confidence is low ({reading.confidence:.2f})."
    return None


def build(reading, F, F_htf, *, status: str, status_reason: str, profile, futures, now: datetime | None = None,
          prev_active: dict | None = None, notes: list[str] | None = None) -> dict:
    """The recommendation for one reading. `futures` is the FuturesService (risk engine, account snapshot, evidence)."""
    now = now or datetime.now(timezone.utc)
    tf = reading.timeframe.value if reading is not None else None
    root = reading.instrument.value if reading is not None else None
    contract = fc.front_contract(root, now.astimezone(fc.CT).date()) if root in ("NQ", "MNQ", "ES", "MES") else None
    code = contract.code if contract else None
    why = quality_gates(reading, status, status_reason, profile)
    if why:
        rec = no_trade(why, contract=code, reading=reading, timeframe=tf)
        if prev_active:
            rec["details"].append("An earlier LONG/SHORT can't be tracked while the chart is unreadable; watch it yourself.")
        return rec
    spec = contract.spec
    price = float(reading.price.value)
    # EXIT: an active recommendation's stop or final target reached, by the price read from the chart text
    if prev_active and prev_active.get("contract") == code:
        d = 1 if prev_active["direction"] == "long" else -1
        if (price - prev_active["stop"]) * d <= 0:
            return {**_base(reading, code, tf, price), "action": "EXIT", "direction": prev_active["direction"],
                    "reason": f"Stop {prev_active['stop']} reached (observed price {price}).", "exit_kind": "stop", "active": prev_active}
        if (price - prev_active["target_2"]) * d >= 0:
            return {**_base(reading, code, tf, price), "action": "EXIT", "direction": prev_active["direction"],
                    "reason": f"Target 2 {prev_active['target_2']} reached (observed price {price}).", "exit_kind": "target", "active": prev_active}
    if F is None or F.empty:
        return no_trade("No completed candles to analyze.", contract=code, reading=reading, timeframe=tf)
    eng = futures.engine
    clk = futures.clock(spec.root)
    snap = eng.snapshot(now, clk)
    from ..futures.risk import RiskEngine
    risk = RiskEngine(eng.rules, eng.personal)
    age = (now - datetime.fromisoformat(reading.captured_at)).total_seconds()
    label = {"provider": "screen", "symbol": code, "status": "screen_capture", "age_seconds": round(age, 1),
             "reason": "Visual observation of your chart (screen capture), not an exchange feed.",
             "data_time": reading.captured_at, "validation": {"ok": True, "summary": f"confidence {reading.confidence:.2f}"}}
    validated = futures.validated_strategies(spec.root) if tf == "5Min" else set()
    dec = fp.run(F, F_htf, contract, label, futures.evidence.get(spec.root, {}).get("by_setup", {}), now=now, current_price=price,
                 risk_engine=risk, snapshot=snap, round_turn=eng.round_turn(spec.root), slippage_ticks=eng.cfg.slippage_ticks_market,
                 flat_by_min_from_rth=futures.flat_minutes(clk), validated=validated, mode="visual", check_unvalidated=True)
    plan = dec.plan or {}
    base = {**_base(reading, code, tf, price), "decision_id": dec.id, "pipeline_outcome": dec.outcome, "steps": dec.steps,
            "regime": dec.regime, "notes": notes or []}
    if dec.outcome == "APPROVED" or (dec.outcome == "WATCH_ONLY" and plan.get("risk_check", {}).get("ok")):
        d = 1 if plan["direction"] == "long" else -1
        risk_pts = abs(plan["entry"] - plan["stop"])
        t1 = _r(plan["entry"] + d * risk_pts, spec)
        t2 = _r(plan["target"], spec) if (plan["target"] - plan["entry"]) * d > risk_pts else _r(plan["entry"] + 2 * d * risk_pts, spec)
        rec = {**base, "direction": plan["direction"], "setup": plan["setup"], "entry": plan["entry"],
               "entry_zone": [_r(plan["entry"] - 0.1 * risk_pts * d, spec), _r(plan["entry"], spec)] if d > 0 else
                             [_r(plan["entry"], spec), _r(plan["entry"] + 0.1 * risk_pts, spec)],
               "stop": plan["stop"], "target_1": t1, "target_2": t2, "reward_risk": round(abs(t2 - plan["entry"]) / risk_pts, 2) if risk_pts else None,
               "invalidation": plan.get("invalidation"), "evidence": [s["detail"] for s in dec.steps if s["passed"]],
               "evidence_tier": plan.get("evidence_short"), "suggested_contracts": plan.get("suggested_contracts"),
               "risk_check": plan.get("risk_check")}
        if dec.outcome == "APPROVED":
            return {**rec, "action": "LONG" if d > 0 else "SHORT", "potential": None,
                    "reason": f"{plan['setup']} {plan['direction']} passed every check, including the risk engine."}
        return {**rec, "action": "WAIT", "potential": "LONG" if d > 0 else "SHORT",
                "reason": f"Potential {('LONG' if d > 0 else 'SHORT')} setup ({plan['setup']}). It passes the risk engine, but it isn't a "
                          f"validated strategy ({plan.get('evidence_short')}), so it's not a trade recommendation."}
    if dec.outcome == "INVALIDATED":
        return {**base, "action": "WAIT", "potential": None, "invalidated": plan, "reason": dec.reason}
    if dec.outcome in ("WAIT",):
        return {**base, "action": "WAIT", "potential": None, "reason": dec.reason}
    return {**base, "action": "NO TRADE", "potential": None, "reason": dec.reason,
            "plan": plan or None}


def _base(reading, code, tf, price) -> dict:
    return {"contract": code, "timeframe": tf, "observed_price": price, "price_class": reading.price.cls,
            "data_confidence": round(reading.confidence, 2), "captured_at": reading.captured_at,
            "data_label": "SCREEN_CAPTURE", "source": "visual observation of your chart, not an exchange feed"}


def expired(active: dict | None, now: datetime, minutes: int = 240) -> bool:
    return bool(active and now - datetime.fromisoformat(active["issued_at"]) > timedelta(minutes=minutes))
