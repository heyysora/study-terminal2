"""Live crypto prices from public exchange data, through the open-source ccxt library. READ-ONLY.

ccxt can also place orders when it is given an account's API keys. Study Terminal never gives it any:
  - exchanges are created with no credentials, and nothing in the app's settings can supply them;
  - every order, transfer, withdrawal and account method is replaced with one that refuses (see BLOCKED / _lock).
So this file can read public prices and nothing else. tests/test_exchanges.py and the safety audit check both points.

Sources are tried in order (US-available exchanges with free public data): Kraken, Coinbase Exchange, Bitstamp.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

log = logging.getLogger(__name__)

EXCHANGES = [("kraken", "Kraken"), ("coinbaseexchange", "Coinbase"), ("bitstamp", "Bitstamp")]
COINS = [("BTC", "Bitcoin"), ("ETH", "Ethereum"), ("SOL", "Solana"), ("XRP", "XRP"), ("DOGE", "Dogecoin"),
         ("ADA", "Cardano"), ("LINK", "Chainlink"), ("LTC", "Litecoin")]
NAMES = dict(COINS)
# Anything that needs an account or moves money. Each is replaced so it raises before any network call.
BLOCKED = ("create_order", "create_orders", "create_market_order", "create_limit_order", "create_market_buy_order", "create_market_sell_order",
           "create_limit_buy_order", "create_limit_sell_order", "create_stop_order", "create_stop_limit_order", "create_stop_market_order",
           "create_order_ws", "create_post_only_order", "create_reduce_only_order", "create_trailing_amount_order", "create_trailing_percent_order",
           "edit_order", "edit_orders", "cancel_order", "cancel_orders", "cancel_all_orders", "withdraw", "transfer", "create_deposit_address",
           "fetch_balance", "fetch_my_trades", "fetch_open_orders", "fetch_orders", "fetch_closed_orders", "fetch_positions", "fetch_deposit_address",
           "set_leverage", "set_margin_mode", "borrow_cross_margin", "borrow_isolated_margin", "repay_cross_margin", "repay_isolated_margin",
           "sign_in", "check_required_credentials")


class ReadOnly(RuntimeError):
    pass


def _refuse(*_a, **_k):
    raise ReadOnly("Study Terminal only reads public prices. It can't place orders or touch an account.")


def _lock(ex):
    """Make an exchange object unable to do anything that needs an account."""
    for key in ("apiKey", "secret", "password", "uid", "privateKey", "walletAddress", "token", "login", "twofa"):
        setattr(ex, key, None)
    for name in BLOCKED:
        setattr(ex, name, _refuse)
    signer = ex.sign                                      # every request passes through sign(); only public ones may continue

    def public_only(path, api="public", *a, **k):
        kinds = [api] if isinstance(api, str) else list(api or [])
        if "public" not in kinds:
            _refuse()
        return signer(path, api, *a, **k)
    ex.sign = public_only
    for name in dir(ex):                                  # the raw per-exchange private endpoints (privatePostAddOrder and friends)
        if name.startswith(("private", "sapi", "wapi")) and callable(getattr(ex, name, None)):
            setattr(ex, name, _refuse)
    return ex


def make(exchange_id: str):
    import ccxt                                           # imported late: only needed once someone looks at crypto

    if exchange_id not in dict(EXCHANGES):
        raise ValueError("unknown exchange")
    ex = getattr(ccxt, exchange_id)({"enableRateLimit": True, "timeout": 8000})
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        ex.https_proxy = proxy
    return _lock(ex)


def lock_check() -> dict:
    """Builds each exchange (no network) and proves the order and account doors are shut. Used by the self-test and System health."""
    try:
        import ccxt  # noqa: F401
    except ImportError:
        return {"library": False, "locked": False, "detail": "The crypto price library isn't installed."}
    tried = 0
    for eid, _label in EXCHANGES:
        ex = make(eid)
        for call in (lambda e=ex: e.create_order("BTC/USD", "market", "buy", 1), lambda e=ex: e.fetch_balance(),
                     lambda e=ex: e.withdraw("BTC", 1, "x"), lambda e=ex: e.sign("Balance", "private", "POST", {})):
            tried += 1
            try:
                call()
            except ReadOnly:
                continue
            except Exception as e:  # noqa: BLE001
                return {"library": True, "locked": False, "detail": f"{eid}: unexpected {type(e).__name__}"}
            return {"library": True, "locked": False, "detail": f"{eid}: a blocked call went through"}
        if ex.apiKey or ex.secret:
            return {"library": True, "locked": False, "detail": f"{eid}: credentials present"}
    return {"library": True, "locked": True, "checked": tried, "detail": "Public prices only. Orders and account access are switched off."}


def pair(symbol: str) -> str | None:
    """'BTC-USD' (how the rest of the app names crypto) or 'BTC' -> 'BTC/USD'. Only US-dollar pairs of the listed coins."""
    s = symbol.upper().strip().replace("/", "-")
    base = s[:-4] if s.endswith("-USD") else s
    return f"{base}/USD" if base in NAMES else None


class CryptoMarkets:
    """Cached public tickers. `tickers()` is cheap to call often; the exchange is asked at most every `ttl` seconds."""

    def __init__(self, ttl: float = 8.0, history_ttl: float = 300.0, factory=make):
        self.ttl, self.history_ttl, self._factory = ttl, history_ttl, factory
        self._ex: dict[str, object] = {}
        self._tick: dict | None = None
        self._tick_at = 0.0
        self._hist: dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._hist_task: asyncio.Task | None = None
        self.last_error: str | None = None

    def _exchange(self, eid: str):
        if eid not in self._ex:
            self._ex[eid] = self._factory(eid)
        return self._ex[eid]

    # ---- blocking calls (run in a worker thread) ----
    def _fetch_tickers(self) -> dict:
        wanted = [f"{c}/USD" for c, _ in COINS]
        err = None
        for eid, label in EXCHANGES:
            try:
                ex = self._exchange(eid)
                raw = ex.fetch_tickers(wanted)
                rows = {}
                for sym in wanted:
                    t = raw.get(sym)
                    if not t or t.get("last") is None:
                        continue
                    rows[sym] = {"last": float(t["last"]), "high_24h": t.get("high"), "low_24h": t.get("low"),
                                 "bid": t.get("bid"), "ask": t.get("ask"), "exchange_ts": t.get("timestamp")}
                if rows:
                    return {"source": label, "source_id": eid, "rows": rows, "fetched_at": time.time()}
                err = f"{label} returned no prices"
            except (ReadOnly, ImportError):
                raise
            except Exception as e:  # noqa: BLE001 - try the next exchange
                err = f"{label}: {type(e).__name__}"
                log.info("crypto tickers from %s failed: %s", eid, str(e)[:200])
        raise RuntimeError(err or "no exchange answered")

    def _fetch_history(self, eid: str, sym: str) -> dict | None:
        """Last 24 hourly closes: the 24-hour change and a small trend line."""
        rows = self._exchange(eid).fetch_ohlcv(sym, "1h", limit=26)
        rows = [r for r in rows if r and r[4] is not None]
        if len(rows) < 3:
            return None
        day = rows[-24:]                                  # 24 hourly candles ending now
        return {"closes": [float(r[4]) for r in day], "ref": float(day[0][1] if day[0][1] is not None else day[0][4]), "at": time.time()}

    # ---- async API ----
    async def tickers(self) -> dict:
        async with self._lock:
            if not self._tick or time.time() - self._tick_at > self.ttl:
                try:
                    self._tick = await asyncio.to_thread(self._fetch_tickers)
                    self._tick_at, self.last_error = time.time(), None
                except ReadOnly:
                    raise
                except Exception as e:  # noqa: BLE001
                    self.last_error = str(e)
                    if not self._tick:
                        return {"ok": False, "rows": [], "source": None, "library_missing": isinstance(e, ImportError),
                                "error": "Couldn't reach a crypto exchange for live prices just now.",
                                "note": "Charts still work from Yahoo Finance."}
        t = self._tick
        self._kick_history(t["source_id"], list(t["rows"]))
        age = time.time() - t["fetched_at"]
        out = []
        for c, name in COINS:
            r = t["rows"].get(f"{c}/USD")
            if not r:
                continue
            h = self._hist.get(f"{c}/USD")
            ref = h["ref"] if h else None
            out.append({"symbol": f"{c}-USD", "coin": c, "name": name, "price": r["last"], "high_24h": r["high_24h"], "low_24h": r["low_24h"],
                        "change_24h_pct": round((r["last"] - ref) / ref * 100, 2) if ref else None,
                        "spark": h["closes"] if h else None})
        return {"ok": True, "rows": out, "source": t["source"], "age_seconds": round(age, 1), "stale": age > 60,
                "error": self.last_error and "Showing the last prices received; the exchange didn't answer just now.",
                "note": f"Live public prices from {t['source']} (free, no account). Watch only: crypto can't be practised here."}

    def _fetch_each(self, symbols: list[str]) -> dict:
        """One public ticker per symbol from EVERY exchange separately (no fallback), for cross-checking. Blocking."""
        out: dict[str, dict] = {}
        for eid, label in EXCHANGES:
            try:
                raw = self._exchange(eid).fetch_tickers(symbols)
                rows = {}
                for sym in symbols:
                    t = raw.get(sym)
                    if t and t.get("last") is not None:
                        rows[sym] = {"last": float(t["last"]), "bid": t.get("bid"), "ask": t.get("ask"), "ts": t.get("timestamp"),
                                     "returned_symbol": t.get("symbol")}
                out[label] = {"ok": bool(rows), "rows": rows, "error": None if rows else "no prices in the reply"}
            except (ReadOnly, ImportError):
                raise
            except Exception as e:  # noqa: BLE001 - one exchange being down is a finding, not a crash
                msg = str(e)
                out[label] = {"ok": False, "rows": {}, "error": f"{type(e).__name__}: {msg[:120]}", "rate_limited": "429" in msg or "RateLimit" in type(e).__name__}
        return out

    async def each_exchange(self, symbols: list[str] | None = None) -> dict:
        return await asyncio.to_thread(self._fetch_each, symbols or ["BTC/USD", "ETH/USD", "SOL/USD"])

    async def price(self, symbol: str) -> dict | None:
        p = pair(symbol)
        if not p:
            return None
        t = await self.tickers()
        for r in t["rows"]:
            if r["symbol"] == p.replace("/", "-"):
                return {**r, "source": t["source"], "age_seconds": t["age_seconds"], "stale": t["stale"]}
        return None

    def _kick_history(self, eid: str, syms: list[str]):
        due = [s for s in syms if s not in self._hist or time.time() - self._hist[s]["at"] > self.history_ttl]
        if not due or (self._hist_task and not self._hist_task.done()):
            return

        async def run():
            for s in due:
                try:
                    h = await asyncio.to_thread(self._fetch_history, eid, s)
                    if h:
                        self._hist[s] = h
                except Exception as e:  # noqa: BLE001 - the change column just stays empty
                    log.info("crypto history for %s failed: %s", s, str(e)[:200])
        try:
            self._hist_task = asyncio.get_running_loop().create_task(run())
        except RuntimeError:
            pass

    async def stop(self):
        if self._hist_task:
            self._hist_task.cancel()
