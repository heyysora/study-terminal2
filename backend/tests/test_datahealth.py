"""Data health. Everything here uses SIMULATED data to prove the software handles good and bad data correctly.
None of it is evidence that any live source is accurate; live results are recorded separately (docs/DATA_VALIDATION_REPORT.md)."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.datahealth import checks as C
from app.datahealth.chartwatch import ChartWatch
from app.datahealth.compare import compare_prices, tolerance, within_range
from app.datahealth.engine import GOOD, DataHealth, classify, coverage
from app.datahealth.probes import CryptoProbe, MemecoinProbe, YahooProbe, feat, fomo_probe, pumpfun_probe
from app.db.models import ChartObservation, DataHealthRecord
from app.market_data.types import Bar
from app.safety import SafetyController

NOW = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)      # a Thursday, market open


def candles(n=60, step=300, start=None, px=100.0, symbol="SPY"):
    start = start or NOW - timedelta(seconds=step * n)
    return [{"symbol": symbol, "ts": start + timedelta(seconds=step * i), "open": px + i * 0.01, "high": px + i * 0.01 + 0.2,
             "low": px + i * 0.01 - 0.2, "close": px + i * 0.01 + 0.05, "volume": 1000 + i} for i in range(n)]


def bars(**kw):
    return [Bar(symbol=c["symbol"], timeframe="5Min", ts=c["ts"], open=c["open"], high=c["high"], low=c["low"], close=c["close"],
                volume=c["volume"], provider="fake", source="fake") for c in candles(**kw)]


# ------------------------------------------------------------------ checks on deliberately corrupted data
def test_clean_candles_pass_every_check():
    fs = C.candle_checks(candles(), 300, "SPY", NOW, 1200, True)
    assert all(f["ok"] is True for f in fs), [f for f in fs if f["ok"] is not True]


@pytest.mark.parametrize("corrupt,check", [
    (lambda c: c[10].update(high=c[10]["low"] - 1), "candle_shape"),
    (lambda c: c[10].update(close=float("nan")), "candle_shape"),
    (lambda c: c[10].update(open=-5), "candle_shape"),
    (lambda c: c[10].update(volume=-1), "volume"),
    (lambda c: [x.update(volume=0) for x in c], "volume"),
    (lambda c: c.insert(11, dict(c[10])), "order"),
    (lambda c: c.__setitem__(slice(10, 12), [c[11], c[10]]), "order"),
    (lambda c: c[10].update(ts="yesterday"), "order"),
    (lambda c: c[10].update(ts=datetime(2026, 11, 12, 14, 0)), "order"),                    # no time zone: can't be placed
    (lambda c: [x.update(symbol="QQQ") for x in c], "symbol"),
    (lambda c: c[30].update(close=c[30]["close"] * 2, high=c[30]["high"] * 2), "continuity"),
    (lambda c: c.__delitem__(slice(10, 16)), "missing"),                              # a 30-minute hole inside the session
])
def test_corrupted_candles_are_caught(corrupt, check):
    c = candles()
    corrupt(c)
    fs = {f["check"]: f for f in C.candle_checks(c, 300, "SPY", NOW, 1200, True)}
    assert fs[check]["ok"] is False, fs[check]


def test_wrong_timeframe_stale_future_and_stopped_feeds():
    assert C.timeframe_matches(candles(step=60), 300)["ok"] is False                        # asked 5-minute, got 1-minute
    assert C.fresh(NOW - timedelta(hours=2), NOW, 1200, True)["ok"] is False                # stale while open
    assert C.fresh(NOW - timedelta(hours=40), NOW, 1200, False)["ok"] is None               # closed: can't be judged, never a pass
    assert C.fresh(NOW + timedelta(minutes=10), NOW, 1200, True)["ok"] is False             # dated in the future
    assert C.fresh(None, NOW, 1200, True)["ok"] is False
    t = NOW - timedelta(minutes=5)
    assert C.advancing(t, t, 1800, 300, True)["ok"] is False                                # nothing new for 30 minutes while open
    assert C.advancing(t, t - timedelta(minutes=5), 60, 300, True)["ok"] is False           # time went backwards
    assert C.advancing(t, t, 1800, 300, False)["ok"] is None and C.advancing(None, t, 0, 300, True)["ok"] is None
    assert C.advancing(t, NOW, 300, 300, True)["ok"] is True


def test_format_change_and_price_sanity():
    need = {"priceUsd": str, "baseToken": dict}
    assert C.shape({"priceUsd": "1.0", "baseToken": {}}, need, "x")["ok"] is True
    assert C.shape({"price_usd": "1.0", "baseToken": {}}, need, "x")["ok"] is False          # renamed field
    assert C.shape({"priceUsd": 1.0, "baseToken": {}}, need, "x")["ok"] is False             # changed type
    assert C.shape(["list"], need, "x")["ok"] is False
    assert C.price_reasonable(0)["ok"] is False and C.price_reasonable(None)["ok"] is False
    assert C.price_reasonable(250, 100)["ok"] is False and C.price_reasonable(101, 100)["ok"] is True


# ------------------------------------------------------------------ comparing sources
def test_sources_are_compared_never_averaged():
    ok = compare_prices({"A": 100.0, "B": 100.2, "C": 99.9}, 0.004)
    assert ok["verdict"] == "agree" and ok["independent"] and ok["values"] == {"A": 100.0, "B": 100.2, "C": 99.9}
    bad = compare_prices({"A": 100.0, "B": 103.0}, 0.004)
    assert bad["verdict"] == "questionable" and bad["ok"] is False and "Neither is assumed right" in bad["detail"]
    assert "average" not in json.dumps(bad).lower() and bad["values"] == {"A": 100.0, "B": 103.0}     # both numbers kept as they were
    one = compare_prices({"A": 100.0, "B": None}, 0.004)
    assert one["verdict"] == "single" and one["ok"] is None and not one["independent"] and one["silent"] == ["B"]
    assert compare_prices({"A": None, "B": float("nan")}, 0.01)["verdict"] == "none"


def test_tolerance_allows_for_spread_and_time_not_for_real_disagreement():
    assert tolerance(0.004) == 0.004
    assert tolerance(0.004, [0.001, 0.003]) == pytest.approx(0.013)                         # wide spreads widen the allowance
    assert tolerance(0.004, None, age_seconds=120, per_minute=0.001) == pytest.approx(0.006)
    assert within_range(100.05, 100.0, 100.4, 0.0006)["ok"] is True
    assert within_range(99.95, 100.0, 100.4, 0.0006)["ok"] is True                           # inside the allowance
    assert within_range(98.0, 100.0, 100.4, 0.0006)["ok"] is False
    assert within_range(100.0, None, 100.4, 0.0006)["ok"] is None


# ------------------------------------------------------------------ classification
def _res(**features):
    return {"source": "s", "name": "S", "market": "stocks", "reachable": True, "features": features, "findings": [], "symbols": {}}


def test_status_rules():
    assert classify({**_res(), "reachable": False})[0] == "OFFLINE"
    assert classify({**_res(), "unsupported": True})[0] == "UNSUPPORTED"
    assert classify(_res(candles=feat("fail", "bad"), price=feat("pass", "ok", independent=True)))[0] == "DEGRADED"
    assert classify(_res(freshness=feat("fail", "old"), candles=feat("pass", "ok")))[0] == "STALE"
    assert classify(_res(price=feat("questionable", "two sources disagree", independent=True), candles=feat("pass", "ok")))[0] == "CONFLICTING"
    assert classify(_res(price=feat("pass", "agree", independent=True), freshness=feat("pass", "ok")))[0] == "VERIFIED"
    assert classify(_res(price=feat("pass", "self-reported"), candles=feat("pass", "ok")))[0] == "HEALTHY"       # a pass that isn't independent isn't verified
    assert classify(_res(price=feat("unknown", "no second source"), candles=feat("pass", "ok")))[0] == "HEALTHY"
    assert classify({**_res(price=feat("unknown", "x"), candles=feat("pass", "ok")), "delayed": "10 minutes"})[0] == "DELAYED"
    assert classify(_res(price=feat("unknown", "x"), candles=feat("unknown", "x")))[0] == "UNVERIFIED"           # nothing actually passed
    assert classify(_res())[0] == "UNVERIFIED"
    assert classify({**_res(candles=feat("pass", "ok")), "rate_limited": True})[0] == "DEGRADED"
    cov = coverage(_res(price=feat("pass", "a", independent=True), volume=feat("unknown", "b"), candles=feat("pass", "c")))
    assert cov["passing"] == 2 and cov["independently_confirmed"] == ["price"] and cov["by_state"]["unknown"] == ["volume"]


# ------------------------------------------------------------------ probes on simulated sources
class FakeMonitor:
    def __init__(self, data, open_=True):
        self.data, self.open_, self.fail = data, open_, None
        self.provider = self

    def market_state(self, symbol):
        return {"open": self.open_}

    async def get_bars(self, symbol, tf, start, end=None):
        if self.fail:
            raise self.fail
        d = self.data[symbol]
        return (d() if callable(d) else d), []


def fresh_bars(symbol="SPY", **kw):
    now = datetime.now(timezone.utc)
    return [Bar(symbol=symbol, timeframe="5Min", ts=c["ts"], open=c["open"], high=c["high"], low=c["low"], close=c["close"], volume=c["volume"],
                provider="fake", source="fake") for c in candles(start=now - timedelta(seconds=300 * 60), symbol=symbol, **kw)]


async def test_yahoo_probe_healthy_then_wrong_symbol_then_outage():
    mon = FakeMonitor({"SPY": fresh_bars()})
    p = YahooProbe("yahoo_stocks", "Stocks", "stocks", mon, ["SPY"], 1200)
    r = await p.run()
    assert classify(r)[0] == "HEALTHY" and r["features"]["price"]["state"] == "unknown" and r["symbols"]["SPY"]["ok"]
    mon.data["SPY"] = fresh_bars(symbol="QQQ")                                               # the source hands back another symbol
    r = await p.run()
    assert classify(r)[0] == "DEGRADED" and r["features"]["symbol identity"]["state"] == "fail" and r["symbols"]["SPY"]["ok"] is False
    mon.fail = httpx.ConnectError("no internet")
    r = await p.run()
    assert classify(r)[0] == "OFFLINE" and not r["reachable"]
    mon.fail = RuntimeError("429 Too Many Requests")
    assert (await p.run())["rate_limited"] is True


async def test_yahoo_probe_stale_and_closed_market():
    old = [Bar(symbol="SPY", timeframe="5Min", ts=c["ts"], open=c["open"], high=c["high"], low=c["low"], close=c["close"], volume=c["volume"],
               provider="fake", source="fake") for c in candles(start=datetime.now(timezone.utc) - timedelta(hours=9))]
    r = await YahooProbe("yahoo_stocks", "Stocks", "stocks", FakeMonitor({"SPY": old}, open_=True), ["SPY"], 1200).run()
    assert classify(r)[0] == "STALE"
    r = await YahooProbe("yahoo_stocks", "Stocks", "stocks", FakeMonitor({"SPY": old}, open_=False), ["SPY"], 1200).run()
    assert classify(r)[0] == "HEALTHY" and r["features"]["freshness"]["state"] == "unknown"   # closed: not stale, and not counted as a pass


async def test_micro_and_mini_contract_must_track_each_other():
    a, b = fresh_bars(symbol="NQ=F", px=20000), fresh_bars(symbol="MNQ=F", px=20000)
    r = await YahooProbe("yahoo_futures", "Futures", "futures", FakeMonitor({"NQ=F": a, "MNQ=F": b}), ["NQ=F", "MNQ=F"], 1800,
                         pairs=[("NQ=F", "MNQ=F")], delayed="10 minutes").run()
    assert classify(r)[0] == "DELAYED" and "not independent proof" in r["features"]["consistency"]["detail"]
    b = fresh_bars(symbol="MNQ=F", px=20300)                                                # 1.5% apart: something is wrong
    r = await YahooProbe("yahoo_futures", "Futures", "futures", FakeMonitor({"NQ=F": a, "MNQ=F": b}), ["NQ=F", "MNQ=F"], 1800, pairs=[("NQ=F", "MNQ=F")]).run()
    assert classify(r)[0] == "DEGRADED"


class FakeCrypto:
    def __init__(self, prices, ts_age=5, errors=()):
        self.prices, self.ts_age, self.errors = prices, ts_age, set(errors)

    async def each_exchange(self, symbols):
        now = datetime.now(timezone.utc).timestamp() * 1000
        out = {}
        for ex, px in self.prices.items():
            if ex in self.errors:
                out[ex] = {"ok": False, "rows": {}, "error": "NetworkError: down"}
                continue
            out[ex] = {"ok": True, "error": None, "rows": {s: {"last": px * (i + 1), "bid": px * (i + 1) * 0.9999, "ask": px * (i + 1) * 1.0001,
                                                               "ts": now - self.ts_age * 1000, "returned_symbol": s} for i, s in enumerate(symbols)}}
        return out


async def test_crypto_verified_conflicting_single_and_offline():
    r = await CryptoProbe(FakeCrypto({"Kraken": 64000, "Coinbase": 64020, "Bitstamp": 63990})).run()
    assert classify(r)[0] == "VERIFIED" and r["features"]["price"]["independent"] and r["features"]["volume"]["state"] == "unknown"
    r = await CryptoProbe(FakeCrypto({"Kraken": 64000, "Coinbase": 66000, "Bitstamp": 63990})).run()
    assert classify(r)[0] == "CONFLICTING" and "disagree" in r["explain"] and r["symbols"]["BTC-USD"]["ok"] is False
    r = await CryptoProbe(FakeCrypto({"Kraken": 64000, "Coinbase": 64020, "Bitstamp": 63990}, errors={"Coinbase", "Bitstamp"})).run()
    assert classify(r)[0] == "HEALTHY" and r["features"]["price"]["state"] == "unknown"       # one exchange: reachable, not verified
    r = await CryptoProbe(FakeCrypto({"Kraken": 1, "Coinbase": 1, "Bitstamp": 1}, errors={"Kraken", "Coinbase", "Bitstamp"})).run()
    assert classify(r)[0] == "OFFLINE"
    r = await CryptoProbe(FakeCrypto({"Kraken": 64000, "Coinbase": 64020, "Bitstamp": 63990}, ts_age=3600)).run()
    assert classify(r)[0] == "STALE"


BONK, WIF = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"


class FakeMeme:
    def __init__(self, dex=1.0, jup=1.0, gecko=1.0, decimals=None, fail=()):
        self.dex, self.jup, self.gecko, self.decimals, self.fail = dex, jup, gecko, decimals or {BONK: 5, WIF: 6}, set(fail)
        self.rename = False
        self.slots = iter(range(100, 10_000, 9))

    def _pair(self, m):
        p = {"chainId": "solana", "dexId": "raydium", "pairAddress": "POOL", "baseToken": {"address": m, "symbol": "T"}, "priceUsd": str(self.dex),
             "liquidity": {"usd": 500_000}}
        if self.rename:
            p["price_usd"] = p.pop("priceUsd")
        return p

    async def pairs_for(self, mints, ttl=15):
        if "dex" in self.fail:
            raise RuntimeError("DexScreener answered 503")
        return {m: self._pair(m) for m in mints}

    async def jupiter_prices(self, mints, ttl=20):
        if "jup" in self.fail:
            raise RuntimeError("lite-api.jup.ag is rate-limiting requests (429)")
        return {m: {"usdPrice": self.jup, "decimals": self.decimals.get(m, 6)} for m in mints}

    async def gecko_prices(self, mints, ttl=30):
        if "gecko" in self.fail:
            raise RuntimeError("down")
        return {m: self.gecko for m in mints}

    async def mint_info(self, m):
        if "rpc" in self.fail:
            raise RuntimeError("rpc refused")
        return {"decimals": self.decimals.get(m, 6)}

    async def slot(self):
        return next(self.slots)


async def test_memecoin_data_verified_conflicting_changed_format_and_offline():
    r = await MemecoinProbe(FakeMeme(1.0, 1.01, 0.995)).run()
    assert classify(r)[0] == "VERIFIED" and r["features"]["token identity"]["state"] == "pass" and r["features"]["volume"]["state"] == "unknown"
    assert r["features"]["creator activity"]["state"] == "unsupported"
    r = await MemecoinProbe(FakeMeme(1.0, 1.25, 1.24)).run()
    assert classify(r)[0] == "CONFLICTING" and "paused practice buys" in r["explain"]
    m = FakeMeme()
    m.rename = True                                                                          # the provider renames a field
    r = await MemecoinProbe(m).run()
    assert classify(r)[0] == "DEGRADED" and "changed its format" in r["features"]["reply format"]["detail"]
    r = await MemecoinProbe(FakeMeme(fail={"jup", "gecko"})).run()
    assert classify(r)[0] in ("DEGRADED", "HEALTHY") and r["features"]["price"]["state"] == "unknown" and classify(r)[0] != "VERIFIED"
    r = await MemecoinProbe(FakeMeme(decimals={BONK: 9, WIF: 6})).run()                      # the chain disagrees about the token
    assert r["features"]["token identity"]["state"] == "fail" and classify(r)[0] == "DEGRADED"
    assert classify(await MemecoinProbe(FakeMeme(fail={"dex"})).run())[0] == "OFFLINE"


async def test_fomo_and_pumpfun_are_reported_as_unsupported_not_faked():
    f = await fomo_probe().run()
    assert classify(f)[0] == "UNSUPPORTED" and all(v["state"] == "unsupported" for v in f["features"].values())
    assert {"token price", "liquidity", "holder information", "price history"} <= set(f["features"]) and "section 16" in f["features"]["token price"]["detail"]
    assert classify(await pumpfun_probe().run())[0] == "UNSUPPORTED"
    assert coverage(f)["passing"] == 0


# ------------------------------------------------------------------ engine: persistence, outages, recovery, the gate
class Scripted:
    every = 1

    def __init__(self, source, market, results):
        self.source, self.name, self.market, self.results, self.i = source, source.title(), market, results, 0

    async def run(self, now=None):
        r = self.results[min(self.i, len(self.results) - 1)]
        self.i += 1
        if isinstance(r, Exception):
            raise r
        return {"source": self.source, "name": self.name, "market": self.market, "reachable": True, "findings": [], "symbols": {}, **r}


GOOD_RES = {"features": {"price": feat("pass", "agree", independent=True), "freshness": feat("pass", "ok")}}
DOWN_RES = {"reachable": False, "features": {}, "findings": [{"check": "reachable", "ok": False, "detail": "no answer"}]}
BAD_SYMBOL = {"features": {"symbol identity": feat("fail", "asked SPY got QQQ"), "price": feat("unknown", "x")},
              "symbols": {"SPY": {"ok": False, "why": "asked SPY got QQQ"}}}


async def test_outage_recovery_and_records_survive_a_restart(db):
    p = Scripted("yahoo_stocks", "stocks", [GOOD_RES, DOWN_RES, DOWN_RES, GOOD_RES])
    dh = DataHealth(db, [p], kind="simulated")
    dh.enforcing = True
    assert (await dh.run_probe(p))["status"] == "VERIFIED" and dh.permit("stocks")[0]
    assert (await dh.run_probe(p))["status"] == "OFFLINE" and not dh.permit("stocks")[0]
    await dh.run_probe(p)
    e = await dh.run_probe(p)
    assert e["status"] == "VERIFIED" and e["recovered"] and dh.permit("stocks")[0]
    out = dh.outages()
    assert len(out) == 1 and out[0]["ended_at"] and out[0]["status"] == "OFFLINE" and out[0]["reason"] == "no answer"
    assert [h["status"] for h in dh.history("yahoo_stocks")] == ["VERIFIED", "OFFLINE", "OFFLINE", "VERIFIED"]
    with db.session() as s:
        row = s.query(DataHealthRecord).first()
        assert row.app_version and row.test_version == C.TEST_VERSION and row.kind == "simulated"
    # a new engine on the same data file (as after a restart) still has the history, and does NOT trust the old result
    dh2 = DataHealth(db, [Scripted("yahoo_stocks", "stocks", [GOOD_RES])], kind="simulated")
    dh2.enforcing = True
    assert len(dh2.history("yahoo_stocks")) == 4 and dh2.state["yahoo_stocks"]["from_previous_run"]
    ok, why = dh2.permit("stocks")
    assert not ok and "haven't finished yet" in why


async def test_a_crashing_or_hanging_check_is_a_failure_not_silence(db):
    p = Scripted("yahoo_stocks", "stocks", [RuntimeError("boom")])
    dh = DataHealth(db, [p], kind="simulated")
    dh.enforcing = True
    e = await dh.run_probe(p)
    assert e["status"] == "OFFLINE" and not dh.permit("stocks")[0]


async def test_gate_blocks_per_market_and_per_symbol(db):
    stocks, crypto = Scripted("yahoo_stocks", "stocks", [BAD_SYMBOL]), Scripted("crypto_exchanges", "crypto", [GOOD_RES])
    dh = DataHealth(db, [stocks, crypto], kind="simulated")
    assert dh.permit("stocks")[0]                                    # not enforcing (background checks off): says so, doesn't pretend
    dh.enforcing = True
    assert not dh.permit("stocks")[0]                                # nothing checked yet
    await dh.run_all()
    ok, why = dh.permit("stocks", "SPY")
    assert not ok and "degraded" in why.lower()
    assert dh.permit("crypto")[0]                                    # one bad market doesn't switch off a healthy one
    s = dh.summary()
    assert s["tone"] == "bad" and "paused new ideas" in s["overall"] and len(s["sources"]) == 2
    assert not any(x["signals_permitted"] for x in s["sources"] if x["status"] not in GOOD)


async def test_open_practice_trades_are_flagged_when_their_data_goes_bad(db):
    p = Scripted("yahoo_stocks", "stocks", [DOWN_RES])
    dh = DataHealth(db, [p], positions_fn=lambda: [{"market": "stocks", "symbol": "SPY", "account": "stock practice"}], kind="simulated")
    dh.enforcing = True
    await dh.run_all()
    fl = dh.summary()["flagged_positions"]
    assert len(fl) == 1 and "may be wrong until the data recovers" in fl[0]["warning"]


def test_safety_controller_has_the_last_word(db):
    dh = SimpleNamespace(enforcing=True, permit=lambda market, symbol=None: (market != "futures", "Futures prices are stale." if market == "futures" else "ok"))
    stop = {"on": False, "rec": False}
    sc = SafetyController(dh, stopped_fn=lambda: stop["on"], recovery_fn=lambda: stop["rec"])
    assert sc.permit("stocks")[0] and not sc.permit("futures")[0] and sc.permit_symbol("NQ=F") == (False, "Futures prices are stale.")
    assert sc.permit_symbol("BTC-USD")[0] and sc.market_of("AAPL") == "stocks"
    stop["on"] = True
    assert not any(sc.permit(m)[0] for m in ("stocks", "futures", "crypto", "memecoins"))    # Stop everything covers every market
    stop["on"], stop["rec"] = False, True
    assert not sc.permit("stocks")[0] and "recovery mode" in sc.permit("stocks")[1]
    st = sc.status()
    assert st["recovery_mode"] and "can't place" in st["note"]


def test_no_scanner_can_skip_the_controller():
    from pathlib import Path
    app = Path(__file__).resolve().parents[1] / "app"
    assert "safety.permit_symbol(symbol)" in (app / "signals" / "service.py").read_text(encoding="utf-8")
    assert 'safety.permit("futures"' in (app / "futures" / "service.py").read_text(encoding="utf-8")
    meme = (app / "api" / "routes_meme.py").read_text(encoding="utf-8")
    assert meme.count("_data_gate(request") >= 3 and 'safety.permit("memecoins")' in meme
    ctl = (app / "safety.py").read_text(encoding="utf-8")
    assert "def allow" not in ctl and "override" not in ctl and "bypass" not in ctl.lower().replace("no scanner or strategy has a way", "")


# ------------------------------------------------------------------ TopstepX chart validation (simulated screen)
class FakeVisual:
    state = "running"

    def __init__(self):
        self.ch = {"status": "screen_capture", "reason": "", "capture_method": "wgc",
                   "reading": {"instrument": {"value": "MNQZ26"}, "timeframe": {"value": "5m"}, "price": {"value": 20010.0, "class": "DIRECTLY_READ"},
                               "size": [1200, 800], "confidence": 0.9}}

    def status(self):
        return {"charts": {"p1": self.ch}}


def ref_bars(t0, px=20010.0):
    return [Bar(symbol="NQ=F", timeframe="1Min", ts=t0 + timedelta(minutes=i), open=px, high=px + 3, low=px - 3, close=px, volume=10,
                provider="fake", source="fake") for i in range(-3, 4)]


async def test_chart_readings_are_compared_with_reference_candles_later(db):
    t0 = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)
    vis, mon = FakeVisual(), FakeMonitor({"NQ=F": ref_bars(t0)})
    cw = ChartWatch(db, vis, mon, real_fn=lambda: True)
    cw.observe(t0)
    assert await cw.settle(t0 + timedelta(minutes=5)) == 0                                   # too soon: the delayed reference hasn't caught up
    assert await cw.settle(t0 + timedelta(minutes=25)) == 1
    s = cw.summary()
    assert s["counts"]["matched"] == 1 and s["recent"][0]["outcome"] == "match" and s["recent"][0]["ref_low"] == 20007.0
    assert s["features"]["price extraction"]["state"] == "unknown" and "Needs 30 matches" in s["features"]["price extraction"]["detail"]
    assert s["features"]["timeframe detection"]["state"] == "unknown"                        # never verified from the label alone
    with db.session() as sess:
        o = sess.query(ChartObservation).filter(ChartObservation.outcome == "match").one()
        assert o.ref_symbol == "NQ=F" and o.tolerance_pct and o.app_version and o.os_version and o.real_capture == 1
    # a reading far from the reference (wrong contract, or a misread digit) is a mismatch
    vis.ch["reading"]["price"]["value"] = 5800.0
    cw.observe(t0 + timedelta(minutes=2))
    await cw.settle(t0 + timedelta(minutes=30))
    assert cw.summary()["counts"]["mismatched"] == 1


async def test_chart_verified_only_after_enough_real_matches_on_two_days(db):
    vis = FakeVisual()
    days = [datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc), datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)]
    for real in (False, True):
        with db.session() as s:
            s.query(ChartObservation).delete()
        cw = ChartWatch(db, vis, FakeMonitor({"NQ=F": []}), real_fn=lambda real=real: real)
        for d in days:
            cw.monitor.data["NQ=F"] = [b for i in range(16) for b in ref_bars(d + timedelta(minutes=2 * i))]
            for i in range(16):
                cw._prev.clear()
                cw.observe(d + timedelta(minutes=2 * i))
            for _ in range(2):
                await cw.settle(d + timedelta(hours=1))
        f = cw.summary()["features"]["price extraction"]
        if real:
            assert f["state"] == "pass" and f["independent"] and "over 2 days" in f["detail"]
        else:
            assert f["state"] == "unknown" and cw.summary()["counts"]["test_source_readings"] >= 30   # test sources never count as evidence


async def test_chart_scenarios_are_recognised_without_touching_the_browser(db):
    t0 = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)
    vis = FakeVisual()
    cw = ChartWatch(db, vis, FakeMonitor({"NQ=F": []}), real_fn=lambda: True)
    cw.observe(t0)
    vis.ch = {**vis.ch, "status": "disconnected", "reason": "The TopstepX window is minimized; minimized windows can't be captured."}
    cw.observe(t0 + timedelta(seconds=20))
    good = FakeVisual().ch
    vis.ch = good
    cw.observe(t0 + timedelta(seconds=40))
    vis.ch = {**good, "status": "unreadable", "reason": "another tab"}
    cw.observe(t0 + timedelta(seconds=60))
    vis.ch = good
    cw.observe(t0 + timedelta(seconds=80))
    vis.ch = {**good, "reading": {**good["reading"], "size": [900, 600]}}
    cw.observe(t0 + timedelta(seconds=100))
    vis.ch = {**good, "reading": {**good["reading"], "size": [900, 600], "instrument": {"value": "MESZ26"}}}
    cw.observe(t0 + timedelta(seconds=120))
    vis.ch = {**good, "status": "stale", "reason": "Chart frozen: nothing on it has changed for 200 s"}
    cw.observe(t0 + timedelta(seconds=140))
    seen = {s["key"]: s["count"] for s in cw.summary()["scenarios"]}
    assert seen["normal"] == 1 and seen["minimized_restored"] == 1 and seen["hidden_recovered"] == 1 and seen["resized"] == 1
    assert seen["symbol_changed"] == 1 and seen["frozen"] == 1
    assert "Browser zoom changes" in cw.summary()["cannot_observe"]
    assert ChartWatch(db, vis, FakeMonitor({}), real_fn=lambda: True).scenarios["frozen"]["count"] == 1     # kept across a restart
    src = __import__("pathlib").Path(__import__("app.datahealth.chartwatch", fromlist=["x"]).__file__).read_text(encoding="utf-8")
    assert not any(w in src for w in ("SendInput", "pyautogui", "mouse_event", "keybd_event", ".click("))   # it only looks


# ------------------------------------------------------------------ through the running app
async def test_bad_data_cannot_produce_an_idea_through_the_app(settings):
    from .test_memecoins import TOK, _client, pair
    async with await _client(settings) as (app, c):
        dh = app.state.datahealth
        assert (await c.get("/api/datahealth")).json()["enforcing"] is False
        dh.enforcing = True
        dh.probes = [Scripted("yahoo_stocks", "stocks", [BAD_SYMBOL]), Scripted("yahoo_futures", "futures", [DOWN_RES]),
                     Scripted("memecoin_data", "memecoins", [GOOD_RES])]
        dh.kind = "simulated"
        body = (await c.post("/api/datahealth/run")).json()
        assert {s["source"]: s["status"] for s in body["sources"]}["yahoo_stocks"] == "DEGRADED"
        assert body["safety"]["markets"]["stocks"]["allowed"] is False and body["safety"]["markets"]["futures"]["allowed"] is False
        assert body["safety"]["markets"]["memecoins"]["allowed"] is True
        # stocks: the controller refuses (the signal engine itself is driven in test_integration.py)
        assert app.state.safety.permit_symbol("SPY")[0] is False and app.state.signals.safety is app.state.safety
        # futures: whatever the strategy said, the controller turns it into NO TRADE
        fut = (await c.get("/api/futures/analysis/MNQ")).json()["signal"]
        assert fut["action"] in ("NO TRADE", "WAIT") and fut["data_health"]["allowed"] is False
        # memecoins: a token whose price sources conflict can't be bought in practice
        async def pairs_for(addrs, ttl=30):
            return {TOK: pair(price="0.0001", liq=1_000_000)}
        app.state.meme.data.pairs_for = pairs_for

        async def conflicted(mint):
            return {"ok": False, "why": "DexScreener and Jupiter disagree on the price by 25.00% (allowed 3.00%)."}
        dh.check_token = conflicted
        buy = {"token": TOK, "usd": 20, "stop_pct": 30}
        pv = (await c.post("/api/meme/practice/preview", json=buy)).json()
        assert pv["ok"] is False and "paused for this token" in pv["errors"][0]
        assert (await c.post("/api/meme/practice/buy", json={**buy, "confirm": True})).status_code == 409

        async def unconfirmed(mint):
            return {"ok": None, "why": "Only DexScreener gave a price."}
        dh.check_token = unconfirmed
        pv = (await c.post("/api/meme/practice/preview", json=buy)).json()
        assert pv["ok"] is True and "couldn't be confirmed" in pv["warnings"][0]
        rep = (await c.get("/api/datahealth/report")).json()
        assert "thresholds" in rep and rep["history"]["yahoo_stocks"] and (await c.get("/api/datahealth/chart")).status_code == 200
