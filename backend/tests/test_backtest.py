from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.analysis.features import build
from app.backtest.engine import BacktestConfig, metrics, run
from app.backtest.walkforward import optimize, walk_forward
from app.core.market_clock import ET, MarketClock
from app.market_data.types import Timeframe
from app.ml.model import ModelRegistry, psi, train
from app.signals.setups import SetupParams

from .synth import intraday

CLOCK = MarketClock()
LOOSE = SetupParams(rvol_min=0, vol_ratio_min=0)


def frames(days=12, seed=5):
    return build(intraday(days=days, seed=seed, vol=0.003, start=datetime(2026, 8, 3).date()), Timeframe.M5)


def test_backtest_produces_trades_and_charges_costs():
    ff = frames()
    free = run("T", ff, BacktestConfig(params=LOOSE, slippage_bps=0, slippage_min=0), CLOCK)
    costly = run("T", ff, BacktestConfig(params=LOOSE, slippage_bps=5, slippage_min=0.02, commission_per_order=1), CLOCK)
    assert len(free["trades"]) >= 5
    assert sum(t["pnl"] for t in costly["trades"]) < sum(t["pnl"] for t in free["trades"])
    assert all(t["cost_r"] > 0 for t in costly["trades"])


def test_flat_every_night_and_entries_after_signal():
    r = run("T", frames(), BacktestConfig(params=LOOSE), CLOCK)
    for t in r["trades"]:
        e, x, s = (pd.Timestamp(t[k]).tz_convert(ET) for k in ("entry_ts", "exit_ts", "signal_ts"))
        assert e.date() == x.date()          # intraday: never held overnight
        assert e > s                          # entry strictly after the signal bar
        assert t["exit_reason"] in ("stop_loss", "take_profit", "eod")


def test_no_look_ahead_future_bars_dont_change_past_trades():
    bars = intraday(days=12, seed=9, vol=0.003, start=datetime(2026, 8, 3).date())
    full = build(bars, Timeframe.M5)
    cut_day = sorted(full.df["session"].unique())[8]
    cut_ts = full.df[full.df["session"] == cut_day].index[0]
    part = build([b for b in bars if b.ts < cut_ts], Timeframe.M5)
    a = run("T", part, BacktestConfig(params=LOOSE), CLOCK)["trades"]
    b = [t for t in run("T", full, BacktestConfig(params=LOOSE), CLOCK)["trades"] if pd.Timestamp(t["exit_ts"]) < cut_ts]
    strip = lambda ts: [{k: v for k, v in t.items() if k not in ("features",)} for t in ts]  # noqa: E731
    assert strip(a) == strip(b)


def test_metrics_math():
    t = lambda pnl, r: {"pnl": pnl, "r_multiple": r, "hold_minutes": 10, "exit_reason": "x", "cost_r": 0.1}  # noqa: E731
    trades = [t(200, 2), t(-100, -1), t(-100, -1), t(200, 2)]
    eq = [("2026-01-02T15:00:00+00:00", 25_000), ("2026-01-02T16:00:00+00:00", 25_200), ("2026-01-05T16:00:00+00:00", 24_900),
          ("2026-01-06T16:00:00+00:00", 25_200)]
    m = metrics(trades, eq, 25_000)
    assert m["win_rate"] == 50 and m["profit_factor"] == 2.0 and m["expectancy"] == 50 and m["expectancy_r"] == 0.5
    assert m["max_drawdown_pct"] == pytest.approx(-1.19, abs=0.01) and m["total_return_pct"] == 0.8
    assert "sample_warning" in m and m["expectancy_r_before_costs"] == 0.6


def test_walk_forward_tests_only_on_unseen_windows():
    fr = {"A": frames(days=16, seed=11), "B": frames(days=16, seed=12)}
    wf = walk_forward(fr, BacktestConfig(params=LOOSE), CLOCK, grid={"target_r": [1.5, 2.0]}, train_sessions=8, test_sessions=4, min_trades=1)
    assert wf["folds"]
    for fold in wf["folds"]:
        assert fold["train"][1] < fold["test"][0]
    for t in wf["oos_trades"]:
        fold = wf["folds"][t["fold"]]
        assert fold["test"][0] <= str(pd.Timestamp(t["entry_ts"]).tz_convert(ET).date()) <= fold["test"][1]


def test_optimize_ranks_by_expectancy():
    res = optimize({"A": frames()}, BacktestConfig(params=LOOSE), CLOCK, grid={"target_r": [1.0, 3.0]}, min_trades=1)
    assert len(res) == 2 and res[0]["score"] >= res[1]["score"]


def _fake_trades(n, signal_strength, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    t0 = datetime(2026, 1, 2, 15, tzinfo=timezone.utc)
    for k in range(n):
        x = rng.normal()
        win = rng.random() < (0.5 + signal_strength * np.tanh(x))
        out.append({"features": {"rsi": 50 + 10 * x, "vol_ratio": rng.random() * 2}, "setup": "vwap_reclaim", "direction": "long",
                    "pnl": 100 if win else -100, "signal_ts": (t0 + timedelta(hours=k)).isoformat()})
    return out


def test_ml_refuses_noise_and_deploys_real_signal(tmp_path):
    noise = train(_fake_trades(300, 0.0), tmp_path / "a")
    assert noise["deployed"] is False and "Not deployed" in noise["reason"]
    real = train(_fake_trades(600, 0.45, seed=1), tmp_path / "b")
    assert real["deployed"] is True and real["n_test"] == 180
    assert real["train_period"][1] < real["test_period"][0]  # chronological split
    assert real["feature_importance"][0]["feature"] == "rsi"
    reg = ModelRegistry(tmp_path / "b")
    reg.load()
    hi = reg.predict({"rsi": 75, "vol_ratio": 1}, "vwap_reclaim", "long")["probability_of_profit"]
    lo = reg.predict({"rsi": 25, "vol_ratio": 1}, "vwap_reclaim", "long")["probability_of_profit"]
    assert hi > lo
    assert train(_fake_trades(30, 0.4), tmp_path / "c")["deployed"] is False


def test_psi():
    rng = np.random.default_rng(0)
    a = rng.normal(size=2000)
    assert psi(a, rng.normal(size=2000)) < 0.1
    assert psi(a, rng.normal(2, 1, size=2000)) > 0.25
