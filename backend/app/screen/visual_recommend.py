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
    try:
        analysis = market_analysis(F, reading, spec)
    except Exception as e:  # noqa: BLE001 - analysis summary must never block the recommendation
        analysis = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    base = {**_base(reading, code, tf, price), "decision_id": dec.id, "pipeline_outcome": dec.outcome, "steps": dec.steps,
            "regime": dec.regime, "notes": notes or [], "analysis": analysis}
    if dec.outcome == "APPROVED" or (dec.outcome == "WATCH_ONLY" and plan.get("risk_check", {}).get("ok")):
        d = 1 if plan["direction"] == "long" else -1
        risk_pts = abs(plan["entry"] - plan["stop"])
        t1 = _r(plan["entry"] + d * risk_pts, spec)
        t2 = _r(plan["target"], spec) if (plan["target"] - plan["entry"]) * d > risk_pts else _r(plan["entry"] + 2 * d * risk_pts, spec)
        rec = {**base, "direction": plan["direction"], "setup": plan["setup"], "entry": plan["entry"],
               "target_levels": [t1, t2], "entry_zone": [_r(plan["entry"] - 0.1 * risk_pts * d, spec), _r(plan["entry"], spec)] if d > 0 else
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


def market_analysis(F, reading, spec) -> dict:
    """What the visible chart says, item by item. Everything here is derived from visually estimated candles (or read lines), so it is
    labelled VISUALLY_ESTIMATED; items that need history that isn't on screen are UNAVAILABLE with the reason."""
    import pandas as pd

    from ..futures import features as ff
    est = "VISUALLY_ESTIMATED"
    r = F.iloc[-1]
    price = reading.price.value
    out: dict = {"class": est, "as_of": r["ts"].isoformat(), "timeframe": reading.timeframe.value}
    trend = {1: "bullish (the last break of structure was up)", -1: "bearish (the last break of structure was down)",
             0: "undetermined (no break of structure yet)"}[int(r["trend"])]
    out["structure"] = trend
    # swing sequence
    seq = []
    for col, kind in (("swing_h", "high"), ("swing_l", "low")):
        vals = [v for v in F[col].dropna().drop_duplicates().tolist()][-3:]
        for i in range(1, len(vals)):
            up = vals[i] > vals[i - 1]
            seq.append(("HH" if up else "LH") if kind == "high" else ("HL" if up else "LL"))
    out["swings"] = {"recent_highs": F["swing_h"].dropna().drop_duplicates().tolist()[-3:],
                     "recent_lows": F["swing_l"].dropna().drop_duplicates().tolist()[-3:], "pattern": seq}
    ev = F[F["bos_up"] | F["bos_dn"]].tail(1)
    out["last_structure_break"] = None if ev.empty else {
        "kind": "CHoCH" if bool(ev["choch"].iloc[0]) else "BOS", "direction": "up" if bool(ev["bos_up"].iloc[0]) else "down",
        "level": float(ev["swing_h"].iloc[0] if bool(ev["bos_up"].iloc[0]) else ev["swing_l"].iloc[0]), "at": ev["ts"].iloc[0].isoformat()}
    vw = r.get("vwap")
    out["vwap"] = {"value": None if pd.isna(vw) else float(vw),
                   "position": None if pd.isna(vw) or price is None else ("above" if price > vw else "below" if price < vw else "at"),
                   "class": est if not pd.isna(vw) else "UNAVAILABLE"}
    emas = {k: v.get("last") for k, v in reading.indicators.items() if k.startswith("EMA") and isinstance(v, dict) and v.get("last") is not None}
    order = sorted(emas, key=lambda k: int(k.split()[1]))
    if len(order) >= 2:
        vals = [emas[k] for k in order]
        align = "bullish (shorter above longer)" if all(a > b for a, b in zip(vals, vals[1:])) else \
                "bearish (shorter below longer)" if all(a < b for a, b in zip(vals, vals[1:])) else "mixed"
    else:
        align = None
    out["ema_alignment"] = {"emas": emas, "alignment": align, "class": est if align else "UNAVAILABLE",
                            "note": None if align else "Assign at least two EMA line colors in the chart profile."}
    lv = {}
    for name, col in (("previous_day_high", "pdh"), ("previous_day_low", "pdl"), ("overnight_high", "onh"), ("overnight_low", "onl"),
                      ("opening_range_high", "or_h"), ("opening_range_low", "or_l")):
        v = r.get(col)
        lv[name] = {"value": float(v), "class": est} if v is not None and not pd.isna(v) else \
            {"value": None, "class": "UNAVAILABLE", "note": "that part of the session isn't visible on the chart"}
    out["levels"] = lv
    out["fair_value_gaps"] = ff.recent_fvgs(F, lookback=min(len(F), 120))[:4]
    keyed = {k: v["value"] for k, v in lv.items() if v["value"] is not None}
    today = F[F["td"] == r["td"]]
    out["liquidity_sweeps"] = ff.sweep_events(today, keyed, spec, lookback=len(today))[-3:] if keyed else []
    if F["v"].sum() > 0 and len(F) >= 21:
        avg = float(F["v"].iloc[-21:-1].mean())
        ratio = float(F["v"].iloc[-1]) / avg if avg else None
        out["volume"] = {"last_vs_20_bar_average": None if ratio is None else round(ratio, 2), "class": est,
                         "note": "relative bar heights from the volume pane (no contract counts)"}
    else:
        out["volume"] = {"class": "UNAVAILABLE", "note": "volume pane not visible or not configured"}
    sr = sorted({round(x["price"], 4) for x in reading.levels} | {float(v) for v in keyed.values()})
    if price is not None:
        below = [x for x in sr if x < price][-2:]
        above = [x for x in sr if x > price][:2]
        out["support_resistance"] = {"support": below[::-1], "resistance": above,
                                     "note": "visible horizontal lines and session levels"}
    score, why = 0, []
    t = int(r["trend"])
    score += t
    if t:
        why.append(f"structure {'up' if t > 0 else 'down'}")
    if out["vwap"]["position"] in ("above", "below"):
        s = 1 if out["vwap"]["position"] == "above" else -1
        score += s
        why.append(f"price {out['vwap']['position']} VWAP")
    if align and align != "mixed":
        s = 1 if align.startswith("bullish") else -1
        score += s
        why.append(f"EMAs {align.split()[0]}")
    lb = out["last_structure_break"]
    if lb:
        score += 1 if lb["direction"] == "up" else -1
        why.append(f"last {lb['kind']} {lb['direction']}")
    out["bias"] = {"label": "bullish" if score >= 2 else "bearish" if score <= -2 else "neutral", "score": int(score), "reasons": why,
                   "class": est}
    return out


def _base(reading, code, tf, price) -> dict:
    return {"contract": code, "timeframe": tf, "observed_price": price, "price_class": reading.price.cls,
            "data_confidence": round(reading.confidence, 2), "captured_at": reading.captured_at,
            "data_label": "LIVE VISUAL OBSERVATION", "source": "SCREEN CAPTURE: visual observation of your chart, not an exchange feed",
            "values": "entry/stop/targets come from VISUALLY_ESTIMATED candles; the observed price is DIRECTLY_READ"}


def expired(active: dict | None, now: datetime, minutes: int = 240) -> bool:
    return bool(active and now - datetime.fromisoformat(active["issued_at"]) > timedelta(minutes=minutes))
