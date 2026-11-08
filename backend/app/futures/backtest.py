"""Futures backtest of the fixed setups in setups.py, with tick-accurate costs.

Rules (same as the simulator's fill model):
  * Signal at the close of bar i; entry at the open of bar i+1 plus slippage ticks (market order).
  * Stop: stop price (or worse on a gap) minus slippage ticks. Target: limit, needs one tick of trade-through.
  * A bar touching both stop and target counts as a stop.
  * Flat by the prop rules' flat time (15:10 CT for Topstep) or RTH end, whichever is first.
  * One position at a time, at most `max_trades_per_day` entries per trade date.
  * Results are per contract, net of round-turn fees. R = net P&L / planned risk in dollars.

Nothing is optimized: setup rules are fixed, so every trade is out-of-sample with respect to the rules.
Folds are chronological quarters of the trade dates, used to check consistency.
"""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

from ..backtest.stats import summarize
from .contracts import ProductSpec, round_to_tick
from .setups import SETUPS, SetupParams, detect


def scan(F: pd.DataFrame, spec: ProductSpec, params: SetupParams | None = None, max_trades_hint: int = 3) -> dict[int, object]:
    """Setups confirmed at each RTH bar close (the expensive part; reused across cost scenarios)."""
    p = params or SetupParams()
    out = {}
    rth = F["rth"].values
    for i in range(len(F) - 1):
        if rth[i]:
            found, _ = detect(F, i, spec, p)
            if found:
                out[i] = found[0]
    return out


def _bucket_time(m: float) -> str:
    return "first hour" if m < 60 else "midday" if m < 300 else "last part of RTH"


def simulate(F: pd.DataFrame, spec: ProductSpec, signals: dict, fee_round_turn: float, slippage_ticks: float = 1.0,
             max_trades_per_day: int = 3, flat_by_min_from_rth: float | None = 400) -> list[dict]:
    tick = float(spec.tick)
    bm = F.attrs.get("bar_minutes", 5)
    trades: list[dict] = []
    pos = None
    per_day: dict = defaultdict(int)
    n = len(F)
    rows = F.to_dict("records")
    atr_pct = F["atr"].rolling(600, min_periods=50).rank(pct=True).values
    for i in range(n - 1):
        r = rows[i]
        nxt = rows[i + 1]
        if pos is None and r["rth"] and per_day[r["td"]] < max_trades_per_day and i in signals:
            s = signals[i]
            if flat_by_min_from_rth is not None and r["min_from_rth"] + bm > flat_by_min_from_rth - 20:
                s = None
            if s is not None and nxt["td"] == r["td"] and nxt["rth"]:
                d = s.direction
                fill = round_to_tick(nxt["o"] + d * slippage_ticks * tick, spec)
                risk_pts = abs(fill - s.stop)
                if (fill - s.stop) * d > 0:
                    ap = atr_pct[i]
                    pos = {"setup": s.name, "dir": d, "entry": fill, "stop": s.stop, "target": s.target, "i": i + 1, "td": r["td"],
                           "entry_ts": nxt["ts"].isoformat(), "risk_usd": risk_pts / tick * spec.tick_value, "risk_pts": risk_pts,
                           "mfe": 0.0, "mae": 0.0,
                           "attrs": {"volatility": "unknown" if ap != ap else "low" if ap < 0.2 else "normal" if ap < 0.8 else "high",
                                     "trend_aligned": "with structure" if int(r["trend"]) == d else "against structure" if int(r["trend"]) == -d else "no structure",
                                     "time_of_day": _bucket_time(r["min_from_rth"]),
                                     "volume": ("above average" if r["vol_avg20"] and r["v"] > 1.2 * r["vol_avg20"] else "average or below"),
                                     "entry_lateness_atr": round(abs(r["c"] - s.trigger) / r["atr"], 2) if r["atr"] else None,
                                     "vs_vwap": "above VWAP" if r["c"] > r["vwap"] else "below VWAP"}}
                    per_day[r["td"]] += 1
        if pos and i + 1 >= pos["i"]:
            b = nxt if i + 1 > pos["i"] else rows[pos["i"]]
            j = i + 1
            d = pos["dir"]
            pos["mfe"] = max(pos["mfe"], ((b["h"] if d > 0 else -b["l"]) - (pos["entry"] if d > 0 else -pos["entry"])) / pos["risk_pts"])
            pos["mae"] = max(pos["mae"], ((pos["entry"] if d > 0 else -pos["entry"]) - (b["l"] if d > 0 else -b["h"])) / pos["risk_pts"])
            exit_px = role = None
            hit_stop = (b["l"] <= pos["stop"]) if d > 0 else (b["h"] >= pos["stop"])
            hit_tgt = (b["h"] >= pos["target"] + tick) if d > 0 else (b["l"] <= pos["target"] - tick)
            if hit_stop:
                gap = (b["o"] < pos["stop"]) if d > 0 else (b["o"] > pos["stop"])
                raw = b["o"] if gap else pos["stop"]
                exit_px, role = round_to_tick(raw - d * slippage_ticks * tick, spec), "stop"
            elif hit_tgt:
                gap = (b["o"] > pos["target"]) if d > 0 else (b["o"] < pos["target"])
                exit_px, role = (b["o"] if gap else pos["target"]), "target"
            else:
                last_bar = (j + 1 >= n or rows[j + 1]["td"] != b["td"] or not rows[j + 1]["rth"]
                            or (flat_by_min_from_rth is not None and b["min_from_rth"] + 2 * bm > flat_by_min_from_rth))
                if last_bar:
                    exit_px, role = round_to_tick(b["c"] - d * slippage_ticks * tick, spec), "time"
            if exit_px is not None:
                ticks = round((exit_px - pos["entry"]) / tick) * d
                gross = ticks * spec.tick_value
                net = gross - fee_round_turn
                trades.append({"setup": pos["setup"], "direction": "long" if d > 0 else "short", "entry_ts": pos["entry_ts"],
                               "exit_ts": b["ts"].isoformat(), "trade_date": str(pos["td"]), "entry": pos["entry"], "exit": exit_px,
                               "stop": pos["stop"], "target": pos["target"], "exit_role": role, "ticks": ticks,
                               "pnl": round(net, 2), "gross": round(gross, 2), "costs": round(fee_round_turn + 2 * slippage_ticks * spec.tick_value, 2),
                               "r_multiple": round(net / pos["risk_usd"], 3) if pos["risk_usd"] else 0.0,
                               "mfe_r": round(pos["mfe"], 2), "mae_r": round(pos["mae"], 2), **pos["attrs"]})
                pos = None
    return trades


def run(F: pd.DataFrame, spec: ProductSpec, fee_round_turn: float, slippage_ticks: float = 1.0, max_trades_per_day: int = 3,
        flat_by_min_from_rth: float | None = 400, params: SetupParams | None = None, n_folds: int = 4) -> dict:
    p = params or SetupParams()
    p.flat_by_min_from_rth = flat_by_min_from_rth
    trades = simulate(F, spec, scan(F, spec, p), fee_round_turn, slippage_ticks, max_trades_per_day, flat_by_min_from_rth)
    return report(trades, n_folds, spec, fee_round_turn, slippage_ticks, F)


def report(trades: list[dict], n_folds: int, spec: ProductSpec, fee: float, slip: float, F: pd.DataFrame) -> dict:
    days = sorted({t["trade_date"] for t in trades})
    folds = []
    if days:
        k = max(1, len(days) // n_folds)
        for f in range(n_folds):
            ds = set(days[f * k:(f + 1) * k] if f < n_folds - 1 else days[f * k:])
            ft = [t for t in trades if t["trade_date"] in ds]
            if ft:
                folds.append({"test_metrics": {"trades": len(ft), "expectancy_r": sum(t["r_multiple"] for t in ft) / len(ft)}})
    by: dict = {}
    for name in SETUPS:
        for d in ("long", "short"):
            sub = [t for t in trades if t["setup"] == name and t["direction"] == d]
            if sub:
                by[f"{name}|{d}"] = summarize(sub)
    tds = list(dict.fromkeys(F["td"])) if len(F) else []
    return {"product": spec.root, "overall": summarize(trades, folds), "by_setup": by, "trades": trades,
            "assumptions": {"fee_round_turn": fee, "slippage_ticks_per_side_on_market_and_stop": slip,
                            "target_fill": "limit, one tick of trade-through", "same_bar_stop_and_target": "stop",
                            "one_position_at_a_time": True, "contracts": 1},
            "data": {"bars": len(F), "first": F["ts"].iloc[0].isoformat() if len(F) else None,
                     "last": F["ts"].iloc[-1].isoformat() if len(F) else None, "trade_dates": len(tds)},
            "no_optimization": "Setup rules are fixed; nothing was tuned on this data."}
