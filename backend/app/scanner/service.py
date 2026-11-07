"""Market scanner: finds candidates without you naming tickers, then ranks them.

Pipeline (rate-limit aware):
  1. Universe   = your watchlists + the provider's market-wide lists (Yahoo: day gainers/losers,
                  most active, small-cap gainers)
  2. Pre-filter = price, % change, average volume, dollar liquidity, market cap (from list data, no extra calls)
  3. Deep scan  = the top candidates get bars + full analysis + signal evaluation
  4. Rank       = transparent score (components shown); symbols with no active setup rank low
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from ..analysis.service import AnalysisService
from ..market_data.providers.base import ProviderError
from ..market_data.types import Timeframe

log = logging.getLogger(__name__)


class ScanFilters(BaseModel):
    sources: list[str] = ["watchlist", "day_gainers", "day_losers", "most_actives", "small_cap_gainers"]
    min_price: float = 2.0
    max_price: float = 1500.0
    min_change_pct: float | None = None       # e.g. 3 = only stocks up 3%+ ; use abs_change_min for either way
    abs_change_min: float | None = None
    min_avg_volume: float = 500_000
    min_dollar_volume: float = 5_000_000      # liquidity: price x average volume
    min_market_cap: float | None = 300_000_000
    max_market_cap: float | None = None
    min_rvol: float = 0.0
    min_atr_pct: float | None = None          # volatility floor (ATR as % of price)
    max_atr_pct: float | None = None
    premarket_active: bool = False            # require a premarket move (|premarket change| >= 2%)
    min_setup_quality: int = 0
    timeframe: Timeframe = Timeframe.M5
    deep_scan_limit: int = 15


def rank(item: dict) -> tuple[float, dict]:
    best = item.get("best_signal")
    q = best["confidence"]["setup_quality"]["score"] if best else 0
    rv = item.get("rvol") or 0
    chg = abs(item.get("change_pct") or 0)
    bias = abs(item.get("bias_score") or 0)
    dv = item.get("dollar_volume") or 0
    comp = {
        "setup_quality": round(40 * q / 100, 1),
        "relative_volume": round(20 * min(rv / 3, 1), 1),
        "move_size": round(15 * min(chg / 10, 1), 1),
        "trend_clarity": round(15 * bias / 100, 1),
        "liquidity": round(10 * min(max(math.log10(dv + 1) - 6, 0) / 3, 1), 1),
    }
    score = sum(comp.values())
    if not best:
        score *= 0.5
        comp["no_active_setup_penalty"] = "x0.5"
    hist = best["confidence"]["historical"] if best else None
    if hist and hist.get("available") and hist.get("expectancy_r", 0) < 0:
        score *= 0.6
        comp["negative_history_penalty"] = "x0.6"
    return round(score, 1), comp


class ScannerService:
    def __init__(self, monitor, analysis: AnalysisService, signals, interval_s: float = 180.0):
        self.monitor, self.analysis, self.signals = monitor, analysis, signals
        self.filters = ScanFilters()
        self.interval_s = interval_s
        self.results: list[dict] = []
        self.rejected: list[dict] = []
        self.last_run: datetime | None = None
        self.running = False
        self.enabled = True
        self.errors: list[str] = []
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        await asyncio.sleep(20)  # let monitoring settle first
        while True:
            sess = self.monitor.clock.session_at().session.value
            if self.enabled and sess in ("premarket", "regular"):
                try:
                    await self.run_once()
                except Exception:
                    log.exception("scan failed")
            await asyncio.sleep(self.interval_s)

    async def universe(self, f: ScanFilters) -> list[dict]:
        rows: dict[str, dict] = {}
        self.errors = []
        for src in f.sources:
            if src == "watchlist":
                for s in self.monitor.watchlist_symbols():
                    rows.setdefault(s, {"symbol": s, "source": "watchlist"})
                continue
            try:
                for r in await self.monitor.provider.get_movers(src, 25):
                    rows.setdefault(r["symbol"], r)
            except ProviderError as e:
                self.errors.append(f"{src}: {e}")
        return list(rows.values())

    def prefilter(self, rows: list[dict], f: ScanFilters) -> tuple[list[dict], list[dict]]:
        keep, rej = [], []
        for r in rows:
            if r.get("source") == "watchlist" and r.get("price") is None:
                keep.append(r)  # no list data yet; judged after the deep scan
                continue
            price, chg = r.get("price") or 0, r.get("change_pct")
            avgv = r.get("avg_volume") or 0
            mc = r.get("market_cap")
            r["dollar_volume"] = price * avgv
            why = None
            if not (f.min_price <= price <= f.max_price):
                why = f"price ${price:,.2f} outside ${f.min_price}-${f.max_price}"
            elif f.min_change_pct is not None and (chg is None or chg < f.min_change_pct):
                why = f"change {chg}% < {f.min_change_pct}%"
            elif f.abs_change_min is not None and (chg is None or abs(chg) < f.abs_change_min):
                why = f"|change| < {f.abs_change_min}%"
            elif avgv < f.min_avg_volume:
                why = f"avg volume {avgv:,.0f} < {f.min_avg_volume:,.0f}"
            elif r["dollar_volume"] < f.min_dollar_volume:
                why = f"dollar volume ${r['dollar_volume']:,.0f} too thin"
            elif f.min_market_cap and (mc or 0) < f.min_market_cap:
                why = f"market cap below ${f.min_market_cap:,.0f}"
            elif f.max_market_cap and mc and mc > f.max_market_cap:
                why = "market cap above max"
            elif f.premarket_active and abs(r.get("premarket_change_pct") or 0) < 2:
                why = "no premarket move >= 2%"
            (rej if why else keep).append({**r, "rejected_because": why} if why else r)
        keep.sort(key=lambda r: (r.get("source") != "watchlist", -abs(r.get("change_pct") or 0) * math.log10((r.get("volume") or 0) + 10)))
        return keep, rej

    async def run_once(self, filters: ScanFilters | None = None) -> dict:
        if self.running:
            return self.snapshot()
        self.running = True
        f = filters or self.filters
        try:
            uni = await self.universe(f)
            keep, rej = self.prefilter(uni, f)
            deep, results = keep[: f.deep_scan_limit], []
            for r in deep:
                sym = r["symbol"]
                try:
                    ev, snap, ff = await self.signals.evaluate_symbol(sym, f.timeframe)
                except ProviderError as e:
                    rej.append({**r, "rejected_because": f"no bars ({e})"})
                    continue
                if not snap.get("available"):
                    rej.append({**r, "rejected_because": "not enough history"})
                    continue
                row = ff.df.iloc[-1]
                if not r.get("dollar_volume"):  # watchlist symbols have no list data: estimate liquidity from bars
                    daily_vol = ff.df.groupby("session")["volume"].sum()
                    r = {**r, "avg_volume": float(daily_vol.iloc[:-1].mean()) if len(daily_vol) > 1 else float(daily_vol.mean()),
                         "volume_source": "estimated from intraday bars (partial-source volume)"}
                    r["dollar_volume"] = r["avg_volume"] * float(row["close"])
                item: dict[str, Any] = {
                    **r, "price": r.get("price") or snap["price"], "rvol": snap["volume"]["rvol"], "atr_pct": snap["volatility"]["atr_pct"],
                    "bias": snap["bias"]["label"], "bias_score": snap["bias"]["score"], "structure": snap["structure"]["state"],
                    "action": ev["action"], "best_signal": ev.get("best"), "signals": ev["signals"],
                    "label": self.monitor.label(sym).model_dump(mode="json") if sym in self.monitor.monitored_symbols() else None,
                    "change_pct": r.get("change_pct") if r.get("change_pct") is not None else
                    (round(100 * (row["close"] / row["pdc"] - 1), 2) if row["pdc"] == row["pdc"] else None),
                }
                why = None
                if (item["rvol"] or 0) < f.min_rvol:
                    why = f"RVOL {item['rvol']} < {f.min_rvol}"
                elif f.min_atr_pct and (item["atr_pct"] or 0) < f.min_atr_pct:
                    why = "too quiet (ATR%)"
                elif f.max_atr_pct and (item["atr_pct"] or 0) > f.max_atr_pct:
                    why = "too volatile (ATR%)"
                elif f.min_setup_quality and (not item["best_signal"] or item["best_signal"]["confidence"]["setup_quality"]["score"] < f.min_setup_quality):
                    why = "no setup above the quality floor"
                if why:
                    rej.append({**item, "signals": None, "rejected_because": why})
                    continue
                item["rank_score"], item["rank_components"] = rank(item)
                results.append(item)
            results.sort(key=lambda x: -x["rank_score"])
            self.results, self.rejected = results, rej
            self.last_run = datetime.now(timezone.utc)
            self.monitor.broadcaster.publish({"type": "scanner", "data": self.snapshot(brief=True)})
            return self.snapshot()
        finally:
            self.running = False

    def snapshot(self, brief: bool = False) -> dict:
        res = self.results
        if brief:
            res = [{k: v for k, v in r.items() if k not in ("signals",)} for r in res]
        return {"last_run": self.last_run.isoformat() if self.last_run else None, "running": self.running,
                "filters": self.filters.model_dump(mode="json"), "results": res, "rejected": self.rejected[:100],
                "errors": self.errors, "interval_seconds": self.interval_s,
                "note": "Universe from your watchlists and Yahoo's market-wide lists (polled snapshots, not a live feed). "
                        "Ranking weights are judgment, shown so you can see why a symbol ranks where it does."}
