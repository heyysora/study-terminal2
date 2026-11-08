"""Futures journal: round trips from simulator fills, automated vs manual comparison, and futures-specific mistake checks."""
from __future__ import annotations

import numpy as np

from . import contracts as fc


def round_trips(fills: list, orders: dict) -> list[dict]:
    trips, cur = [], {}
    for f in fills:
        t = cur.get(f.contract)
        if t is None:
            o = orders.get(f.order_id)
            stop = (o.bracket or {}).get("stop") if o else None
            t = cur[f.contract] = {"contract": f.contract, "root": f.root, "direction": "long" if f.side > 0 else "short", "opened": f.ts,
                                   "qty": 0, "max_qty": 0, "entry_value": 0.0, "exit_value": 0.0, "exit_qty": 0, "fees": 0.0, "realized": 0.0,
                                   "stop": stop, "signal_id": o.signal_id if o else None, "origin": getattr(f, "origin", None) or (o.origin if o else "manual"),
                                   "limit": (o.limit_price if o else None), "exits": [], "bases": set()}
        t["fees"] += f.fee
        t["bases"].add(f.basis.split(";")[0])
        sgn = 1 if t["direction"] == "long" else -1
        if f.side == sgn:
            t["qty"] += f.qty
            t["max_qty"] = max(t["max_qty"], t["qty"])
            t["entry_value"] += f.price * f.qty
        else:
            t["qty"] -= f.qty
            t["exit_value"] += f.price * f.qty
            t["exit_qty"] += f.qty
            t["realized"] += f.realized
            t["exits"].append(f.role)
        if t["qty"] <= 0:
            spec = fc.get(t["root"])
            entry = t["entry_value"] / max(t["max_qty"], 1)
            net = round(t["realized"] - t["fees"], 2)
            risk = abs(fc.ticks_between(entry, t["stop"], spec)) * spec.tick_value * t["max_qty"] if t["stop"] else None
            trips.append({"contract": t["contract"], "direction": t["direction"], "contracts": t["max_qty"], "opened": t["opened"], "closed": f.ts,
                          "entry": round(entry, spec.decimals + 2), "exit": round(t["exit_value"] / max(t["exit_qty"], 1), spec.decimals + 2),
                          "gross": round(t["realized"], 2), "fees": round(t["fees"], 2), "net": net, "stop": t["stop"],
                          "r": round(net / risk, 2) if risk else None, "exit_reason": t["exits"][-1] if t["exits"] else None,
                          "signal_id": t["signal_id"], "origin": t["origin"], "trade_date": f.trade_date,
                          "execution": "simulated: " + ", ".join(sorted(t["bases"]))})
            del cur[f.contract]
    return trips


def summary(trips: list[dict]) -> dict:
    n = len(trips)
    if not n:
        return {"trades": 0}
    net = np.array([t["net"] for t in trips])
    rs = [t["r"] for t in trips if t["r"] is not None]
    wins, losses = net[net > 0], net[net <= 0]
    eq = np.cumsum(net)
    return {"trades": n, "net": round(float(net.sum()), 2), "win_rate": round(100 * len(wins) / n, 1),
            "avg_r": round(float(np.mean(rs)), 3) if rs else None,
            "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if len(losses) and losses.sum() < 0 else None,
            "max_drawdown": round(float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()), 2),
            "fees": round(sum(t["fees"] for t in trips), 2),
            "sample_warning": "Fewer than 30 trades: results say little yet." if n < 30 else None}


def mistakes(trips: list[dict], decisions: list[dict]) -> list[dict]:
    """Futures checks: no stop, chasing (filled worse than the plan), overtrading, trading when the pipeline said no,
    repeating a losing strategy."""
    out = []
    by_id = {d["id"]: d for d in decisions}
    per_day: dict = {}
    for t in trips:
        per_day.setdefault(t["trade_date"], []).append(t)
        if t["stop"] is None:
            out.append({"code": "no_stop", "trade": t["opened"], "contract": t["contract"], "text": "Traded without a protective stop."})
        if t["origin"] in ("manual", "replay") and t["signal_id"] and t["signal_id"] in by_id and by_id[t["signal_id"]]["outcome"] != "APPROVED":
            out.append({"code": "against_pipeline", "trade": t["opened"], "contract": t["contract"],
                        "text": f"Entered although the pipeline said {by_id[t['signal_id']]['outcome']}: {by_id[t['signal_id']].get('reason')}"})
        plan = (by_id.get(t["signal_id"]) or {}).get("plan") if t["signal_id"] else None
        if plan and plan.get("entry") is not None:
            worse = (t["entry"] - plan["entry"]) * (1 if t["direction"] == "long" else -1)
            if plan.get("stop") is not None and worse > 0.25 * abs(plan["entry"] - plan["stop"]):
                out.append({"code": "chasing", "trade": t["opened"], "contract": t["contract"],
                            "text": f"Filled {worse:g} points worse than the planned entry (more than a quarter of the stop distance)."})
    for d, ts in per_day.items():
        if len(ts) > 6:
            out.append({"code": "overtrading", "trade": d, "contract": "", "text": f"{len(ts)} trades on {d}."})
    return out


def journal_report(fills: list, orders: dict, decisions: list[dict]) -> dict:
    trips = round_trips(fills, orders)
    auto = [t for t in trips if t["origin"] in ("automation", "sandbox", "replay-auto")]
    manual = [t for t in trips if t["origin"] in ("manual", "replay")]
    rejected = [d for d in decisions if d.get("outcome") in ("REJECTED", "INVALIDATED")]
    return {"trades": trips[::-1], "summary": summary(trips), "automated": summary(auto), "manual": summary(manual),
            "comparison_note": ("Automated and manual paper trades are measured separately to see whether automation helps. "
                                "With small samples the difference is noise."),
            "mistakes": mistakes(trips, decisions), "recent_rejections": [{k: d.get(k) for k in ("id", "contract", "evaluated_at", "outcome", "reason")}
                                                                         for d in rejected[:30]]}
