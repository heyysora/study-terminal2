"""The TopstepX tab's real title, as seen on a real PC on 2026-11-14: "NQZ26 $27,927.25 ▼ -1.61%". It contains no platform name,
which is why 0.16.0 and earlier never found or read the window. These tests use that exact title."""
import pytest

from app.screen.chart_profile import ChartProfile
from app.screen.platforms import pick, topstepx_title
from app.screen.vision import guess_platform, recognize, title_looks_like_trading

from .test_visual_monitor import fut  # noqa: F401  (fixture)

REAL = "NQZ26 $27,927.25 ▼ -1.61%"
EDGE = [REAL, REAL + " - Personal - Microsoft​ Edge", REAL + " and 3 more pages - Personal - Microsoft Edge",
        "MNQZ6 $27,927.25 ▲ +0.40% - Work - Microsoft Edge", "ESH27 $7,512.50 ▼ -0.2%", "CLF27 $61.02 ▲ +1.10% - Microsoft Edge"]
NOT = ["Chase Online - Account Summary - Microsoft Edge", "Inbox (3) - someone@example.com - Microsoft Edge", "AAPL $250.10 ▲ +1.2% - Microsoft Edge",
       "ABCZ26 $10.00 ▼ -1.0%", "NQZ26 chart ideas - Search", "Order #NQZ26 $27,927.25 confirmed", "", None]


@pytest.mark.parametrize("title", EDGE)
def test_the_real_tab_title_is_recognised_everywhere(title):
    t = topstepx_title(title)
    assert t and t["root"] in ("NQ", "MNQ", "ES", "CL") and t["price"] > 0
    assert guess_platform(title, "msedge.exe") == "topstepx" and pick(title, "msedge.exe").id == "topstepx"
    assert title_looks_like_trading(title, "msedge.exe")                                  # the privacy guard lets the chart tab through
    assert ChartProfile(window_title_contains="TopstepX").matches(title, "msedge.exe")    # the default profile finds it
    assert ChartProfile(window_title_contains="TopstepX", window_process="msedge.exe").matches(title, "msedge.exe")


@pytest.mark.parametrize("title", NOT)
def test_other_tabs_are_still_kept_out(title):
    assert topstepx_title(title) is None
    assert not ChartProfile(window_title_contains="TopstepX").matches(title, "msedge.exe")
    if title:
        assert guess_platform(title, "msedge.exe") != "topstepx"
    if title and "AAPL" not in title:
        assert not title_looks_like_trading(title, "msedge.exe")                          # bank and mail tabs are never captured


def test_contract_and_price_are_read_from_the_title():
    assert topstepx_title(REAL) == {"contract": "NQZ26", "root": "NQ", "price": 27927.25}
    r = recognize(REAL + " - Personal - Microsoft Edge", [], "topstepx")
    assert r.ticker == "NQZ26" and r.title_price == 27927.25 and r.asset_class == "futures" and "topstepx" in r.ticker_source


def test_a_profile_looking_for_some_other_text_is_not_widened():
    assert not ChartProfile(window_title_contains="My Broker").matches(REAL, "msedge.exe")
    assert ChartProfile(window_title_contains="").matches(REAL, "msedge.exe")


def test_window_list_marks_the_real_tab():
    from app.api.routes_visual import edge_first
    w = edge_first([{"kind": "window", "id": 1, "title": "Inbox - Microsoft Edge", "process": "msedge.exe"},
                    {"kind": "window", "id": 2, "title": REAL + " - Personal - Microsoft Edge", "process": "msedge.exe"}])["windows"]
    assert w[0]["id"] == 2 and w[0]["looks_like_topstepx"] and not w[1]["looks_like_topstepx"]


async def test_the_monitor_finds_and_reads_a_window_with_the_real_title(fut):  # noqa: F811
    """End to end with the default chart profile ("TopstepX") and an Edge window titled the way TopstepX really titles it.
    The picture is a test fixture, so this proves the window is found and let through, not that your chart is read correctly."""
    from .test_visual_monitor import T_RTH, Clock, fixture, make_monitor
    img, _, _ = fixture("mnq_5m_basic")
    wins = [{"kind": "window", "id": 7, "title": "Inbox - Personal - Microsoft Edge", "process": "msedge.exe"},
            {"kind": "window", "id": 42, "title": "MNQZ26 $27,927.25 ▼ -1.61% - Personal - Microsoft Edge", "process": "msedge.exe"}]   # the fixture picture is an MNQ chart
    m, rt, win = make_monitor(fut, lambda t: (img, "wgc"), wins, Clock(T_RTH))
    await m.tick(rt)
    assert rt.hwnd == 42 and rt.status not in ("disconnected", "unreadable"), (rt.status, rt.reason)
    assert "No open window" not in (rt.reason or "") and "another tab" not in (rt.reason or "")
    # the same Edge window switched to another tab: nothing is captured, and it says why
    assert not m.store.p.matches("Chase Online - Account Summary - Personal - Microsoft Edge", "msedge.exe")



def test_the_contract_is_taken_from_the_tab_title_when_the_picture_cannot_supply_it():
    from datetime import datetime, timezone

    from app.screen.chart_reader import read_chart
    from .test_visual_monitor import fixture, prof
    img, _, toks = fixture("mnq_5m_basic")
    no_header = [t for t in toks if "MNQ" not in t.text.upper()]                          # as if the chart header couldn't be read
    now = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)
    blind = read_chart(img, prof(root="auto"), now, tokens=list(no_header), title="Some window")
    seen = read_chart(img, prof(root="auto"), now, tokens=list(no_header), title="MNQZ26 $20,010.25 ▲ +0.10% - Microsoft Edge")
    assert blind.instrument.value is None
    assert seen.instrument.value == "MNQ" and seen.instrument.cls == "DIRECTLY_READ" and "tab title" in seen.instrument.source
    clash = read_chart(img, prof(root="auto"), now, tokens=list(toks), title="ESH27 $7,512.50 ▼ -0.2% - Microsoft Edge")
    assert any("Instrument conflict" in x for x in clash.problems) and clash.instrument.confidence <= 0.2
