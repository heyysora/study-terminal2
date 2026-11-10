"""Plain-language layer: words only. These tests keep every reason the app can produce explained, and keep the
frontend word list identical to the backend one."""
import json
import re
from pathlib import Path

from app import plain
from app.futures import pipeline

ROOT = Path(__file__).resolve().parents[2]


def test_frontend_word_list_matches_backend():
    on_disk = json.loads((ROOT / "frontend" / "src" / "plain.json").read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(plain.export())), "run: python -m app.plain > ../frontend/src/plain.json"


def _literals(path: Path, pattern: str) -> list[str]:
    out = []
    for m in re.finditer(pattern, path.read_text(encoding="utf-8")):
        out.append(re.sub(r"\{[^}]*\}", "12", m.group(1)))
    return out


def test_every_pipeline_reason_has_plain_words():
    src = ROOT / "backend" / "app" / "futures" / "pipeline.py"
    reasons = _literals(src, r'done\("\w+",\s*f?"([^"]+)"')
    assert len(reasons) >= 15
    missing = [r for r in reasons if not plain.plain_reason(r)["matched"]]
    assert not missing, f"add plain words in app/plain.py for: {missing}"


def test_every_chart_quality_reason_has_plain_words():
    src = ROOT / "backend" / "app" / "screen" / "visual_recommend.py"
    body = src.read_text(encoding="utf-8")
    gates = body[body.index("def quality_gates"):body.index("def build")]
    reasons = [re.sub(r"\{[^}]*\}", "12", m.group(1)) for m in re.finditer(r'return f?"([^"]+)"', gates)]
    assert len(reasons) >= 8
    reasons = [r for r in reasons if re.search("[a-z]{4}", r)]          # drop the pure "{STATUS}: {reason}" template
    from app.screen.visual_monitor import LABEL_TEXT
    reasons += [f"{s.upper()}: something" for s in LABEL_TEXT if s != "screen_capture"]   # every non-working chart status
    missing = [r for r in reasons if not plain.plain_reason(r)["matched"]]
    assert not missing, missing


def test_risk_messages_have_plain_words_and_keep_their_numbers():
    r = plain.plain_reason("This trade risks $180.50 with slippage and fees; your per-trade limit is $150.")
    assert r["matched"] and "$180.50" in r["headline"] and "$150 per trade" in r["headline"] and r["kind"] == "risk"
    for msg in ["Reward-to-risk to the first target is 1.20; your minimum is 1.5.", "A stop loss is required.",
                "The stop loss ($300.00) is bigger than what's left of the Daily Loss Limit ($120.00).",
                "The stop loss ($300.00) is bigger than what's left of your own daily limit ($120.00).",
                "Open risk would be $900.00; your limit is $600.",
                "3 ES would put you at 6 mini-equivalent contracts; the limit is 5",
                "Market data is 300 s old (your limit is 180 s). Entries wait for fresh data.",
                "ES isn't trading right now (maintenance break, weekend or holiday)."]:
        assert plain.plain_reason(msg)["matched"], msg


def test_every_outcome_reads_as_wait_unless_it_passed_everything():
    for o in pipeline.OUTCOMES:
        assert o in plain.ACTIONS, o
        tone = plain.plain_action(o)["tone"]
        assert (tone == "idea") == (o == "APPROVED"), o
    for shown in pipeline.ACTION_OF.values():
        assert plain.plain_action(shown)["word"] == "WAIT"
    assert plain.plain_action("something new")["word"] == "WAIT"            # unknown never becomes an idea
    assert plain.plain_action(None)["word"] == "WAIT"


def test_only_live_statuses_read_as_working_and_delayed_is_never_called_live():
    ok = {k for k, v in plain.STATUSES.items() if v["level"] == "ok"}
    assert ok == {"realtime", "near_realtime", "polling", "screen_capture"}
    for s in ("delayed", "historical", "replay", "cached", "stale", "unreadable", "disconnected", "unavailable"):
        w = plain.plain_status(s)
        assert w["level"] != "ok" and "Working" not in w["word"] and "live" not in w["word"].lower()
    assert plain.plain_status("never heard of it")["level"] == "bad"


def test_unknown_reasons_pass_through_and_nothing_is_invented():
    r = plain.plain_reason("Quantum flux exceeded 7.25 at 14:02.")
    assert not r["matched"] and r["headline"] == "Quantum flux exceeded 7.25 at 14:02." and r["do"] == "" and r["original"] == r["headline"]
    assert plain.plain_reason(None)["matched"] is False


def test_simplify_only_touches_known_words():
    assert plain.simplify("how long is RTH") == "how long is main trading hours"       # lowercase "long" is an ordinary word
    assert plain.simplify("Potential LONG at 24974.50") == "Potential UP at 24974.50"
    assert plain.simplify("paper account balance 50,000.25") == "practice account balance 50,000.25"
    assert plain.simplify("") == "" and plain.simplify(None) == ""


def test_confidence_is_words_not_a_probability():
    assert [plain.confidence_word(x) for x in (0.95, 0.8, 0.7, 0.59, None)] == ["High", "High", "Medium", "Low", "Unknown"]
    assert "not about the trade working" in plain.TERMS["data_confidence"]["explain"]


def test_every_term_has_everyday_words_and_an_explanation():
    for k, t in plain.TERMS.items():
        assert t["simple"] and t["technical"] and len(t["explain"]) > 20, k
