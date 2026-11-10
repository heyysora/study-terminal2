"""Rules of the Trust & Validation dashboard. The inputs here are hand-built records that exercise the RULES; they are not evidence
and are never stored. Passing these tests doesn't raise anyone's readiness level: only recorded real evidence does."""
import io

import cv2

from app.validation import trust as T

from .test_futures_api import client  # noqa: F401 - fixture


def rows(n, ok, field="price", synthetic=False, platform="topstepx-visual: NQ 5m", start=0):
    return [{"id": f"s{start + i}", "at": f"2026-11-{10 + i % 10:02d}T15:00:00", "platform": platform, "synthetic": synthetic,
             "result": {field: {"ok": i < ok, "read": 1, "truth": 1}}} for i in range(n)]


def trips(n, r=0.5, basis="realtime market data", origin="manual", days=25, stop=True, contracts=1, net=None):
    out = []
    for i in range(n):
        rr = r if not isinstance(r, list) else r[i % len(r)]
        out.append({"contract": "MNQZ26", "opened": f"t{i}", "closed": f"c{i:04d}", "trade_date": f"2026-{10 + (i % days) // 28:02d}-{1 + (i % days) % 28:02d}",
                    "entry_basis": basis, "origin": origin, "r": rr, "net": net if net is not None else rr * 100, "stop": 21000.0 if stop else None,
                    "contracts": contracts})
    return out


def test_synthetic_and_non_visual_samples_never_count():
    assert T.ocr_price(rows(50, 50, synthetic=True))["status"] == T.UNTESTED
    assert T.ocr_price(rows(50, 50, platform="topstepx"))["status"] == T.UNTESTED       # live copilot reader, not the monitor's
    c = T.ocr_price(rows(50, 50, synthetic=True) + rows(10, 10))
    assert c["status"] == T.IN_PROGRESS and c["observations"] == 10


def test_accuracy_thresholds_use_the_lower_confidence_bound():
    assert T.ocr_price(rows(25, 25))["status"] == T.IN_PROGRESS                         # 25/25: lower bound 87% < 90%
    p = T.ocr_price(rows(40, 40))
    assert p["status"] == T.PASSED and p["metrics"]["ci95"][0] >= 0.90 and p["remaining"] == []
    assert T.ocr_price(rows(30, 18))["status"] == T.FAILED                              # clearly below the bar
    assert T.ocr_price(rows(10, 10))["status"] == T.IN_PROGRESS                         # too few samples
    assert T.ocr_price([])["status"] == T.UNTESTED


def test_categories_need_every_part():
    it = T.instrument_timeframe(rows(40, 40, "ticker"))
    assert it["status"] == T.IN_PROGRESS and any("Timeframe" in r for r in it["remaining"])
    assert T.instrument_timeframe(rows(40, 40, "ticker") + rows(40, 40, "timeframe", start=100))["status"] == T.PASSED
    ci = T.candles_indicators(rows(40, 40, "last_candle"))
    assert ci["status"] == T.IN_PROGRESS and any("VWAP/EMA" in r for r in ci["remaining"])
    vc = T.visual_capture(rows(40, 40, "price_axis"), {})
    assert vc["status"] == T.IN_PROGRESS and any("monitoring captures" in r for r in vc["remaining"])
    days = {f"2026-11-1{i}": {"attempts": 400, "window_found": 400, "live": 390, "methods": {"wgc": 400}} for i in range(3)}
    assert T.visual_capture(rows(40, 40, "price_axis"), days)["status"] == T.PASSED
    bad = {f"2026-11-1{i}": {"attempts": 400, "window_found": 400, "live": 200} for i in range(3)}
    assert T.visual_capture(rows(40, 40, "price_axis"), bad)["status"] == T.FAILED


def test_signal_generation_integrity_and_volume():
    def dec(i, status="realtime", outcome="NO_TRADE", steps=13, failed=False):
        return {"id": f"d{i}", "evaluated_at": f"2026-11-{1 + i % 12:02d}T15:00:00", "outcome": outcome, "data": {"status": status},
                "steps": [{"n": k, "passed": (False if failed and k == 7 else True)} for k in range(1, steps + 1)]}
    assert T.signal_generation([dec(i, status="delayed") for i in range(300)])["status"] == T.UNTESTED   # delayed data isn't live
    assert T.signal_generation([dec(i) for i in range(250)])["status"] == T.PASSED
    assert T.signal_generation([dec(i) for i in range(50)])["status"] == T.IN_PROGRESS
    v = T.signal_generation([dec(i) for i in range(250)] + [dec(999, status="delayed", outcome="APPROVED")])
    assert v["status"] == T.FAILED and v["metrics"]["integrity_violations"] == 1
    assert T.signal_generation([dec(i) for i in range(250)] + [dec(998, outcome="APPROVED", failed=True)])["status"] == T.FAILED


def test_strategy_categories_need_out_of_sample_evidence():
    assert T.historical_performance({})["status"] == T.UNTESTED
    ev = {"NQ": {"overall": {"trades": 50, "avg_r": 0.3, "tier": "inconclusive"}, "registry": {}, "validated": [],
                 "holdout_metrics": {"trades": 17, "avg_r": 0.39}},
          "ES": {"overall": {"trades": 68, "avg_r": -0.06, "tier": "losing"}, "registry": {}, "validated": [],
                 "holdout_metrics": {"trades": 14, "avg_r": -0.12}}}
    assert T.historical_performance(ev)["status"] == T.IN_PROGRESS and T.walk_forward(ev)["status"] == T.IN_PROGRESS
    losing = {"ES": ev["ES"]}
    assert T.historical_performance(losing)["status"] == T.FAILED and T.walk_forward(losing)["status"] == T.FAILED
    good = {"NQ": {**ev["NQ"], "overall": {**ev["NQ"]["overall"], "tier": "reliable"}, "validated": ["vwap_reclaim|long"]}}
    assert T.historical_performance(good)["status"] == T.PASSED and T.walk_forward(good)["status"] == T.PASSED


def test_paper_trading_counts_only_completed_live_trades():
    assert T.paper_trading(trips(80, basis="DELAYED price (practice mode)"))["status"] == T.UNTESTED
    assert T.paper_trading(trips(80, origin="sandbox"))["status"] == T.UNTESTED
    assert T.paper_trading(trips(80, origin="replay-auto"))["status"] == T.UNTESTED
    assert T.paper_trading(trips(20))["status"] == T.IN_PROGRESS
    p = T.paper_trading(trips(60, r=[1.0, -0.5, 0.8]))
    assert p["status"] == T.PASSED and p["metrics"]["avg_r_ci95"][0] > 0
    assert T.paper_trading(trips(60, r=[-1.0, 0.5]))["status"] == T.FAILED


def test_risk_management_audit():
    personal = {"require_stop": True, "max_risk_per_trade_usd": 200, "max_daily_loss_usd": 500}
    rules = {"max_contracts_mini": 5}
    assert T.risk_management(trips(60, r=0.5), rules, personal, confirmed=True)["status"] == T.PASSED
    assert T.risk_management(trips(60, r=0.5), rules, personal, confirmed=False)["status"] == T.IN_PROGRESS
    no_stop = T.risk_management(trips(60, stop=False), rules, personal, confirmed=True)
    assert no_stop["status"] == T.FAILED and no_stop["metrics"]["violations"] == 60
    big = T.risk_management(trips(60, contracts=70), rules, personal, confirmed=True)             # 70 micros = 7 minis > 5
    assert big["status"] == T.FAILED
    after_limit = trips(3, r=-3.0, net=-300, days=1)                                              # third trade after -600 that day
    assert any(v["rule"] == "daily_loss" for v in T.risk_audit(after_limit, rules, personal))


def _passed_visual():
    return (rows(40, 40, "price_axis") + rows(40, 40, "price", start=100) + rows(40, 40, "ticker", start=200)
            + rows(40, 40, "timeframe", start=300) + rows(40, 40, "last_candle", start=400) + rows(40, 40, "indicators", start=500))


def test_readiness_is_sequential_and_never_enables_live():
    days = {f"2026-11-1{i}": {"attempts": 400, "window_found": 400, "live": 395} for i in range(3)}
    base = dict(decisions=[], evidence={}, trips=[], rules={"max_contracts_mini": 5},
                personal={"require_stop": True, "max_risk_per_trade_usd": 200, "max_daily_loss_usd": 500}, rules_confirmed=True)
    r0 = T.build(cal_rows=[], capture_days={}, **base)
    assert r0["readiness"]["level"] == "EXPERIMENTAL" and r0["readiness"]["next_level"] == "VISUAL VALIDATION"
    assert len(r0["readiness"]["remaining_for_next_level"]) >= 4 and "DISABLED" in r0["readiness"]["live_execution"]
    # passing paper trading alone doesn't skip the visual and strategy levels
    r1 = T.build(cal_rows=[], capture_days={}, **{**base, "trips": trips(120, r=[1.0, -0.4], days=45)})
    assert r1["readiness"]["level"] == "EXPERIMENTAL"
    r2 = T.build(cal_rows=_passed_visual(), capture_days=days, **base)
    assert r2["readiness"]["level"] == "VISUAL VALIDATION" and r2["readiness"]["next_level"] == "STRATEGY VALIDATION"
    assert any("Signal generation" in m for m in r2["readiness"]["remaining_for_next_level"])
    decs = [{"id": f"d{i}", "evaluated_at": f"2026-11-{1 + i % 12:02d}T15:00:00", "outcome": "NO_TRADE", "data": {"status": "screen_capture"},
             "steps": [{"n": k, "passed": True} for k in range(1, 14)]} for i in range(250)]
    ev = {"NQ": {"overall": {"trades": 80, "avg_r": 0.4, "tier": "reliable"}, "registry": {}, "validated": ["x|long"],
                 "holdout_metrics": {"trades": 35, "avg_r": 0.3}}}
    r3 = T.build(cal_rows=_passed_visual(), capture_days=days, **{**base, "decisions": decs, "evidence": ev})
    assert r3["readiness"]["level"] == "STRATEGY VALIDATION"
    r4 = T.build(cal_rows=_passed_visual(), capture_days=days, **{**base, "decisions": decs, "evidence": ev,
                                                                   "trips": trips(60, r=[1.0, -0.4], days=25)})
    assert r4["readiness"]["level"] == "PAPER TRADING VALIDATION"
    assert any("longer paper record" in m for m in r4["readiness"]["remaining_for_next_level"])
    r5 = T.build(cal_rows=_passed_visual(), capture_days=days, **{**base, "decisions": decs, "evidence": ev,
                                                                   "trips": trips(120, r=[1.0, -0.4], days=45)})
    assert r5["readiness"]["level"] == "LIVE ELIGIBILITY REVIEW" and "DISABLED" in r5["readiness"]["live_execution"]


async def test_api_fresh_install_is_experimental_and_synthetic_uploads_dont_count(client):  # noqa: F811
    c, app = client
    d = (await c.get("/api/trust")).json()
    assert d["readiness"]["level"] == "EXPERIMENTAL"
    assert {x["key"] for x in d["categories"]} == {"visual_capture", "ocr_price", "instrument_timeframe", "candles_indicators",
                                                    "signal_generation", "historical_performance", "walk_forward", "paper_trading",
                                                    "risk_management"}
    for x in d["categories"]:
        assert {"status", "observations", "metrics", "last_validated", "limitations", "evidence", "remaining"} <= set(x)
    from .test_futures_screen import es_chart
    img, _ = es_chart(ticker="MESZ6", price=7402.25)
    _, png = cv2.imencode(".png", img)
    for _ in range(3):
        await c.post("/api/screen/calibration/sample", files={"file": ("c.png", io.BytesIO(png.tobytes()), "image/png")},
                     data={"ticker": "MESZ26", "price": "7402.25", "platform": "topstepx", "synthetic": "true"})
    d2 = (await c.get("/api/trust")).json()
    assert d2["excluded"]["synthetic_screenshots"] == 3
    assert all(x["status"] == "UNTESTED" for x in d2["categories"] if x["key"] in ("ocr_price", "instrument_timeframe"))
    # the endpoint is read-only
    assert (await c.post("/api/trust")).status_code in (404, 405)
