"""Trust & Validation dashboard API. Read-only: it reports evidence; it can't change any status or enable anything."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Request

from ..validation import trust

router = APIRouter(prefix="/api/trust", tags=["trust"])


@router.get("")
def trust_status(request: Request):
    st = request.app.state
    f = st.futures
    cal = list(st.screen.calibration._rows()) if getattr(st.screen, "calibration", None) else []
    dh = getattr(st, "datahealth", None)
    if dh is not None and dh.chartwatch is not None:          # automatic evidence: no labelling by hand needed
        cal += dh.chartwatch.trust_rows()
    profiles = [rt.profile for rt in st.visual.runtimes.values()] if getattr(st, "visual", None) else []
    indicators_used = any(p.vwap_color or p.ema_colors for p in profiles) if profiles else True
    capture_days = dict(st.visual.capture_stats.days) if getattr(st, "visual", None) else {}
    risk = f.account()["risk"]
    out = trust.build(cal_rows=cal, capture_days=capture_days, decisions=f.all_decisions(), evidence=f.evidence,
                       trips=f.journal("practice")["trades"], rules=risk.get("official", {}), personal=asdict(f.engine.personal),
                       rules_confirmed=bool(f.engine.rules.confirmed), indicators_used=indicators_used)
    ar = getattr(f, "autoresearch", None)
    a = f.automation.state
    out["unattended"] = {
        "chart_checks": "Your chart's readings are checked automatically while it's open." if cal else
                        "Nothing yet: open your TopstepX chart so its readings can be checked automatically.",
        "strategy_testing": (f"Strategies are re-tested by the app every {ar.every.days} days on newer market data." if ar and ar.enabled
                             else "Weekly strategy testing is switched off (Settings > research.weekly)."),
        "practice_trades": ("Practice trades are placed automatically for strategies that pass testing. "
                            + (f"Passing now: {sum(len(v) for v in ((ar.status().get('validated_now') or {}) if ar else {}).values())}."
                               if ar else "")
                            if a.mode == "paper_auto" else
                            "You place every practice trade yourself (Automation Center). The practice record grows only as fast as you trade."),
        "note": "These levels can't be rushed: they need real evidence over real days. Nothing here is skipped or assumed."}
    return out
