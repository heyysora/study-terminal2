"""Does each part of Study Terminal actually work IN THIS BUILD?

0.18.1 taught the lesson this file exists for. Unit tests run against the source tree, where every file is on disk, so
they cannot tell you anything about what ended up inside the .exe. The screen-text reader was missing three modules
from the packaged app and 657 tests still passed, CI was green, and the first person to find out was the user.

So: ask the built application. Each check here does the smallest piece of real work that proves a subsystem is wired
up -- fit a model, open a database, build a calendar, decode an image, construct an exchange client -- rather than
importing a name and hoping. `StudyTerminal.exe --deps-check` runs them all, scripts/windows-reliability.ps1 runs that
against the freshly built installer, and the release fails if any of them fail.

Nothing here touches the user's data, the network, or any account: every check works on scratch values in memory.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

log = logging.getLogger(__name__)

PASS, FAIL = "pass", "fail"


def _cv2() -> str:
    import cv2
    import numpy as np
    img = np.zeros((40, 80, 3), dtype=np.uint8)
    img[10:30, 20:60] = 255
    grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    n, _ = cv2.findContours(grey, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[:2]
    assert len(n) == 1, "contour detection is wrong"
    assert cv2.resize(img, (20, 20)).shape == (20, 20, 3)
    return f"opencv {cv2.__version__}"


def _numpy_pandas() -> str:
    import numpy as np
    import pandas as pd
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    assert float(df["a"].rolling(2).mean().iloc[-1]) == 2.5
    assert float(np.std([1.0, 2.0, 3.0])) > 0
    return f"numpy {np.__version__}, pandas {pd.__version__}"


def _sklearn() -> str:
    """The strategy code fits models. A missing sklearn sub-package only shows up when one is actually fitted."""
    import numpy as np
    from sklearn.ensemble import RandomForestClassifier
    x = np.array([[0.0], [1.0], [0.0], [1.0]])
    y = np.array([0, 1, 0, 1])
    m = RandomForestClassifier(n_estimators=4, random_state=0).fit(x, y)
    assert list(m.predict([[1.0]])) == [1]
    import sklearn
    return f"scikit-learn {sklearn.__version__}"


def _database() -> str:
    import sqlalchemy as sa
    eng = sa.create_engine("sqlite://")                      # in memory: never touches the user's file
    with eng.begin() as con:
        con.execute(sa.text("create table t (a int)"))
        con.execute(sa.text("insert into t values (7)"))
        assert con.execute(sa.text("select a from t")).scalar() == 7
    return f"sqlalchemy {sa.__version__}"


def _calendars() -> str:
    """Market hours are computed locally from this; a missing calendar module would silently mislabel sessions."""
    import exchange_calendars as xc
    cal = xc.get_calendar("XNYS")
    assert cal.is_session("2026-01-05"), "a normal Monday should be a trading day"
    assert not cal.is_session("2026-01-04"), "a Sunday should not be"
    return f"exchange_calendars {xc.__version__}, XNYS loaded"


def _onnx() -> str:
    import onnxruntime as ort
    providers = ort.get_available_providers()
    assert providers, "no execution providers"
    return f"onnxruntime {ort.__version__} ({', '.join(providers[:2])})"


def _ocr() -> str:
    from .screen import ocr_health
    r = ocr_health.check(deep=True)
    if not r["ok"]:
        raise RuntimeError(r["headline"] + " " + r["advice"])
    return r["versions"].get("rapidocr_onnxruntime", "?")


def _exchanges() -> str:
    """ccxt builds its exchange classes from a generated list, so a packaging gap shows up on construction, not import.
    This builds one and confirms the read-only lock is on; it makes no network call."""
    from .market_data import exchanges
    info = exchanges.lock_check()
    if not info.get("locked"):
        raise RuntimeError(f"the read-only lock is not on: {info.get('detail')}")
    return info.get("detail", "locked")[:80]


def _timezones() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    ny = datetime(2026, 7, 1, 12, tzinfo=ZoneInfo("America/New_York"))
    assert ny.utcoffset().total_seconds() == -4 * 3600, "summer time is wrong; the tz database is missing or stale"
    return "America/New_York resolved"


def _app_imports() -> str:
    """Every page the app serves is backed by a router. One missing module in the bundle is a dead page."""
    from .main import create_app                        # noqa: F401
    from .screen import chart_reader, visual_monitor, visual_recommend   # noqa: F401
    return "api and chart modules import"


CHECKS: list[tuple[str, str, Callable[[], str]]] = [
    ("imports", "App modules", _app_imports),
    ("cv2", "Image handling", _cv2),
    ("numpy", "Maths and tables", _numpy_pandas),
    ("sklearn", "Model fitting", _sklearn),
    ("database", "Database", _database),
    ("calendars", "Market calendars", _calendars),
    ("timezones", "Time zones", _timezones),
    ("onnx", "Model runtime", _onnx),
    ("ocr", "Screen-text reader", _ocr),
    ("exchanges", "Crypto price library (read-only)", _exchanges),
]


def subsystems() -> dict:
    """Run every check. Never raises: a failure is a result, not an exception."""
    t0 = time.monotonic()
    out = []
    for cid, name, fn in CHECKS:
        start = time.monotonic()
        try:
            detail = fn()
            out.append({"id": cid, "name": name, "status": PASS, "detail": detail, "ms": int((time.monotonic() - start) * 1000)})
        except Exception as e:  # noqa: BLE001
            log.exception("subsystem check %s failed", cid)
            msg = str(e).strip().splitlines()[0][:200] if str(e).strip() else ""
            out.append({"id": cid, "name": name, "status": FAIL, "ms": int((time.monotonic() - start) * 1000),
                        "detail": f"{type(e).__name__}{': ' + msg if msg else ''}"})
    bad = [c for c in out if c["status"] == FAIL]
    return {"ok": not bad, "checks": out, "failed": [c["id"] for c in bad], "took_ms": int((time.monotonic() - t0) * 1000),
            "headline": "Every part of Study Terminal works in this build." if not bad
                        else f"{len(bad)} part(s) of Study Terminal don't work in this build: {', '.join(c['name'] for c in bad)}."}
