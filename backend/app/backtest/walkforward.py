"""Parameter optimization and walk-forward testing.

Optimization alone overfits: the best parameters on past data are partly best by luck.
Walk-forward fixes that: pick parameters on a training window, then measure them on the
*following* window they never saw. Only those out-of-sample results calibrate signal confidence.
"""
from __future__ import annotations

import itertools
from dataclasses import replace

import pandas as pd

from ..analysis.features import FeatureFrame
from ..core.market_clock import MarketClock
from .engine import BacktestConfig, metrics, run

DEFAULT_GRID = {"target_r": [1.5, 2.0, 3.0], "stop_buffer_atr": [0.1, 0.25], "rvol_min": [1.0, 1.5]}


def _grid(grid: dict) -> list[dict]:
    keys = list(grid)
    return [dict(zip(keys, vals, strict=False)) for vals in itertools.product(*(grid[k] for k in keys))]


def run_many(frames: dict[str, FeatureFrame], cfg: BacktestConfig, clock: MarketClock, start=None, end=None) -> tuple[list, list]:
    trades, curves = [], []
    for sym, ff in frames.items():
        r = run(sym, ff, cfg, clock, start, end)
        trades += r["trades"]
        curves.append(pd.Series([e for _, e in r["equity"]], index=pd.to_datetime([t for t, _ in r["equity"]], utc=True)))
    return trades, curves


def combine_equity(curves: list[pd.Series], starting_cash: float) -> list[tuple[str, float]]:
    """Portfolio view: each symbol traded with its own account; P&L is summed."""
    curves = [c for c in curves if len(c)]
    if not curves:
        return []
    pnl = sum((c - starting_cash).reindex(sorted(set().union(*[c.index for c in curves]))).ffill().fillna(0) for c in curves)
    eq = pnl + starting_cash
    return [(t.isoformat(), round(float(v), 2)) for t, v in eq.items()]


def score(m: dict, min_trades: int) -> float:
    if m["trades"] < min_trades or m.get("expectancy_r") is None:
        return float("-inf")
    return m["expectancy_r"]


def optimize(frames, cfg: BacktestConfig, clock, grid: dict | None = None, start=None, end=None, min_trades: int = 10) -> list[dict]:
    results = []
    for combo in _grid(grid or DEFAULT_GRID):
        c = replace(cfg, params=replace(cfg.params, **combo))
        trades, curves = run_many(frames, c, clock, start, end)
        m = metrics(trades, combine_equity(curves, cfg.starting_cash), cfg.starting_cash)
        results.append({"params": combo, "metrics": m, "score": score(m, min_trades)})
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def walk_forward(frames, cfg: BacktestConfig, clock, grid: dict | None = None, train_sessions: int = 20,
                 test_sessions: int = 5, min_trades: int = 8) -> dict:
    all_sessions = sorted(set().union(*[set(ff.df["session"]) for ff in frames.values()]))
    folds, oos_trades, oos_curves = [], [], []
    k = train_sessions
    while k + 1 <= len(all_sessions):
        tr_s, tr_e = all_sessions[k - train_sessions], all_sessions[k - 1]
        te_s = all_sessions[k]
        te_e = all_sessions[min(k + test_sessions, len(all_sessions)) - 1]
        to_ts = lambda d, end=False: pd.Timestamp(d).tz_localize("America/New_York").tz_convert("UTC") + (pd.Timedelta(days=1) if end else pd.Timedelta(0))  # noqa: E731
        opt = optimize(frames, cfg, clock, grid, to_ts(tr_s), to_ts(tr_e, True), min_trades)
        best = opt[0]
        if best["score"] == float("-inf"):
            folds.append({"train": [str(tr_s), str(tr_e)], "test": [str(te_s), str(te_e)], "skipped": "not enough training trades"})
        else:
            c = replace(cfg, params=replace(cfg.params, **best["params"]))
            trades, curves = run_many(frames, c, clock, to_ts(te_s), to_ts(te_e, True))
            for t in trades:
                t["fold"] = len(folds)
                t["oos"] = True
            oos_trades += trades
            oos_curves += curves
            folds.append({"train": [str(tr_s), str(tr_e)], "test": [str(te_s), str(te_e)], "chosen_params": best["params"],
                          "train_metrics": best["metrics"], "test_metrics": metrics(trades, [], cfg.starting_cash)})
        k += test_sessions
    eq = combine_equity(oos_curves, cfg.starting_cash)
    n_combos = len(_grid(grid or DEFAULT_GRID))
    search = {"combos_per_fold": n_combos, "folds": len(folds),
              "note": (f"Each fold tried {n_combos} parameter combinations on its training window and kept the best. The more "
                       "combinations tried, the more the training winner is a lucky draw - which is exactly why only the "
                       "following, unseen test window is reported.")}
    return {"search": search, "folds": folds, "oos_trades": oos_trades, "oos_metrics": metrics(oos_trades, eq, cfg.starting_cash), "oos_equity": eq,
            "note": "Out-of-sample: each test window used parameters chosen only from the window before it."}
