"""P8 (screen calibration) and P9 (published economic values, event warnings, futures mentor answers)."""
import io
import json
from datetime import datetime, timedelta, timezone

import cv2
import httpx
import pytest

from app.ai.assistant import Assistant, classify
from app.news.econ_data import EconData, parse
from app.screen.calibration import CalibrationStore, norm_tf, score, wilson

from .test_futures_api import client  # noqa: F401 - fixture
from .test_futures_screen import es_chart


def bls_payload(series=("CES0000000001", "CUSR0000SA0", "LNS14000000")):
    vals = {"CES0000000001": ["159293", "159180", "159100"], "CUSR0000SA0": ["324.0", "323.0", "322.5"], "LNS14000000": ["4.3", "4.2", "4.2"]}
    out = []
    for sid in series:
        v = vals[sid]
        out.append({"seriesID": sid, "data": [
            {"year": "2026", "period": "M10", "periodName": "October", "latest": "true", "value": v[0], "footnotes": [{"code": "P", "text": "preliminary"}]},
            {"year": "2026", "period": "M09", "periodName": "September", "value": v[1], "footnotes": [{}]},
            {"year": "2026", "period": "M08", "periodName": "August", "value": v[2], "footnotes": [{}]}]})
    return {"status": "REQUEST_SUCCEEDED", "Results": {"series": out}}


# ---------------- P9: BLS published values ----------------

def test_parse_bls_values_as_published():
    v = parse(bls_payload())
    nfp = v["CES0000000001"]
    assert nfp["actual"] == 113 and nfp["previous"] == 80 and nfp["period"] == "October 2026" and nfp["preliminary"]
    assert nfp["forecast"] is None and "forecast" in nfp["forecast_note"].lower()
    cpi = v["CUSR0000SA0"]
    assert cpi["actual"] == pytest.approx(0.31, abs=0.01) and cpi["unit"] == "% m/m"
    assert v["LNS14000000"]["actual"] == 4.3 and v["LNS14000000"]["previous"] == 4.2


def test_parse_refusal_raises():
    with pytest.raises(RuntimeError, match="threshold"):
        parse({"status": "REQUEST_NOT_PROCESSED", "message": ["daily threshold reached"]})


async def test_econ_refresh_caches_and_keeps_last_good_copy():
    calls = []
    payloads = [bls_payload(), {"status": "REQUEST_NOT_PROCESSED", "message": ["daily threshold reached"]}]

    def handler(req: httpx.Request):
        calls.append(json.loads(req.content))
        return httpx.Response(200, json=payloads[min(len(calls) - 1, 1)])

    e = EconData(transport=httpx.MockTransport(handler))
    s1 = await e.refresh()
    assert s1["values"]["CES0000000001"]["actual"] == 113 and s1["error"] is None and len(calls) == 1
    assert "registrationkey" not in calls[0] and len(calls[0]["seriesid"]) == 5      # ONE request for all series
    await e.refresh()                                                                 # cached: no new request
    assert len(calls) == 1
    s3 = await e.refresh(force=True)                                                  # refused: values kept, error shown
    assert len(calls) == 2 and "threshold" in s3["error"] and s3["values"]["CES0000000001"]["actual"] == 113


async def test_econ_uses_v2_with_key():
    urls = []

    def handler(req):
        urls.append(str(req.url))
        return httpx.Response(200, json=bls_payload())
    e = EconData(api_key="k", transport=httpx.MockTransport(handler))
    await e.refresh()
    assert "/v2/" in urls[0]


def test_calendar_events_get_values_and_relevance():
    from app.news.service import NewsService
    n = NewsService.__new__(NewsService)
    n.econ = EconData()
    n.econ.values = parse(bls_payload())
    out = n._with_values({"kind": "bls_jobs", "event": "Employment Situation", "date": "2026-12-04", "time_et": "08:30"})
    assert out["market_relevance"].startswith("high") and {v["series_id"] for v in out["published_values"]} == {"CES0000000001", "LNS14000000"}
    assert "published_values" not in n._with_values({"kind": "fomc", "event": "FOMC", "date": "2026-12-09", "time_et": "14:00"})


# ---------------- P9: event warnings ----------------

async def test_event_warning_fires_once_inside_lead_time(client):  # noqa: F811
    c, app = client
    fut = app.state.futures
    now = datetime(2026, 12, 4, 13, 10, tzinfo=timezone.utc)
    fut.engine.upcoming_events = [("Employment Situation", now + timedelta(minutes=20)), ("FOMC", now + timedelta(hours=3))]
    first = fut.event_warnings(now)
    assert [w["event"] for w in first] == ["Employment Situation"] and first[0]["minutes"] == 20
    assert fut.event_warnings(now + timedelta(minutes=1)) == []                      # not repeated
    fut.store.update({"events.warn_minutes": 0})
    fut.engine.upcoming_events = [("CPI", now + timedelta(minutes=5))]
    assert fut.event_warnings(now) == []                                              # 0 turns warnings off


# ---------------- P9: futures mentor ----------------

def test_futures_intents_classify():
    assert classify("How many MNQ contracts fit my limits?") == "size"
    assert classify("Where is the nearest support?") == "support"
    assert classify("Why was this trade rejected?") == "why_rejected"
    assert classify("why is it watch only") == "why_rejected"


def _fctx():
    plan = {"setup": "vwap_reclaim", "direction": "long", "entry": 21000.0, "stop": 20990.0, "target": 21020.0, "stop_ticks": 40,
            "risk_per_contract_usd": 22.5, "reward_risk": 2.0, "invalidation": "back below VWAP", "suggested_contracts": 3,
            "sizing_note": "Capped by your per-trade risk."}
    dec = {"id": "d1", "outcome": "REJECTED", "reason": "Risk check failed.", "evaluated_at": "2026-11-06T15:00:00",
           "steps": [{"n": 1, "step": "data quality", "passed": True, "detail": "ok"},
                     {"n": 9, "step": "risk check", "passed": False, "detail": "Daily loss limit reached."}]}
    return {"symbol": "MNQZ26", "market_mode": "futures",
            "futures": {"contract": {"code": "MNQZ26", "root": "MNQ"}, "spec": {"root": "MNQ", "tick_size": "0.25", "tick_value": 0.5, "point_value": 2},
                        "data": {"status": "delayed"}, "signal": {"action": "WATCH ONLY", "watch": [plan], "decision": dec},
                        "levels": {"last": 21005.0, "as_of": "2026-11-06T15:00", "vwap": 20998.0, "prev_day_high": 21030.0,
                                   "overnight_low": 20950.0, "session_high": 21012.0}},
            "futures_account": {"risk": {"official": {"max_contracts_mini": 5}, "personal": {"daily_loss_remaining": 100.0}}},
            "futures_decisions": [{"id": "d0", "outcome": "WATCH ONLY", "reason": "Strategy not validated."}],
            "futures_journal": {"summary": {"trades": 4, "net": -120.0},
                                "mistakes": [{"code": "chasing", "text": "Filled 3 points worse than planned."},
                                             {"code": "chasing", "text": "Filled 2 points worse."}]},
            "futures_research": {"run": {"at": "2026-11-08", "source": "Yahoo"}, "validated": [],
                                 "overall": {"trades": 42, "avg_r": 0.42, "avg_r_ci95": [-0.07, 0.86], "tier": "inconclusive", "tier_text": "luck"},
                                 "holdout_metrics": {"trades": 17, "avg_r": 0.387},
                                 "registry": {"vwap_reclaim|long": {"status": "experimental", "why": "few trades"}}}}


async def _ask(q):
    return await Assistant().ask(q, _fctx())


async def test_mentor_size_uses_risk_engine_numbers():
    a = (await _ask("How many MNQ can I trade?"))["answer"]
    assert "allows 3 contract(s)" in a and "$22.50" in a and "room for 4" in a and "can't raise" in a


async def test_mentor_support_from_levels():
    a = (await _ask("Where is the nearest support?"))["answer"]
    assert "session high 21012 (28 ticks away)" in a.replace(".0 ", " ") or "session high 21012" in a
    assert "VWAP 20998" in a and "previous day high 21030" in a and "not predictions" in a


async def test_mentor_why_rejected_names_failed_step():
    a = (await _ask("Why was this trade rejected?"))["answer"]
    assert "Step 9 (risk check) failed: Daily loss limit reached." in a and "WATCH ONLY" in a


async def test_mentor_mistakes_and_best_strategy_from_futures_data():
    a = (await _ask("What mistakes do I keep making?"))["answer"]
    assert "chasing: 2 time(s)" in a and "Fewer than 20" in a
    b = (await _ask("Which strategy performs best?"))["answer"]
    assert "Validated strategies: none" in b and "inconclusive" in b and "17 trades" in b


async def test_mentor_too_late_and_rr():
    a = (await _ask("Am I too late?"))["answer"]
    assert "5 points from the planned entry" in a and "50% of the stop distance" in a
    b = (await _ask("What's the risk reward?"))["answer"]
    assert "2.0R" in b


# ---------------- P8: calibration ----------------

def test_wilson_and_normalizers():
    assert wilson(0, 0) is None
    lo, hi = wilson(18, 20)
    assert lo < 90 < hi
    assert norm_tf("5m") == "5Min" == norm_tf("5 min") and norm_tf("1h") == "1Hour"


def test_score_fields():
    obs = {"ticker": "MES", "ticker_confidence": 0.6, "futures": {"root": "MES"}, "timeframe": "5Min", "visible_price": 7402.25,
           "price_axis": {"points": 6, "max_error_pct": 0.01}}
    r = score(obs, {"ticker": "MESZ26", "timeframe": "5m", "price": "7402.75"}, tick_size=0.25)
    assert r["ticker"]["ok"] and r["timeframe"]["ok"] and r["price"]["ok"] and r["price_axis"]["ok"]
    r2 = score(obs, {"ticker": "ESZ26", "price": "7403.00", "tolerance_ticks": 2}, tick_size=0.25)
    assert not r2["ticker"]["ok"] and not r2["price"]["ok"] and r2["price"]["error"] == -0.75
    assert score({"blocked": True, "reason": "login"}, {"ticker": "X"})["blocked"]


def test_store_privacy_and_report(tmp_path):
    st = CalibrationStore(tmp_path)
    good = {"ticker": {"ok": True, "confidence": 0.6}, "price": {"ok": True}}
    bad = {"ticker": {"ok": False, "confidence": 0.5, "read": "ES", "truth": "MESZ26"}, "price": {"ok": True}}
    a = st.add("topstepx", {"ticker": "MESZ26"}, {}, good, b"png", keep_image=False, keep_result=True)
    assert not a["image_kept"] and not list((tmp_path / "calibration").glob("*.png"))   # no image without consent
    st.add("topstepx", {"ticker": "MESZ26"}, {}, bad, b"png", keep_image=True, keep_result=True)
    st.add("topstepx", {"ticker": "MESZ26", "synthetic": True}, {}, good, None, keep_image=False, keep_result=True)
    st.add("topstepx", {"ticker": "MESZ26"}, {}, good, b"png", keep_image=False, keep_result=False)    # not counted
    st.add("topstepx", {}, {}, {"blocked": True}, b"png", keep_image=True, keep_result=True)            # login screen: nothing kept
    rep = st.report()
    t = rep["platforms"]["topstepx"]["ticker"]
    assert rep["real_samples"] == 2 and rep["synthetic_samples"] == 1 and t["samples"] == 2 and t["accuracy_pct"] == 50.0
    assert not t["meaningful"] and "20" in t["note"] and t["failures"][0]["read"] == "ES"
    assert rep["images_kept"] == 1 and len(list((tmp_path / "calibration").glob("*.png"))) == 1
    assert st.delete(None) == 3 and not list((tmp_path / "calibration").glob("*.png")) and st.report()["real_samples"] == 0
    assert st.image("../../etc/passwd") is None


async def test_calibration_routes_end_to_end(client):  # noqa: F811
    c, app = client
    img, _ = es_chart(ticker="MESZ6", price=7402.25)
    _, png = cv2.imencode(".png", img)
    files = lambda: {"file": ("c.png", io.BytesIO(png.tobytes()), "image/png")}  # noqa: E731
    r = await c.post("/api/screen/calibration/sample", files=files(),
                     data={"ticker": "MESZ26", "price": "7402.25", "platform": "topstepx", "title": "TopstepX", "synthetic": "true"})
    j = r.json()
    assert r.status_code == 200 and j["result"]["ticker"]["ok"] and j["result"]["price"]["ok"] and not j["kept"]["image"]
    rep = (await c.get("/api/screen/calibration")).json()["report"]
    assert rep["synthetic_samples"] == 1 and rep["real_samples"] == 0 and rep["platforms"] == {}    # synthetic never counts
    r2 = (await c.post("/api/screen/calibration/sample", files=files(),
                       data={"ticker": "ESZ26", "platform": "topstepx", "title": "TopstepX", "keep_image": "true"})).json()
    assert r2["kept"]["image"] and not r2["result"]["ticker"]["ok"]
    assert (await c.get(f"/api/screen/calibration/{r2['id']}/image")).status_code == 200
    rs = (await c.post("/api/screen/calibration/rescore")).json()
    assert rs["rescored"] == 1 and rs["report"]["platforms"]["topstepx"]["ticker"]["samples"] == 1
    assert (await c.post("/api/screen/calibration/sample", files=files(), data={"price": "abc"})).status_code == 422
    assert (await c.delete("/api/screen/calibration/all")).json()["deleted"] == 2
    assert (await c.get(f"/api/screen/calibration/{r2['id']}/image")).status_code == 404


async def test_calendar_route_includes_published_values_block(client):  # noqa: F811
    c, app = client
    d = (await c.get("/api/calendar?days=14")).json()
    assert "published_values" in d and "Forecasts aren't shown" in d["published_values"]["note"]
