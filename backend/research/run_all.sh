#!/bin/sh
# Re-runs every walk-forward study used in docs/BACKTEST_RESULTS.md (from backend/).
PY=${PY:-../.venv/bin/python}
$PY -m research.run_walkforward 5Min 58 --fixed  > research/out_5m_fixed.log 2>&1 &
$PY -m research.run_walkforward 15Min 58 --fixed > research/out_15m_fixed.log 2>&1
wait
$PY -m research.run_walkforward 1Hour 720 --fixed > research/out_1h_fixed.log 2>&1 &
$PY -m research.run_walkforward 15Min 58 > research/out_15m.log 2>&1
wait
$PY -m research.run_walkforward 5Min 58 > research/out_5m.log 2>&1 &
$PY -m research.run_walkforward 1Hour 720 > research/out_1h.log 2>&1
wait
echo ALLDONE > research/out_done.log
