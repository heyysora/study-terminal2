"""Statistical uncertainty for backtest results, and the evidence tiers that gate signals.

Why a *day-clustered* bootstrap: trades on the same day share the same market move (a bad SPY
morning hits every long at once), so they are not independent. Resampling whole days instead of
single trades gives wider, more honest intervals than the textbook formula.

Evidence tiers (used by the signal engine; the thresholds are written down, not tuned):
  none          no out-of-sample trades at all
  insufficient  fewer than MIN_TRADES out-of-sample trades: the average is mostly noise
  negative      the whole 95% interval of average R is below zero: it lost money, convincingly
  losing        average below zero but the interval still reaches zero
  inconclusive  average >= 0 but the interval includes zero: can't tell skill from luck
  promising     interval entirely above zero but fewer than RELIABLE_TRADES trades or too few
                independent days/folds: interesting, not yet reliable
  reliable      interval entirely above zero, at least RELIABLE_TRADES trades over at least
                RELIABLE_DAYS separate days, positive in most walk-forward folds
Only `reliable` allows BUY/SHORT. STRONG additionally needs the current market regime's own
history to be non-negative and a high checklist score.
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

MIN_TRADES = 30
RELIABLE_TRADES = 100
RELIABLE_DAYS = 30
FOLD_CONSISTENCY = 0.6
N_BOOT = 2000

TIER_TEXT = {
    "none": "Never tested out-of-sample.",
    "insufficient": "Too few out-of-sample trades to judge (need {min}).",
    "negative": "Lost money out-of-sample, and the loss is statistically clear.",
    "losing": "Lost money out-of-sample on average (not conclusive, but no evidence of an edge).",
    "inconclusive": "Out-of-sample results can't be told apart from luck.",
    "promising": "Positive out-of-sample, but not enough trades or days yet to rely on it.",
    "reliable": "Positive out-of-sample with enough trades, days and consistent folds.",
}
TRADE_OK = {"reliable"}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% interval for a win rate (Wilson score: behaves well for small n and rates near 0/100%)."""
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(100 * (c - h), 1), round(100 * (c + h), 1)


def _day(t: dict) -> str:
    return str(t.get("entry_ts", ""))[:10]


def mean_ci(trades: list[dict], key: str = "r_multiple", n_boot: int = N_BOOT, seed: int = 7) -> tuple[float, float] | None:
    """95% day-clustered bootstrap interval for the mean of `key` across trades."""
    if len(trades) < 2:
        return None
    by: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        by[_day(t)].append(float(t[key]))
    days = [np.asarray(v) for v in by.values()]
    if len(days) < 2:
        return None
    sums = np.array([d.sum() for d in days])
    cnts = np.array([len(d) for d in days])
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(days), size=(n_boot, len(days)))
    means = sums[idx].sum(axis=1) / cnts[idx].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return round(float(lo), 3), round(float(hi), 3)


def summarize(trades: list[dict], folds: list[dict] | None = None) -> dict:
    """Sample size, average R with interval, win rate with interval, and the evidence tier."""
    n = len(trades)
    if n == 0:
        return {"trades": 0, "tier": "none", "tier_text": TIER_TEXT["none"]}
    r = np.array([float(t["r_multiple"]) for t in trades])
    wins = int((np.array([t["pnl"] for t in trades]) > 0).sum())
    days = len({_day(t) for t in trades})
    ci = mean_ci(trades)
    out = {
        "trades": n, "days": days, "avg_r": round(float(r.mean()), 3), "total_r": round(float(r.sum()), 2),
        "avg_r_ci95": list(ci) if ci else None, "win_rate": round(100 * wins / n, 1),
        "win_rate_ci95": list(wilson(wins, n) or []) or None,
    }
    fold_pos = None
    if folds:
        fr = [f["test_metrics"].get("expectancy_r") for f in folds if f.get("test_metrics", {}).get("trades")]
        fr = [x for x in fr if x is not None]
        if fr:
            fold_pos = sum(x > 0 for x in fr) / len(fr)
            out["folds_positive"] = f"{sum(x > 0 for x in fr)}/{len(fr)}"
    out["tier"] = tier(n, days, ci, out["avg_r"], fold_pos)
    out["tier_text"] = TIER_TEXT[out["tier"]].format(min=MIN_TRADES)
    return out


def tier(n: int, days: int, ci: tuple[float, float] | None, avg: float, fold_pos: float | None = None) -> str:
    if n == 0:
        return "none"
    if n < MIN_TRADES or ci is None:
        return "insufficient"
    lo, hi = ci
    if hi < 0:
        return "negative"
    if avg < 0:
        return "losing"
    if lo <= 0:
        return "inconclusive"
    if n >= RELIABLE_TRADES and days >= RELIABLE_DAYS and (fold_pos is None or fold_pos >= FOLD_CONSISTENCY):
        return "reliable"
    return "promising"
