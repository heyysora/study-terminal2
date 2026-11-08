"""Futures levels, setups, signals, backtest, data labels and the read-only TopstepX client.
Uses real ES 5-minute bars (Yahoo, 2026-10-25 to 2026-11-06) saved as a fixture."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest

from app.futures import backtest as fbt
from app.futures import contracts as fc
from app.futures import features as ff
from app.futures import signals as fsig
from app.futures.data import FuturesData
from app.futures.projectx import READ_ONLY_PATHS, ProjectXClient, ProjectXError
from app.futures.risk import PersonalRisk, PropRules, RiskEngine
from app.futures.sessions import FuturesClock
from app.futures.setups import SetupParams, detect
from app.market_data.types import Timeframe

FIX = Path(__file__).parent / "fixtures" / "es_5m_2026-10-25_11-06.csv"
ES = fc.get("ES")
CLK = FuturesClock(ES)


def load_bars():
    df = pd.read_csv(FIX, index_col=0, parse_dates=True)
    return [{"ts": t.to_pydatetime(), "open": r.Open, "high": r.High, "low": r.Low, "close": r.Close, "volume": r.Volume} for t, r in df.iterrows()]


@pytest.fixture(scope="module")
def F():
    return ff.build(ff.bars_to_frame(load_bars(), CLK), ES, CLK)


def test_trade_dates_and_rth_flags(F):
    # every bar maps to a trade date; Sunday-evening bars belong to Monday
    sun = F[F["ts"] >= pd.Timestamp("2026-11-01T23:00:00Z")].head(1)   # Sunday 17:00 CST (DST ended Nov 1)
    assert len(sun) and str(sun["td"].iloc[0]) == "2026-11-02"
    rth = F[F["rth"]]
    ct = rth["ts"].dt.tz_convert("America/Chicago")
    assert ct.dt.time.min().strftime("%H:%M") == "08:30" and ct.dt.time.max().strftime("%H:%M") == "14:55"


def test_previous_day_levels_use_previous_trade_date_rth(F):
    td = F["td"].iloc[-1]
    tds = list(dict.fromkeys(F["td"]))
    prev = tds[tds.index(td) - 1]
    prth = F[(F["td"] == prev) & F["rth"]]
    last = F.iloc[-1]
    assert last["pdh"] == prth["h"].max() and last["pdl"] == prth["l"].min() and last["pdc"] == prth["c"].iloc[-1]
    # overnight high/low only uses the current trade date before RTH
    on = F[(F["td"] == td) & ~F["rth"] & (F["min_from_rth"] < 0)]
    assert last["onh"] == on["h"].max() and last["onl"] == on["l"].min()


def test_no_lookahead_in_opening_range_and_ib(F):
    td = F["td"].iloc[-1]
    day = F[F["td"] == td]
    first = day[day["rth"]].iloc[0]
    assert np.isnan(first["or_h"]) and np.isnan(first["ib_h"])         # not known on the first RTH bar
    done = day[day["min_from_rth"] == 10].iloc[0]                       # the 08:40 bar closes the 15-min range
    rng = day[(day["min_from_rth"] >= 0) & (day["min_from_rth"] < 15)]
    assert done["or_h"] == rng["h"].max() and done["or_l"] == rng["l"].min()
    assert np.isnan(day[day["min_from_rth"] == 50].iloc[0]["ib_h"]) and not np.isnan(day[day["min_from_rth"] == 55].iloc[0]["ib_h"])


def test_features_are_causal(F):
    """Recomputing on a truncated history must give the same values for the overlapping rows."""
    bars = load_bars()
    cut = len(bars) - 300
    G = ff.build(ff.bars_to_frame(bars[:cut], CLK), ES, CLK)
    cols = ["vwap", "pdh", "pdl", "onh", "onl", "or_h", "ib_h", "swing_h", "swing_l", "trend", "atr"]
    a, b = F.iloc[:len(G)][cols].reset_index(drop=True), G[cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b, check_exact=False, rtol=1e-9)


def test_vwap_matches_definition(F):
    td = F["td"].iloc[-1]
    day = F[F["td"] == td]
    tp = (day["h"] + day["l"] + day["c"]) / 3
    assert day["vwap"].iloc[-1] == pytest.approx((tp * day["v"]).sum() / day["v"].sum())


def test_volume_profile_value_area_contains_poc(F):
    day = F[F["td"] == F["td"].iloc[-2]]
    vp = ff.volume_profile(day, ES)
    assert vp["val"] <= vp["poc"] <= vp["vah"]
    for x in (vp["poc"], vp["val"], vp["vah"]):
        assert fc.round_to_tick(x, ES) == x
    assert "approximate" in vp["note"]


def test_setups_produce_tick_valid_plans_with_correct_sides(F):
    seen = 0
    for i in range(len(F) - 400, len(F)):
        found, _ = detect(F, i, ES, SetupParams(flat_by_min_from_rth=400))
        for s in found:
            seen += 1
            for px in (s.entry, s.stop, s.target):
                assert fc.round_to_tick(px, ES) == px
            assert (s.entry - s.stop) * s.direction > 0 and (s.target - s.entry) * s.direction > 0
            assert abs(s.target - s.entry) == pytest.approx(2 * abs(s.entry - s.stop), abs=0.25)
            assert F.iloc[i]["rth"]
    assert seen > 0


def test_no_entries_near_flat_time_or_after_extension(F):
    late = F[F["rth"] & (F["min_from_rth"] >= 390)].index
    for i in late[-20:]:
        found, why = detect(F, int(i), ES, SetupParams(flat_by_min_from_rth=400))
        assert not found


def test_signal_gates_on_data_status(F):
    ev = {}
    for status in ("stale", "historical", "cached", "unavailable"):
        out = fsig.evaluate(F, ES, "ESZ26", {"status": status, "reason": "x"}, ev)
        assert out["action"] == "NO TRADE" and not out["watch"] and not out["study_only"]
    out = fsig.evaluate(F, ES, "ESZ26", {"status": "delayed", "reason": "10 min"}, ev)
    assert out["action"] == "NO TRADE" and "delayed" in out["reasons"][0]


def test_signal_incomplete_data_blocks(F):
    G = F[~((F["td"] == F["td"].iloc[-1]) & (F["min_from_rth"].between(60, 120)))].reset_index(drop=True)
    G["gap_min"] = G["ts"].diff().dt.total_seconds().div(60).where(G["td"].eq(G["td"].shift(1)), 0)
    G.attrs.update(F.attrs)
    out = fsig.evaluate(G, ES, "ESZ26", {"status": "polling"}, {})
    assert out["action"] == "NO TRADE" and "incomplete" in out["reasons"][0].lower()


def _find_setup_row(F):
    for i in range(len(F) - 1, 300, -1):
        found, _ = detect(F, i, ES, SetupParams(flat_by_min_from_rth=400))
        if found:
            return i, found[0]
    raise AssertionError("no setup in fixture")


def test_signal_watch_only_without_reliable_evidence_and_long_short_with_it(F):
    i, s = _find_setup_row(F)
    G = F.iloc[:i + 1].copy()
    G.attrs.update(F.attrs)
    key = f"{s.name}|{'long' if s.direction > 0 else 'short'}"
    risk = RiskEngine(PropRules.from_preset("topstep_tc_150k"), PersonalRisk(max_risk_per_trade_usd=1000, max_daily_loss_usd=None,
                                                                               min_reward_risk=None))
    from app.futures.paper import FuturesPaperEngine
    snap = FuturesPaperEngine(risk.rules, risk.personal).snapshot(G["ts"].iloc[-1].to_pydatetime(), None)
    out = fsig.evaluate(G, ES, "ESZ26", {"status": "polling"}, {}, risk_engine=risk, snapshot=snap, flat_by_min_from_rth=400)
    assert out["action"] == "NO TRADE" and out["watch"] and out["watch"][0]["evidence_short"] == "untested"
    good = {key: {"tier": "reliable", "trades": 150, "days": 40}}
    out = fsig.evaluate(G, ES, "ESZ26", {"status": "polling"}, good, risk_engine=risk, snapshot=snap, flat_by_min_from_rth=400)
    assert out["action"] == ("LONG" if s.direction > 0 else "SHORT")
    sig = out["signal"]
    assert sig["stop"] == s.stop and sig["risk_per_contract_usd"] > 0 and sig["suggested_contracts"] >= 1 and sig["reward_risk"] >= 1.9
    for k in ("entry_range", "target", "invalidation", "conditions", "levels_nearby"):
        assert sig[k] is not None
    # a high-impact release window turns it into watch-only
    out = fsig.evaluate(G, ES, "ESZ26", {"status": "polling"}, good, risk_engine=risk, snapshot=snap, flat_by_min_from_rth=400,
                        events={"gate": True, "reason": "CPI in 5 minutes"})
    assert out["action"] == "NO TRADE" and "CPI" in out["reasons"][0]


def test_open_position_gets_hold_or_exit(F):
    pos = {"qty": 1, "avg_price": float(F["c"].iloc[-1])}
    out = fsig.evaluate(F, ES, "ESZ26", {"status": "polling"}, {}, position=pos, position_stop=None, minutes_to_flat=5)
    assert out["action"] == "EXIT" and any("flat-by" in r for r in out["reasons"])
    out = fsig.evaluate(F, ES, "ESZ26", {"status": "polling"}, {}, position=pos, position_stop=None, minutes_to_flat=200)
    assert out["action"] in ("HOLD", "EXIT") and any("No stop" in r for r in out["reasons"])


def test_backtest_costs_and_report(F):
    res = fbt.run(F, ES, 3.78, 1.0, 3, 400)
    assert res["overall"]["trades"] == len(res["trades"]) > 0
    for t in res["trades"]:
        assert t["pnl"] == pytest.approx(t["ticks"] * 12.5 - 3.78, abs=0.01)
        assert t["exit_role"] in ("stop", "target", "time")
        if t["exit_role"] == "stop":
            assert t["ticks"] < 0 or t["pnl"] < 0
    per_day = pd.Series([t["trade_date"] for t in res["trades"]]).value_counts()
    assert per_day.max() <= 3
    assert res["overall"]["tier"] in ("insufficient", "losing", "negative", "inconclusive", "promising", "reliable")
    assert "nothing was tuned" in res["no_optimization"]


def test_levels_snapshot_fields(F):
    L = fsig.levels_snapshot(F, ES)
    for k in ("vwap", "prev_day_high", "prev_day_low", "overnight_high", "overnight_low", "opening_range_high", "ib_high",
              "profile_prev_rth", "fvgs", "structure", "sweeps", "trend"):
        assert k in L


# ---------------- data labels ----------------

class _Yahoo:
    def __init__(self, delay=10, fail_specific=False):
        self.delay, self.fail_specific, self.calls = delay, fail_specific, []

    async def get_feed_info(self, symbol):
        from app.market_data.types import SymbolFeedInfo
        return SymbolFeedInfo(symbol=symbol, provider="yahoo", delay_minutes=self.delay, realtime_price=False)

    async def get_bars(self, symbol, tf, start, end=None):
        from app.market_data.types import Bar
        self.calls.append(symbol)
        if self.fail_specific and "." in symbol:
            raise RuntimeError("no data")
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        return [Bar(symbol=symbol, timeframe=tf.value, ts=now - timedelta(minutes=15), open=1, high=1, low=1, close=1, volume=1,
                    provider="yahoo", source="t")], []


class _Store(dict):
    def get(self, k, d=None):
        return super().get(k, d)


async def test_yahoo_futures_labeled_delayed_or_stale():
    d = FuturesData(_Yahoo(delay=10), _Store())
    now = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)   # Tuesday 09:00 CT, open
    bars = [{"ts": now - timedelta(minutes=15), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]
    lab = await d.label(bars, Timeframe.M5, CLK, "yahoo", "ESZ26.CME", now)
    assert lab["status"] == "delayed" and lab["delay_minutes"] == 10
    old = [{"ts": now - timedelta(minutes=90), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]
    assert (await d.label(old, Timeframe.M5, CLK, "yahoo", "ESZ26.CME", now))["status"] == "stale"
    sat = datetime(2026, 11, 7, 15, 0, tzinfo=timezone.utc)
    assert (await d.label(bars, Timeframe.M5, CLK, "yahoo", "ESZ26.CME", sat))["status"] == "historical"
    d2 = FuturesData(_Yahoo(delay=None), _Store())
    lab = await d2.label(bars, Timeframe.M5, CLK, "yahoo", "X", now)
    assert lab["status"] == "delayed" and "treated as delayed" in lab["reason"]


async def test_specific_contract_falls_back_to_continuous_with_note():
    y = _Yahoo(fail_specific=True)
    d = FuturesData(y, _Store())
    bars, label, notes = await d.bars(fc.Contract("ES", 2026, 12), Timeframe.M5, CLK)
    assert y.calls == ["ESZ26.CME", "ES=F"] and any("continuous" in n for n in notes)


# ---------------- TopstepX (ProjectX) client: read-only ----------------

def _transport(log):
    def handler(req: httpx.Request):
        log.append(req.url.path)
        body = json.loads(req.content or b"{}")
        if req.url.path == "/api/Auth/loginKey":
            ok = body.get("apiKey") == "k"
            return httpx.Response(200, json={"token": "tok" if ok else None, "success": ok, "errorCode": 0 if ok else 3, "errorMessage": None})
        assert req.headers["Authorization"] == "Bearer tok"
        if req.url.path == "/api/Contract/search":
            return httpx.Response(200, json={"contracts": [{"id": "CON.F.US.MES.Z26", "name": "MESZ6", "tickSize": 0.25, "tickValue": 1.25}],
                                             "success": True, "errorCode": 0})
        if req.url.path == "/api/History/retrieveBars":
            assert body["contractId"] == "CON.F.US.MES.Z26" and body["unit"] == 2 and body["unitNumber"] == 5
            return httpx.Response(200, json={"bars": [{"t": "2026-11-10T15:05:00+00:00", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 9},
                                                      {"t": "2026-11-10T15:00:00+00:00", "o": 1, "h": 1, "l": 1, "c": 1, "v": 3}],
                                             "success": True, "errorCode": 0})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


async def test_projectx_client_reads_bars_and_sorts():
    log = []
    c = ProjectXClient("me", "k", transport=_transport(log))
    bars = await c.bars("MESZ6", 5, datetime(2026, 11, 10, tzinfo=timezone.utc), datetime(2026, 11, 11, tzinfo=timezone.utc))
    assert [b["close"] for b in bars] == [1, 1.5]
    assert log == ["/api/Auth/loginKey", "/api/Contract/search", "/api/History/retrieveBars"]
    await c.aclose()


async def test_projectx_blocks_any_non_read_only_path():
    c = ProjectXClient("me", "k", transport=_transport([]))
    for path in ("/api/Order/place", "/api/Order/cancel", "/api/Position/closeContract"):
        with pytest.raises(ProjectXError, match="read-only"):
            await c._post(path, {})
    assert all("Order" not in p and "Position" not in p for p in READ_ONLY_PATHS)
    await c.aclose()


async def test_projectx_bad_key_reports_error():
    c = ProjectXClient("me", "wrong", transport=_transport([]))
    res = await c.check()
    assert res["ok"] is False and "error 3" in res["detail"]
    await c.aclose()


def test_projectx_key_comes_from_env_and_is_redacted(tmp_path):
    from app.config import Settings

    s = Settings(_env_file=None, STUDY_TERMINAL_DATA_DIR=tmp_path, STUDY_PROJECTX_USERNAME="trader1", STUDY_PROJECTX_API_KEY="secret-key-123")
    assert s.projectx_username == "trader1" and s.projectx_api_key.get_secret_value() == "secret-key-123"
    assert "secret-key-123" in s.secret_values()      # log redaction picks it up
    assert "secret-key-123" not in repr(s)
