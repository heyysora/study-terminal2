# Backtest results (0.5.0)

Run 2026-11-07 on real Yahoo Finance data with the app's own backtester (same setups, fill rules and costs as paper
trading). Reproduce: `backend\research\run_all.sh` (or the `run_walkforward` commands in the README). Raw output:
`backend/research/out/*.json`.

**Bottom line: no setup has a reliable edge.** Every study is either slightly losing or indistinguishable from
zero after costs. The app therefore shows every setup as watch-only, three setup/direction combinations as NO TRADE,
and never shows BUY or SHORT. Nothing below was tuned to make a number look better.

**These supersede the Stage 10 figure** (−0.11R on 274 trades). That run was smaller and came before four backtester
bugs were fixed (audit H6–H8, M12): hourly positions carried past the close, early-close days, same-bar stops filled
at the close, and target exits miscounted.

## Setup

| | |
|---|---|
| Universe | SPY QQQ IWM AAPL MSFT NVDA AMD TSLA META AMZN GOOGL NFLX AVGO JPM XOM BA COIN PLTR MU UBER (today's large caps: **survivorship bias**) |
| Data | 5- and 15-minute: last 58 calendar days (Yahoo's limit). 1-hour: last 720 days |
| Rules | 10 setups, long and short, risk 0.5% per trade, max 3 trades/symbol/day, flat at the close |
| Costs | Slippage max(1 bp, 1¢) per fill, stops gap-filled at the worse price, no commission |
| Walk-forward | Train 20 sessions → test the next 5 (1-hour: 60 → 20). Only test windows are reported |
| Two variants | **Fixed**: the default rules, no fitting at all. **Optimized**: each fold picks the best of 12 parameter sets (target 1.5/2/3R × stop buffer × RVOL floor) on its training window |
| Uncertainty | 95% intervals by day-clustered bootstrap (trades on the same day move together); Wilson intervals for win rate |

## Results (out-of-sample only)

| Study | Trades | Test days | Win % | Avg R after costs | 95% interval | Avg R before costs | Cost/trade | Profit factor | Positive test windows | Evidence tier |
|---|---|---|---|---|---|---|---|---|---|---|
| 5-min, fixed | 843 | 21 | 38.1 | **−0.027** | −0.117 to +0.074 | +0.042 | 0.069R | 1.00 | 2/5 | losing |
| 5-min, optimized | 792 | 21 | 37.6 | **−0.062** | −0.182 to +0.066 | +0.000 | 0.062R | 0.94 | 2/5 | losing |
| 15-min, fixed | 446 | 21 | 44.4 | **+0.001** | −0.138 to +0.154 | +0.037 | 0.036R | 1.02 | 3/5 | inconclusive |
| 15-min, optimized | 431 | 21 | 46.4 | **+0.016** | −0.103 to +0.151 | +0.050 | 0.034R | 1.04 | 4/5 | inconclusive |
| 1-hour, fixed | 2,796 | 427 | 46.6 | **−0.027** | −0.065 to +0.015 | −0.008 | 0.019R | 0.89 | 7/22 | losing |
| 1-hour, optimized | 2,794 | 426 | 47.2 | **−0.019** | −0.053 to +0.019 | −0.001 | 0.017R | 0.92 | 8/22 | losing |

(1R = the amount risked on a trade. Max drawdown is in the JSON files but isn't comparable here: 20 symbols trade in
parallel against one $25k base, which overstates it.)

How to read it:
- The **1-hour study is the strongest evidence**: almost 2,800 trades over 21 months, and the whole 95% interval sits
  between −0.065R and +0.019R. If there were an edge worth trading it would show up there. It doesn't.
- The 5- and 15-minute studies cover **one 21-day market period** (Oct 9 – Nov 6, 2026). Their intervals are wide
  (±0.1–0.15R), so a modest edge or a modest loss would both fit.
- **Optimization didn't help.** On 5-minute bars it made results worse (−0.062 vs −0.027R), and the chosen parameters
  changed from fold to fold. That's what fitting to noise looks like.
- **Costs matter on fast timeframes**: about 0.07R per trade on 5-minute bars (tight stops make a cent of slippage
  large in R). Before costs the 5-minute setups were roughly break-even, so costs alone make them losing.

## Why they lose: diagnostics (5-minute fixed unless noted)

| Question | What the data shows |
|---|---|
| Win rate vs what's needed | 38.1% won; 39.1% needed to break even with the actual average winner (+1.61R) and loser (−1.03R). Close to break-even before costs, losing after. |
| Do targets get reached? | 44% of trades ever reached +1R, 24% reached +2R, under 1% reached +3R. The 2R target is reachable but rarely. |
| False breakouts | 35% of stopped trades were stopped within 2 bars of entry (15-minute: 39%; 1-hour: 73%). |
| Exits and giving back | 17% of losers had been up +1R first. Moving the stop to breakeven at +1R would affect a minority; not the main problem. |
| Stop placement | 16% of stopped trades later hit the original target the same day; 40% of those never went more than 1.5R against the entry. A wider stop might hold some, but means smaller size. Untested. |
| Long vs short | Longs: −0.224R, interval −0.36 to −0.10 (**clearly losing**, all three intraday studies). Shorts: +0.166R, interval −0.09 to +0.41 (inconclusive). Over 21 months on hourly bars, both lose (−0.040R / −0.013R): the short advantage looks specific to this autumn's market. |
| With vs against trend | Against the trend −0.11R; with the trend +0.03R (both inconclusive on 5-minute). On hourly: no clear trend −0.17R (clearly losing), with trend +0.008R. Trading against or without a trend is the most consistent weakness. |
| Time of day | Nothing clear on 5- or 15-minute. 15-minute midday was the weakest (−0.19R, small sample). |
| Volatility / chop | No clear difference. Normal-volatility hours lost slightly on 1-hour (−0.039R, interval just below zero). |
| Volume confirmation | "Volume confirmed" entries did slightly better everywhere (+0.03 to +0.19R) but never clearly. |
| Late / extended entries | No consistent penalty for entries far from the 9 EMA. Entries one bar after the signal are the norm (median 1 bar). |
| Checklist score | Score < 50 was the worst bucket in every study (hourly −0.057R, clearly losing); ≥ 70 never clearly positive. The checklist separates bad from mediocre, not good from bad. |
| Streaks | Results after 3+ losses were worse and after 2–3+ wins better (hourly "after 3+ wins" +0.19R). That reflects trades clustering in good and bad market stretches, not a usable rule. |
| Hourly specifics | 83% of hourly trades end at the close (avg winner only +0.52R): an hourly setup triggers with only a few bars left in the session, so a 2R target rarely has time. These intraday setups don't suit hourly bars. |

## Every strategy, including the unsuccessful ones

Average R after costs (out-of-sample trades in brackets). **Bold** = the 95% interval is entirely below zero.

| Setup | Dir. | 5-min fixed | 5-min optimized | 15-min fixed | 1-hour fixed |
|---|---|---|---|---|---|
| Failed breakdown (reclaim of support) | long | −0.206 (143) | −0.270 (134) | −0.146 (82) | −0.036 (533) |
| Trend pullback | short | +0.277 (108) | +0.233 (111) | +0.342 (29) | +0.044 (264) |
| Failed breakout (rejection of resistance) | short | +0.182 (106) | +0.120 (98) | −0.056 (63) | −0.014 (412) |
| Trend pullback | long | −0.168 (104) | +0.086 (96) | −0.185 (32) | −0.030 (299) |
| VWAP rejection | short | −0.029 (86) | −0.299 (67) | +0.146 (47) | +0.007 (220) |
| Level breakout | long | **−0.306 (86)** | **−0.407 (71)** | −0.040 (17) | −0.058 (50) |
| Level breakdown | short | −0.044 (83) | −0.024 (87) | +0.342 (26) | −0.110 (71) |
| Opening-range breakdown | short | +0.630 (44) | +0.605 (42) | +0.338 (60) | −0.044 (375) |
| VWAP reclaim | long | −0.209 (44) | **−0.582 (47)** | −0.340 (36) | −0.049 (275) |
| Opening-range breakout | long | −0.281 (39) | −0.158 (39) | **−0.209 (54)** | −0.044 (297) |

- **Clearly losing** somewhere: level breakout long, VWAP reclaim long, opening-range breakout long. Live signals for
  setups calibrated as clearly losing return NO TRADE ("study only").
- **Looked best**: opening-range breakdown short and trend pullback short on 5- and 15-minute bars. But they come from one
  21-day window, the intervals include zero, and over 21 months of hourly data both are flat (−0.044R / +0.044R).
  **Not an edge**: a hypothesis to re-test on new data in a month.
- No setup reached "promising", let alone "reliable".

## What would be needed to find out more (not done here)
- More history for 5/15-minute bars (a paid data provider; see `docs/DATA_PROVIDERS.md`) so studies span several market
  regimes instead of one month.
- Re-running walk-forward every few weeks as new data arrives: the evidence tiers update automatically when you do.
- Testing specific ideas suggested by the diagnostics (shorts only, with-trend only, wider stops), **each on data
  collected after today**, since choosing them from these results and re-testing on the same trades would be curve-fitting.

## ML model (win/loss classifier on these trades)

| Trades from | Test trades | Brier skill vs base rate | 95% interval (day-clustered) | AUC | Deployed |
|---|---|---|---|---|---|
| 5-min fixed | 253 | +0.003 | −0.062 to +0.055 | 0.58 | No |
| 15-min fixed | 134 (8 trading days) | +0.026 | −0.064 to +0.150 | 0.57 | No |
| 1-hour fixed | 839 | −0.016 | −0.032 to +0.002 | 0.50 | No |

Two things happened here that you should know about:
1. The model training **picked the best of three model types by their test-set score** and then judged them on that
   same test set, which flatters the result. Fixed: the type is now chosen on a validation slice at the end of the
   training period, and the test period is scored once (audit M14).
2. Even after that fix, the 15-minute model **passed the old gate** (skill > 0.02, AUC > 0.55, 40+ test trades)
   narrowly, on 134 trades from 8 trading days in which the win rate jumped from 42% to 51%. That gate had no
   uncertainty check, unlike everything else in this release, so **after seeing this result** I added one: the 95%
   interval of the skill must be above zero. With that rule nothing deploys. I'm telling you the rule came after the
   result so you can judge it; the old numbers are in the table above either way.

So no model probability is shown on signals. The ML page retrains on whatever walk-forward trades you've generated and
applies the same gate.
