"""Memecoins: watch, check, practise. Read-only data; pretend money. See sources.py, checks.py and practice.py."""
from __future__ import annotations

import asyncio
import logging
import re
import time

from .checks import checks
from .practice import MemePractice
from .sources import MemeData, SourceError

log = logging.getLogger(__name__)


# Token names are chosen by anonymous creators. Names with slurs are hidden from lists and masked when opened directly.
# Matching ignores case, spaces and common letter swaps (0->o, 1/!->i, 3->e, 4/@->a, $->s).
_SWAP = str.maketrans({"0": "o", "1": "i", "!": "i", "3": "e", "4": "a", "@": "a", "$": "s", "5": "s", "7": "t"})
_LONG = re.compile(r"n+i+g{2,}(?:e+r|a+|u+h|l+e+t)|f+a+g{2,}o+t|w+e+t+b+a+c+k|r+a+g+h+e+a+d|t+o+w+e+l+h+e+a+d|"
                   r"b+e+a+n+e+r|t+r+a+n{2,}(?:y|i+e)|r+e+t+a+r+d")          # distinctive enough to match inside other letters
_SHORT = re.compile(r"(?:f+a+g+s?|k+i+k+e+s?|c+h+i+n+k+s?|s+p+i+c+k?s?|g+o+o+k+s?|c+o+o+n+s?|k+y+k+e+s?|d+y+k+e+s?)")   # whole words only


def offensive(*texts: str | None) -> bool:
    raw = " ".join((x or "") for x in texts).lower().translate(_SWAP)
    words = [re.sub(r"[^a-z]", "", w) for w in re.split(r"[\s_\-./]+", raw)]
    if any(_SHORT.fullmatch(w) for w in words if w):
        return True
    return bool(_LONG.search(re.sub(r"[^a-z]", "", raw)))          # also catches spaced-out spellings


def stage(p: dict | None) -> dict | None:
    """Where a pump.fun token is in its life, from the exchange DexScreener lists it on."""
    dex = (p or {}).get("dexId")
    if dex == "pumpfun":
        return {"key": "curve", "label": "On pump.fun's starting curve",
                "text": "Still on pump.fun's starting price curve. It hasn't moved to a normal trading pool yet, and most tokens never do."}
    if dex == "pumpswap":
        return {"key": "graduated", "label": "Graduated to PumpSwap",
                "text": "Filled pump.fun's starting curve and moved to a PumpSwap trading pool. That says people bought it, not that it's safe."}
    return None


def row(p: dict, now_ms: float | None = None) -> dict:
    """One line for a list: what a beginner needs to see first."""
    now_ms = now_ms or time.time() * 1000
    liq = (p.get("liquidity") or {}).get("usd")
    created = p.get("pairCreatedAt")
    hours = (now_ms - created) / 3_600_000 if created else None
    flags = []
    if liq is None:
        flags.append("pool size unknown")
    elif liq < 10_000:
        flags.append("tiny pool")
    if hours is not None and hours < 1:
        flags.append("under 1 hour old")
    tx = (p.get("txns") or {}).get("h1") or {}
    bt = p.get("baseToken") or {}
    bad = offensive(bt.get("name"), bt.get("symbol"))
    return {"token": bt.get("address"), "symbol": "(hidden)" if bad else bt.get("symbol"),
            "name": "Name hidden: offensive" if bad else bt.get("name"), "hidden": bad, "price_usd": float(p["priceUsd"]) if p.get("priceUsd") else None,
            "change": p.get("priceChange") or {}, "liquidity_usd": liq, "volume_h1": (p.get("volume") or {}).get("h1"),
            "market_cap": p.get("marketCap") or p.get("fdv"), "age_hours": round(hours, 1) if hours is not None else None,
            "buys_h1": tx.get("buys"), "sells_h1": tx.get("sells"), "dex": p.get("dexId"), "url": p.get("url"), "flags": flags,
            "stage": stage(p), "links": len(((p.get("info") or {}).get("websites") or [])) + len(((p.get("info") or {}).get("socials") or []))}


class MemeService:
    def __init__(self, db, alerts=None, rpc_url: str | None = None):
        self.data = MemeData(rpc_url)
        self.practice = MemePractice(db)
        self.alerts = alerts
        self._task: asyncio.Task | None = None

    def set_rpc(self, url: str | None):
        self.data.rpc_url = (url or "").strip() or "https://api.mainnet-beta.solana.com"

    async def feed(self, kind: str = "profiles") -> dict:
        items = await (self.data.promoted_boosts() if kind == "boosts" else self.data.promoted_profiles())
        pairs = await self.data.pairs_for([x.get("tokenAddress") for x in items][:60])
        rows = [r for r in (row(pairs[a]) for a in dict.fromkeys(x.get("tokenAddress") for x in items) if a in pairs) if not r["hidden"]]
        return {"kind": kind, "rows": rows,
                "label": ("Tokens whose creators paid DexScreener for a boost (advertising, not a sign of quality)." if kind == "boosts"
                          else "Newest tokens with a DexScreener profile (projects pay for profiles; not a recommendation)."),
                "source": "DexScreener (free, unofficial for this app; can lag or change)"}

    async def search(self, q: str) -> list[dict]:
        pairs = await self.data.search(q)
        best: dict[str, dict] = {}
        for p in pairs:
            a = (p.get("baseToken") or {}).get("address")
            if a and (a not in best or (p.get("liquidity") or {}).get("usd", 0) > (best[a].get("liquidity") or {}).get("usd", 0)):
                best[a] = p
        return [r for r in (row(p) for p in best.values()) if not r["hidden"]][:20]

    async def token(self, address: str) -> dict:
        pairs = await self.data.pairs_for([address], ttl=10)
        pair = pairs.get(address)
        mint, mint_err, holders, hold_err, supply = None, None, None, None, None
        try:
            mint = await self.data.mint_info(address)
            if mint.get("supply_raw") and mint.get("decimals") is not None:
                supply = int(mint["supply_raw"]) / 10 ** mint["decimals"]
        except SourceError as e:
            mint_err = str(e)
        if mint:
            try:
                holders = await self.data.largest_holders(address)
            except SourceError as e:
                hold_err = str(e)
        return {"address": address, "pair": row(pair) if pair else None, "raw_pair": pair,
                "checks": checks(pair, mint, holders, supply, mint_err, hold_err), "mint": mint,
                "not_listed": pair is None,
                "real_trading": "Study Terminal only practises. Real memecoin trading is done outside it (see the guide on this page)."}

    async def pairs_for_positions(self) -> dict[str, dict]:
        toks = [p["token"] for p in self.practice.positions()]
        return await self.data.pairs_for(toks, ttl=10) if toks else {}

    async def tick(self) -> list[dict]:
        if not self.practice.positions():
            return []
        try:
            pairs = await self.pairs_for_positions()
        except SourceError:
            return []
        done = self.practice.check_exits(pairs)
        for d in done:
            if self.alerts and d.get("ok"):
                word = d["reason"]
                kept = f" Kept {d['kept_fraction'] * 100:g}% with the stop moved up to your buy price." if d.get("kept_fraction") else ""
                self.alerts.emit("position", "high" if "stop" in word else "medium", f"Memecoin practice {word} hit - {d['symbol']}",
                                 f"Sold in practice for ${d['received_usd']:,.2f} ({'+' if d['pnl_usd'] >= 0 else ''}${d['pnl_usd']:,.2f}). "
                                 f"Price impact about {d['impact_pct']}%.{kept}", key=f"meme|{d['symbol']}|{word}")
        return done

    async def start(self):
        async def loop():
            while True:
                try:
                    await self.tick()
                except Exception:  # noqa: BLE001 - the watcher must not take the app down
                    log.exception("memecoin practice check failed")
                await asyncio.sleep(20)
        self._task = asyncio.create_task(loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
        await self.data.aclose()
