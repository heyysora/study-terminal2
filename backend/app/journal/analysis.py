"""Turns paper fills into journal trades, judges whether each trade followed its plan, detects
recurring mistakes, and computes performance statistics.

Everything here is computed from recorded facts: fills, the orders (with the stop/target you set),
and the snapshot of conditions saved when you placed the order. Where a judgment needs data the
journal doesn't have (for example, there was no signal behind a manual trade), the check is
reported as "not applicable" rather than guessed.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np

from ..backtest.stats import summarize
from ..core.market_clock import ET
from ..paper.trades import RoundTrip

TRADABLE_DATA = {"realtime", "near_realtime", "polling"}

MISTAKES = {
    "late_entry": "Entered late",
    "chasing": "Chased an extended move",
    "early_exit": "Exited a winner early",
    "held_loser": "Held a loser past the plan",
    "ignored_stop": "No stop / removed the stop",
    "bad_conditions": "Traded in unfavorable conditions",
    "overtrading": "Too many trades",
    "poor_setup": "Used a poorly performing setup",
}


def _g(o, k, default=None):
    if o is None:
        return default
    v = o.get(k, default) if isinstance(o, dict) else getattr(o, k, default)
    return getattr(v, "value", v)


def _dt(x):
    return datetime.fromisoformat(x) if isinstance(x, str) else x


def time_bucket(ts: datetime) -> str:
    t = ts.astimezone(ET)
    m = t.hour * 60 + t.minute
    if m < 570:
        return "premarket"
    if m >= 960:
        return "after hours"
    return ("09:30-10:00 open" if m < 600 else "10:00-11:30 morning" if m < 690 else
            "11:30-14:00 midday" if m < 840 else "14:00-16:00 afternoon")


def build_trade(rt: RoundTrip, orders: dict, mark: float | None = None) -> dict:
    """One journal trade from a round trip and the orders behind it."""
    entry_o = orders.get(rt.first_entry_order)
    ctx = _g(entry_o, "context") or {}
    sig = ctx.get("signal") or {}
    long = rt.direction == "long"
    sgn = 1 if long else -1
    avg_entry = rt.avg_entry
    stop = _g(entry_o, "bracket_stop") or None
    target = _g(entry_o, "bracket_target") or None
    risk_ps = abs(avg_entry - stop) if (stop and avg_entry) else None
    risk_d = risk_ps * rt.entry_qty if risk_ps else None
    # stop handling: the bracket stop orders that belonged to this trade's entries
    entry_ids = set(rt.entry_order_ids)
    stops = [o for o in orders.values() if _g(o, "parent_id") in entry_ids and _g(o, "role") == "stop_loss"]
    stop_removed = any(_g(o, "status") == "canceled" and (_g(o, "reject_reason") or "").startswith("Canceled by you") for o in stops)
    open_qty = rt.entry_qty - rt.exit_qty
    unreal = (mark - avg_entry) * sgn * open_qty if (mark is not None and avg_entry and open_qty) else 0.0
    net = rt.net_pnl
    total_now = net + unreal
    roles = set(rt.exit_roles)
    exit_type = ("open" if rt.is_open else "stop" if roles == {"stop_loss"} else "target" if roles == {"take_profit"} else
                 "manual" if roles <= {"exit"} else "mixed")
    planned_r = abs(target - avg_entry) / risk_ps if (target and risk_ps) else None
    t = {
        "key": rt.fill_ids[0], "symbol": rt.symbol, "direction": rt.direction, "open": rt.is_open,
        "opened_at": rt.opened_at.isoformat(), "closed_at": rt.closed_at.isoformat() if rt.closed_at else None,
        "hold_minutes": round(((rt.closed_at or datetime.now(rt.opened_at.tzinfo)) - rt.opened_at).total_seconds() / 60, 1),
        "qty": rt.max_qty, "entry_qty": rt.entry_qty, "exit_qty": rt.exit_qty, "open_qty": open_qty,
        "avg_entry": round(avg_entry, 4) if avg_entry else None, "avg_exit": round(rt.avg_exit, 4) if rt.avg_exit else None,
        "stop": stop, "target": target, "risk_per_share": round(risk_ps, 4) if risk_ps else None,
        "risk_dollars": round(risk_d, 2) if risk_d else None, "planned_r": round(planned_r, 2) if planned_r else None,
        "realized_pnl": round(net, 2), "unrealized_pnl": round(unreal, 2), "mark": mark,
        "commissions": round(rt.commissions, 2), "slippage": round(rt.slippage, 2),
        "r_multiple": round(total_now / risk_d, 3) if risk_d else None,
        "pnl": round(total_now, 2), "exit_type": exit_type, "stop_removed": stop_removed,
        "strategy": sig.get("setup") or "manual", "strategy_name": sig.get("setup_name") or "Manual (no signal)",
        "signal": sig or None, "context": {k: v for k, v in ctx.items() if k != "signal"},
        "time_of_day": time_bucket(rt.opened_at), "regime": ctx.get("regime") or "unknown",
    }
    t["plan_checks"] = plan_checks(t)
    t["followed_plan_auto"] = all(c["passed"] for c in t["plan_checks"] if c["passed"] is not None)
    return t


def plan_checks(t: dict) -> list[dict]:
    """Did the trade follow the plan? passed=None means the check doesn't apply."""
    sig, ctx = t.get("signal") or {}, t.get("context") or {}
    long = t["direction"] == "long"
    out = []

    def chk(name, passed, detail):
        out.append({"check": name, "passed": passed, "detail": detail})

    chk("Protective stop set at entry", t["stop"] is not None,
        f"stop ${t['stop']:,.2f}" if t["stop"] else "entered without a stop")
    chk("Stop left in place", not t["stop_removed"] if t["stop"] else None,
        "you canceled the stop while the trade was open" if t["stop_removed"] else "kept")
    rng = sig.get("entry_range")
    if rng and t["avg_entry"]:
        lo, hi = rng
        inside = (t["avg_entry"] <= hi) if long else (t["avg_entry"] >= lo)
        chk("Entry inside the signal's entry range", inside, f"entry ${t['avg_entry']:,.2f} vs range ${lo:,.2f}-${hi:,.2f}")
    else:
        chk("Entry inside the signal's entry range", None, "no signal behind this trade")
    if sig.get("stop") and t["stop"] and t["risk_per_share"]:
        same = abs(t["stop"] - sig["stop"]) <= max(0.1 * t["risk_per_share"], 0.01)
        chk("Stop where the plan put it", same, f"your stop ${t['stop']:,.2f} vs plan ${sig['stop']:,.2f}")
    else:
        chk("Stop where the plan put it", None, "no signal stop to compare")
    if ctx.get("max_risk_dollars") and t["risk_dollars"]:
        ok = t["risk_dollars"] <= ctx["max_risk_dollars"] * 1.05
        chk("Risk within your per-trade limit", ok, f"risked ${t['risk_dollars']:,.0f} vs limit ${ctx['max_risk_dollars']:,.0f}")
    else:
        chk("Risk within your per-trade limit", None, "risk unknown (no stop)" if not t["risk_dollars"] else "limit not recorded")
    if not t["open"]:
        chk("Exited at the stop, the target, or per plan", t["exit_type"] in ("stop", "target"),
            {"stop": "stopped out as planned", "target": "target hit", "manual": "closed manually",
             "mixed": "partly manual exits"}.get(t["exit_type"], t["exit_type"]))
    return out


def detect_mistakes(trades: list[dict], max_trades_per_day: int = 3, own_history_min: int = 5) -> None:
    """Adds `mistakes` (list of {code,label,evidence}) to each trade. Needs all trades (cross-trade patterns)."""
    trades.sort(key=lambda t: t["opened_at"])
    per_day: dict[str, int] = defaultdict(int)
    last_loss_close: datetime | None = None
    setup_hist: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        ms = []
        sig, ctx = t.get("signal") or {}, t.get("context") or {}
        long = t["direction"] == "long"

        def add(code, ev, ms=ms):
            ms.append({"code": code, "label": MISTAKES[code], "evidence": ev})

        rng = sig.get("entry_range")
        if rng and t["avg_entry"]:
            lo, hi = rng
            past = (t["avg_entry"] - hi) if long else (lo - t["avg_entry"])
            if past > 0:
                add("late_entry", f"Entry ${t['avg_entry']:,.2f} was past the signal's entry range (${lo:,.2f}-${hi:,.2f}).")
        if sig.get("state") in ("extended", "expired"):
            add("late_entry", f"The signal was already '{sig['state']}' when you entered: {sig.get('state_reason', '')}")
        ext = ctx.get("ext_from_ema9_atr")
        if ext is not None and ((ext > 2) if long else (ext < -2)):
            add("chasing", f"Price was {abs(ext):.1f} ATR {'above' if long else 'below'} the 9 EMA at entry (stretched).")
        r = t.get("r_multiple")
        if not t["open"] and t["exit_type"] == "manual" and r is not None and t.get("planned_r") and 0 < r < min(1.0, 0.5 * t["planned_r"]):
            add("early_exit", f"Closed manually at {r:+.2f}R on a trade planned for {t['planned_r']:.1f}R.")
        if r is not None and r < -1.2:
            add("held_loser", f"Lost {r:.2f}R, more than the 1R the stop allowed" + (" (stop was removed)." if t["stop_removed"] else "."))
        if t["stop"] is None:
            add("ignored_stop", "Entered without a protective stop: the loss had no planned limit.")
        elif t["stop_removed"]:
            add("ignored_stop", "You canceled the protective stop while the trade was open.")
        bad = []
        mk = ctx.get("market") or {}
        if mk.get("high_risk"):
            bad.append("SPY flagged high-risk conditions (" + "; ".join(mk.get("reasons", [])[:2]) + ")")
        ds = (ctx.get("data_label") or {}).get("status")
        if ds and ds not in TRADABLE_DATA:
            bad.append(f"market data was '{ds}', not live")
        if ctx.get("trend_alignment") == "against trend":
            bad.append("traded against the trend on the signal timeframe")
        if sig and sig.get("tradeable") is False:
            bad.append(f"the setup had no reliable edge ({sig.get('evidence_tier', 'untested')})")
        if bad:
            add("bad_conditions", "; ".join(bad).capitalize() + ".")
        day = _dt(t["opened_at"]).astimezone(ET).date().isoformat()
        per_day[day] += 1
        if per_day[day] > max_trades_per_day:
            add("overtrading", f"Trade #{per_day[day]} that day (your limit is {max_trades_per_day}).")
        opened = _dt(t["opened_at"])
        if last_loss_close and timedelta(0) <= opened - last_loss_close <= timedelta(minutes=10):
            add("overtrading", f"Opened {int((opened - last_loss_close).total_seconds() // 60)} min after closing a loss (possible revenge trade).")
        if sig.get("evidence_tier") in ("negative", "losing"):
            add("poor_setup", f"{t['strategy_name']} lost money in out-of-sample testing ({sig.get('evidence_tier')}).")
        own = setup_hist[t["strategy"]]
        if t["strategy"] != "manual" and len(own) >= own_history_min and np.mean(own) < 0:
            add("poor_setup", f"Your own last {len(own)} {t['strategy_name']} trades averaged {np.mean(own):+.2f}R.")
        t["mistakes"] = ms
        if not t["open"]:
            if r is not None:
                setup_hist[t["strategy"]].append(r)
            if t["pnl"] < 0 and t["closed_at"]:
                last_loss_close = _dt(t["closed_at"])


def _group_stats(trades: list[dict], key) -> list[dict]:
    g: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        g[key(t)].append(t)
    rows = []
    for k, v in g.items():
        pnl = [t["pnl"] for t in v]
        rs = [t["r_multiple"] for t in v if t["r_multiple"] is not None]
        rows.append({"bucket": k, "trades": len(v), "net_pnl": round(sum(pnl), 2),
                     "win_rate": round(100 * sum(p > 0 for p in pnl) / len(v), 1),
                     "avg_r": round(float(np.mean(rs)), 3) if rs else None, "total_r": round(float(np.sum(rs)), 2) if rs else None})
    rows.sort(key=lambda r: -r["net_pnl"])
    return rows


def performance(trades: list[dict]) -> dict:
    closed = sorted([t for t in trades if not t["open"]], key=lambda t: t["closed_at"])
    n = len(closed)
    out: dict = {"closed_trades": n, "open_trades": sum(1 for t in trades if t["open"])}
    if not n:
        out["note"] = "No closed trades in this selection yet."
        return out
    pnl = np.array([t["pnl"] for t in closed])
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    with_r = [t for t in closed if t["r_multiple"] is not None]
    rs = np.array([t["r_multiple"] for t in with_r]) if with_r else np.array([])
    curve = np.cumsum(pnl)
    peak = np.maximum.accumulate(np.concatenate([[0.0], curve]))[1:]
    dd = curve - peak
    out.update({
        "net_pnl": round(float(pnl.sum()), 2),
        "win_rate": round(100 * len(wins) / n, 1),
        "avg_winner": round(float(wins.mean()), 2) if len(wins) else None,
        "avg_loser": round(float(losses.mean()), 2) if len(losses) else None,
        "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if losses.sum() < 0 else None,
        "expectancy": round(float(pnl.mean()), 2),
        "max_drawdown": round(float(dd.min()), 2),
        "total_r": round(float(rs.sum()), 2) if len(rs) else None,
        "avg_r": round(float(rs.mean()), 3) if len(rs) else None,
        "trades_without_risk": n - len(with_r),
        "commissions": round(sum(t["commissions"] for t in closed), 2),
        "evidence": summarize([{**t, "entry_ts": t["opened_at"]} for t in with_r]) if with_r else None,
        "equity_curve": [{"t": t["closed_at"], "pnl": round(float(c), 2)} for t, c in zip(closed, curve, strict=True)],
        "by_strategy": _group_stats(closed, lambda t: t["strategy_name"]),
        "by_symbol": _group_stats(closed, lambda t: t["symbol"]),
        "by_time_of_day": _group_stats(closed, lambda t: t["time_of_day"]),
        "by_regime": _group_stats(closed, lambda t: t["regime"]),
        "by_direction": _group_stats(closed, lambda t: t["direction"]),
        "by_plan": _group_stats(closed, lambda t: "followed plan" if t.get("followed_plan") else "broke plan"),
    })
    strat = [r for r in out["by_strategy"] if r["trades"] >= 3]
    out["best_strategy"] = strat[0] if strat else None
    out["worst_strategy"] = strat[-1] if len(strat) > 1 else None
    if n < 30:
        out["sample_warning"] = f"Only {n} closed trades: these numbers can swing a lot with a few more trades."
    return out


def mistake_summary(trades: list[dict]) -> list[dict]:
    """How often each mistake happens and what it costs, compared with trades without it."""
    closed = [t for t in trades if not t["open"]]
    rows = []
    for code, label in MISTAKES.items():
        hit = [t for t in closed if any(m["code"] == code for m in t.get("mistakes", []))]
        clean = [t for t in closed if not t.get("mistakes")]
        if not hit:
            continue
        hit_r = [t["r_multiple"] for t in hit if t["r_multiple"] is not None]
        clean_r = [t["r_multiple"] for t in clean if t["r_multiple"] is not None]
        rows.append({"code": code, "label": label, "count": len(hit), "share_pct": round(100 * len(hit) / len(closed), 1),
                     "net_pnl": round(sum(t["pnl"] for t in hit), 2),
                     "avg_r": round(float(np.mean(hit_r)), 3) if hit_r else None,
                     "avg_r_clean_trades": round(float(np.mean(clean_r)), 3) if clean_r else None,
                     "recent": [t["key"] for t in sorted(hit, key=lambda t: t["opened_at"])[-5:]]})
    rows.sort(key=lambda r: r["net_pnl"])
    return rows
