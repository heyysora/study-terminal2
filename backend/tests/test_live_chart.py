"""0.8 Live Market chart API through the real app (fake provider serving recorded real ES bars; no TopstepX credentials,
so the stream is off and nothing may be labelled live)."""
from datetime import datetime, timedelta, timezone

from app.futures.paper import TRADABLE

from .test_futures_api import client  # noqa: F401 - fixture

UTC = timezone.utc


async def test_chart_without_credentials_is_never_live(client):  # noqa: F811
    c, app = client
    st = (await c.get("/api/futures/live/status")).json()
    assert st["state"] == "off" and "credentials" in st["reason"]
    d = (await c.get("/api/futures/live/chart?root=ES&timeframe=5Min")).json()
    assert d["contract"]["code"] == "ESZ26" and d["candles"]
    assert d["data"]["status"] not in TRADABLE and d["data"]["status"] != "realtime"
    assert d["stream"]["state"] == "off"
    times = {x["time"] for x in d["candles"]}
    for n in ("9", "20", "50", "200"):
        assert d["ema"][n] and all(p["time"] in times for p in d["ema"][n])
    assert len(d["ema"]["200"]) == len(d["candles"]) - 199
    # every overlay is a real level at a real time
    assert d["vwap"] and all(p["time"] in times for p in d["vwap"])
    for k in ("prev_day_high", "prev_day_low", "session_open"):
        assert isinstance(d["levels"][k]["price"], float)
    for m in d["overlays"]["structure"]:
        assert m["time"] in times and m["kind"] in ("BOS", "CHoCH") and isinstance(m["level"], float)
    for s in d["overlays"]["swings"]:
        bar = next(x for x in d["candles"] if x["time"] == s["time"])
        assert s["price"] == (bar["high"] if s["kind"] == "high" else bar["low"]) and s["confirmed"] > s["time"]
    for g in d["overlays"]["fvgs"]:
        assert g["formed"] in times and g["low"] < g["high"]
    vp = d["overlays"]["volume_profile"]["previous_rth"]
    assert vp and vp["bins"] and vp["val"] <= vp["poc"] <= vp["vah"]
    assert d["overlays"]["support_resistance"]


async def test_higher_timeframes_are_session_aligned(client):  # noqa: F811
    c, app = client
    clk = app.state.futures.clock("ES")
    for tf, secs in (("1Hour", 3600), ("4Hour", 14400)):
        d = (await c.get(f"/api/futures/live/chart?root=ES&timeframe={tf}")).json()
        assert d["candles"]
        for x in d["candles"]:
            t = datetime.fromtimestamp(x["time"], UTC)
            w = clk.window_at(t)
            assert w is not None and int((t - w.open).total_seconds()) % secs == 0
    day = (await c.get("/api/futures/live/chart?root=ES&timeframe=1Day")).json()
    assert day["candles"] and all(datetime.fromtimestamp(x["time"], UTC).hour == 0 for x in day["candles"])
    assert day["vwap"] == [] and any("VWAP" in n for n in day["notes"])


async def test_bad_inputs_rejected(client):  # noqa: F811
    c, app = client
    assert (await c.get("/api/futures/live/chart?root=CL")).status_code == 422
    assert (await c.get("/api/futures/live/chart?root=ES&timeframe=2Min")).status_code == 422


async def test_stream_bar_close_triggers_automation_only_on_5min_boundary(client):  # noqa: F811
    c, app = client
    f = app.state.futures
    a = f.automation
    a.state.status = "running"
    open_ = datetime(2026, 11, 9, 23, 0, tzinfo=UTC)          # Globex open of trade date 2026-11-10
    assert f._on_live_bar_close("MNQ", {"ts": open_ + timedelta(minutes=3)}) is None
    coro = f._on_live_bar_close("MNQ", {"ts": open_ + timedelta(minutes=4)})       # bar 17:04 closes at 17:05
    assert coro is not None
    coro.close()
    a.state.status = "paused"
    assert f._on_live_bar_close("MNQ", {"ts": open_ + timedelta(minutes=9)}) is None
    a.state.status = "stopped"


async def test_decisions_skip_the_forming_candle(client, monkeypatch):  # noqa: F811
    c, app = client
    f = app.state.futures
    from app.futures import contracts as fc
    from app.market_data.types import Timeframe
    con = fc.front_contract("ES", datetime(2026, 11, 3).date())
    real = f.data.bars

    async def with_forming(contract, tf, clock, days=6, now=None):
        bars, label, notes = await real(contract, tf, clock, days)
        if not bars:
            return bars, label, notes
        return bars[:-1] + [{**bars[-1], "closed": False}], label, notes
    monkeypatch.setattr(f.data, "bars", with_forming)
    F_all, *_ = await f.frame(con, Timeframe.M5)
    F_done, *_ = await f.frame(con, Timeframe.M5, completed_only=True)
    assert len(F_all) == len(F_done) + 1
