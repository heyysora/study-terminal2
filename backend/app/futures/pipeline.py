"""Deterministic decision pipeline for futures trades. Every potential trade passes the same 13 steps, in order;
the first failing step decides the outcome. Each step's result is kept, so any decision can be explained later.

Outcomes: APPROVED (eligible for a paper trade), WATCH_ONLY, WAIT (for confirmation), REJECTED, INVALIDATED, NO_TRADE.
Nothing here places an order. The automation engine may act on APPROVED decisions in the simulator only; the mentor
and the UI only display them and cannot change the outcome.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import pandas as pd

from ..backtest.stats import TRADE_OK
from ..signals.engine import TIER_SHORT
from .contracts import CT, Contract, ProductSpec, size_for_risk
from .features import regime
from .setups import SetupParams, detect, developing, key_levels
from .contracts import fmt_num

OUTCOMES = ("APPROVED", "WATCH_ONLY", "WAIT", "REJECTED", "INVALIDATED", "NO_TRADE")
ACTION_OF = {"WATCH_ONLY": "WATCH ONLY", "WAIT": "WAIT FOR CONFIRMATION", "INVALIDATED": "INVALIDATED", "NO_TRADE": "NO TRADE",
             "REJECTED": "NO TRADE"}
LIVE = {"realtime", "near_realtime", "polling", "replay"}
STEPS = ["Market-data validation", "Contract validation", "Market-session validation", "Market-regime classification",
         "Technical setup identification", "Multi-timeframe confirmation", "Strategy performance validation", "Entry-quality evaluation",
         "Risk/reward calculation", "Position-size calculation", "Prop-firm and personal risk validation", "Slippage and cost evaluation",
         "Final eligibility decision"]


@dataclass
class PipelineConfig:
    min_reward_risk: float = 1.5
    max_cost_fraction: float = 0.25        # fees + slippage as a share of the dollar risk
    max_drift_atr: float = 0.5             # current price this far past the planned entry (in the trade's direction) = extended
    require_htf_alignment: bool = True     # 15-minute structure must not point the other way
    extreme_volatility_blocks: bool = True
    max_data_age_seconds: float = 180


@dataclass
class Decision:
    id: str
    contract: str
    root: str
    evaluated_at: str
    bar_time: str | None
    outcome: str
    action: str
    reason: str
    steps: list[dict] = field(default_factory=list)
    plan: dict | None = None
    candidates: list[dict] = field(default_factory=list)
    regime: dict | None = None
    development: str = "none"
    current_price: float | None = None
    data: dict | None = None
    mode: str = "assisted"

    def to_dict(self) -> dict:
        return asdict(self)


def decision_id(contract: str, setup: str | None, direction: str | None, bar_time: str | None) -> str:
    raw = f"{contract}|{setup or '-'}|{direction or '-'}|{bar_time or '-'}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _step(steps: list, n: int, passed: bool | None, detail: str, **data) -> bool:
    steps.append({"n": n, "step": STEPS[n - 1], "passed": passed, "detail": detail, **({"data": data} if data else {})})
    return passed is not False


def run(F5: pd.DataFrame, F15: pd.DataFrame | None, contract: Contract, label: dict, evidence: dict, *, now: datetime | None = None,
        current_price: float | None = None, risk_engine=None, snapshot=None, round_turn: float = 0.0, slippage_ticks: float = 1.0,
        flat_by_min_from_rth: float | None = None, validated: set[str] | None = None, prev_plan: dict | None = None,
        cfg: PipelineConfig | None = None, mode: str = "assisted") -> Decision:
    cfg = cfg or PipelineConfig()
    now = now or datetime.now(timezone.utc)
    spec: ProductSpec = contract.spec
    steps: list[dict] = []
    bm = F5.attrs.get("bar_minutes", 5) if len(F5) else 5
    bar_time = F5["ts"].iloc[-1].isoformat() if len(F5) else None
    cur = current_price if current_price is not None else (float(F5["c"].iloc[-1]) if len(F5) else None)

    def done(outcome: str, reason: str, plan=None, cands=None, reg=None, dev="none") -> Decision:
        s = (plan or {}).get("setup")
        d = (plan or {}).get("direction")
        for k in range(len(steps) + 1, 14):
            steps.append({"n": k, "step": STEPS[k - 1], "passed": None, "detail": "Not reached."})
        steps[-1].update({"passed": outcome == "APPROVED", "detail": f"{outcome}: {reason}"})
        act = ("LONG" if d == "long" else "SHORT") if outcome == "APPROVED" else ACTION_OF[outcome]
        return Decision(decision_id(contract.code, s, d, bar_time), contract.code, contract.root, now.isoformat(), bar_time, outcome, act,
                        reason, steps, plan, cands or [], reg, dev, cur, {k: label.get(k) for k in ("provider", "symbol", "status", "reason",
                                                                                                 "data_time", "age_seconds")}, mode)

    # 1. market data
    status = label.get("status")
    from .signals import completeness
    ok, why = completeness(F5, bm) if len(F5) else (False, "No bars.")
    age = label.get("age_seconds")
    val = label.get("validation") or {}
    if not len(F5) or not ok:
        _step(steps, 1, False, f"Data incomplete: {why}")
        return done("NO_TRADE", f"Data incomplete: {why}")
    if val and val.get("ok") is False:
        _step(steps, 1, False, f"Bar validation failed: {val.get('summary')}")
        return done("NO_TRADE", "Market data failed validation.")
    if status not in LIVE:
        _step(steps, 1, False, f"Data is {status}: {label.get('reason', '')}", status=status)
        found, _ = detect(F5, len(F5) - 1, spec, SetupParams(flat_by_min_from_rth=flat_by_min_from_rth))
        study = [s.to_dict() for s in found] if status == "delayed" else []
        return done("NO_TRADE", f"No decisions on {status} data." + (" Setups are listed for study only." if study else ""), cands=study)
    if status != "replay" and age is not None and age > max(cfg.max_data_age_seconds, 2 * bm * 60):
        _step(steps, 1, False, f"Newest bar is {age:.0f} s old.")
        return done("NO_TRADE", "Market data is too old to act on.")
    _step(steps, 1, True, f"{label.get('provider')} {status}, bar {bar_time}, {val.get('summary', 'validated')}")
    # 2. contract
    cd = contract.to_dict(now.astimezone(CT).date())
    if cd["expired"]:
        _step(steps, 2, False, f"{contract.code} has expired.")
        return done("REJECTED", f"{contract.code} has expired.")
    if cd["in_roll_window"]:
        _step(steps, 2, False, f"{contract.code} is past its roll date ({cd['roll_date']}); the next contract is the front month.")
        return done("REJECTED", "Past the roll date: trade the front contract.")
    _step(steps, 2, True, f"{contract.code}, {cd['days_to_last_trade']} days to last trade" + (" (user-defined spec)" if spec.user_defined else ""))
    # 3. session
    r = F5.iloc[-1]
    if not r["rth"]:
        _step(steps, 3, False, "Outside regular trading hours; setups are evaluated in RTH only.")
        return done("NO_TRADE", "Outside RTH.", dev="none")
    if flat_by_min_from_rth is not None and r["min_from_rth"] + bm > flat_by_min_from_rth - 20:
        _step(steps, 3, False, "Within 20 minutes of the flat-by time.")
        return done("NO_TRADE", "Too close to the flat-by time.")
    _step(steps, 3, True, f"RTH, {r['min_from_rth']:.0f} min after the open")
    # 4. regime
    reg = regime(F5, len(F5) - 1)
    if cfg.extreme_volatility_blocks and reg["volatility"] == "extreme":
        _step(steps, 4, False, f"Volatility is extreme (ATR at the {reg['atr_percentile']:.0f}th percentile).", **reg)
        return done("REJECTED", "Extreme volatility: stops and fills are unreliable.", reg=reg)
    _step(steps, 4, True, f"{reg['label']}; {reg['vs_vwap']}; {reg['day_type']}", **reg)
    # 5. setup
    p = SetupParams(flat_by_min_from_rth=flat_by_min_from_rth, target_r=max(2.0, cfg.min_reward_risk))
    found, rejected = detect(F5, len(F5) - 1, spec, p)
    if prev_plan and not found:
        stop, d = prev_plan.get("stop"), 1 if prev_plan.get("direction") == "long" else -1
        if stop is not None and cur is not None and (cur - stop) * d <= 0:
            _step(steps, 5, False, f"The earlier {prev_plan['setup']} idea is invalidated: price {fmt_num(cur)} is through its stop {fmt_num(stop)}.")
            return done("INVALIDATED", f"{prev_plan['setup']} invalidated before entry.", plan=prev_plan, reg=reg, dev="invalidated")
    if not found:
        extended = [x for x in rejected if "chase" in x or "Extended" in x]
        if extended:
            _step(steps, 5, False, extended[0])
            return done("REJECTED", "Move already extended; not chasing.", reg=reg, dev="extended")
        notes = developing(F5, len(F5) - 1, spec)
        _step(steps, 5, False, "No setup confirmed on the last closed bar." + (" " + notes[0] if notes else ""), rejected=rejected[:5])
        return done("WAIT" if notes and any("Watch how it reacts" in n for n in notes) else "NO_TRADE",
                    "Price is near a key level; waiting for a setup to confirm." if notes else "No setup.", reg=reg,
                    dev="approaching" if notes else "none")
    s = found[0]
    d = "long" if s.direction > 0 else "short"
    plan = s.to_dict()
    cands = [x.to_dict() for x in found]
    _step(steps, 5, True, f"{s.name} {d}: " + "; ".join(s.conditions))
    # 6. higher timeframe
    if F15 is not None and len(F15):
        t15 = int(F15["trend"].iloc[-1])
        against = (t15 == -1 and s.direction > 0) or (t15 == 1 and s.direction < 0)
        if against and cfg.require_htf_alignment:
            _step(steps, 6, False, f"15-minute structure points the other way ({'down' if t15 == -1 else 'up'}).")
            return done("WATCH_ONLY", "Against the 15-minute structure.", plan, cands, reg, "confirmed")
        _step(steps, 6, True, f"15-minute structure {'aligned' if t15 == s.direction else 'neutral'}")
    else:
        _step(steps, 6, None, "No 15-minute data; check skipped.")
    # 7. evidence
    ev = evidence.get(f"{s.name}|{d}") or {"tier": "none", "trades": 0}
    plan["evidence"] = {k: ev.get(k) for k in ("tier", "tier_text", "trades", "days", "avg_r", "avg_r_ci95", "win_rate", "profit_factor")}
    plan["evidence_short"] = TIER_SHORT.get(ev.get("tier", "none"), ev.get("tier"))
    is_valid = ev.get("tier") in TRADE_OK and (validated is None or f"{s.name}|{d}" in validated)
    plan["tradeable_evidence"] = is_valid
    if not is_valid:
        _step(steps, 7, False, f"Tested evidence for {s.name} {d}: {plan['evidence_short']}. Only validated strategies can be traded.")
        return done("WATCH_ONLY", f"{s.name} {d} isn't a validated strategy ({plan['evidence_short']}).", plan, cands, reg, "confirmed")
    _step(steps, 7, True, f"Validated: {ev.get('trades')} trades, avg {ev.get('avg_r')}R")
    # 8. entry quality
    atr = float(r["atr"])
    if cur is not None:
        drift = (cur - s.entry) * s.direction
        if (cur - s.stop) * s.direction <= 0:
            _step(steps, 8, False, f"Price {fmt_num(cur)} is already through the stop {fmt_num(s.stop)}.")
            return done("INVALIDATED", "Invalidated before entry.", plan, cands, reg, "invalidated")
        if drift > cfg.max_drift_atr * atr:
            _step(steps, 8, False, f"Price has moved {fmt_num(drift)} points past the entry ({drift / atr:.2f} ATR).")
            return done("REJECTED", "Entry is gone: chasing would worsen reward/risk.", plan, cands, reg, "extended")
    _step(steps, 8, True, f"Current {fmt_num(cur)} vs entry {fmt_num(s.entry)}")
    # 9. reward/risk
    rr = abs(s.target - s.entry) / s.risk_points if s.risk_points else 0
    plan["reward_risk"] = round(rr, 2)
    if rr < cfg.min_reward_risk:
        _step(steps, 9, False, f"Reward/risk {rr:.2f} < {cfg.min_reward_risk}.")
        return done("REJECTED", "Reward/risk too low.", plan, cands, reg, "confirmed")
    _step(steps, 9, True, f"{rr:.2f}R to target")
    # 10. size
    budget = (risk_engine.personal.max_risk_per_trade_usd if risk_engine and risk_engine.personal.enabled else None) or 0
    sized = size_for_risk(budget, s.entry, s.stop, spec, slippage_ticks, round_turn)
    plan.update({"risk_per_contract_usd": sized["total_usd"], "stop_ticks": sized["stop_ticks"]})
    qty = sized["contracts"]
    if risk_engine and snapshot is not None:
        st = risk_engine.evaluate(snapshot)
        probe = risk_engine.check_entry(snapshot, spec, 1, s.entry, s.stop, [s.target], round_turn, slippage_ticks, s.direction, status=st)
        caps = [v for v in probe["limits"].values() if v is not None]
        for room in (st["official"].get("mll_remaining"), st["official"].get("dll_remaining"), st["personal"].get("daily_loss_remaining")):
            if room is not None and sized["total_usd"] > 0:
                caps.append(max(0, int((room - 0.01) // sized["total_usd"])))
        qty = min([qty] + caps)
    plan["suggested_contracts"] = qty
    if qty < 1:
        _step(steps, 10, False, sized.get("reason") or "No size fits inside your limits.")
        return done("REJECTED", "Even one contract would exceed a risk limit.", plan, cands, reg, "confirmed")
    _step(steps, 10, True, f"{qty} contract(s), ${sized['total_usd']:.2f} each incl. slippage and fees")
    # 11. risk
    if risk_engine and snapshot is not None:
        chk = risk_engine.check_entry(snapshot, spec, qty, s.entry, s.stop, [s.target], round_turn, slippage_ticks, s.direction)
        plan["risk_check"] = {"ok": chk["ok"], "problems": chk["problems"], "warnings": chk["warnings"]}
        if not chk["ok"]:
            _step(steps, 11, False, "; ".join(chk["problems"]))
            return done("REJECTED", chk["problems"][0], plan, cands, reg, "confirmed")
        _step(steps, 11, True, "All limits pass" + (f" ({'; '.join(chk['warnings'][:2])})" if chk["warnings"] else ""))
    else:
        _step(steps, 11, False, "No risk engine available.")
        return done("REJECTED", "Risk checks couldn't run.", plan, cands, reg, "confirmed")
    # 12. costs
    gross = sized["gross_usd"]
    costs = sized["slippage_usd"] + sized["costs_usd"]
    frac = costs / gross if gross else 1
    plan["cost_fraction_of_risk"] = round(frac, 3)
    if frac > cfg.max_cost_fraction:
        _step(steps, 12, False, f"Fees and slippage are {frac:.0%} of the stop distance (limit {cfg.max_cost_fraction:.0%}).")
        return done("REJECTED", "Costs are too large relative to the risk.", plan, cands, reg, "confirmed")
    _step(steps, 12, True, f"Costs {frac:.0%} of the risk")
    plan["levels_nearby"] = {k: v for k, v in key_levels(r).items() if abs(v - s.entry) <= 2 * atr}
    return done("APPROVED", f"{s.name} {d} passed every check.", plan, cands, reg, "confirmed")
