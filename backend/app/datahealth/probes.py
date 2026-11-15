"""Live probes: one per data source. Each asks the real source, runs the checks, compares with independent sources where any
exist, and returns a plain result. Nothing here can trade, sign, or touch a wallet or account.

A probe result:
  {"source", "name", "market", "reachable", "features": {name: {"state", "independent", "detail", "values"?}}, "findings": [...],
   "explain": one beginner sentence or None, "rate_limited": bool, "latency_ms": float | None}
Feature states: pass | fail | questionable | unknown | unsupported.  "unknown" is never counted as a pass.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from ..market_data.types import Timeframe
from . import checks as C
from .compare import compare_prices, tolerance

REF_TOKENS = {"DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": ("BONK", 5),
              "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm": ("WIF", 6)}       # long-established tokens with known decimals


def feat(state: str, detail: str, independent: bool = False, **values) -> dict:
    return {"state": state, "independent": independent, "detail": detail, **({"values": values} if values else {})}


def _state(f: dict) -> str:
    return "pass" if f["ok"] is True else "fail" if f["ok"] is False else "unknown"


def _result(source: str, name: str, market: str, **kw) -> dict:
    return {"source": source, "name": name, "market": market, "reachable": True, "features": {}, "findings": [], "explain": None,
            "rate_limited": False, "latency_ms": None, "symbols": {}, **kw}


def _err(e: Exception) -> tuple[str, bool]:
    msg = f"{type(e).__name__}: {str(e)[:160]}"
    return msg, ("429" in msg or "rate" in msg.lower())


# ---------------------------------------------------------------- Yahoo (stocks, futures proxies)
class YahooProbe:
    """Candles from the app's own provider for a few reference symbols. Yahoo is the only free source the app has for stocks
    and futures, so its prices can pass every check here and still not be independently confirmed."""

    def __init__(self, source: str, name: str, market: str, monitor, symbols: list[str], max_age_s: float, pairs: list[tuple[str, str]] = (),
                 every: float = 300, delayed: str | None = None):
        self.delayed = delayed
        self.source, self.name, self.market, self.monitor = source, name, market, monitor
        self.symbols, self.max_age_s, self.pairs, self.every = symbols, max_age_s, list(pairs), every
        self._last: dict[str, tuple[datetime | None, float]] = {}

    async def run(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        r = _result(self.source, self.name, self.market, delayed=self.delayed)
        tf = Timeframe.M5
        closes: dict[str, tuple[datetime, float]] = {}
        worst: dict[str, str] = {}
        t0 = time.monotonic()
        failed = 0
        for sym in self.symbols:
            is_open = bool(self.monitor.market_state(sym).get("open"))
            try:
                bars, _notes = await self.monitor.provider.get_bars(sym, tf, now - timedelta(days=4))
            except Exception as e:  # noqa: BLE001 - an unreachable source is a result, not a crash
                msg, rl = _err(e)
                failed += 1
                r["rate_limited"] |= rl
                r["findings"].append(C.finding("reachable", False, f"{sym}: {msg}", symbol=sym))
                r["symbols"][sym] = {"ok": False, "why": "the source didn't answer for this symbol"}
                continue
            fs = C.candle_checks(bars, tf.seconds, sym, now, self.max_age_s, is_open, expect_volume=self.market != "futures" or True)
            last = max((b.ts for b in bars), default=None)
            prev = self._last.get(sym)
            fs.append(C.advancing(prev[0] if prev else None, last, (time.monotonic() - prev[1]) if prev else 0.0, tf.seconds, is_open))
            self._last[sym] = (last, time.monotonic())
            bad = [f for f in fs if f["ok"] is False]
            for f in fs:
                r["findings"].append({**f, "symbol": sym})
                cur = worst.get(f["check"])
                st = _state(f)
                if cur is None or (st == "fail") or (st == "pass" and cur == "unknown"):
                    if cur != "fail":
                        worst[f["check"]] = st
            r["symbols"][sym] = {"ok": not bad, "why": bad[0]["detail"] if bad else "passed its checks",
                                 "last": last.isoformat() if last else None, "market_open": is_open}
            if bars:
                closes[sym] = (bars[-1].ts, float(bars[-1].close))
        r["latency_ms"] = round((time.monotonic() - t0) * 1000 / max(1, len(self.symbols)))
        if failed == len(self.symbols):
            r["reachable"] = False
            r["explain"] = f"{self.name} isn't answering right now."
            return r
        names = {"symbol": "symbol identity", "candle_shape": "candles", "volume": "volume", "order": "order and duplicates",
                 "timeframe": "timeframe", "missing": "missing candles", "continuity": "price continuity", "fresh": "freshness",
                 "advancing": "still updating"}
        for chk, label in names.items():
            st = worst.get(chk, "unknown")
            det = next((f["detail"] for f in r["findings"] if f["check"] == chk and _state(f) == st), "Not checked.")
            r["features"][label] = feat(st, det)
        # same-provider consistency (NOT independent): e.g. the micro and mini contract track the same index
        for a, b in self.pairs:
            if a in closes and b in closes and abs((closes[a][0] - closes[b][0]).total_seconds()) <= tf.seconds:
                cmp = compare_prices({a: closes[a][1], b: closes[b][1]}, 0.002, "price")
                r["features"]["consistency"] = feat("pass" if cmp["ok"] else "fail",
                                                    (f"{a} and {b} follow the same index and are {cmp['max_diff_pct']:.2f}% apart (allowed 0.20%). " if cmp["ok"]
                                                     else f"{a} and {b} follow the same index but are {cmp['max_diff_pct']:.2f}% apart (allowed 0.20%). ")
                                                    + "Both come from Yahoo, so this is a consistency check, not independent proof.",
                                                    values=cmp["values"])
        r["features"]["price"] = feat("unknown", "Prices pass the checks above, but there is no second free source to confirm them against. "
                                                 "Passing checks is not the same as verified.", independent=False)
        if failed:
            r["features"]["reachability"] = feat("fail", f"{failed} of {len(self.symbols)} reference symbols didn't answer.")
        return r


# ---------------------------------------------------------------- crypto: three independent exchanges
class CryptoProbe:
    source, name, market, every = "crypto_exchanges", "Crypto exchange prices (Kraken, Coinbase, Bitstamp)", "crypto", 60
    SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD"]

    def __init__(self, crypto):
        self.crypto = crypto

    async def run(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        r = _result(self.source, self.name, self.market)
        t0 = time.monotonic()
        try:
            each = await self.crypto.each_exchange(self.SYMBOLS)
        except Exception as e:  # noqa: BLE001
            msg, rl = _err(e)
            return {**r, "reachable": False, "rate_limited": rl, "findings": [C.finding("reachable", False, msg)],
                    "explain": "The crypto exchanges couldn't be reached."}
        r["latency_ms"] = round((time.monotonic() - t0) * 1000 / 3)
        up = [k for k, v in each.items() if v["ok"]]
        r["rate_limited"] = any(v.get("rate_limited") for v in each.values())
        for k, v in each.items():
            r["findings"].append(C.finding("reachable", v["ok"], f"{k}: answered." if v["ok"] else f"{k}: {v['error']}", exchange=k))
        if not up:
            return {**r, "reachable": False, "explain": "None of the three crypto exchanges answered."}
        states, stale, wrong = [], [], []
        for sym in self.SYMBOLS:
            quotes, spreads = {}, []
            for ex in each:
                row = each[ex]["rows"].get(sym)
                quotes[ex] = row["last"] if row else None
                if not row:
                    continue
                if row.get("returned_symbol") and row["returned_symbol"] != sym:
                    wrong.append(f"{ex} returned {row['returned_symbol']} for {sym}")
                if row.get("bid") and row.get("ask") and row["ask"] > row["bid"] > 0:
                    spreads.append((row["ask"] - row["bid"]) / row["bid"])
                if row.get("ts"):
                    age = now.timestamp() - row["ts"] / 1000
                    if age > 600:
                        stale.append(f"{ex} {sym} is {age:.0f} s old")
            cmp = compare_prices(quotes, tolerance(0.005, spreads), "price")
            states.append(cmp)
            code = sym.replace("/", "-")
            r["symbols"][code] = {"ok": cmp["ok"] is True, "why": cmp["detail"], "comparison": cmp}
            r["findings"].append(C.finding("compare", cmp["ok"], f"{sym}: {cmp['detail']}", symbol=code, comparison=cmp))
        if any(c["verdict"] == "questionable" for c in states):
            bad = next(c for c in states if c["verdict"] == "questionable")
            r["features"]["price"] = feat("questionable", bad["detail"], independent=True)
            r["explain"] = "Crypto prices are updating, but two exchanges disagree by more than normal. They're treated as questionable until they agree again."
        elif all(c["verdict"] == "agree" for c in states):
            r["features"]["price"] = feat("pass", f"{len(up)} independent exchanges agree on Bitcoin, Ethereum and Solana prices "
                                                  f"(largest gap {max(c['max_diff_pct'] for c in states):.2f}%).", independent=True)
        else:
            r["features"]["price"] = feat("unknown", "Only one exchange answered, so the price can't be cross-checked right now.")
        r["features"]["pair identity"] = feat("fail" if wrong else "pass", "; ".join(wrong) if wrong else "Each exchange returned the pair that was asked for.")
        r["features"]["freshness"] = feat("fail" if stale else "pass", "; ".join(stale) if stale else "Exchange quote times are current.")
        r["features"]["volume"] = feat("unknown", "Each exchange only reports its own trading volume, so volumes aren't comparable and aren't verified.")
        r["features"]["liquidity"] = feat("unknown", "Order-book depth isn't collected, so liquidity isn't verified.")
        return r


# ---------------------------------------------------------------- Solana memecoin data
class MemecoinProbe:
    """DexScreener (what the app uses) against Jupiter, GeckoTerminal and the Solana chain itself."""
    source, name, market, every = "memecoin_data", "Solana token data (DexScreener)", "memecoins", 300
    PAIR_FIELDS = {"chainId": str, "dexId": str, "pairAddress": str, "baseToken": dict, "priceUsd": str}

    def __init__(self, data, extra_tokens=lambda: []):
        self.data, self.extra = data, extra_tokens

    async def check_tokens(self, mints: list[str]) -> tuple[dict, list[dict], dict]:
        """Per token: {"ok", "why", "comparison"}; plus findings and which references answered."""
        findings, refs = [], {}
        pairs = await self.data.pairs_for(mints, ttl=20)
        jup, gecko = {}, {}
        try:
            jup = await self.data.jupiter_prices(mints)
            refs["Jupiter"] = True
        except Exception as e:  # noqa: BLE001
            refs["Jupiter"] = False
            findings.append(C.finding("reference", False, f"Jupiter: {_err(e)[0]}"))
        try:
            gecko = await self.data.gecko_prices(mints)
            refs["GeckoTerminal"] = True
        except Exception as e:  # noqa: BLE001
            refs["GeckoTerminal"] = False
            findings.append(C.finding("reference", False, f"GeckoTerminal: {_err(e)[0]}"))
        out = {}
        for m in mints:
            p = pairs.get(m)
            if not p:
                out[m] = {"ok": None, "why": "DexScreener lists no trading pool for this token.", "comparison": None}
                continue
            sh = C.shape(p, self.PAIR_FIELDS, "DexScreener pair")
            findings.append({**sh, "token": m})
            ident = (p.get("baseToken") or {}).get("address") == m and p.get("chainId") == "solana"
            findings.append(C.finding("symbol", ident, "DexScreener returned the token that was asked for." if ident
                                      else "DexScreener returned a different token or chain than was asked for.", token=m))
            try:
                dex_px = float(p.get("priceUsd"))
            except (TypeError, ValueError):
                dex_px = None
            cmp = compare_prices({"DexScreener": dex_px, "Jupiter": (jup.get(m) or {}).get("usdPrice"), "GeckoTerminal": gecko.get(m)},
                                 0.03, "price")
            findings.append(C.finding("compare", cmp["ok"], cmp["detail"], token=m, comparison=cmp))
            ok = None if not ident or sh["ok"] is False else cmp["ok"]
            out[m] = {"ok": False if (not ident or sh["ok"] is False) else ok,
                      "why": ("DexScreener's reply for this token is malformed or for another token." if (not ident or sh["ok"] is False) else cmp["detail"]),
                      "comparison": cmp, "jupiter_decimals": (jup.get(m) or {}).get("decimals"), "symbol": (p.get("baseToken") or {}).get("symbol")}
        return out, findings, refs

    async def run(self, now: datetime | None = None) -> dict:
        r = _result(self.source, self.name, self.market)
        mints = list(dict.fromkeys(list(REF_TOKENS) + [t for t in self.extra() if t][:6]))
        t0 = time.monotonic()
        try:
            per, findings, refs = await self.check_tokens(mints)
        except Exception as e:  # noqa: BLE001
            msg, rl = _err(e)
            return {**r, "reachable": False, "rate_limited": rl, "findings": [C.finding("reachable", False, f"DexScreener: {msg}")],
                    "explain": "DexScreener isn't answering, so memecoin prices can't be checked."}
        r["latency_ms"] = round((time.monotonic() - t0) * 1000)
        r["findings"] = findings
        r["symbols"] = {m: {k: v for k, v in d.items()} for m, d in per.items()}
        r["rate_limited"] = any("429" in f["detail"] for f in findings)
        listed = [d for d in per.values() if d["comparison"]]
        if not listed:
            r["features"]["price"] = feat("unknown", "None of the reference tokens came back, so nothing could be compared.")
        elif any(d["comparison"]["verdict"] == "questionable" for d in listed):
            bad = next(d for d in listed if d["comparison"]["verdict"] == "questionable")
            r["features"]["price"] = feat("questionable", bad["comparison"]["detail"], independent=True)
            r["explain"] = ("Solana data is updating, but two sources disagree about a token's price. "
                            "Study Terminal has paused practice buys for that token.")
        elif all(d["comparison"]["verdict"] == "agree" for d in listed):
            r["features"]["price"] = feat("pass", f"DexScreener's prices for {len(listed)} reference token(s) match "
                                                  f"{' and '.join(k for k, v in refs.items() if v)}.", independent=True)
        else:
            r["features"]["price"] = feat("unknown", "The independent price sources didn't answer, so DexScreener's prices are unconfirmed right now.")
        fmt_bad = [f for f in findings if f["check"] in ("format", "symbol") and f["ok"] is False]
        r["features"]["reply format"] = feat("fail" if fmt_bad else "pass", fmt_bad[0]["detail"] if fmt_bad else "DexScreener's replies have the expected fields.")
        # token identity against the chain itself
        ident, det = "unknown", "The Solana chain didn't answer, so token identity is unconfirmed."
        try:
            good = 0
            for m, (_sym, dec) in REF_TOKENS.items():
                info = await self.data.mint_info(m)
                jd = per.get(m, {}).get("jupiter_decimals")
                if info.get("decimals") == dec and (jd is None or jd == dec):
                    good += 1
            ident = "pass" if good == len(REF_TOKENS) else "fail"
            det = (f"The chain's own record for {good} of {len(REF_TOKENS)} reference tokens matches what the data sources say (decimals)."
                   if ident == "pass" else "The chain's record for a reference token doesn't match the data sources.")
        except Exception as e:  # noqa: BLE001
            det = f"The Solana chain didn't answer ({_err(e)[0]}), so token identity is unconfirmed."
        r["features"]["token identity"] = feat(ident, det, independent=ident == "pass")
        r["features"]["liquidity"] = feat("unknown", "DexScreener reports one pool; Jupiter reports all pools together. The numbers measure "
                                                     "different things, so they're shown but not treated as confirming each other.")
        r["features"]["volume"] = feat("unknown", "Trading volume comes from DexScreener only. No free second source measures it the same way.")
        r["features"]["buys and sells"] = feat("unknown", "Trade counts come from DexScreener only and aren't independently checked.")
        r["features"]["token age"] = feat("unknown", "Age is the pool's creation time from DexScreener only.")
        r["features"]["holders"] = feat("unknown", "Holder data comes from the Solana chain only, and the free public address often refuses the request.")
        r["features"]["creator activity"] = feat("unsupported", "No free source gives a token creator's history reliably.")
        return r


class SolanaRpcProbe:
    source, name, market, every = "solana_rpc", "Solana public chain data", "memecoins", 300

    def __init__(self, data):
        self.data = data

    async def run(self, now: datetime | None = None) -> dict:
        import asyncio
        r = _result(self.source, self.name, self.market)
        t0 = time.monotonic()
        try:
            a = await self.data.slot()
            r["latency_ms"] = round((time.monotonic() - t0) * 1000)
            await asyncio.sleep(2.0)
            b = await self.data.slot()
        except Exception as e:  # noqa: BLE001
            msg, rl = _err(e)
            return {**r, "reachable": False, "rate_limited": rl, "findings": [C.finding("reachable", False, msg)],
                    "explain": "The free Solana address isn't answering. Token safety checks that read the chain are unavailable."}
        adv = b > a
        r["findings"].append(C.finding("advancing", adv, f"Block number went from {a} to {b} in 2 seconds." if adv
                                       else f"Block number stayed at {a}: this address is serving old chain data."))
        r["features"]["still updating"] = feat("pass" if adv else "fail", r["findings"][-1]["detail"])
        r["features"]["chain data"] = feat("unknown", "Read from one public address. A second address isn't configured, so it isn't cross-checked.")
        return r


# ---------------------------------------------------------------- sources with no legitimate integration
class StaticProbe:
    """A source the app deliberately does not connect to. Reported honestly instead of being left out."""
    every = 3600

    def __init__(self, source: str, name: str, market: str, features: dict[str, str], explain: str, checked: str, needs: str):
        self.source, self.name, self.market = source, name, market
        self._features, self._explain, self.checked, self.needs = features, explain, checked, needs

    async def run(self, now: datetime | None = None) -> dict:
        r = _result(self.source, self.name, self.market, unsupported=True)
        r["features"] = {k: feat("unsupported", v) for k, v in self._features.items()}
        r["explain"] = self._explain
        r["findings"] = [C.finding("integration", None, f"Reviewed {self.checked}. {self.needs}")]
        return r


_FOMO_WHY = ("fomo.family publishes no developer API, and its Terms of Service (section 16) forbid bots, scrapers and third-party tools "
             "from collecting its pricing, transaction or user data without Fomo's permission.")


def fomo_probe() -> StaticProbe:
    caps = ["token name and mint address", "token price", "market capitalization", "trading volume", "liquidity", "buy and sell transactions",
            "holder information", "token age", "creator information", "price history", "trading pairs", "risk indicators", "token discovery"]
    return StaticProbe("fomo", "FOMO (fomo.family)", "memecoins", {c: _FOMO_WHY for c in caps},
                       "FOMO has no way for outside apps to read its data that its own rules allow, so Study Terminal doesn't connect to it. "
                       "Tokens you find on FOMO can still be checked here by pasting their address into Memecoins.",
                       "fomo.family, its Terms of Service and robots.txt on 2026-11-14",
                       "To change this, Fomo Labs would have to publish an API or give written permission (support@fomo.family). "
                       "Unofficial tools that copy a login token or resell scraped data were not used.")


def pumpfun_probe() -> StaticProbe:
    why = ("pump.fun documents its on-chain programs but runs no documented data service; the addresses its own website calls are "
           "undocumented and can change without notice, so they aren't used.")
    return StaticProbe("pumpfun_direct", "pump.fun (direct)", "memecoins",
                       {"token discovery": why, "price": why, "transactions": why, "bonding-curve progress": why + " Reading the curve "
                        "account from the chain is possible in principle but isn't built.",
                        "graduation status": "Not read from pump.fun. Study Terminal shows it from which exchange DexScreener lists the token on "
                                             "(see Solana token data).",
                        "liquidity": why},
                       "Study Terminal doesn't read pump.fun directly. pump.fun tokens are covered through DexScreener and the Solana chain instead.",
                       "pump.fun's public program documentation on 2026-11-14",
                       "pump.fun tokens still appear in Memecoins through DexScreener, with their stage (starting curve or graduated).")
