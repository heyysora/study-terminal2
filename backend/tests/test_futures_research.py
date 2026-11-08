"""Strategy research: metrics, diagnostics, walk-forward structure and the validation rule."""
import pytest

from app.futures import contracts as fc
from app.futures import features as ff
from app.futures import research as fr
from app.futures.sessions import FuturesClock

from .test_futures_analysis import load_bars

ES = fc.get("ES")
CLK = FuturesClock(ES)


def tr(pnl, r, day="2026-11-02", **kw):
    return {"pnl": pnl, "r_multiple": r, "gross": pnl + 3.78, "costs": 3.78 + 25, "trade_date": day, "entry_ts": day + "T15:00:00+00:00",
            "setup": "sweep_reversal", "direction": "long", "exit_role": "stop" if pnl < 0 else "target", **kw}


def test_metrics_profit_factor_drawdown_winners_losers():
    t = [tr(200, 2.0), tr(-100, -1.0), tr(-100, -1.0, "2026-11-03"), tr(300, 3.0, "2026-11-03"), tr(-100, -1.0, "2026-11-04")]
    m = fr.metrics(t)
    assert m["trades"] == 5 and m["days"] == 3 and m["win_rate"] == 40.0
    assert m["profit_factor"] == pytest.approx(500 / 300, abs=0.01)
    assert m["avg_winner_usd"] == 250 and m["avg_loser_usd"] == -100 and m["expectancy_usd"] == 40
    assert m["max_drawdown_usd"] == 200 and m["max_drawdown_r"] == 2.0          # +200, -100, -100 from the peak
    assert m["pnl_before_costs_usd"] == pytest.approx(200 + 5 * 28.78)
    assert m["tier"] == "insufficient"


def test_diagnostics_slices():
    t = [tr(100, 1.0, volatility="high", time_of_day="first hour", entry_lateness_atr=0.1),
         tr(-100, -1.0, volatility="low", time_of_day="midday", entry_lateness_atr=0.6)]
    d = fr.diagnostics(t)
    assert {x["bucket"] for x in d["volatility"]} == {"high", "low"}
    assert d["entry_lateness"][0]["avg_r"] == 1.0 and d["entry_lateness"][1]["avg_r"] == -1.0


def test_walk_forward_structure_and_no_validation_on_small_samples():
    F = ff.build(ff.bars_to_frame(load_bars(), CLK), ES, CLK)
    with pytest.raises(ValueError):
        fr.walk_forward(F, ES, 3.78)                                            # fixture has fewer than 15 trade dates
    res = fr.walk_forward(F, ES, 3.78, grid=[{"target_r": 2.0, "max_chase_atr": 0.5}], n_folds=3, min_days=6)
    dev_last, hold_first = res["data"]["development"].split(" to ")[1], res["data"]["holdout"].split(" to ")[0]
    assert dev_last < hold_first                                                # holdout strictly after development
    assert all(f["train"].split(" to ")[1] < f["test"].split(" to ")[0] for f in res["folds"])
    assert res["validated"] == [] and all(v["status"] == "experimental" for v in res["registry"].values())
    assert set(res["cost_sensitivity"]) == {"0 tick slippage per side", "1 tick slippage per side", "2 tick slippage per side"}
    a0 = res["cost_sensitivity"]["0 tick slippage per side"].get("total_usd") or 0
    a2 = res["cost_sensitivity"]["2 tick slippage per side"].get("total_usd") or 0
    assert a2 <= a0                                                             # more slippage never helps


def test_pipeline_requires_research_validation(settings, db):
    from app.futures.service import FuturesService
    from app.settings.store import SettingsStore

    svc = FuturesService(settings, db, SettingsStore(db), provider=None)
    svc.evidence["ES"] = {"by_setup": {"sweep_reversal|long": {"tier": "reliable"}}}      # an old quick backtest, no registry
    assert svc.validated_strategies("ES") == set()
    svc.evidence["ES"]["validated"] = ["sweep_reversal|long"]
    assert svc.validated_strategies("ES") == {"sweep_reversal|long"}
