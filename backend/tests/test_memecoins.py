"""Memecoins: read-only data parsing, rug-risk rules, price impact, the PRACTICE account (buy, sell, stops, limits), the name
filter, and the API. Fake HTTP responses shaped like DexScreener / Solana RPC; nothing here is evidence about any token."""
import json
import time

import httpx
import pytest

from app.memecoins.checks import checks, price_impact
from app.memecoins.practice import MemeCosts, MemePractice
from app.memecoins.service import MemeService, offensive, row
from app.memecoins.sources import MemeData, SourceError

TOK = "Hi6qQHwHBnx9uaxT3KyBxaHaUn4JTAG6ijygQbiopump"
NOW = time.time() * 1000


def pair(price="0.0001", liq=50_000.0, age_h=48, buys=100, sells=80, addr=TOK, sym="SWIF"):
    return {"chainId": "solana", "dexId": "pumpswap", "url": f"https://dexscreener.com/solana/{addr.lower()}", "pairAddress": "POOL1111",
            "baseToken": {"address": addr, "name": "Snoopy Wif Hat", "symbol": sym}, "priceUsd": price,
            "liquidity": {"usd": liq} if liq is not None else {}, "volume": {"h1": 1000}, "txns": {"h1": {"buys": buys, "sells": sells}},
            "priceChange": {"m5": 1, "h1": 5}, "pairCreatedAt": NOW - age_h * 3_600_000, "marketCap": 100_000}


def mint(mint_auth=None, freeze=None, ext=None):
    return {"program": "token-2022", "mint_authority": mint_auth, "freeze_authority": freeze, "decimals": 6, "supply_raw": "1000000000000",
            "extensions": ext or {}}


def test_rules_in_plain_words():
    ok = checks(pair(), mint())
    assert ok["verdict"] == "Fewer red flags" and "can still drop 90%" in ok["say"]
    assert checks(pair(), mint(mint_auth="X"))["verdict"] == "High risk"
    assert checks(pair(), mint(freeze="X"))["verdict"] == "High risk"
    assert checks(pair(), mint(ext={"permanentDelegate": {"delegate": "X"}}))["verdict"] == "High risk"
    assert checks(pair(), mint(ext={"transferFeeConfig": {}}))["verdict"] == "High risk"
    assert checks(pair(liq=30_000), mint())["verdict"] == "Risky"
    assert checks(pair(liq=5_000), mint())["verdict"] == "High risk"
    assert checks(pair(age_h=0.5), mint())["verdict"] == "High risk"
    assert checks(pair(age_h=5), mint())["verdict"] == "Risky"
    assert checks(pair(buys=10, sells=30), mint())["verdict"] == "Risky"
    holders = [{"account": "POOLACCT", "owner": "POOL1111", "ui": 800_000}] + [{"account": f"A{i}", "owner": f"O{i}", "ui": 31_000} for i in range(12)]
    c = checks(pair(), mint(), holders, supply_ui=1_000_000)
    h = next(i for i in c["items"] if i["key"] == "holders")
    assert "31%" in h["text"] and "pool is left out" in h["text"] and h["level"] == "caution"     # 10 x 3.1%, pool excluded
    unk = checks(pair(), None, mint_error="Couldn't read", holders_error="refused")
    assert "Token record" in unk["unknown"] or unk["items"][0]["level"] == "unknown"
    assert "never" not in ok["verdict"].lower() and "safe" not in ok["verdict"].lower()


def test_price_impact():
    assert price_impact(1000, 100_000, "buy") == pytest.approx(0.02)
    assert price_impact(1000, 100_000, "sell") == pytest.approx(1000 / 51_000)
    assert price_impact(1000, None) is None


def test_names_with_slurs_are_hidden():
    assert offensive("get a job n1gga") and offensive("n i g g a") and offensive("Coon")
    assert not any(offensive(x) for x in ("Niger River", "Raccoon", "Cocoon", "Snoopy Wif Hat", "Bigger", "Scunthorpe"))
    r = row(pair(sym="NIGGA"))
    assert r["hidden"] and r["symbol"] == "(hidden)"


def test_practice_account(db):
    pr = MemePractice(db, MemeCosts(start_usd=500, fee_pct=1, network_fee_usd=0.05, max_trade_pct=10))
    p = pair(price="0.0001", liq=100_000)
    pv = pr.preview_buy(p, 40, 30)
    assert pv["ok"] and pv["impact_pct"] == pytest.approx(0.08) and pv["fee_usd"] == pytest.approx(0.45) and pv["loss_at_stop_usd"] > 12
    assert not pr.preview_buy(p, 60, 30)["ok"]                         # over 10% of the account
    assert not pr.preview_buy(p, 40, 2)["ok"]                          # stop required, 5-90%
    assert not pr.preview_buy(pair(liq=None), 40, 30)["ok"]           # no pool size, no practice
    assert not pr.preview_buy(pair(liq=200), 30, 30)["ok"]            # would move the price over 25% (30 / 100)
    r = pr.buy(p, 40, 30, target_pct=50)
    assert r["done"] and pr.cash() == pytest.approx(500 - 40.45)
    s = pr.summary({TOK: p})
    assert s["positions"][0]["if_sold_now_usd"] < 40 and s["equity_usd"] < 500
    assert pr.check_exits({TOK: pair(price="0.000099")}) == []          # above the stop
    out = pr.check_exits({TOK: pair(price="0.00006")})                  # dropped past the 30% stop: fills BELOW it
    assert out and out[0]["reason"] == "stop" and out[0]["pnl_usd"] < -12 and pr.positions() == []
    pr.buy(p, 40, 30, target_pct=20)
    assert pr.check_exits({TOK: pair(price="0.000125")})[0]["reason"] == "target"
    assert not pr.sell(p, TOK)["ok"]                                    # nothing left
    assert len(pr.fills()) == 4


def test_sources_parse_and_refusals():
    def handler(req: httpx.Request):
        u = str(req.url)
        if "token-profiles" in u:
            return httpx.Response(200, json=[{"chainId": "solana", "tokenAddress": TOK}, {"chainId": "base", "tokenAddress": "0xabc"}])
        if "/tokens/v1/solana/" in u:
            return httpx.Response(200, json=[pair(liq=10_000), pair(liq=60_000)])
        if req.method == "POST":
            body = json.loads(req.content)
            if body["method"] == "getAccountInfo":
                return httpx.Response(200, json={"result": {"value": {"owner": "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb", "data": {"parsed": {
                    "type": "mint", "info": {"mintAuthority": None, "freezeAuthority": None, "decimals": 6, "supply": "5",
                                             "extensions": [{"extension": "tokenMetadata", "state": {}}]}}}}}})
            return httpx.Response(200, json={"error": {"code": 429, "message": "Too many requests for a specific RPC call"}})
        return httpx.Response(404)

    async def go():
        d = MemeData(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        assert [x["tokenAddress"] for x in await d.promoted_profiles()] == [TOK]          # Solana only
        best = await d.pairs_for([TOK])
        assert best[TOK]["liquidity"]["usd"] == 60_000                                    # most liquid pair
        m = await d.mint_info(TOK)
        assert m["program"] == "token-2022" and m["mint_authority"] is None and "tokenMetadata" in m["extensions"]
        with pytest.raises(SourceError, match="free RPC address"):
            await d.largest_holders(TOK)
    import asyncio
    asyncio.run(go())


async def test_meme_api(settings):
    from app.main import create_app

    from .test_futures_api import FutProvider, always_open_clock
    app = create_app(settings, provider=FutProvider(), clock=always_open_clock(), start_loops=False)
    async with app.router.lifespan_context(app):
        m: MemeService = app.state.meme

        async def pairs_for(addrs, ttl=15):
            return {TOK: pair(liq=100_000)} if TOK in addrs else {}
        m.data.pairs_for = pairs_for
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", headers={"X-Study-Terminal": "1"}) as c:
            assert (await c.get("/api/meme/token/not-an-address")).status_code == 422
            assert (await c.post("/api/meme/practice/buy", json={"token": TOK, "usd": 20, "stop_pct": 30})).status_code == 400   # confirm
            r = await c.post("/api/meme/practice/buy", json={"token": TOK, "usd": 20, "stop_pct": 30, "confirm": True})
            assert r.status_code == 200 and r.json()["done"]
            a = (await c.get("/api/meme/practice")).json()
            assert a["positions"][0]["symbol"] == "SWIF" and "Pretend money" in a["note"] and len(a["history"]) == 1
            assert (await c.post("/api/meme/practice/sell", json={"token": TOK})).json()["ok"]
            bad = await c.post("/api/meme/practice/buy", json={"token": TOK, "usd": 2000, "stop_pct": 30, "confirm": True})
            assert bad.status_code == 409
        # the stock and futures practice accounts are untouched
        assert app.state.paper.engine.fills == [] and not any(t for t in app.state.paper.engine.positions)
