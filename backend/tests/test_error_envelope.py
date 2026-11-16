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
