"""The 0.18.1 "Unexpected token 'I', "Internal S"... is not valid JSON" fault: a crashing endpoint answered with the
plain words "Internal Server Error" and the page parsed that blind. A crash must answer in JSON."""
import httpx
import pytest

from fastapi.routing import APIRoute

from app.main import create_app
from .fakes import FakeProvider, always_open_clock


@pytest.fixture
async def crashy(settings):
    """Like the normal client, but the transport returns the 500 instead of re-raising, which is what a browser sees."""
    settings.anthropic_api_key = None
    app = create_app(settings, provider=FakeProvider(), clock=always_open_clock(), start_loops=False)

    async def _crash():
        reading = None
        return reading.price                        # the shape of the real OCR fault

    # Ahead of the "/" mount that serves the page, which otherwise swallows any path added after start-up.
    app.router.routes.insert(0, APIRoute("/api/_crash_test", _crash, methods=["GET"]))

    async with app.router.lifespan_context(app):
        tr = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=tr, base_url="http://t", timeout=60, headers={"X-Study-Terminal": "1"}) as c:
            yield c


async def test_a_crashing_endpoint_answers_in_json(crashy):
    r = await crashy.get("/api/_crash_test")
    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/json"), "plain text here is what broke the page in 0.18.1"
    d = r.json()["detail"]
    assert d["kind"] == "internal" and d["where"] == "/api/_crash_test"
    assert d["error"].startswith("AttributeError") and ".py:" in d["error"], d["error"]
    assert "/" not in d["error"] and "\\" not in d["error"], "no file paths in a message the user sees"
    assert "log file" in d["message"]


async def test_a_refused_request_still_says_why(crashy):
    r = await crashy.put("/api/settings", json={"ui.mode": "expert"})
    assert r.status_code == 422 and r.headers["content-type"].startswith("application/json")


async def test_an_unknown_api_path_is_refused(crashy):
    """In a packaged build the page files are mounted at "/" and answer an unknown /api/ path in plain text; with no
    page files it is JSON. The browser helper has to cope with either, which is why it checks before it parses."""
    r = await crashy.get("/api/_no_such_endpoint")
    assert r.status_code == 404


async def test_a_dead_text_reader_is_reported_as_itself_not_as_a_parse_error(crashy, monkeypatch):
    """The 0.18.1 chart-setup error. Reading a chart hit the dead text reader, the backend answered with the plain
    words "Internal Server Error", and the setup page showed "Unexpected token 'I', "Internal S"... is not valid
    JSON". The answer must be JSON, must say the reader is the problem, and must carry the repair."""
    import cv2
    import numpy as np

    from app.screen import vision

    def dead():
        raise vision.OcrUnavailable("AttributeError: module 'ch_ppocr_v3_det' has no attribute 'TextDetector'",
                                    "Reinstalling the latest version fixes it.")
    monkeypatch.setattr(vision, "_start_engine", dead)
    monkeypatch.setattr(vision, "_OCR", None)
    monkeypatch.setattr(vision, "_OCR_FAILED", None)

    # Big enough, and not a flat colour: both are checked before the reader is ever asked for text.
    img = np.full((400, 700, 3), 20, dtype=np.uint8)
    cv2.putText(img, "NQZ26 27686.00", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (235, 235, 235), 2)
    for i in range(12):
        cv2.rectangle(img, (40 + i * 50, 120 + i * 8), (60 + i * 50, 300 - i * 5), (90, 200, 120), -1)
    png = cv2.imencode(".png", img)[1].tobytes()
    r = await crashy.post("/api/visual/upload-read", files={"file": ("chart.png", png, "image/png")},
                          data={"profile": '{"name": "x"}'})
    assert r.headers["content-type"].startswith("application/json"), "plain text here is the bug the user hit"
    assert "Unexpected token" not in r.text
    assert r.status_code == 503, r.text[:200]
    d = r.json()["detail"]
    assert d["kind"] == "ocr_unavailable"
    assert "reads text off your screen" in d["message"] and "Reinstalling" in d["message"]
    assert "ch_ppocr_v3_det" in d["error"], "the technical cause is kept for support, just not as the headline"
