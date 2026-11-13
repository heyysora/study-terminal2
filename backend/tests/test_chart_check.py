"""Chart check: the guided real-chart test records honestly. These tests use a SYNTHETIC chart, so every result they create must
be labelled as a test source and never counted."""
import asyncio

import pytest

from app.validation.chart_check import STEPS, ChartCheck
from app.watchdog import Watchdog

from .test_watchdog import monitor
from .visual_chart import render, walk


@pytest.fixture
async def rig(tmp_path):
    frames = {"img": render(walk(70, start=25000.0, seed=5))[0]}
    m, rt, win = monitor(frames)
    await m.tick(rt)
    m._task = asyncio.get_event_loop().create_task(asyncio.sleep(3600))
    import time
    m.loop_at = time.monotonic()
    wd = Watchdog(m, None)
    cc = ChartCheck(tmp_path, m, wd, "test")
    yield cc, m, rt, win, frames
    m._task.cancel()


def test_every_requested_real_world_check_exists():
    ids = {s["id"] for s in STEPS}
    assert ids >= {"contract", "timeframe", "price", "candle", "indicators", "scale", "resize", "zoom", "frozen", "tab", "minimize",
                   "interrupt", "restart"}


async def test_compare_steps_show_how_each_value_was_obtained_and_record_answers(rig):
    cc, m, rt, *_ = rig
    s = cc.sample("contract")
    assert s["shown"]["values"]["contract"]["how"] == "read directly" and s["shown"]["values"]["contract"]["value"] == "MNQ"
    rec = cc.answer(s["sample"], True)
    assert rec["outcome"] == "pass" and rec["counts"] is False and "TEST SOURCE" in rec["source"]   # synthetic: never counts
    p = cc.sample("price")
    assert p["image"].startswith("data:image/jpeg;base64,") and p["shown"]["values"]["price"]["value"] == rt.reading.price.value
    rec = cc.answer(p["sample"], False, {"price": 1.0}, "box showed something else")
    assert rec["outcome"] == "fail" and (cc.dir / rec["image"]).exists()
    with pytest.raises(KeyError):
        cc.answer(p["sample"], True)                                      # one answer per sample


async def test_candles_are_scored_against_typed_values_and_unavailable_isnt_wrong(rig):
    cc, m, rt, *_ = rig
    s = cc.sample("candle")
    c = rt.reading.candles[-2]
    rec = cc.answer(s["sample"], None, {"open": c.open, "high": c.high, "low": c.low, "close": c.close})
    assert rec["outcome"] == "pass" and all(abs(e) < 1e-9 for e in rec["errors"].values())
    s = cc.sample("candle")
    rec = cc.answer(s["sample"], None, {"open": c.open + 50, "high": c.high, "low": c.low, "close": c.close})
    assert rec["outcome"] == "fail" and rec["errors"]["open"] == -50
    s = cc.sample("indicators")
    rec = cc.answer(s["sample"], None, {"no such line": 25000})
    assert rec["outcome"] == "unavailable"
    with pytest.raises(ValueError):
        cc.answer(cc.sample("candle")["sample"], None, {})


async def test_watch_step_records_detection_and_recovery(rig):
    cc, m, rt, win, _ = rig
    cc.watch_start("minimize")
    win.min = True
    cc.watch_phase("did")
    await m.tick(rt)
    cc.watch_state()
    win.min = False
    cc.watch_phase("undid")
    await m.tick(rt)
    rec = cc.watch_finish()
    assert rec["detected"] and rec["recovered"] and rec["outcome"] == "pass"
    assert [e["code"] for e in rec["timeline"]] == ["HEALTHY", "DISCONNECTED", "HEALTHY"]


async def test_watch_step_fails_when_nothing_is_detected(rig):
    cc, m, rt, *_ = rig
    cc.watch_start("tab")
    cc.watch_phase("did")
    await m.tick(rt)                                                       # the user "switched tabs" but nothing changed
    cc.watch_phase("undid")
    rec = cc.watch_finish()
    assert rec["detected"] is False and rec["outcome"] == "fail"


async def test_watch_needs_a_healthy_start_and_an_undo(rig):
    cc, m, rt, win, _ = rig
    win.min = True
    await m.tick(rt)
    with pytest.raises(ValueError):
        cc.watch_start("minimize")
    win.min = False
    await m.tick(rt)
    cc.watch_start("minimize")
    cc.watch_phase("did")
    assert cc.watch_finish()["outcome"] == "incomplete"


async def test_summary_never_counts_test_sources(rig):
    cc, *_ = rig
    for _ in range(3):
        cc.answer(cc.sample("contract")["sample"], True)
    st = {s["id"]: s for s in cc.summary()["steps"]}
    assert st["contract"]["status"] == "NOT TESTED" and st["contract"]["test_source_results"] == 3 and st["contract"]["real_results"] == 0


async def test_restart_answers(rig):
    cc, *_ = rig
    assert cc.manual("restart", {"watching_resumed": True, "stop_kept": None})["outcome"] == "pass"
    assert cc.manual("restart", {"watching_resumed": False, "stop_kept": True})["outcome"] == "fail"
