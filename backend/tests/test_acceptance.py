"""The acceptance test is the thing that decides whether to tell the user their chart works. So the property that
matters most about it is not that it passes -- it is that it cannot pass by accident.

These tests attack it from that side: no backend, a backend that lies, a chart that reads nothing, a price that
disagrees with the window title, a market that disagrees with the tab. In every case the verdict must come back
negative and say which stage, because a false "your chart works" is worse than no test at all.
"""
from __future__ import annotations

from app.acceptance import BLOCKED, FAIL, PASS, Acceptance


def _stage(rep: dict, sid: str) -> dict:
    return next(s for s in rep["stages"] if s["id"] == sid)


def test_with_nothing_running_it_proves_nothing_and_says_so():
    rep = Acceptance().run("http://127.0.0.1:9")            # nothing listens on port 9
    assert rep["real_chart_reading_proved"] is False
    assert "NOT been shown to read your real chart" in rep["verdict"]
    assert _stage(rep, "backend")["status"] == BLOCKED
    for sid in ("window", "capture", "read", "validate", "fresh"):
        assert _stage(rep, sid)["status"] in (BLOCKED, FAIL), sid
    # the stages that genuinely can be checked anywhere still are: this must not become a test that checks nothing
    assert _stage(rep, "ocr")["status"] == PASS
    assert _stage(rep, "subsystems")["status"] == PASS


def test_the_verdict_needs_all_five_chart_stages(monkeypatch):
    """Reading a chart is only proved when the window was found, captured, read, checked and stamped. Four out of
    five is not four fifths of a proof -- it is no proof."""
    a = Acceptance()
    for sid in ("window", "capture", "read", "validate", "fresh"):
        a.add(sid, sid, PASS)
    assert a.report()["real_chart_reading_proved"] is True
    a2 = Acceptance()
    for sid in ("window", "capture", "read", "validate"):
        a2.add(sid, sid, PASS)
    a2.add("fresh", "fresh", BLOCKED, "market closed")
    assert a2.report()["real_chart_reading_proved"] is False, "a blocked freshness check is not a pass"


def test_a_price_that_disagrees_with_the_window_title_is_a_failure():
    """The strongest check available without a data feed: the price read off the pixels against the price TopstepX
    itself writes into the tab's name. If those disagree, something is being read wrong and no signal is safe."""
    a = Acceptance()
    win = {"title": "NQZ26 $27,686.00 ▼ -1.24% and 1 more page - Profile 1 - Microsoft Edge", "hwnd": 1}
    reading = {"ok": True, "instrument": {"value": "NQ", "source": "chart text"},
               "timeframe": {"value": "1Min", "source": "chart text"},
               "price": {"value": 27_586.00, "source": "price tag"}}        # 100 points out
    a.s10_validate(reading, win)
    st = _stage(a.report(), "validate")
    assert st["status"] == FAIL
    assert "differ by" in st["detail"]
    assert st["evidence"]["price_in_window_title"] == 27_686.0


def test_a_price_that_agrees_with_the_window_title_passes():
    a = Acceptance()
    win = {"title": "NQZ26 $27,686.00 ▼ -1.24% and 1 more page - Profile 1 - Microsoft Edge", "hwnd": 1}
    reading = {"ok": True, "instrument": {"value": "NQ", "source": "chart text"},
               "timeframe": {"value": "1Min", "source": "chart text"},
               "price": {"value": 27_686.25, "source": "price tag"}}
    a.s10_validate(reading, win)
    st = _stage(a.report(), "validate")
    assert st["status"] == PASS and st["evidence"]["difference"] == 0.25


def test_the_market_disagreeing_with_the_tab_is_a_failure():
    a = Acceptance()
    win = {"title": "ESZ26 $6,120.25 - Profile 1 - Microsoft Edge", "hwnd": 1}
    reading = {"ok": True, "instrument": {"value": "NQ", "source": "chart text"},
               "timeframe": {"value": "1Min", "source": "chart text"},
               "price": {"value": 6_120.25, "source": "price tag"}}
    a.s10_validate(reading, win)
    assert _stage(a.report(), "validate")["status"] == FAIL


def test_a_reading_with_no_timeframe_does_not_pass_validation():
    a = Acceptance()
    reading = {"ok": True, "instrument": {"value": "NQ", "source": "tab title"},
               "timeframe": {"value": None, "source": "not readable"},
               "price": {"value": 27_686.0, "source": "price tag"}}
    a.s10_validate(reading, None)
    st = _stage(a.report(), "validate")
    assert st["status"] == FAIL and "timeframe" in st["detail"]


def test_a_stale_reading_fails_the_freshness_check():
    from datetime import datetime, timedelta, timezone
    a = Acceptance()
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    a.s11_freshness({"captured_at": old})
    assert _stage(a.report(), "fresh")["status"] == FAIL

    b = Acceptance()
    b.s11_freshness({"captured_at": datetime.now(timezone.utc).isoformat()})
    assert _stage(b.report(), "fresh")["status"] == PASS

    c = Acceptance()
    c.s11_freshness({})                                      # no stamp at all
    assert _stage(c.report(), "fresh")["status"] == FAIL


def test_a_stage_that_throws_is_a_failure_not_a_crash():
    a = Acceptance()

    def boom():
        raise RuntimeError("the window vanished")
    st = a._run("x", "something", boom)
    assert st.status == FAIL and "RuntimeError: the window vanished" in st.detail
    assert "traceback" in st.evidence


def test_the_written_report_carries_the_evidence(tmp_path):
    from app.acceptance import write_report
    a = Acceptance()
    a.add("window", "Your Edge window", PASS, "NQZ26 at 27,686.00", {"title": "NQZ26 $27,686.00"})
    j, m = write_report(a.report(), tmp_path)
    text = m.read_text(encoding="utf-8")
    assert "NQZ26" in text and "**PASS**" in text
    assert "NOT been shown" in text, "with only one stage passing it must not read as a success"
    import json
    assert json.loads(j.read_text(encoding="utf-8"))["counts"]["PASS"] == 1


# ---------------------------------------------------------------- which window is it actually looking at

def _png(w=400, h=300, text="NQZ26"):
    import cv2
    import numpy as np
    img = np.full((h, w, 3), 20, dtype=np.uint8)
    cv2.putText(img, text, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (240, 240, 240), 2)
    return cv2.imencode(".png", img)[1].tobytes()


def test_the_window_diagnostic_reports_each_window_separately(tmp_path, monkeypatch):
    """When the app says it can't read a chart that is plainly on screen, the question is which window it looked
    at. With several Edge windows open this is the only thing that answers it."""
    import httpx

    from app import acceptance
    windows = {"windows": [
        {"kind": "window", "id": 1, "title": "NQZ26 $27,686.00 - Profile 1 - Microsoft Edge", "process": "msedge.exe"},
        {"kind": "window", "id": 2, "title": "TopstepX - Log in - Microsoft Edge", "process": "msedge.exe"},
        {"kind": "window", "id": 3, "title": "Notepad", "process": "notepad.exe"},
    ]}

    def fake_get(url, **kw):
        if "windows" in url:
            return httpx.Response(200, json=windows)
        hwnd = kw.get("params", {}).get("hwnd")
        return httpx.Response(200, content=_png(text="Password" if hwnd == 2 else "NQZ26 27686"))
    monkeypatch.setattr(httpx, "get", fake_get)
    rep = acceptance.diagnose_windows("http://127.0.0.1:1", tmp_path)
    assert rep["supported"] and rep["browser_windows"] == 2, "the text editor is not a browser and is not captured"
    first, second = rep["windows"]
    assert first["looks_like_a_topstepx_chart"] is True
    assert second["looks_like_a_topstepx_chart"] is False
    assert "window-1.png" in first["picture_saved"]
    # the login window had a credential word on it, so its picture is deliberately not kept
    assert second["credential_word"] and "not kept" in second["picture_saved"]
    assert not (tmp_path / "window-2.png").exists(), "a screen with a credential word must never be written to disk"

