"""Free, read-only memecoin data. No wallet, no keys, nothing that can trade.

- DexScreener public API (no key): prices, liquidity, volume, buys/sells, price change, pair age; and its lists of tokens with a
  paid profile or paid "boost". Those lists are PROMOTED, not trending, and are labelled that way.
- Solana JSON-RPC (the free public endpoint by default, or your own free RPC address in Settings): the token's mint record
  (who can create more tokens or freeze wallets, special Token-2022 rules) and, where the RPC allows it, the largest holders.
  The public endpoint often refuses the largest-holders call; the app says so instead of guessing.

Endpoints were checked by calling them (2026-11-14). DexScreener and the public Solana RPC can change or rate-limit at any time.
"""
from __future__ import annotations

import asyncio
import time

import httpx

DEX = "https://api.dexscreener.com"
PUBLIC_RPC = "https://api.mainnet-beta.solana.com"
UA = {"User-Agent": "StudyTerminal/practice (read-only)"}


class SourceError(Exception):
    pass


class _Cache:
    def __init__(self):
        self.d: dict[str, tuple[float, object]] = {}

    def get(self, k: str, ttl: float):
        v = self.d.get(k)
        return v[1] if v and time.monotonic() - v[0] < ttl else None

    def put(self, k: str, v):
        self.d[k] = (time.monotonic(), v)
        if len(self.d) > 500:
            for key in sorted(self.d, key=lambda x: self.d[x][0])[:100]:
                self.d.pop(key, None)
        return v


class MemeData:
    def __init__(self, rpc_url: str | None = None, client: httpx.AsyncClient | None = None):
        self.rpc_url = rpc_url or PUBLIC_RPC
        self._client = client
        self.cache = _Cache()
        self._lock = asyncio.Lock()

    async def _c(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(headers=UA, timeout=15)
        return self._client

    async def aclose(self):
        if self._client is not None:
            await self._client.aclose()

    async def _get(self, path: str, ttl: float):
        hit = self.cache.get(path, ttl)
        if hit is not None:
            return hit
        try:
            r = await (await self._c()).get(DEX + path)
        except httpx.HTTPError as e:
            raise SourceError(f"DexScreener didn't answer ({type(e).__name__}).") from None
        if r.status_code == 429:
            raise SourceError("DexScreener says too many requests; try again in a minute.")
        if r.status_code >= 400:
            raise SourceError(f"DexScreener error {r.status_code}.")
        return self.cache.put(path, r.json())

    # ---------------- DexScreener ----------------
    async def promoted_profiles(self) -> list[dict]:
        return [x for x in (await self._get("/token-profiles/latest/v1", 60) or []) if x.get("chainId") == "solana"]

    async def promoted_boosts(self) -> list[dict]:
        return [x for x in (await self._get("/token-boosts/top/v1", 60) or []) if x.get("chainId") == "solana"]

    async def pairs_for(self, addresses: list[str], ttl: float = 15) -> dict[str, dict]:
        """Best (most liquid) Solana pair per token address, up to 30 addresses per request."""
        out: dict[str, dict] = {}
        addrs = list(dict.fromkeys(a for a in addresses if a))
        for i in range(0, len(addrs), 30):
            chunk = addrs[i:i + 30]
            pairs = await self._get("/tokens/v1/solana/" + ",".join(chunk), ttl) or []
            for p in pairs:
                a = (p.get("baseToken") or {}).get("address")
                if a and (a not in out or (p.get("liquidity") or {}).get("usd", 0) > (out[a].get("liquidity") or {}).get("usd", 0)):
                    out[a] = p
        return out

    async def search(self, q: str) -> list[dict]:
        from urllib.parse import quote
        d = await self._get("/latest/dex/search?q=" + quote(q.strip()[:60]), 30) or {}
        return [p for p in (d.get("pairs") or []) if p.get("chainId") == "solana"]

    # ---------------- Solana RPC ----------------
    async def _rpc(self, method: str, params: list, ttl: float):
        key = f"rpc|{method}|{params!r}"
        hit = self.cache.get(key, ttl)
        if hit is not None:
            return hit
        try:
            r = await (await self._c()).post(self.rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            d = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise SourceError(f"The Solana RPC didn't answer ({type(e).__name__}).") from None
        if d.get("error"):
            err = d["error"]
            raise SourceError("The Solana RPC refused this (too many requests). A free RPC address of your own in Settings fixes it."
                              if err.get("code") == 429 or "Too many" in str(err.get("message")) else f"Solana RPC error: {err.get('message')}")
        return self.cache.put(key, d.get("result"))

    async def mint_info(self, mint: str) -> dict:
        res = await self._rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}], 300)
        v = (res or {}).get("value")
        if not v:
            raise SourceError("That address isn't a token on Solana.")
        parsed = (v.get("data") or {}).get("parsed") or {}
        if parsed.get("type") != "mint":
            raise SourceError("That address isn't a token mint.")
        info = parsed.get("info") or {}
        return {"program": "token-2022" if v.get("owner", "").startswith("Tokenz") else "spl-token",
                "mint_authority": info.get("mintAuthority"), "freeze_authority": info.get("freezeAuthority"),
                "decimals": info.get("decimals"), "supply_raw": info.get("supply"),
                "extensions": {e.get("extension"): e.get("state") for e in info.get("extensions") or []}}

    async def largest_holders(self, mint: str) -> list[dict]:
        """Largest token accounts with their owners (needs an RPC that allows it)."""
        res = await self._rpc("getTokenLargestAccounts", [mint], 300)
        accts = (res or {}).get("value") or []
        if not accts:
            return []
        owners = await self._rpc("getMultipleAccounts", [[a["address"] for a in accts], {"encoding": "jsonParsed"}], 300)
        out = []
        for a, o in zip(accts, (owners or {}).get("value") or [], strict=False):
            owner = ((((o or {}).get("data") or {}).get("parsed") or {}).get("info") or {}).get("owner")
            out.append({"account": a["address"], "owner": owner, "amount_raw": a.get("amount"), "ui": a.get("uiAmount")})
        return out

    # ---------------- independent references, used only to CHECK DexScreener (never to replace it) ----------------
    async def _ref_get(self, url: str, ttl: float):
        hit = self.cache.get("ref|" + url, ttl)
        if hit is not None:
            return hit
        try:
            r = await (await self._c()).get(url, headers={**UA, "accept": "application/json"})
        except httpx.HTTPError as e:
            raise SourceError(f"couldn't reach {url.split('/')[2]}: {type(e).__name__}") from None
        if r.status_code == 429:
            raise SourceError(f"{url.split('/')[2]} is rate-limiting requests (429)")
        if r.status_code != 200:
            raise SourceError(f"{url.split('/')[2]} answered {r.status_code}")
        try:
            data = r.json()
        except ValueError:
            raise SourceError(f"{url.split('/')[2]} sent something that isn't JSON") from None
        self.cache.put("ref|" + url, data)
        return data

    async def jupiter_prices(self, mints: list[str], ttl: float = 20) -> dict[str, dict]:
        """Jupiter's free price endpoint: {mint: {"usdPrice", "decimals", "liquidity", "createdAt", "blockId"}}."""
        d = await self._ref_get("https://lite-api.jup.ag/price/v3?ids=" + ",".join(mints[:50]), ttl)
        if not isinstance(d, dict):
            raise SourceError("lite-api.jup.ag changed its reply format")
        return {k: v for k, v in d.items() if isinstance(v, dict)}

    async def gecko_prices(self, mints: list[str], ttl: float = 30) -> dict[str, float]:
        """GeckoTerminal's free token-price endpoint: {mint: price in USD}."""
        d = await self._ref_get("https://api.geckoterminal.com/api/v2/simple/networks/solana/token_price/" + ",".join(mints[:30]), ttl)
        try:
            raw = d["data"]["attributes"]["token_prices"]
        except (KeyError, TypeError):
            raise SourceError("api.geckoterminal.com changed its reply format") from None
        out = {}
        for k, v in (raw or {}).items():
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                continue
        return out

    async def slot(self) -> int:
        return int(await self._rpc("getSlot", [], 0))

