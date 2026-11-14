"""Strategy research for futures: chronological walk-forward with a held-out final period, full metrics after costs,
diagnostics, and the validated-vs-experimental strategy registry used by the decision pipeline.

Procedure (no look-ahead, no tuning on the holdout):
  1. Trade dates are split chronologically: the last `holdout_frac` of dates is the HOLDOUT, never used to choose anything.
  2. The rest (development) is cut into `n_folds` chronological folds. For each fold after the first, the parameter set with the
     best average R on all earlier folds is chosen, then applied to that fold. Only those next-fold trades count as
     out-of-sample (OOS).
  3. The parameter set chosen on the whole development period is applied once to the holdout.
  4. A strategy (setup + direction) is VALIDATED only if its OOS evidence tier is "reliable" AND the holdout agrees
     (at least `min_holdout_trades`, positive average R, profit factor > 1.1). Everything else is EXPERIMENTAL and may run only
     in the research sandbox.

Disclosure: the holdout here is the most recent part of Yahoo's ~59-day window. Those bars were already looked at in aggregate
during 0.6.0 development (overall results only, no tuning), so it is not perfectly pristine. Each run records its date, so data
arriving after that date is genuinely unseen and can be checked with "forward" runs.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from ..backtest.stats import summarize
from .backtest import scan, simulate
from .contracts import ProductSpec
from .setups import SETUPS, SetupParams

GRID = [{"target_r": 1.5, "max_chase_atr": 0.5}, {"target_r": 2.0, "max_chase_atr": 0.5},
        {"target_r": 2.0, "max_chase_atr": 0.3}, {"target_r": 3.0, "max_chase_atr": 0.5}]
DIMENSIONS = ["setup", "direction", "volatility", "trend_aligned", "time_of_day", "volume", "vs_vwap", "exit_role"]


def in_sample_only(costs: dict) -> dict:
    """The cost table uses every date with the final parameters (including the dates they were chosen on). Evidence tier labels
    like "promising" only mean something out-of-sample, so they are removed and the table is marked in-sample."""
    out = {}
    for k, m in (costs or {}).items():
        m = {f: v for f, v in m.items() if f not in ("tier", "tier_text")} if isinstance(m, dict) else m
        if isinstance(m, dict):
            m["sample"] = "all dates with the final parameters (in-sample, not evidence of an edge)"
        out[k] = m
    return out


def metrics(trades: list[dict]) -> dict:
    """Everything the directive asks for, after costs."""
    n = len(trades)
    if not n:
        return {"trades": 0}
    pnl = np.array([t["pnl"] for t in trades])
    r = np.array([t["r_multiple"] for t in trades])
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    eq = np.cumsum(pnl)
    dd = float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())
    eq_r = np.cumsum(r)
    dd_r = float((np.maximum.accumulate(np.r_[0, eq_r]) - np.r_[0, eq_r]).max())
    days = len({t["trade_date"] for t in trades})
    gross_before_costs = float(sum(t["pnl"] + t.get("costs", 0) for t in trades))
    s = summarize(trades)
    return {"trades": n, "days": days, "trades_per_day": round(n / days, 2) if days else None,
            "win_rate": round(100 * len(wins) / n, 1), "win_rate_ci95": s.get("win_rate_ci95"),
            "avg_winner_usd": round(float(wins.mean()), 2) if len(wins) else None,
            "avg_loser_usd": round(float(losses.mean()), 2) if len(losses) else None,
            "avg_winner_r": round(float(r[r > 0].mean()), 3) if (r > 0).any() else None,
            "avg_loser_r": round(float(r[r <= 0].mean()), 3) if (r <= 0).any() else None,
            "expectancy_usd": round(float(pnl.mean()), 2), "avg_r": round(float(r.mean()), 3), "avg_r_ci95": s.get("avg_r_ci95"),
            "total_usd": round(float(pnl.sum()), 2), "total_r": round(float(r.sum()), 2),
            "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if len(losses) and losses.sum() < 0 else None,
            "max_drawdown_usd": round(dd, 2), "max_drawdown_r": round(dd_r, 2),
            "avg_cost_usd": round(float(np.mean([t.get("costs", 0) for t in trades])), 2),
            "pnl_before_costs_usd": round(gross_before_costs, 2),
            "tier": s["tier"], "tier_text": s["tier_text"]}


def diagnostics(trades: list[dict]) -> dict:
    out = {}
    for dim in DIMENSIONS:
        groups: dict = defaultdict(list)
        for t in trades:
            groups[str(t.get(dim))].append(t)
        out[dim] = [{"bucket": k, "trades": len(v), "avg_r": round(float(np.mean([x["r_multiple"] for x in v])), 3),
                     "win_rate": round(100 * sum(x["pnl"] > 0 for x in v) / len(v), 1)} for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))]
    late = [t for t in trades if t.get("entry_lateness_atr") is not None]
    if late:
        q = np.quantile([t["entry_lateness_atr"] for t in late], [0.5])[0]
        out["entry_lateness"] = [{"bucket": f"<= {q:.2f} ATR past trigger", "trades": int(sum(t["entry_lateness_atr"] <= q for t in late)),
                                  "avg_r": round(float(np.mean([t["r_multiple"] for t in late if t["entry_lateness_atr"] <= q])), 3)},
                                 {"bucket": f"> {q:.2f} ATR past trigger", "trades": int(sum(t["entry_lateness_atr"] > q for t in late)),
                                  "avg_r": round(float(np.mean([t["r_multiple"] for t in late if t["entry_lateness_atr"] > q] or [0])), 3)}]
    if trades:
        mfe = np.array([t.get("mfe_r", 0) for t in trades])
        losers = [t for t in trades if t["pnl"] <= 0]
        out["mechanics"] = {"reached_1r_pct": round(100 * float((mfe >= 1).mean()), 1), "reached_2r_pct": round(100 * float((mfe >= 2).mean()), 1),
                            "losers_up_1r_first_pct": round(100 * sum(t.get("mfe_r", 0) >= 1 for t in losers) / len(losers), 1) if losers else None,
                            "median_mae_r": round(float(np.median([t.get("mae_r", 0) for t in trades])), 2)}
    return out


def _days(F: pd.DataFrame) -> list:
    return sorted({str(d) for d in F.loc[F["rth"], "td"]})


def _subset(trades, days: set) -> list[dict]:
    return [t for t in trades if t["trade_date"] in days]


def walk_forward(F: pd.DataFrame, spec: ProductSpec, fee: float, slippage_ticks: float = 1.0, flat_by_min_from_rth: float | None = 400,
                 n_folds: int = 4, holdout_frac: float = 0.2, grid: list[dict] | None = None, min_holdout_trades: int = 30,
                 min_days: int = 15) -> dict:
    grid = grid or GRID
    days = _days(F)
    if len(days) < min_days:
        raise ValueError(f"Only {len(days)} trade dates of data; need at least {min_days} for a walk-forward test.")
    h = max(3, int(len(days) * holdout_frac))
    dev, hold = days[:-h], days[-h:]
    k = max(2, n_folds)
    size = len(dev) // k
    folds = [dev[i * size:(i + 1) * size] if i < k - 1 else dev[i * size:] for i in range(k)]
    # one scan per parameter set over the whole series (setups only use past bars, so this is causal)
    runs = []
    for g in grid:
        p = SetupParams(target_r=g["target_r"], max_chase_atr=g["max_chase_atr"], flat_by_min_from_rth=flat_by_min_from_rth)
        trades = simulate(F, spec, scan(F, spec, p), fee, slippage_ticks, 3, flat_by_min_from_rth)
        runs.append((g, trades))

    def best_on(dset: set) -> tuple[dict, list]:
        scored = []
        for g, tr in runs:
            sub = _subset(tr, dset)
            scored.append((np.mean([t["r_multiple"] for t in sub]) if len(sub) >= 10 else -9, g, tr))
        scored.sort(key=lambda x: -x[0])
        return scored[0][1], scored[0][2]

    oos, fold_rows = [], []
    for j in range(1, k):
        train = set(sum(folds[:j], []))
        g, tr = best_on(train)
        test = _subset(tr, set(folds[j]))
        oos += test
        fold_rows.append({"train": f"{folds[0][0]} to {folds[j - 1][-1]}", "test": f"{folds[j][0]} to {folds[j][-1]}", "params": g,
                          "test_metrics": {"trades": len(test), "expectancy_r": float(np.mean([t["r_multiple"] for t in test])) if test else None}})
    g_final, tr_final = best_on(set(dev))
    hold_trades = _subset(tr_final, set(hold))
    # cost sensitivity with the final parameters
    p = SetupParams(target_r=g_final["target_r"], max_chase_atr=g_final["max_chase_atr"], flat_by_min_from_rth=flat_by_min_from_rth)
    sig = scan(F, spec, p)
    costs = {f"{s} tick slippage per side": metrics(_subset(simulate(F, spec, sig, fee, s, 3, flat_by_min_from_rth), set(days)))
             for s in (0, 1, 2)}
    costs = in_sample_only(costs)
    by_setup, holdout_by, validated, registry = {}, {}, [], {}
    for name in SETUPS:
        for d in ("long", "short"):
            key = f"{name}|{d}"
            o = [t for t in oos if t["setup"] == name and t["direction"] == d]
            ho = [t for t in hold_trades if t["setup"] == name and t["direction"] == d]
            if not o and not ho:
                continue
            fr = [{"test_metrics": {"trades": len([t for t in o if t["trade_date"] in set(fd)]),
                                    "expectancy_r": (float(np.mean([t["r_multiple"] for t in o if t["trade_date"] in set(fd)]))
                                                     if any(t["trade_date"] in set(fd) for t in o) else None)}} for fd in folds[1:]]
            ev = {**summarize(o, fr), **{k2: v for k2, v in metrics(o).items() if k2 in ("profit_factor", "max_drawdown_r", "expectancy_usd")}}
            hm = metrics(ho)
            by_setup[key] = ev
            holdout_by[key] = hm
            ok = (ev.get("tier") == "reliable" and hm.get("trades", 0) >= min_holdout_trades and (hm.get("avg_r") or -1) > 0
                  and (hm.get("profit_factor") or 0) > 1.1)
            registry[key] = {"status": "validated" if ok else "experimental",
                             "why": ("Reliable out-of-sample and confirmed on the holdout." if ok else
                                     f"OOS tier '{ev.get('tier')}', holdout {hm.get('trades', 0)} trades avg {hm.get('avg_r')}R.")}
            if ok:
                validated.append(key)
    return {"product": spec.root, "method": "walk-forward + final holdout", "run_at": datetime.now(timezone.utc).isoformat(),
            "data": {"trade_dates": len(days), "first": days[0], "last": days[-1], "development": f"{dev[0]} to {dev[-1]}",
                     "holdout": f"{hold[0]} to {hold[-1]}", "bars": len(F)},
            "grid": grid, "folds": fold_rows, "final_params": g_final,
            "overall": summarize(oos, fold_rows), "oos_metrics": metrics(oos), "holdout_metrics": metrics(hold_trades),
            "by_setup": by_setup, "holdout_by_setup": holdout_by, "registry": registry, "validated": validated,
            "diagnostics": diagnostics(oos), "cost_sensitivity": costs,
            "assumptions": {"fee_round_turn": fee, "slippage_ticks": slippage_ticks, "one_contract": True, "max_trades_per_day": 3,
                            "target_fill": "one tick of trade-through", "same_bar_stop_and_target": "stop"},
            "trades_sample": oos[-40:], "disclosure": __doc__.split("Disclosure:")[1].strip()}


def asdict_params(p: SetupParams) -> dict:
    return asdict(p)
