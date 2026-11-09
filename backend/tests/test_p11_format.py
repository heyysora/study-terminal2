"""P11 regression: prices in messages keep every digit (":g" turned 26952.25 into 26952.2 for NQ-sized prices)."""
from app.ai.assistant import Assistant
from app.futures.contracts import fmt_num

from .test_p8_p9 import _fctx


def test_fmt_num_keeps_tick_digits():
    assert fmt_num(26952.25) == "26952.25" and fmt_num(26952.0) == "26952" and fmt_num(7402.5) == "7402.5"
    assert fmt_num(1.5) == "1.5" and fmt_num(15) == "15" and fmt_num(None) == "None"


async def test_mentor_prints_nq_prices_exactly():
    ctx = _fctx()
    lv = ctx["futures"]["levels"]
    lv.update({"last": 26971.75, "overnight_low": 26952.25, "vwap": 26960.5, "session_high": 26990.75, "prev_day_high": 27001.25})
    a = (await Assistant().ask("Where is the nearest support?", ctx))["answer"]
    assert "26971.75" in a and "overnight low 26952.25" in a and "session high 26990.75" in a
