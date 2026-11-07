"""Lessons, quizzes, progress, personalized recommendations, and real-chart exercises."""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..analysis.features import build
from ..db.models import LearningProgressRecord
from ..db.session import Database
from ..market_data.types import Timeframe
from ..signals.setups import SETUPS, SetupParams, detect
from .content import GLOSSARY, LESSONS

BY_ID = {l["id"]: l for l in LESSONS}
SETUP_LESSON = {"vwap_reclaim": "vwap", "vwap_rejection": "vwap", "orb_long": "breakouts", "orb_short": "breakouts",
                "level_breakout": "breakouts", "level_breakdown": "breakouts", "trend_pullback_long": "ma",
                "trend_pullback_short": "ma", "failed_breakdown": "structure", "failed_breakout": "structure"}


class EducationService:
    def __init__(self, db: Database, analysis=None):
        self.db, self.analysis = db, analysis
        self._exercises: dict[str, dict] = {}

    def lessons(self) -> list[dict]:
        prog = self.progress()
        return [{k: l[k] for k in ("id", "title", "module", "level", "minutes", "prerequisites")} |
                {"completed": l["id"] in prog["completed"], "best_quiz": prog["quiz_best"].get(l["id"]),
                 "has_exercise": bool(l["exercise"])} for l in LESSONS]

    def lesson(self, lid: str) -> dict | None:
        l = BY_ID.get(lid)
        if not l:
            return None
        return {**l, "quiz": [{k: q[k] for k in ("q", "options")} for q in l["quiz"]],  # answers stay server-side
                "prerequisite_titles": [BY_ID[p]["title"] for p in l["prerequisites"] if p in BY_ID]}

    def grade(self, lid: str, answers: list[int]) -> dict:
        l = BY_ID[lid]
        res = []
        for q, a in zip(l["quiz"], answers):
            res.append({"q": q["q"], "your_answer": a, "correct": a == q["answer"], "answer": q["answer"], "explain": q["explain"]})
        score = round(100 * sum(r["correct"] for r in res) / len(l["quiz"]))
        self._record(lid, "quiz", score, {"results": res})
        if score >= 70:
            self._record(lid, "completed", None, {})
        return {"score": score, "passed": score >= 70, "results": res}

    def complete(self, lid: str) -> None:
        if lid in BY_ID:
            self._record(lid, "completed", None, {})

    def _record(self, lid, kind, score, data) -> None:
        with self.db.session() as s:
            s.add(LearningProgressRecord(lesson_id=lid, kind=kind, score=score, data=json.dumps(data)))

    def progress(self) -> dict:
        with self.db.session() as s:
            rows = s.scalars(select(LearningProgressRecord)).all()
            completed = sorted({r.lesson_id for r in rows if r.kind == "completed"})
            best: dict[str, float] = {}
            attempts = 0
            for r in rows:
                if r.kind == "quiz":
                    attempts += 1
                    best[r.lesson_id] = max(best.get(r.lesson_id, 0), r.score or 0)
        core = [l for l in LESSONS if l["module"] == "core"]
        return {"completed": completed, "quiz_best": best, "quiz_attempts": attempts,
                "core_done": sum(1 for l in core if l["id"] in completed), "core_total": len(core),
                "known_terms": sorted({t for l in LESSONS if l["id"] in completed for t in l["key_terms"]})}

    def recommendations(self, mistakes: list[str] | None = None) -> list[dict]:
        p = self.progress()
        recs = []
        for lid, sc in p["quiz_best"].items():
            if sc < 70:
                recs.append({"lesson": lid, "title": BY_ID[lid]["title"], "why": f"Your best quiz score here is {sc:.0f}% - worth a review."})
        for m in mistakes or []:
            lid = {"chasing": "momentum", "no_stop": "risk", "oversized": "sizing", "revenge": "psychology"}.get(m)
            if lid:
                recs.append({"lesson": lid, "title": BY_ID[lid]["title"], "why": f"Your recent trades show a '{m}' pattern."})
        for l in LESSONS:
            if l["id"] not in p["completed"] and all(pr in p["completed"] for pr in l["prerequisites"]) and l["module"] == "core":
                recs.append({"lesson": l["id"], "title": l["title"], "why": "Next lesson in the path (prerequisites done)."})
                break
        seen, out = set(), []
        for r in recs:
            if r["lesson"] not in seen:
                seen.add(r["lesson"])
                out.append(r)
        return out[:5]

    def glossary(self, q: str | None = None) -> dict:
        if not q:
            return GLOSSARY
        ql = q.lower()
        return {k: v for k, v in GLOSSARY.items() if ql in k.lower() or ql in v.lower()}

    # ---------------- real-chart exercise: spot the setup ----------------

    async def new_exercise(self, symbols: list[str]) -> dict:
        """A real historical chart cut off right at a detected setup. You call it; then see what happened."""
        if not self.analysis:
            raise RuntimeError("analysis unavailable")
        random.shuffle(symbols)
        for sym in symbols[:5]:
            ff = await self.analysis.frame(sym, Timeframe.M5)
            d = detect(ff.df, SetupParams())
            if len(d) < 3 or len(ff.df) < 150:
                continue
            ts = random.choice(list(d.index[d.index > ff.df.index[120]]) or list(d.index))
            cand = d.loc[[ts]].iloc[0]
            i = ff.df.index.get_loc(ts)
            bars = ff.df.iloc[max(0, i - 120): i + 1]
            future = ff.df.iloc[i + 1: i + 25]
            eid = f"{sym}-{int(ts.timestamp())}"
            options = sorted({cand["setup"], *random.sample([s for s in SETUPS if s != cand["setup"]], 3)})
            self._exercises[eid] = {"answer": cand["setup"], "direction": cand["direction"], "symbol": sym,
                                    "trigger": float(cand["trigger"]), "stop": float(cand["stop"]),
                                    "future": [_bar(t, r) for t, r in future.iterrows()]}
            return {"id": eid, "symbol": sym, "timeframe": "5Min", "bars": [_bar(t, r) for t, r in bars.iterrows()],
                    "vwap": [{"time": int(t.timestamp()), "value": round(float(v), 4)} for t, v in bars["vwap"].dropna().items()],
                    "question": "Which setup just formed on the last candle?",
                    "options": [{"id": o, "label": SETUPS[o][1]} for o in options],
                    "note": "Real historical data. The chart stops at the signal candle; the future is hidden until you answer."}
        raise RuntimeError("Couldn't find a usable chart right now; try again.")

    def answer_exercise(self, eid: str, choice: str) -> dict:
        ex = self._exercises.pop(eid, None)
        if not ex:
            raise KeyError(eid)
        fut = ex["future"]
        long = ex["direction"] == "long"
        hit_trigger = any((b["high"] >= ex["trigger"]) if long else (b["low"] <= ex["trigger"]) for b in fut)
        hit_stop = any((b["low"] <= ex["stop"]) if long else (b["high"] >= ex["stop"]) for b in fut)
        correct = choice == ex["answer"]
        self._record(SETUP_LESSON.get(ex["answer"], "candles"), "exercise", 100.0 if correct else 0.0, {"choice": choice, **{k: ex[k] for k in ("answer", "symbol")}})
        return {"correct": correct, "answer": ex["answer"], "answer_label": SETUPS[ex["answer"]][1], "direction": ex["direction"],
                "trigger": ex["trigger"], "stop": ex["stop"], "future": fut,
                "what_happened": ("Price never reached the trigger - no trade would have happened." if not hit_trigger else
                                  "Price triggered the entry and later hit the stop." if hit_stop else
                                  "Price triggered the entry and hadn't hit the stop within the next 2 hours."),
                "lesson": SETUP_LESSON.get(ex["answer"])}


def _bar(t, r) -> dict:
    return {"time": int(t.timestamp()), "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]),
            "close": float(r["close"]), "volume": float(r["volume"])}
