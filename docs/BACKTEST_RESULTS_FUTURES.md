# Futures strategy research (0.7.0)

Run 2026-11-08T22:58 UTC on Yahoo continuous 5-minute bars (2026-08-31 to 2026-11-06, 49 trade dates). Method: chronological walk-forward over the development period (2026-08-31 to 2026-10-26), parameters chosen only on earlier folds, then one pass over the holdout (2026-10-27 to 2026-11-06). One contract, TopstepX round-turn fees, 1 tick slippage per side on market and stop fills, targets need one tick of trade-through, stop assumed first when a bar touches both, flat by 15:10 CT, at most 3 trades per day.

**Result: no strategy is validated for any product, so automated paper trading (mode B) approves nothing.** NO TRADE remains the correct default. Experimental strategies can run in the research sandbox, which keeps its own account and never mixes with validated results.

| Product | OOS trades / days | Win rate | Avg R (95% interval) | Profit factor | Expectancy | Max drawdown | Holdout trades | Holdout avg R | Holdout PF | OOS tier |
|---|---|---|---|---|---|---|---|---|---|---|
| NQ | 50 / 27 | 38.0% | +0.291 (-0.24 to +0.84) | 2.02 | $370.82 | $3,038 (6.24R) | 17 | +0.394 | 1.48 | inconclusive |
| MNQ | 42 / 25 | 50.0% | +0.420 (-0.07 to +0.86) | 2.27 | $42.17 | $347 (4.16R) | 17 | +0.387 | 1.5 | inconclusive |
| ES | 68 / 29 | 38.2% | -0.065 (-0.35 to +0.22) | 0.93 | $-12.05 | $3,076 (15.39R) | 14 | -0.120 | 1.0 | losing |
| MES | 81 / 30 | 43.2% | -0.032 (-0.27 to +0.21) | 0.99 | $-0.19 | $196 (7.41R) | 20 | -0.102 | 0.77 | losing |

Average winner / loser (OOS, in R): NQ 2.428 / -1.018; MNQ 1.876 / -1.036; ES 1.562 / -1.073; MES 1.319 / -1.06.

## Why nothing is validated

Validation needs a *reliable* out-of-sample tier (≥100 trades, ≥30 days, 95% interval above zero, consistent folds) **and** a holdout with ≥30 trades, positive average R and profit factor above 1.1. With ~59 days of 5-minute history, each setup and direction gets between 0 and 27 out-of-sample trades, so every one is 'insufficient' on its own. The data window, not just the strategies, is the binding limit: Yahoo serves no older intraday futures bars.

## What the numbers suggest (not evidence of an edge)

**NQ** (final parameters {'target_r': 2.0, 'max_chase_atr': 0.3})
- Volatility: high +0.52R (30), normal +0.05R (18)
- Time of day: midday +0.30R (36), first hour +0.78R (10)
- Versus structure: against structure +0.48R (25), with structure +0.10R (25)
- Entry bar volume: average or below +0.14R (35), above average +0.64R (15)
- Entry lateness: <= 0.21 ATR past trigger +0.44R (25), > 0.21 ATR past trigger +0.15R (25)
- Mechanics: 52.0% of trades reached +1R, 42.0% reached +2R; 22.6% of losers were up 1R first.
- Cost sensitivity (all dates, final parameters, so not out-of-sample): 0 tick slippage per side: +0.474R PF 1.88, 1 tick slippage per side: +0.456R PF 1.84, 2 tick slippage per side: +0.438R PF 1.81

**MNQ** (final parameters {'target_r': 2.0, 'max_chase_atr': 0.3})
- Volatility: high +0.40R (28), normal +0.34R (13)
- Time of day: midday +0.40R (28), first hour +0.46R (12)
- Versus structure: with structure +0.47R (22), against structure +0.37R (20)
- Entry bar volume: average or below +0.28R (26), above average +0.65R (16)
- Entry lateness: <= 0.17 ATR past trigger +0.16R (21), > 0.17 ATR past trigger +0.68R (21)
- Mechanics: 52.4% of trades reached +1R, 47.6% reached +2R; 9.5% of losers were up 1R first.
- Cost sensitivity (all dates, final parameters, so not out-of-sample): 0 tick slippage per side: +0.413R PF 1.77, 1 tick slippage per side: +0.397R PF 1.74, 2 tick slippage per side: +0.381R PF 1.71

**ES** (final parameters {'target_r': 2.0, 'max_chase_atr': 0.3})
- Volatility: high -0.05R (41), normal -0.09R (27)
- Time of day: midday -0.05R (51), first hour +0.08R (12)
- Versus structure: against structure +0.00R (37), with structure -0.15R (31)
- Entry bar volume: average or below -0.10R (53), above average +0.05R (15)
- Entry lateness: <= 0.23 ATR past trigger +0.09R (34), > 0.23 ATR past trigger -0.22R (34)
- Mechanics: 45.6% of trades reached +1R, 17.6% reached +2R; 14.3% of losers were up 1R first.
- Cost sensitivity (all dates, final parameters, so not out-of-sample): 0 tick slippage per side: +0.079R PF 1.36, 1 tick slippage per side: -0.009R PF 1.2, 2 tick slippage per side: -0.088R PF 1.07

**MES** (final parameters {'target_r': 1.5, 'max_chase_atr': 0.5})
- Volatility: high +0.01R (47), normal -0.10R (34)
- Time of day: midday -0.02R (59), first hour -0.02R (16)
- Versus structure: with structure +0.05R (43), against structure -0.12R (38)
- Entry bar volume: average or below -0.04R (60), above average +0.01R (21)
- Entry lateness: <= 0.26 ATR past trigger +0.13R (43), > 0.26 ATR past trigger -0.21R (38)
- Mechanics: 46.9% of trades reached +1R, 11.1% reached +2R; 6.5% of losers were up 1R first.
- Cost sensitivity (all dates, final parameters, so not out-of-sample): 0 tick slippage per side: +0.004R PF 1.02, 1 tick slippage per side: -0.076R PF 0.91, 2 tick slippage per side: -0.146R PF 0.81

Observations across products, stated as hypotheses to test with more data, not conclusions:

- NQ and MNQ were positive out-of-sample (+0.29R and +0.42R) and on the holdout (+0.39R each), but with 42-50 trades the intervals still include zero. These are the strongest candidates for the sandbox, not for automated trading.
- ES and MES lost slightly out-of-sample and on the holdout. MES is hurt most by costs: fees are about one tick per round turn on a $1.25-tick contract.
- Late entries (further past the trigger) did worse on ES and MES; on MNQ the split went the other way, which is what noise looks like at these sample sizes.
- Trades in the last part of RTH lost on every product except MNQ (tiny samples).

## Per setup and direction (out-of-sample, then holdout)

**NQ**

| Setup | OOS trades | OOS avg R (95%) | Holdout trades | Holdout avg R | Status |
|---|---|---|---|---|---|
| sweep reversal long | 13 | +0.930 (-0.03 to +1.77) | 5 | -1.013 | experimental |
| sweep reversal short | 16 | -0.013 (-1.02 to +0.90) | 6 | +1.480 | experimental |
| orb retest long | 3 | -0.016 (-1.02 to +1.99) | 1 | -1.003 | experimental |
| orb retest short | 6 | -0.713 (-1.01 to -0.12) | 0 |  | experimental |
| ib breakout long | 1 | -1.013 | 0 |  | experimental |
| trend pullback long | 3 | -0.012 (-1.01 to +1.99) | 0 |  | experimental |
| trend pullback short | 8 | +1.008 (-0.45 to +2.27) | 5 | +0.775 | experimental |

**MNQ**

| Setup | OOS trades | OOS avg R (95%) | Holdout trades | Holdout avg R | Status |
|---|---|---|---|---|---|
| sweep reversal long | 12 | +1.057 (+0.53 to +1.67) | 6 | -0.523 | experimental |
| sweep reversal short | 11 | -0.233 (-0.84 to +0.66) | 6 | +1.478 | experimental |
| orb retest long | 3 | -0.047 (-1.03 to +1.91) | 1 | -1.007 | experimental |
| orb retest short | 4 | -1.024 (-1.03 to -1.02) | 0 |  | experimental |
| vwap reclaim short | 2 | -1.012 (-1.01 to -1.01) | 0 |  | experimental |
| trend pullback long | 5 | +1.382 (+0.16 to +2.01) | 0 |  | experimental |
| trend pullback short | 5 | +1.372 (-0.29 to +2.03) | 4 | +0.466 | experimental |

**ES**

| Setup | OOS trades | OOS avg R (95%) | Holdout trades | Holdout avg R | Status |
|---|---|---|---|---|---|
| sweep reversal long | 24 | -0.066 (-0.55 to +0.47) | 4 | -0.310 | experimental |
| sweep reversal short | 23 | +0.114 (-0.40 to +0.74) | 5 | +0.062 | experimental |
| orb retest long | 5 | +0.013 (-1.08 to +0.84) | 3 | -0.074 | experimental |
| orb retest short | 5 | -0.576 (-1.06 to +0.75) | 1 | -1.050 | experimental |
| vwap reclaim long | 1 | -1.024 | 0 |  | experimental |
| vwap reclaim short | 0 |  | 1 | +0.514 | experimental |
| trend pullback long | 6 | -0.431 (-1.06 to +0.43) | 0 |  | experimental |
| trend pullback short | 4 | +0.237 (-1.03 to +1.51) | 0 |  | experimental |

**MES**

| Setup | OOS trades | OOS avg R (95%) | Holdout trades | Holdout avg R | Status |
|---|---|---|---|---|---|
| sweep reversal long | 27 | -0.049 (-0.52 to +0.49) | 5 | -0.573 | experimental |
| sweep reversal short | 23 | +0.098 (-0.41 to +0.65) | 6 | +0.494 | experimental |
| orb retest long | 5 | -0.193 (-1.13 to +0.75) | 5 | -0.074 | experimental |
| orb retest short | 8 | -0.173 (-0.79 to +0.55) | 1 | -1.076 | experimental |
| vwap reclaim long | 2 | -0.585 (-1.08 to -0.09) | 0 |  | experimental |
| ib breakout long | 0 |  | 1 | -1.058 | experimental |
| ib breakout short | 1 | +1.378 | 0 |  | experimental |
| trend pullback long | 9 | +0.016 (-0.97 to +0.76) | 0 |  | experimental |
| trend pullback short | 6 | -0.254 (-1.07 to +0.59) | 2 | +0.177 | experimental |

## Walk-forward folds

**NQ**: test 2026-09-15 to 2026-09-28 with {'target_r': 3.0, 'max_chase_atr': 0.5} -> 19 trades, +0.232R; test 2026-09-29 to 2026-10-12 with {'target_r': 3.0, 'max_chase_atr': 0.5} -> 17 trades, +0.184R; test 2026-10-13 to 2026-10-26 with {'target_r': 2.0, 'max_chase_atr': 0.3} -> 14 trades, +0.502R
**MNQ**: test 2026-09-15 to 2026-09-28 with {'target_r': 2.0, 'max_chase_atr': 0.3} -> 14 trades, +0.440R; test 2026-09-29 to 2026-10-12 with {'target_r': 2.0, 'max_chase_atr': 0.3} -> 10 trades, +0.876R; test 2026-10-13 to 2026-10-26 with {'target_r': 2.0, 'max_chase_atr': 0.3} -> 18 trades, +0.150R
**ES**: test 2026-09-15 to 2026-09-28 with {'target_r': 2.0, 'max_chase_atr': 0.3} -> 21 trades, +0.063R; test 2026-09-29 to 2026-10-12 with {'target_r': 2.0, 'max_chase_atr': 0.3} -> 20 trades, -0.495R; test 2026-10-13 to 2026-10-26 with {'target_r': 1.5, 'max_chase_atr': 0.5} -> 27 trades, +0.153R
**MES**: test 2026-09-15 to 2026-09-28 with {'target_r': 1.5, 'max_chase_atr': 0.5} -> 27 trades, -0.176R; test 2026-09-29 to 2026-10-12 with {'target_r': 1.5, 'max_chase_atr': 0.5} -> 28 trades, +0.029R; test 2026-10-13 to 2026-10-26 with {'target_r': 1.5, 'max_chase_atr': 0.5} -> 26 trades, +0.052R

## Disclosure

the holdout here is the most recent part of Yahoo's ~59-day window. Those bars were already looked at in aggregate
during 0.6.0 development (overall results only, no tuning), so it is not perfectly pristine. Each run records its date, so data
arriving after that date is genuinely unseen and can be checked with "forward" runs.

Re-run anytime from Futures > Evidence ("Run research") or `python -m research.futures_report` after `walk_forward`. Results for later dates are genuinely unseen.