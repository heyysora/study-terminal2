"""Live price: fast price-box read, its checks, the price tape, and the /api/visual/live endpoint.
SYNTHETIC screenshots only. They test the logic; they say nothing about accuracy on real TopstepX charts."""
import asyncio
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.screen.chart_profile import ChartProfile
from app.screen.chart_reader import read_chart
from app.screen.live_price import PriceTape, read_tag, session_start

from .test_visual_monitor import FakeWin, fixture
from .visual_chart import render, walk


def full_read(img):
    p = ChartProfile.from_dict({"name": "t", "window_title_contains": "x", "root": "MNQ", "timeframe": "5Min"})
    return read_chart(img, p, datetime.now(UTC))


def test_price_box_read_matches_the_full_read():
    img = fixture("mnq_5m_basic")[0]
    r = full_read(img)
    tr = read_tag(img, r.axis, 0.25, None)
    assert tr.value == r.price.value == 24974.5 and tr.confidence >= 0.7


@pytest.mark.parametrize("seed,start", [(3, 21000.0), (7, 25500.0), (11, 24000.25)])
def test_price_box_read_follows_a_moving_chart(seed, start):
    base = walk(70, start=start, seed=seed)
    r = full_read(render(base)[0])
    assert r.ok
    moved = [dict(c) for c in base]
    moved[-1]["close"] = moved[-1]["close"] + 1.5                 # the last candle ticks up 6 ticks; the scale doesn't change
    moved[-1]["high"] = max(moved[-1]["high"], moved[-1]["close"])
    tr = read_tag(render(moved)[0], r.axis, 0.25, r.price.value)
    assert tr.value == moved[-1]["close"]


def test_every_check_can_reject():
    img = fixture("mnq_5m_basic")[0]
    axis = full_read(img).axis
    assert read_tag(img, None, 0.25, None).why.startswith("no price scale")
    assert read_tag(img, axis, 0.25, None, recognize=lambda c: ("24974.50", 0.5)).value is None        # not confident
    assert read_tag(img, axis, 0.25, None, recognize=lambda c: ("24974.60", 0.99)).value is None       # off the tick grid
    assert read_tag(img, axis, 0.25, None, recognize=lambda c: ("2497.50", 0.99)).value is None        # dropped digit: off the scale
    assert read_tag(img, axis, 0.25, None, recognize=lambda c: ("24934.50", 0.99)).value is None       # wrong digit: off the scale
    assert read_tag(img, axis, 0.25, None, recognize=lambda c: ("abc", 0.99)).value is None
    blank = img.copy()
    blank[:, int(axis["x_left"]) - 6:] = (13, 17, 23)
    assert "no price box" in read_tag(blank, axis, 0.25, None).why


def test_jumps_wait_for_confirmation():
    t = PriceTape("p")
    assert t.offer(100.0, 25000.0, 0.25, "full read")
    assert not t.offer(100.5, 25020.0, 0.25, "price box")        # 80 ticks in half a second: held
    assert t.last()[1] == 25000.0 and "waiting" in t.last_reject
    assert t.offer(101.0, 25020.25, 0.25, "price box")           # the next read agrees: accepted
    assert t.last()[1] == 25020.25
    assert not t.offer(101.5, 24900.0, 0.25, "price box")
    assert not t.offer(110.0, 24800.0, 0.25, "price box")         # a different jump doesn't confirm the first
    assert t.offer(111.0, 25021.0, 0.25, "price box")            # small move: fine
    assert t.offer(400.0, 24800.0, 0.25, "price box")            # long gap since the last price: no jump rule


def test_gaps_break_the_line_and_series_thins_evenly():
    t = PriceTape("p")
    for i in range(5000):
        t.offer(1000.0 + i, 25000.0 + (i % 7) * 0.25, 0.25, "price box")
    t.gap(6001.0)
    t.gap(6002.0)                                                # one gap marker, not two
    t.offer(6100.0, 25010.0, 0.25, "full read")
    s = t.series(0, max_points=500)
    assert 450 <= len(s) <= 560 and s[-1] == [6100.0, 25010.0]
    assert sum(1 for x in s if x[1] is None) == 1
    assert [x[0] for x in s] == sorted(x[0] for x in s)


def test_same_price_within_a_second_isnt_stored_twice():
    t = PriceTape("p")
    t.offer(100.0, 25000.0, 0.25, "a")
    t.offer(100.4, 25000.0, 0.25, "a")
    t.offer(101.5, 25000.0, 0.25, "a")
    assert len(t.points) == 2


def test_tape_is_saved_and_reloaded(tmp_path):
    now = time.time()
    t = PriceTape("p1", tmp_path)
    t.offer(now - 10, 25000.0, 0.25, "full read")
    t.gap(now - 5)
    t.offer(now - 1, 25001.0, 0.25, "price box")
    t.flush()
    files = list(tmp_path.glob("*_p1.csv"))
    assert len(files) == 1
    t2 = PriceTape("p1", tmp_path)
    assert [p[1] for p in t2.points] == [25000.0, None, 25001.0]
    old = tmp_path / "2000-01-01_p1.csv"
    old.write_text("1,2,x\n")
    PriceTape("p1", tmp_path)
    assert not old.exists()                                      # older than two weeks: removed


def test_session_starts_at_6pm_new_york():
    ny = ZoneInfo("America/New_York")
    assert session_start(datetime(2026, 11, 13, 14, 0, tzinfo=ny)) == datetime(2026, 11, 12, 18, 0, tzinfo=ny)
    assert session_start(datetime(2026, 11, 13, 19, 0, tzinfo=ny)) == datetime(2026, 11, 13, 18, 0, tzinfo=ny)
    t = PriceTape("p")
    base = session_start(datetime.now(UTC)).timestamp()
    t.offer(base - 600, 24000.0, 0.25, "x")                     # yesterday's session
    t.offer(base + 60, 24010.0, 0.25, "x")
    t.offer(base + 120, 24020.0, 0.25, "x")
    assert t.session_reference(datetime.now(UTC)) == (base + 60, 24010.0)


# ---------------- through the monitor ----------------

class Store:
    def __init__(self, path):
        self.path = path / "visual_profiles.json"
        self.p = ChartProfile.from_dict({"id": "p1", "name": "MNQ 5m", "window_title_contains": "TopstepX", "root": "MNQ",
                                         "timeframe": "5Min", "live_seconds": 0.25})

    def all(self):
        return [self.p]


async def test_monitor_fast_path_and_endpoint(tmp_path, monkeypatch):
    from app.screen.visual_monitor import VisualMonitor
    base = walk(70, start=25000.0, seed=5)
    frames = {"img": render(base)[0]}
    m = VisualMonitor(Store(tmp_path), None, None, None, None, capture_fn=lambda t: (frames["img"], "wgc"),
                      list_fn=lambda: [{"kind": "window", "id": 7, "title": "TopstepX - Microsoft Edge", "process": "msedge.exe"}],
                      win=FakeWin(), now=lambda: datetime.now(UTC))
    m._sync_profiles()
    rt = m.runtimes["p1"]
    assert rt.tape.folder is None                                # injected capture: nothing saved to disk
    await m.tick(rt)                                             # full read
    assert rt.status == "screen_capture" and rt.live["method"] == "full read" and rt.live["price"] == base[-1]["close"]
    for k in (1, 2, 3):
        moved = [dict(c) for c in base]
        moved[-1]["close"] = base[-1]["close"] + 0.25 * k
        moved[-1]["high"] = max(moved[-1]["high"], moved[-1]["close"])
        frames["img"] = render(moved)[0]
        await asyncio.sleep(1.05)                                # one point per second at most
        await m.tick(rt, fast=True)
        assert rt.live["method"] == "price box" and rt.live["price"] == moved[-1]["close"]
    assert rt.tape.accepted == 4 and rt.tape.rejected == 0

    from app.api import routes_visual

    class Req:
        class app:  # noqa: N801
            class state:  # noqa: N801
                visual = m
    v = routes_visual.live_view("p1", Req, "day")
    assert v["price"] == base[-1]["close"] + 0.75 and v["live"] is True and v["status_word"] == "Working"
    assert v["change"] == 0.75 and len(v["series"]) == 4 and "not an official exchange feed" in v["source"]
    m._set(rt, "stale", "Chart frozen: nothing changed")
    v = routes_visual.live_view("p1", Req, "day")
    assert v["live"] is False and v["series"][-1][1] is None and v["reason"]["headline"] == "Your chart has stopped moving."
    assert v["price"] == base[-1]["close"] + 0.75                # the last real price stays visible, marked not live


def test_profiles_get_a_live_interval_and_validate_it():
    assert ChartProfile.from_dict({"name": "x"}).live_seconds == 0.5        # older saved profiles get the default
    with pytest.raises(ValueError):
        ChartProfile.from_dict({"name": "x", "live_seconds": 0.1})


def test_tape_handles_a_missing_folder_gracefully(tmp_path):
    t = PriceTape("p", tmp_path / "new" / "deeper")
    t.offer(time.time(), 1.0, 0.25, "x")
    t.flush()
    assert list((tmp_path / "new" / "deeper").glob("*.csv"))
    _ = timedelta
