"""Phase 3: statistical uncertainty, evidence tiers, trade diagnostics, walk-forward hygiene."""
from datetime import datetime, timedelta

import numpy as np

from app.analysis.features import build
from app.backtest.diagnostics import mechanics, report, time_bucket, trend_alignment
from app.backtest.engine import BacktestConfig, run
from app.backtest.stats import mean_ci, summarize, tier, wilson
from app.backtest.walkforward import walk_forward
from app.market_data.types import Timeframe
from app.signals.setups import SetupParams
from tests.fakes import always_open_clock
from tests.synth import intraday


def _trades(rs, days=None, setup="vwap_reclaim", direction="long"):
    out = []
    for k, r in enumerate(rs):
        d = (days[k] if days else k)
        out.append({"r_multiple": r, "pnl": r * 100, "entry_ts": (datetime(2026, 1, 1) + timedelta(days=d)).isoformat(),
                    "setup": setup, "direction": direction, "symbol": "X", "regime": "up/normal-vol", "exit_reason": "stop_loss" if r < 0 else "take_profit",
                    "features": {"minute": 600 + k % 300, "ema_stack": 1.0, "structure_code": 1.0}, "target": 102, "planned_entry": 100,
                    "risk_per_share": 1.0, "cost_r": 0.02, "mfe_r": max(r, 0.2), "mae_r": 0.5, "bars_to_exit": 3})
    return out


def test_wilson_interval_known_values():
    lo, hi = wilson(50, 100)
    assert 40 < lo < 41 and 59 < hi < 60.5
    assert wilson(0, 0) is None
    lo, hi = wilson(0, 10)
    assert lo == 0 and hi > 25  # zero wins in 10 still leaves a wide upper bound


def test_bootstrap_interval_contains_mean_and_clusters_by_day():
    rng = np.random.default_rng(1)
    rs = list(rng.normal(0.1, 1.0, 400))
    ci = mean_ci(_trades(rs))
    assert ci[0] < np.mean(rs) < ci[1]
    # same values but 20 trades per day that all move together -> far fewer independent observations, wider interval
    day_effect = rng.normal(0, 1.0, 20)
    rs2 = [0.1 + day_effect[k // 20] + rng.normal(0, 0.1) for k in range(400)]
    ci_clustered = mean_ci(_trades(rs2, days=[k // 20 for k in range(400)]))
    ci_iid_view = mean_ci(_trades(rs2))  # pretending each trade was its own day
    assert (ci_clustered[1] - ci_clustered[0]) > 2 * (ci_iid_view[1] - ci_iid_view[0])


def test_tier_rules():
    assert tier(0, 0, None, 0) == "none"
    assert tier(29, 29, (-0.1, 0.5), 0.2) == "insufficient"
    assert tier(80, 40, (-0.4, -0.05), -0.2) == "negative"
    assert tier(80, 40, (-0.3, 0.02), -0.1) == "losing"
    assert tier(80, 40, (-0.05, 0.3), 0.1) == "inconclusive"
    assert tier(80, 40, (0.05, 0.3), 0.15) == "promising"          # positive but under 100 trades
    assert tier(150, 20, (0.05, 0.3), 0.15) == "promising"         # enough trades, too few days
    assert tier(150, 40, (0.05, 0.3), 0.15, fold_pos=0.4) == "promising"  # inconsistent across folds
    assert tier(150, 40, (0.05, 0.3), 0.15, fold_pos=0.7) == "reliable"


def test_summarize_reports_uncertainty():
    s = summarize(_trades([1.0, -1.0] * 20))
    assert s["trades"] == 40 and s["avg_r"] == 0 and s["avg_r_ci95"][0] < 0 < s["avg_r_ci95"][1]
    assert s["win_rate"] == 50 and s["tier"] == "inconclusive"


def test_diagnostic_buckets():
    t = _trades([1.0])[0]
    assert time_bucket({**t, "features": {"minute": 575}}) == "09:30-10:00 open"
    assert time_bucket({**t, "features": {"minute": 700}}) == "11:30-14:00 midday"
    assert trend_alignment(t) == "with trend"
    assert trend_alignment({**t, "direction": "short"}) == "against trend"


def test_report_and_mechanics_on_known_trades():
    trades = _trades([-1.0] * 60 + [2.0] * 20)
    m = mechanics(trades)
    assert m["win_rate_pct"] == 25.0 and abs(m["avg_r_after_costs"] - (-0.25)) < 1e-9
    assert m["breakeven_win_rate_pct"] == 33.3   # 1 / (2 + 1)
    assert m["exit_mix_pct"]["stop"] == 75.0
    rep = report(trades)
    assert rep["overall"]["tier"] in ("negative", "losing")
    titles = [f["title"] for f in rep["findings"]]
    assert "Costs" in titles and "Win rate vs what's needed" in titles
    assert set(rep["slices"]) >= {"setup", "symbol", "direction", "regime", "time_of_day", "volatility", "prior_result", "setup_quality"}
    streaks = {r["bucket"] for r in rep["slices"]["prior_result"]["rows"]}
    assert any("loss streak of 3+" in b for b in streaks)


def test_backtest_trades_carry_excursions():
    ff = build(intraday("T", days=8, minutes=5, seed=3), Timeframe.M5)
    cfg = BacktestConfig(params=SetupParams(rvol_min=0, vol_ratio_min=0), slippage_bps=0, slippage_min=0)
    trades = run("T", ff, cfg, always_open_clock())["trades"]
    assert trades, "synthetic data should produce trades"
    reasons = {t["exit_reason"] for t in trades}
    assert reasons <= {"take_profit", "stop_loss", "eod"}, reasons
    assert "take_profit" in reasons and "stop_loss" in reasons    # both branches below are actually exercised
    for t in trades:
        assert t["mfe_r"] >= 0 and t["mae_r"] >= 0 and t["bars_to_exit"] >= 0
        assert "quality" in t and "timeframe" in t
        if t["exit_reason"] == "take_profit":
            assert t["mfe_r"] >= 1.9                  # it reached a 2R target, so MFE must be about 2R
        if t["exit_reason"] == "stop_loss":
            assert t["mae_r"] >= 0.9 and "target_after_stop" in t


def test_walk_forward_tests_only_on_unseen_windows():
    frames = {"T": build(intraday("T", days=14, minutes=5, seed=5), Timeframe.M5)}
    cfg = BacktestConfig(params=SetupParams(rvol_min=0, vol_ratio_min=0), slippage_bps=0, slippage_min=0)
    wf = walk_forward(frames, cfg, always_open_clock(), {"target_r": [1.5, 2.0]}, train_sessions=5, test_sessions=3, min_trades=1)
    assert wf["search"]["combos_per_fold"] == 2
    for f in wf["folds"]:
        assert f["train"][1] < f["test"][0]          # training ends before testing starts
    for t in wf["oos_trades"]:
        f = wf["folds"][t["fold"]]
        assert f["test"][0] <= t["entry_ts"][:10] <= f["test"][1]
