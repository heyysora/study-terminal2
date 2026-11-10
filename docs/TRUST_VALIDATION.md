# Trust & Validation dashboard (0.11.0)

Menu > **Trust & Validation**. It answers one question: does the recorded evidence justify more serious use of Study Terminal?
Every status is computed from what actually happened on your PC. **Unit tests never count**, synthetic screenshots never count, and
nothing on this page can enable live trading.

## The nine categories

Status: **UNTESTED** (no evidence) · **IN PROGRESS** (some, not enough) · **PASSED** (meets every threshold) · **FAILED** (enough evidence
and it misses the bar, or a hard rule was broken). Each card shows the number of observations, metrics, last validation date, the
evidence, known limitations and what remains.

| # | Category | Evidence that counts | PASSED when |
|---|---|---|---|
| 1 | Visual capture accuracy | real screenshots scored with a Live Visual Monitor profile (price-axis check) + real monitoring captures | axis correct with a 95% lower bound ≥ 90% on ≥ 20 samples, and ≥ 1,000 captures on ≥ 3 days with ≥ 90% readable while the window was present |
| 2 | OCR and price recognition | real screenshots: the price you typed vs the price read | 95% lower bound ≥ 90% on ≥ 20 samples |
| 3 | Instrument and timeframe recognition | real screenshots: contract and timeframe | both ≥ 90% lower bound on ≥ 20 samples each |
| 4 | Candle and indicator recognition | real screenshots: last completed candle O/H/L/C and VWAP/EMA values you typed | both ≥ 80% lower bound on ≥ 20 samples each |
| 5 | Signal generation | stored decisions on live data (TopstepX stream, TopstepX polling or live visual observation) | ≥ 200 decisions over ≥ 10 trading days, every one with all 13 steps, no approval on non-live data or with a failed step |
| 6 | Historical strategy performance | walk-forward research on market data (out of sample) | at least one product in the "reliable" tier with average R > 0 |
| 7 | Walk-forward validation | the strategy registry and final holdout | at least one validated strategy (reliable OOS + holdout of 30+ trades, avg R > 0, PF > 1.1) |
| 8 | Paper trading performance | completed practice-account trades **entered on live data** (not delayed practice, replay, sandbox) | ≥ 50 trades over ≥ 20 trading days with the 95% interval of average R above zero |
| 9 | Risk-management reliability | audit of those completed trades against your limits, plus confirmed prop rules | ≥ 50 trades over ≥ 10 days, zero violations (no stop, size above the limit, loss > 1.25x the per-trade limit, entering after the daily loss limit), rules confirmed |

Accuracy uses the **lower end of the 95% confidence range**, so a small perfect sample isn't enough: about 35 correct out of 35 are
needed to show 90%. FAILED on accuracy means even the upper end of the range is below the bar.

## Readiness levels

Each level needs everything below it, in order:

1. **EXPERIMENTAL**: the starting point.
2. **VISUAL VALIDATION**: categories 1-4 PASSED.
3. **STRATEGY VALIDATION**: plus 5-7 PASSED.
4. **PAPER TRADING VALIDATION**: plus 8-9 PASSED.
5. **LIVE ELIGIBILITY REVIEW**: plus a longer paper record (≥ 100 completed live-data trades over ≥ 40 trading days).

The page lists exactly what's still unverified before the next level. **Live brokerage execution stays disabled at every level.** The
review level only means the record is complete enough for you to review; enabling live trading would still need your explicit written
authorization and an independently verified integration, and Study Terminal contains no order-execution code.

## How to collect the evidence

- **Categories 1-4:** Live copilot > Calibrate screen reading. Upload a real screenshot of your TopstepX chart, choose your Live Visual
  Monitor profile, type the contract, timeframe, price, the last completed candle's O/H/L/C, and VWAP/EMA values. Leave "generated test
  chart" unticked. Capture statistics are recorded automatically while monitoring runs.
- **Category 5:** run monitoring (Automation Center or Live Visual Monitor) during market hours on live data.
- **Categories 6-7:** Futures > Evidence > Run research.
- **Categories 8-9:** take simulated trades on live data in the practice account and confirm your rules (Futures > Rules).

## Where the evidence lives
Calibration samples: `<data dir>\calibration\results.jsonl`. Capture statistics: `<data dir>\visual_capture_stats.json` (only real screen
captures; test or injected sources are never recorded). Decisions, fills and research: the app database. The dashboard API
(`GET /api/trust`) is read-only.

## Tests
`backend/tests/test_trust.py` (9) checks the rules with hand-built records: synthetic and non-visual samples excluded, lower-bound
thresholds, every part of a category required, delayed/replay/sandbox trades excluded, decision-integrity violations, risk-audit
violations, sequential levels, live execution reported disabled, and that synthetic uploads through the API don't move any status.
These tests check the rules; they aren't evidence and don't change readiness.
