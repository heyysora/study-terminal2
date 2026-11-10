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
    cal = st.screen.calibration._rows() if getattr(st.screen, "calibration", None) else []
    capture_days = dict(st.visual.capture_stats.days) if getattr(st, "visual", None) else {}
    risk = f.account()["risk"]
    return trust.build(cal_rows=cal, capture_days=capture_days, decisions=f.all_decisions(), evidence=f.evidence,
                       trips=f.journal("practice")["trades"], rules=risk.get("official", {}), personal=asdict(f.engine.personal),
                       rules_confirmed=bool(f.engine.rules.confirmed))
