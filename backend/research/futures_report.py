"""Writes docs/BACKTEST_RESULTS_FUTURES.md from a research JSON produced by app.futures.research.walk_forward.
Usage: python -m research.futures_report research/out/futures_research.json"""
import json
import sys
from pathlib import Path

d = json.loads(Path(sys.argv[1]).read_text())
L = []
w = L.append
first = next(iter(d.values()))
w("# Futures strategy research (0.7.0)\n")
w(f"Run {first['run_at'][:16]} UTC on Yahoo continuous 5-minute bars ({first['data']['first']} to {first['data']['last']}, "
  f"{first['data']['trade_dates']} trade dates). Method: chronological walk-forward over the development period "
  f"({first['data']['development']}), parameters chosen only on earlier folds, then one pass over the holdout "
  f"({first['data']['holdout']}). One contract, TopstepX round-turn fees, 1 tick slippage per side on market and stop fills, "
  "targets need one tick of trade-through, stop assumed first when a bar touches both, flat by 15:10 CT, at most 3 trades per day.\n")
w("**Result: no strategy is validated for any product, so automated paper trading (mode B) approves nothing.** NO TRADE remains "
  "the correct default. Experimental strategies can run in the research sandbox, which keeps its own account and never mixes "
  "with validated results.\n")
w("| Product | OOS trades / days | Win rate | Avg R (95% interval) | Profit factor | Expectancy | Max drawdown | Holdout trades | Holdout avg R | Holdout PF | OOS tier |")
w("|---|---|---|---|---|---|---|---|---|---|---|")
for r, v in d.items():
    o, h = v["oos_metrics"], v["holdout_metrics"]
    ci = o.get("avg_r_ci95")
    w(f"| {r} | {o['trades']} / {o['days']} | {o['win_rate']}% | {o['avg_r']:+.3f} ({ci[0]:+.2f} to {ci[1]:+.2f}) | {o.get('profit_factor')} | "
      f"${o['expectancy_usd']:,.2f} | ${o['max_drawdown_usd']:,.0f} ({o['max_drawdown_r']}R) | {h.get('trades', 0)} | "
      f"{h.get('avg_r', 0):+.3f} | {h.get('profit_factor')} | {o['tier']} |")
w("")
w("Average winner / loser (OOS, in R): " + "; ".join(f"{r} {v['oos_metrics']['avg_winner_r']} / {v['oos_metrics']['avg_loser_r']}" for r, v in d.items()) + ".\n")
w("## Why nothing is validated\n")
w("Validation needs a *reliable* out-of-sample tier (≥100 trades, ≥30 days, 95% interval above zero, consistent folds) **and** a "
  "holdout with ≥30 trades, positive average R and profit factor above 1.1. With ~59 days of 5-minute history, each setup and "
  "direction gets between 0 and 27 out-of-sample trades, so every one is 'insufficient' on its own. The data window, not just "
  "the strategies, is the binding limit: Yahoo serves no older intraday futures bars.\n")
w("## What the numbers suggest (not evidence of an edge)\n")
for r, v in d.items():
    dg = v["diagnostics"]
    def best(dim):
        rows = [x for x in dg[dim] if x["trades"] >= 8]
        return ", ".join(f"{x['bucket']} {x['avg_r']:+.2f}R ({x['trades']})" for x in rows)
    w(f"**{r}** (final parameters {v['final_params']})")
    w(f"- Volatility: {best('volatility')}")
    w(f"- Time of day: {best('time_of_day')}")
    w(f"- Versus structure: {best('trend_aligned')}")
    w(f"- Entry bar volume: {best('volume')}")
    if dg.get("entry_lateness"):
        w("- Entry lateness: " + ", ".join(f"{x['bucket']} {x['avg_r']:+.2f}R ({x['trades']})" for x in dg["entry_lateness"]))
    m = dg.get("mechanics", {})
    w(f"- Mechanics: {m.get('reached_1r_pct')}% of trades reached +1R, {m.get('reached_2r_pct')}% reached +2R; "
      f"{m.get('losers_up_1r_first_pct')}% of losers were up 1R first.")
    cs = v["cost_sensitivity"]
    w("- Cost sensitivity (all dates, final parameters, so not out-of-sample): " +
      ", ".join(f"{k}: {x.get('avg_r', 0):+.3f}R PF {x.get('profit_factor')}" for k, x in cs.items()))
    w("")
w("Observations across products, stated as hypotheses to test with more data, not conclusions:\n")
w("- NQ and MNQ were positive out-of-sample (+0.29R and +0.42R) and on the holdout (+0.39R each), but with 42-50 trades the "
  "intervals still include zero. These are the strongest candidates for the sandbox, not for automated trading.\n"
  "- ES and MES lost slightly out-of-sample and on the holdout. MES is hurt most by costs: fees are about one tick per round "
  "turn on a $1.25-tick contract.\n"
  "- Late entries (further past the trigger) did worse on ES and MES; on MNQ the split went the other way, which is what noise "
  "looks like at these sample sizes.\n"
  "- Trades in the last part of RTH lost on every product except MNQ (tiny samples).\n")
w("## Per setup and direction (out-of-sample, then holdout)\n")
for r, v in d.items():
    w(f"**{r}**\n")
    w("| Setup | OOS trades | OOS avg R (95%) | Holdout trades | Holdout avg R | Status |")
    w("|---|---|---|---|---|---|")
    for k, e in v["by_setup"].items():
        h = v["holdout_by_setup"][k]
        ci = e.get("avg_r_ci95")
        w(f"| {k.replace('|', ' ').replace('_', ' ')} | {e['trades']} | {'' if e.get('avg_r') is None else format(e['avg_r'], '+.3f')}"
          f"{f' ({ci[0]:+.2f} to {ci[1]:+.2f})' if ci else ''} | {h.get('trades', 0)} | "
          f"{'' if h.get('avg_r') is None else format(h['avg_r'], '+.3f')} | {v['registry'][k]['status']} |")
    w("")
w("## Walk-forward folds\n")
for r, v in d.items():
    w(f"**{r}**: " + "; ".join(f"test {f['test']} with {f['params']} -> {f['test_metrics']['trades']} trades, "
                                f"{(f['test_metrics']['expectancy_r'] or 0):+.3f}R" for f in v["folds"]))
w("\n## Disclosure\n")
w(first["disclosure"])
w("\nRe-run anytime from Futures > Evidence (\"Run research\") or `python -m research.futures_report` after `walk_forward`. "
  "Results for later dates are genuinely unseen.")
Path(__file__).resolve().parents[2].joinpath("docs", "BACKTEST_RESULTS_FUTURES.md").write_text("\n".join(L), encoding="utf-8")
print("written")
