"""Audit fixes for the two misleading numbers: accuracy counted by session, and no evidence labels on the in-sample cost table."""
from app.futures.research import in_sample_only
from app.validation import trust as T

from .test_futures_api import client  # noqa: F401 - fixture


def rows(per_day: dict[str, tuple[int, int]], field="price"):
    out, i = [], 0
    for day, (ok, n) in per_day.items():
        for j in range(n):
            out.append({"id": f"s{i}", "at": f"{day}T15:{j % 60:02d}:00", "platform": "topstepx-visual: NQ 5m", "synthetic": False,
                        "result": {field: {"ok": j < ok, "read": 1, "truth": 1}}})
            i += 1
    return out


def test_one_session_can_never_pass_however_many_screenshots():
    r = T.ocr_price(rows({"2026-11-16": (60, 60)}))
    assert r["status"] == T.IN_PROGRESS and r["metrics"]["sessions"] == 1


def test_misreads_bunched_in_one_session_widen_the_range():
    bunched = T.ocr_price(rows({"2026-11-16": (20, 20), "2026-11-17": (20, 20), "2026-11-18": (14, 20)}))["metrics"]
    spread = T.ocr_price(rows({"2026-11-16": (18, 20), "2026-11-17": (18, 20), "2026-11-18": (18, 20)}))["metrics"]
    assert bunched["accuracy"] == spread["accuracy"] == 0.9
    assert bunched["design_effect"] > 1 and bunched["effective_samples"] < 60
    assert bunched["ci95"][1] - bunched["ci95"][0] > spread["ci95"][1] - spread["ci95"][0]


def test_cost_table_has_no_evidence_labels():
    out = in_sample_only({"1 tick": {"avg_r": 0.4, "tier": "promising", "tier_text": "Positive out-of-sample..."}})
    assert "tier" not in out["1 tick"] and "in-sample" in out["1 tick"]["sample"]


async def test_info_serves_the_cost_table_without_labels(client):  # noqa: F811
    c, _ = client
    ev = (await c.get("/api/futures/info")).json()["evidence"]
    tables = [v["cost_sensitivity"] for v in ev.values() if v.get("cost_sensitivity")]
    assert tables and all("tier" not in m for t in tables for m in t.values())
