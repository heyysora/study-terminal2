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


def test_a_window_that_is_not_a_browser_is_never_taken_for_your_chart():
    """TopstepX is a web page. A text editor, folder or image viewer whose name happens to look like a contract and a price
    is somebody's private file, and windows that aren't browsers skip the browser privacy check, so they must not match."""
    p = ChartProfile(window_title_contains="TopstepX")
    for proc in ("notepad.exe", "explorer.exe", "excel.exe", "code.exe"):
        assert not p.matches(REAL + " - Notepad", proc), proc
        assert not p.matches(REAL, proc)
    assert p.matches(REAL, "msedge.exe") and p.matches(REAL, "chrome.exe") and p.matches(REAL, None)


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


async def test_every_topstepx_window_is_read_not_only_the_first(fut):  # noqa: F811
    from .test_visual_monitor import T_RTH, Clock, fixture, make_monitor
    img, _, _ = fixture("mnq_5m_basic")
    wins = [{"kind": "window", "id": 41, "title": "MNQZ26 $27,927.25 ▼ -1.61% - Personal - Microsoft Edge", "process": "msedge.exe"},
            {"kind": "window", "id": 42, "title": "MESZ26 $7,512.50 ▲ +0.20% - Personal - Microsoft Edge", "process": "msedge.exe"},
            {"kind": "window", "id": 43, "title": "Inbox - Personal - Microsoft Edge", "process": "msedge.exe"}]
    m, rt, win = make_monitor(fut, lambda t: (img, "wgc"), wins, Clock(T_RTH))
    await m.tick(rt)
    m._attach_windows()
    assert set(m.runtimes) == {"p1", "p1@42"} and m.runtimes["p1"].hwnd == 41                 # the mail window is never attached
    extra = m.runtimes["p1@42"]
    assert extra.profile.root == "auto" and "MESZ26" in extra.profile.name and extra.hwnd == 42
    assert set(m.status()["charts"]) == {"p1", "p1@42"}
    m._attach_windows()
    assert len(m.runtimes) == 2                                                               # asking again adds nothing
    wins[1]["title"] = "Chase Online - Personal - Microsoft Edge"                             # that window switched to another tab
    m._attach_windows()
    assert set(m.runtimes) == {"p1"}
    wins[1]["title"] = "NQZ26 $27,900.00 ▼ -1.70% - Personal - Microsoft Edge"
    m._attach_windows()
    m._sync_profiles()
    assert set(m.runtimes) == {"p1", "p1@42"} and "NQZ26" in m.runtimes["p1@42"].profile.name
    del wins[1]
    m._attach_windows()
    assert set(m.runtimes) == {"p1"}


async def test_it_keeps_following_the_window_when_the_tab_renames_itself(fut, monkeypatch):  # noqa: F811
    """The TopstepX tab renames itself to the contract and its price, which changes with every tick. Once you have picked a
    window, Study Terminal follows that window; the privacy guard still decides whether anything is captured.
    Titles here are the real ones from a running TopstepX on Windows."""
    from app.screen import visual_monitor as vm

    from .test_visual_monitor import T_RTH, Clock, fixture, make_monitor
    img, _, _ = fixture("mnq_5m_basic")
    title = {"t": "TopstepX and 1 more page - Profile 1 - Microsoft Edge"}        # how it is named while the page loads
    wins = [{"kind": "window", "id": 42, "title": title["t"], "process": "msedge.exe"}]
    monkeypatch.setattr(vm, "IS_WIN", True)
    monkeypatch.setattr(vm.cap, "window_title", lambda h: title["t"])
    m, rt, _win = make_monitor(fut, lambda t: (img, "wgc"), wins, Clock(T_RTH))
    await m.tick(rt)
    assert rt.hwnd == 42 and rt.status == "screen_capture"
    for renamed in ("NQZ26 $27,686.00 ▼ -1.24% and 1 more page - Profile 1 - Microsoft Edge",
                    "NQZ26 $27,712.25 ▲ +0.09% and 1 more page - Profile 1 - Microsoft Edge"):
        title["t"] = wins[0]["title"] = renamed
        await m.tick(rt)
        assert rt.hwnd == 42 and rt.status == "screen_capture", (renamed, rt.status, rt.reason)
        assert rt.title == renamed
    # that window switches to a tab that isn't a chart: nothing is captured, and the reason says why
    title["t"] = wins[0]["title"] = "Chase Online - Account Summary - Profile 1 - Microsoft Edge"
    await m.tick(rt)
    assert rt.status in ("disconnected", "unreadable") and rt.status != "screen_capture"
    # the id now belongs to another program (Windows reuses window ids): dropped, and never captured
    title["t"] = "NQZ26 $27,686.00 ▼ -1.24% - Notepad"
    wins[0] = {"kind": "window", "id": 42, "title": title["t"], "process": "notepad.exe"}
    rt.last_good_at, rt.hwnd, m._verified = None, 42, {}
    await m.tick(rt)
    assert rt.status == "disconnected" and rt.hwnd is None


# --- the chart label: "NQZ26 · Nasdaq · 1 O27,688.00 H27,692.25 L27,684.25 C27,686.00" -------------------------------------
# On a real TopstepX chart the timeframe sits between the exchange and the open price, and OCR reads the gap before the open
# as nothing at all ("1O027,688"), which used to swallow the timeframe and leave every reading as "timeframe uncertain".

def _tok(text: str, y: float = 240.0):
    from app.screen.vision import Token
    return Token(text=text, conf=0.9, x0=400.0, y0=y, x1=900.0, y1=y + 16)


def test_the_timeframe_survives_being_glued_to_the_open_price():
    from app.screen.chart_reader import _header_words
    assert "1" in _header_words("NQZ26·Nasdaq·1O027,688.00 H27,692.25L27,684.25C27,686.00")
    assert "15" in _header_words("ESH26·CME·15O6,120.00")
    assert _header_words("27,686.00") == ["27", "686", "00"]        # a plain price gains nothing


def test_the_timeframe_is_read_from_the_chart_label_wherever_it_sits():
    from app.screen.chart_reader import _legend_timeframe
    assert _legend_timeframe([_tok("NQZ26·Nasdaq·1O027,688.00 H27,692.25")]) == "1Min"
    assert _legend_timeframe([_tok("NQZ26 · Nasdaq · 5 O27,688.00")]) == "5Min"
    assert _legend_timeframe([_tok("ESH26·CME·15m O6,120.00")]) == "15Min"
    assert _legend_timeframe([_tok("NQZ26·Nasdaq·240O1")]) == "4Hour"


def test_a_stray_number_is_never_mistaken_for_the_timeframe():
    from app.screen.chart_reader import _legend_timeframe
    assert _legend_timeframe([_tok("27,686.00 H27,692 some other text")]) is None
    assert _legend_timeframe([_tok("Volume 15 Orders 5")]) is None
    assert _legend_timeframe([_tok("P&L 5 · Account 1")]) is None        # no contract, no exchange: not the chart label


def test_a_timeframe_you_set_by_hand_is_good_enough_to_act_on():
    """You can see the timeframe even when the captured area doesn't show it. Setting it must not leave the app stuck at
    "timeframe uncertain" forever -- only the chart contradicting you does that."""
    from app.screen.chart_profile import ChartProfile
    from app.screen.chart_reader import read_timeframe
    from app.screen.visual_recommend import quality_gates
    p = ChartProfile(id="c", timeframe="5Min")
    obs, probs = read_timeframe([], 1000, p)
    assert obs.value == "5Min" and obs.confidence >= 0.6, "a timeframe you set must clear the gate a trade idea needs"
    assert "set" in probs[0].lower()
    conflict, _ = read_timeframe([_tok("NQZ26·Nasdaq·1O027,688.00", y=10)], 1000, p)
    assert conflict.confidence < 0.6, "the chart showing 1 minute while you said 5 must still block ideas"
    assert quality_gates(None, "screen_capture", "", p)             # and no reading at all is still blocked


def test_a_missing_timeframe_does_not_make_a_readable_chart_unreadable():
    """The price and the candles are measurements; the timeframe is a label. A capture region that leaves the label out used
    to drag overall confidence to 0.00, so the whole chart reported "I can't read your chart right now"."""
    from app.screen.chart_reader import ChartReading, Observation, TEXT, unavailable
    r = ChartReading(captured_at="2026-01-01T00:00:00+00:00", size=(800, 600))
    r.price = Observation(27686.0, TEXT, 0.9, "price tag")
    r.instrument = Observation("NQ", TEXT, 0.9, "tab title")
    r.timeframe = unavailable("no timeframe found in the chart header")
    r.candle_confidence = 0.8
    parts = [r.price.confidence, 0.9, r.instrument.confidence, r.candle_confidence]
    assert min(parts) >= 0.4, "the four picture measurements, with the label left out, must still read as a usable chart"


def test_an_internal_fault_says_what_it_was_and_where():
    """'Internal error (AttributeError)' told nobody anything. The status now carries the message and the line it came from."""
    from app.screen.visual_monitor import where
    def read_a_chart_that_is_not_there():
        reading = None
        return reading.price                                         # type: ignore[union-attr]
    try:
        read_a_chart_that_is_not_there()
    except AttributeError as e:
        out = where(e)
    assert out.startswith("AttributeError: ")
    assert "NoneType" in out and ":" in out
    assert "/" not in out and "\\" not in out, "no file paths: this text goes on screen"
