"""Futures signal: LONG / SHORT / HOLD / EXIT / NO TRADE, with a full plan and the reasons.

Gates, in order (the first that fails decides):
  1. Data must be tradable (live or polled) and complete. Delayed, stale, cached or gappy data -> NO TRADE.
     Delayed data still gets the analysis and setups labeled "study only", never a signal.
  2. An open paper position in this contract -> HOLD or EXIT with the reason.
  3. A setup confirmed on the last closed bar, with a plan that passes the risk checks.
  4. Evidence: LONG/SHORT only when the futures backtest for that setup and direction is "reliable"
     (same rule as stocks). Otherwise the setup is shown as watch-only and the answer is NO TRADE.
  5. Scheduled high-impact events (CPI, FOMC, jobs...) within 15 minutes -> watch-only.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..backtest.stats import TRADE_OK
from ..signals.engine import TIER_SHORT
from .contracts import ProductSpec, size_for_risk
from .features import recent_fvgs, sweep_events, volume_profile
from .setups import SetupParams, detect, developing, key_levels

TRADABLE = {"realtime", "near_realtime", "polling", "replay"}


def levels_snapshot(F: pd.DataFrame, spec: ProductSpec) -> dict:
    if F.empty:
        return {}
    r = F.iloc[-1]
    td = r["td"]
    today = F[F["td"] == td]
    tds = list(dict.fromkeys(F["td"]))
    prev_td = tds[-2] if len(tds) >= 2 else None
    prev_rth = F[(F["td"] == prev_td) & F["rth"]] if prev_td is not None else F.iloc[0:0]
    f = lambda x: None if x is None or pd.isna(x) else float(x)  # noqa: E731
    out = {"trade_date": str(td), "last": f(r["c"]), "as_of": r["ts"].isoformat(),
           "vwap": f(r["vwap"]), "vwap_upper_1sd": f(r["vwap"] + r["vwap_sd"]) if pd.notna(r["vwap_sd"]) else None,
           "vwap_lower_1sd": f(r["vwap"] - r["vwap_sd"]) if pd.notna(r["vwap_sd"]) else None, "rth_vwap": f(r["rth_vwap"]),
           "prev_day_high": f(r["pdh"]), "prev_day_low": f(r["pdl"]), "prev_day_close": f(r["pdc"]),
           "prev_session_high": f(r["pgh"]), "prev_session_low": f(r["pgl"]),
           "overnight_high": f(r["onh"]), "overnight_low": f(r["onl"]), "premarket_high": f(r["pmh"]), "premarket_low": f(r["pml"]),
           "opening_range_high": f(r["or_h"]), "opening_range_low": f(r["or_l"]), "ib_high": f(r["ib_h"]), "ib_low": f(r["ib_l"]),
           "swing_high": f(r["swing_h"]), "swing_low": f(r["swing_l"]), "atr": f(r["atr"]),
           "trend": {1: "up (higher highs/lows)", -1: "down (lower highs/lows)", 0: "undetermined"}[int(r["trend"])],
           "session_high": f(today["h"].max()), "session_low": f(today["l"].min()),
           "profile_prev_rth": volume_profile(prev_rth, spec), "profile_today": volume_profile(today, spec),
           "fvgs": recent_fvgs(F), "structure": [], "notes": []}
    for _, x in F.tail(30).iterrows():
        if x["bos_up"] or x["bos_dn"]:
            out["structure"].append({"ts": x["ts"].isoformat(), "kind": ("CHoCH" if x["choch"] else "BOS") + (" up" if x["bos_up"] else " down"),
                                     "price": float(x["c"])})
    out["structure"] = out["structure"][-5:][::-1]
    lv = {k.lower().replace(" ", "_"): v for k, v in key_levels(r).items() if k != "VWAP"}
    out["sweeps"] = sweep_events(F, lv, spec)
    if pd.isna(r["pdh"]):
        out["notes"].append("No previous trade date in the loaded data, so previous-day levels are missing.")
    return out


def completeness(F: pd.DataFrame, bar_minutes: int, max_gap: int = 20) -> tuple[bool, str | None]:
    if F.empty:
        return False, "No bars loaded."
    td = F["td"].iloc[-1]
    today = F[F["td"] == td]
    worst = today["gap_min"].max() if len(today) else 0
    if worst and worst > max(max_gap, 3 * bar_minutes):
        return False, f"Today's data has a {worst:.0f}-minute hole; levels and VWAP would be wrong."
    if len(today) < 3:
        return False, "Too few bars in the current session yet."
    return True, None


def position_advice(F: pd.DataFrame, pos: dict, stop: float | None, spec: ProductSpec, minutes_to_flat: float | None) -> dict:
    r = F.iloc[-1]
    d = 1 if pos["qty"] > 0 else -1
    reasons, action = [], "HOLD"
    if minutes_to_flat is not None and minutes_to_flat <= 10:
        action = "EXIT"
        reasons.append(f"{minutes_to_flat:.0f} minutes to the flat-by time.")
    if r["choch"] and ((d > 0 and r["bos_dn"]) or (d < 0 and r["bos_up"])):
        action = "EXIT"
        reasons.append("Change of character against your position on the last closed bar.")
    if pd.notna(r["vwap"]) and ((d > 0 and r["c"] < r["vwap"] and pos["avg_price"] > r["vwap"]) or
                                (d < 0 and r["c"] > r["vwap"] and pos["avg_price"] < r["vwap"])):
        reasons.append("Price closed back through VWAP against you. Consider whether the idea is still valid.")
    if stop is None:
        reasons.append("No stop on this position. Add one: risk to your loss limits is undefined.")
    if action == "HOLD":
        reasons.insert(0, "Structure hasn't turned against the position" + (" and the stop is in place." if stop is not None else "."))
    return {"action": action, "reasons": reasons, "direction": "long" if d > 0 else "short"}


def evaluate(F: pd.DataFrame, spec: ProductSpec, contract: str, label: dict, evidence: dict, *, now: datetime | None = None,
             position: dict | None = None, position_stop: float | None = None, risk_engine=None, snapshot=None,
             round_turn: float = 0.0, slippage_ticks: float = 1.0, flat_by_min_from_rth: float | None = None,
             minutes_to_flat: float | None = None, events: dict | None = None, params: SetupParams | None = None,
             F15: pd.DataFrame | None = None, current_price: float | None = None, validated: set | None = None,
             prev_plan: dict | None = None, pipeline_cfg=None, mode: str = "assisted") -> dict:
    """The signal shown in the UI: the decision pipeline's outcome, or HOLD/EXIT for an open position."""
    from .contracts import parse_symbol
    from .pipeline import run

    now = now or datetime.now(timezone.utc)
    bm = F.attrs.get("bar_minutes", 5) if len(F) else 5
    con = parse_symbol(contract).contract
    i = len(F) - 1
    out: dict = {"contract": contract, "root": spec.root, "action": "NO TRADE", "reasons": [], "signal": None, "watch": [],
                 "study_only": [], "developing": developing(F, i, spec) if len(F) else [], "data": label, "evaluated_at": now.isoformat(),
                 "market_data_time": F["ts"].iloc[-1].isoformat() if len(F) else None, "timeframe": f"{bm}Min",
                 "sim_note": "Signals feed the paper simulator only. Study Terminal never places real orders."}
    if position and position.get("qty") and len(F):
        adv = position_advice(F, position, position_stop, spec, minutes_to_flat)
        out["action"], out["reasons"], out["position"] = adv["action"], adv["reasons"], adv
        return out
    dec = run(F, F15, con, label, evidence, now=now, current_price=current_price, risk_engine=risk_engine, snapshot=snapshot,
              round_turn=round_turn, slippage_ticks=slippage_ticks, flat_by_min_from_rth=flat_by_min_from_rth, validated=validated,
              prev_plan=prev_plan, cfg=pipeline_cfg, mode=mode)
    out["decision"] = dec.to_dict()
    out["action"] = dec.action
    out["outcome"] = dec.outcome
    out["development"] = dec.development
    out["regime"] = dec.regime
    out["current_price"] = dec.current_price
    out["rejected"] = next((st.get("data", {}).get("rejected") for st in dec.steps if st["n"] == 5 and st.get("data")), None) or []
    failing = next((st for st in dec.steps if st["passed"] is False), None)
    out["reasons"] = [dec.reason] + ([failing["detail"]] if failing and failing["detail"] != dec.reason else [])
    if events and events.get("gate") and dec.outcome == "APPROVED":
        dec.outcome, dec.action = "WATCH_ONLY", "WATCH ONLY"
        out.update(action="WATCH ONLY", outcome="WATCH_ONLY")
        out["reasons"].insert(0, events.get("reason") or "A high-impact release is within the event window.")
    if dec.plan:
        if dec.outcome == "APPROVED":
            out["signal"] = dec.plan
        else:
            out["watch"] = [dec.plan | {"label": f"{dec.action}: {dec.reason}"}]
    elif dec.candidates:
        out["study_only"] = [c | {"label": "Delayed data: for study only, not a signal"} for c in dec.candidates]
    return out
