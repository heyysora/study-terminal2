"""Trading safety audit (docs/POST_FEATURE_AUDIT.md, Phase 3). Each test proves one safety claim against the real code.
None of these may be loosened to make them pass."""
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.main import create_app

from .fakes import FakeProvider, always_open_clock

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"


def _src():
    return {p: p.read_text(encoding="utf-8") for p in APP.rglob("*.py")}


@pytest.fixture
async def make_app(settings):
    apps = []

    async def start():
        settings.anthropic_api_key = None
        app = create_app(settings, provider=FakeProvider(), clock=always_open_clock(), start_loops=False)
        ctx = app.router.lifespan_context(app)
        await ctx.__aenter__()
        apps.append(ctx)
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=60, headers={"X-Study-Terminal": "1"})
        return app, c

    async def stop():
        ctx = apps.pop()
        await ctx.__aexit__(None, None, None)
    yield start, stop
    while apps:
        await apps.pop().__aexit__(None, None, None)


# ---------------- 1. no real order execution exists ----------------

# documentation text that mentions an order endpoint without calling it (the live-execution checklist shown in the app)
DOC_MENTIONS = {("futures/automation.py", "ProjectX documents /api/Order/place")}
# every file allowed to make outbound network requests, and what for
NETWORK_FILES = {
    "ai/providers.py": "optional AI: local Ollama (free) or the Anthropic API if you add your own key",
    "futures/projectx.py": "optional TopstepX API, read-only paths only (off unless you add a key)",
    "futures/stream.py": "optional TopstepX market-data stream, subscribe methods only (off unless you add a key)",
    "market_data/providers/yahoo_stream.py": "free Yahoo Finance price stream",
    "news/econ_data.py": "free U.S. Bureau of Labor Statistics data",
    "news/sources.py": "free news and public economic calendars",
    "memecoins/sources.py": "read-only memecoin data: DexScreener prices and Solana public chain data (no wallet, no signing)",
}


def test_no_code_can_send_an_order_to_a_broker():
    # the broker's order endpoints anywhere in the code (the local practice simulator's own order routes never leave your PC)
    order_words = re.compile(r"/api/Order|/api/Position/close|/orders?/(place|submit|cancel|modify)\b", re.I)
    for path, text in _src().items():
        rel = str(path.relative_to(APP)).replace("\\", "/")
        for m in order_words.finditer(text):
            line_text = text[text.rfind("\n", 0, m.start()) + 1: text.find("\n", m.end())]
            if any(rel == f and phrase in line_text for f, phrase in DOC_MENTIONS):
                continue
            line = text[: m.start()].count("\n") + 1
            raise AssertionError(f"order-routing text in {rel}:{line}: {m.group(0)}")
    for lib in ("alpaca", "ib_insync", "ibapi", "tradovate", "rithmic", "ninjatrader"):
        for path, text in _src().items():
            assert not re.search(rf"^\s*(import|from)\s+{lib}\b", text, re.M), f"broker library {lib} imported in {path}"
    # ccxt (crypto exchange library) was allowed on 2026-11-14 at the owner's request, for public prices only, and only inside the
    # one file that locks it to read-only. Anywhere else it is still banned. See test_exchanges.py for the lock itself.
    for path, text in _src().items():
        rel = str(path.relative_to(APP)).replace("\\", "/")
        if rel != CCXT_FILE:
            assert not re.search(r"^\s*(import|from)\s+ccxt\b", text, re.M), f"ccxt imported outside the locked file: {rel}"


CCXT_FILE = "market_data/exchanges.py"


def test_the_exchange_library_is_locked_to_public_prices():
    from app.market_data import exchanges as X
    text = (APP / CCXT_FILE).read_text(encoding="utf-8")
    body = re.sub(r'"""[\s\S]*?"""', "", "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#")))
    # the file never passes credentials to an exchange and never reads them from settings or the environment
    assert not re.search(r"""["\']apiKey["\']\s*:|["\']secret["\']\s*:|settings|store\.get|getenv|environ\[""", body)
    assert re.findall(r"environ\.get\(([^)]*)\)", body) == ['"HTTPS_PROXY"', '"https_proxy"']      # the only environment reads: the network proxy
    r = X.lock_check()
    assert r == {**r, "library": True, "locked": True} and r["checked"] >= 12
    for eid, _ in X.EXCHANGES:
        ex = X.make(eid)
        assert ex.apiKey is None and ex.secret is None
        for name in X.BLOCKED:
            with pytest.raises(X.ReadOnly):
                getattr(ex, name)()
        with pytest.raises(X.ReadOnly):
            ex.sign("AddOrder", "private", "POST", {})
        raw = [n for n in dir(ex) if n.startswith("private") and callable(getattr(ex, n))]
        assert raw, "expected raw private endpoints to exist (and be blocked)"
        for n in raw:
            with pytest.raises(X.ReadOnly):
                getattr(ex, n)()


def test_no_setting_can_hold_exchange_keys():
    from app.settings import store
    text = Path(store.__file__).read_text(encoding="utf-8").lower()
    for word in ("kraken", "coinbase", "bitstamp", "exchange_key", "exchange_secret", "ccxt"):
        assert word not in text, f"settings mention {word}"


def test_only_known_files_reach_the_network():
    net = re.compile(r"httpx\.(AsyncClient|Client|get|post)|requests\.(get|post)|websockets\.|urlopen")
    found = {str(p.relative_to(APP)).replace("\\", "/") for p, t in _src().items() if net.search(t)}
    assert found == set(NETWORK_FILES), f"new network code: {found - set(NETWORK_FILES)}; gone: {set(NETWORK_FILES) - found}"


def test_network_files_contain_no_order_methods():
    for rel in NETWORK_FILES:
        code = "\n".join(ln for ln in (APP / rel).read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#"))
        body = re.sub(r'"""[\s\S]*?"""', "", code)                # docstrings describe what is NOT there
        # an order path or an order-sending call; safety sentences like "never sends orders" are fine
        assert not re.search(r"/Order\b|Order/|\w*order\w*\s*\(", body, re.I), f"{rel} contains order-sending code"


def test_topstepx_clients_can_only_read():
    from app.futures import projectx, stream
    assert projectx.READ_ONLY_PATHS == {"/api/Auth/loginKey", "/api/Contract/search", "/api/History/retrieveBars", "/api/Account/search"}
    assert stream.ALLOWED_METHODS == {"SubscribeContractQuotes", "SubscribeContractTrades"}


async def test_the_read_only_client_refuses_any_other_path():
    from app.futures.projectx import ProjectXClient, ProjectXError
    c = ProjectXClient("u", "k")
    with pytest.raises(ProjectXError):
        await c._post("/api/Order/place", {"x": 1})


async def test_live_mode_cannot_be_turned_on(make_app):
    start, _ = make_app
    app, c = await start()
    r = await c.post("/api/futures/automation/mode", json={"mode": "live"})
    assert r.status_code >= 400
    st = (await c.get("/api/futures/automation")).json()
    assert st["mode"] != "live" and st["live"]["locked"] is True
    h = (await c.get("/api/health")).json()
    assert h["brokerage_connected"] is False and h["brokerage_required"] is False


# ---------------- 2. practice mode is always visible ----------------

async def test_home_always_reports_practice_mode_in_every_setting(make_app):
    start, _ = make_app
    _, c = await start()
    for vals in ({"ui.mode": "simple"}, {"ui.mode": "advanced"}, {"app.market_mode": "futures"}, {"app.market_mode": "equities"}):
        await c.put("/api/settings", json=vals)
        m = (await c.get("/api/home")).json()["mode"]
        assert m["practice"] is True and m["live_locked"] is True and m["label"] == "PRACTICE MODE"


def test_the_practice_badge_is_on_every_screen():
    app_tsx = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    simple = (ROOT / "frontend" / "src" / "simple.tsx").read_text(encoding="utf-8")
    # rendered unconditionally by the app shell, in both Simple and Advanced
    assert re.search(r'<div className=\{`shell ui-\$\{ui\}`\}>\s*<TopBar ', app_tsx)
    assert "<b>PRACTICE MODE</b>" in simple and "no real money" in simple
    assert "<StopEverything />" in simple


# ---------------- 3. stale or unreliable information can't produce an idea ----------------

@pytest.mark.parametrize("status", ["stale", "unreadable", "disconnected", "stopped", "paused"])
def test_any_non_live_chart_status_gives_no_trade(status):
    from app.screen import visual_recommend as vr

    from .test_visual_monitor import fixture, read
    r, _ = read("mnq_5m_basic")
    assert r.ok
    assert vr.quality_gates(r, status, "because", None)                   # refused
    rec = vr.build(r, None, None, status=status, status_reason="because", profile=None, futures=None)
    assert rec["action"] == "NO TRADE" and rec.get("entry") is None
    _ = fixture


def test_low_confidence_and_mismatched_charts_give_no_trade():
    from app.screen import visual_recommend as vr

    from .test_visual_monitor import read
    zoomed, _ = read("mnq_1m_zoomed_out")
    assert vr.quality_gates(zoomed, "screen_capture", "", None)
    wrong, _ = read("mnq_5m_basic", root="ES")
    assert vr.quality_gates(wrong, "screen_capture", "", None).startswith("Chart doesn't match its setup")


def test_every_unknown_or_blocked_outcome_reads_wait_or_stopped():
    from app import plain
    from app.futures import pipeline
    for o in pipeline.OUTCOMES:
        assert (plain.plain_action(o)["tone"] == "idea") == (o == "APPROVED")
    assert plain.plain_action("anything new")["word"] == "WAIT"


def test_unvalidated_strategies_are_never_approved():
    src = (APP / "futures" / "pipeline.py").read_text(encoding="utf-8")
    # the only APPROVED return comes after the validation check
    approved = [m.start() for m in re.finditer(r'done\("APPROVED"', src)]
    check = src.index("if not is_valid:")
    assert len(approved) == 1 and approved[0] > check


# ---------------- 4. restarting doesn't bypass safety ----------------

async def test_stop_everything_survives_a_restart(make_app):
    start, stop = make_app
    app, c = await start()
    await c.put("/api/settings", json={"app.market_mode": "futures"})
    assert (await c.post("/api/stop-everything", json={"confirm": True})).json()["ok"]
    await stop()
    app2, c2 = await start()                                              # same data folder
    st = (await c2.get("/api/futures/automation")).json()
    assert st["status"] == "emergency_stopped"
    assert (await c2.post("/api/futures/automation/start")).status_code >= 400
    h = (await c2.get("/api/home")).json()
    assert h["stopped"] is True and h["decision"]["word"] == "STOPPED"
    assert app2.state.visual.state == "stopped"


async def test_risk_locks_survive_a_restart(make_app):
    start, stop = make_app
    app, c = await start()
    eng = app.state.futures.engine
    eng.locks["mll_breached"] = datetime.now(UTC).isoformat()
    eng.consecutive_losses = getattr(eng, "consecutive_losses", 0)
    app.state.futures.save()
    blocked_before = (await c.get("/api/futures/risk")).json()["blocked"]
    await stop()
    app2, c2 = await start()
    assert app2.state.futures.engine.locks.get("mll_breached")
    r = (await c2.get("/api/futures/risk")).json()
    assert r["blocked"] is True and r["blocked"] == blocked_before


async def test_limits_and_modes_are_identical_after_restart(make_app):
    start, stop = make_app
    _, c = await start()
    await c.put("/api/futures/risk/personal", json={"max_daily_loss_usd": 300, "max_risk_per_trade_usd": 90})
    before = (await c.get("/api/futures/info")).json()["personal"]
    await stop()
    _, c2 = await start()
    assert (await c2.get("/api/futures/info")).json()["personal"] == before
    assert (await c2.get("/api/futures/automation")).json()["live"]["locked"] is True


def test_memecoin_code_cannot_sign_or_send_transactions():
    """Study Terminal practises memecoins only: no wallet, no key, no transaction can exist in its code."""
    import re
    root = Path(__file__).resolve().parents[1] / "app"
    banned = re.compile(r"sendTransaction|sendRawTransaction|simulateTransaction|requestAirdrop|\bKeypair\b|private_?key|secret_?key|"
                        r"seed ?phrase|mnemonic|from_base58|solders|solana\.rpc|anchorpy|\bsign\(", re.I)
    for f in list((root / "memecoins").glob("*.py")) + [root / "api" / "routes_meme.py"]:
        code = f.read_text(encoding="utf-8")
        hits = [m.group(0) for m in banned.finditer(code)]
        assert not hits, f"{f.name} mentions {hits}"
    rpc_methods = set(re.findall(r'_rpc\("([A-Za-z]+)"', (root / "memecoins" / "sources.py").read_text(encoding="utf-8")))
    assert rpc_methods <= {"getAccountInfo", "getTokenLargestAccounts", "getMultipleAccounts", "getSlot"}, rpc_methods     # read-only calls

