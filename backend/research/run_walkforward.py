"""Reproducible real-data walk-forward study. Usage (from backend/):
    python -m research.run_walkforward 5Min 58 [--fixed]
Writes research/out/wf_<tf>_<days>[_fixed].json. Uses the app's own BacktestService (same data path,
validation, fills and costs as the Backtest page), with a throwaway database.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

from app.backtest.service import BacktestService
from app.core.market_clock import MarketClock
from app.db.session import Database
from app.market_data.providers.yahoo import YahooProvider

UNIVERSE = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMD", "TSLA", "META", "AMZN",
            "GOOGL", "NFLX", "AVGO", "JPM", "XOM", "BA", "COIN", "PLTR", "MU", "UBER"]


async def main():
    tf, days = sys.argv[1], int(sys.argv[2])
    fixed = "--fixed" in sys.argv
    out = Path(__file__).parent / "out"
    out.mkdir(exist_ok=True)
    db = Database(f"sqlite:///{out}/research_{tf}{'_fixed' if fixed else ''}.db")
    db.create_all()
    svc = BacktestService(db, YahooProvider(), MarketClock())
    train, test = {"5Min": (20, 5), "15Min": (20, 5), "1Hour": (60, 20)}[tf]
    req = {"mode": "walk_forward", "symbols": UNIVERSE, "timeframe": tf, "days": days,
           "train_sessions": train, "test_sessions": test}
    if fixed:
        req["grid"] = {"target_r": [2.0]}   # no optimization: default rules only
    t0 = time.time()
    res = await svc.execute(req)
    res["runtime_seconds"] = round(time.time() - t0, 1)
    name = f"wf_{tf}_{days}{'_fixed' if fixed else ''}.json"
    (out / name).write_text(json.dumps(res, default=str))
    ev = res["evidence"]
    print(name, res["runtime_seconds"], "s |", ev)


asyncio.run(main())
