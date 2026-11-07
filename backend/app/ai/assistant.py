"""The AI trading assistant.

Answers are always grounded in structured data the app computed (analysis, signals, positions,
screen context, data labels). With an LLM connected, the LLM writes the explanation from that
JSON; without one, built-in templates answer the common questions. Either way, nothing is
invented: if the data isn't there, the answer says what's missing."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..education.content import GLOSSARY
from .providers import LLMProvider, NoLLM

log = logging.getLogger(__name__)

INTENTS = [
    ("too_late", r"\b(too late|late|chas|missed)\b"),
    ("fake_breakout", r"\b(fake|false)\b.*\bbreak|\bbreakout\b.*\b(real|fake)"),
    ("why_moving", r"\bwhy\b.*\b(moving|up|down|running|dump|pump)"),
    ("better", r"\b(better|other|another)\b.*\b(opportunit|setup|stock|trade)"),
    ("missing", r"\b(missing|blind spot|overlook)"),
    ("market", r"\b(market|spy|conditions|overall)\b"),
    ("stop", r"\bstop\b"),
    ("profit", r"\b(take profit|target|profits?)\b"),
    ("invalidate", r"\binvalid"),
    ("exit", r"\b(sell|exit|close|cover|hold)\b"),
    ("short", r"\bshort\b"),
    ("entry", r"\b(buy|long|enter|entry|get in)\b"),
    ("explain", r"\b(explain|what.*(happening|going on|see)|chart)\b"),
]


def classify(q: str) -> str:
    ql = q.lower()
    for name, pat in INTENTS:
        if re.search(pat, ql):
            return name
    return "explain"


def _money(x) -> str:
    return f"${x:,.2f}" if isinstance(x, (int, float)) else "n/a"


def data_caveat(ctx: dict) -> str | None:
    lab = (ctx.get("signals") or {}).get("data_label") or ctx.get("data_label")
    if not lab:
        return "I don't have a live price for this symbol right now; this uses the last closed bar."
    st = lab.get("status")
    if st in ("near_realtime", "realtime"):
        return None
    return f"Data status: {st.upper()} - {lab.get('reason')}"


def explain_chart(snap: dict, level: str = "beginner", known_terms: set[str] | None = None) -> list[dict]:
    """One concept per paragraph, beginner-first, from the structured snapshot."""
    if not snap or not snap.get("available"):
        return [{"heading": "Not enough data", "body": "There aren't enough bars to read this chart yet."}]
    known = known_terms or set()
    define = lambda term, text: "" if (level != "beginner" or term in known) else f" ({text})"  # noqa: E731
    p, ma, mo, vo, se, st = (snap.get(k) or {} for k in ("price", "moving_averages", "momentum", "volume", "session", "structure"))
    price = snap["price"]
    out = []
    trend = st.get("state")
    out.append({"heading": "The big picture", "body":
                f"On the {snap['timeframe']} chart, structure is '{trend}'"
                + define("trend", "uptrend = each swing high and low above the last; downtrend = each below") + ". "
                + ("The moving averages are stacked up (9 > 21 > 50 EMA): recent prices keep beating older ones."
                   if (ma.get("ema9") or 0) > (ma.get("ema21") or 0) > (ma.get("ema50") or 0) else
                   "The moving averages are stacked down (9 < 21 < 50 EMA): recent prices keep losing to older ones."
                   if (ma.get("ema9") or 0) < (ma.get("ema21") or 0) < (ma.get("ema50") or 0) else
                   "The moving averages are tangled: no clean trend on this timeframe.")})
    if se.get("vwap"):
        side = "above" if price > se["vwap"] else "below"
        out.append({"heading": "Where price sits vs VWAP", "body":
                    f"Price {_money(price)} is {side} VWAP {_money(se['vwap'])}"
                    + define("VWAP", "the average price paid today, weighted by volume") + ". "
                    + ("On average, today's buyers are in profit." if side == "above" else "On average, today's buyers are losing.")})
    if mo.get("rsi") is not None:
        r = mo["rsi"]
        out.append({"heading": "Momentum", "body": f"RSI is {r:.0f}" + define("RSI", "0-100 gauge of recent up moves vs down moves") + ". "
                    + ("That's stretched to the upside - chasing is risky, but it's not a sell signal by itself." if r >= 70 else
                       "That's stretched to the downside - not a buy signal by itself; oversold can stay oversold." if r <= 30 else
                       "Momentum leans up." if r >= 55 else "Momentum leans down." if r <= 45 else "Momentum is neutral.")})
    if vo.get("rvol") is not None:
        rv = vo["rvol"]
        out.append({"heading": "Volume", "body": f"Relative volume is {rv:.1f}x" + define("RVOL", "volume vs normal for this time of day") + ". "
                    + ("Heavy participation - moves are more trustworthy." if rv >= 1.5 else
                       "Light participation - moves are less trustworthy." if rv < 0.8 else "About normal participation.")
                    + " (Volume from the free data source is approximate.)"})
    near = [l for l in snap.get("levels", []) if abs(l.get("distance_pct", 99)) <= 1.5 and l["kind"] != "vwap"][:4]
    if near:
        txt = "; ".join(f"{l['label']} {_money(l['price'])} ({l['distance_pct']:+.2f}%)" for l in near)
        out.append({"heading": "Nearby levels", "body": f"Prices where the market reacted before: {txt}. Expect pauses or reactions there."})
    if snap.get("candles"):
        c = snap["candles"][0]
        out.append({"heading": "Recent candle", "body": c["meaning"]})
    b = snap.get("bias", {})
    out.append({"heading": "Weight of evidence", "body": f"Overall: {b.get('label')} (score {b.get('score')}). {b.get('note', '')}"})
    return out


class Assistant:
    def __init__(self, provider: LLMProvider | None = None, provider_desc: str = "Built-in explanations"):
        self.provider = provider or NoLLM()
        self.provider_desc = provider_desc

    async def ask(self, question: str, ctx: dict[str, Any], image_png: bytes | None = None, level: str = "beginner") -> dict:
        intent = classify(question)
        grounded = self.rule_answer(intent, question, ctx, level)
        if isinstance(self.provider, NoLLM):
            return {"answer": grounded, "intent": intent, "engine": self.provider_desc, "grounded_in": list(ctx)}
        try:
            slim = json.dumps(_slim(ctx), default=str)[:60_000]
            text = await self.provider.complete(f"{question}\n\n(User level: {level}.)", slim, image_png)
            return {"answer": text, "intent": intent, "engine": self.provider_desc, "grounded_in": list(ctx),
                    "built_in_answer": grounded}
        except Exception as e:
            log.warning("LLM failed: %s", e)
            return {"answer": grounded, "intent": intent, "engine": f"Built-in (AI provider failed: {str(e)[:120]})",
                    "grounded_in": list(ctx)}

    def rule_answer(self, intent: str, question: str, ctx: dict, level: str) -> str:
        sym = ctx.get("symbol")
        if not sym:
            return ("Tell me which symbol you mean, or open a chart / turn on screen monitoring so I can see what you're looking at. "
                    "I won't guess.")
        parts: list[str] = []
        cav = data_caveat(ctx)
        if cav:
            parts.append(cav)
        sig = ctx.get("signals") or {}
        best = sig.get("best")
        sigs = sig.get("signals") or []
        snap = ctx.get("analysis") or {}
        pos = ctx.get("position")
        adv = ctx.get("position_advice")

        if intent in ("entry", "short", "too_late"):
            want = "short" if intent == "short" else "long"
            cands = [s for s in sigs if s["direction"] == want] or ([best] if best else [])
            if not cands:
                parts.append(f"No active {want} setup on {sym} right now, so the answer is NO TRADE. "
                             + " ".join(sig.get("reasons", [])[:2]))
            else:
                s = cands[0]
                parts.append(f"{s['action']}: {s['setup_name']} on the {s['timeframe']} chart - state '{s['state']}'. {s['state_reason']}")
                parts.append(f"Plan: entry {_money(s['entry_range'][0])}-{_money(s['entry_range'][1])}, stop {_money(s['stop'])}, "
                             f"targets {_money(s['targets']['t1'])} / {_money(s['targets']['t2'])}. {s['education']['money']}")
                if s["state"] == "extended" or intent == "too_late":
                    parts.append("Late? " + ("Yes - price is past the entry window. Entering now means a worse price for the same stop. Skip it."
                                             if s["state"] == "extended" else
                                             "Not yet: price is still within the planned entry window." if s["state"] == "confirmed" else
                                             "It hasn't triggered yet, so you're early, not late. Wait for the trigger."))
                parts.append("Confirmation needed: " + s["confirmation"])
                if s["risks"]:
                    parts.append("Risks: " + " ".join(s["risks"][:3]))
                parts.append(f"Confidence: {s['confidence']['setup_quality']['score']}/100 on the quality checklist (not a probability). "
                             + (s["confidence"]["historical"].get("note") or ""))
        elif intent == "exit":
            if not pos:
                parts.append(f"You have no paper position in {sym}. Nothing to sell or hold.")
            else:
                parts.append(f"You're {pos['side']} {abs(pos['qty'])} shares at {_money(pos['avg_price'])}; unrealized {_money(pos['unrealized_pnl'])}.")
                if adv:
                    parts.append(f"{adv['action']}: " + " ".join(adv["reasons"]))
                    for a in adv.get("alerts", []):
                        parts.append(f"Alert: {a['text']}")
                parts.append("Nothing changes automatically - any exit or stop change is your call.")
        elif intent == "stop" or intent == "invalidate":
            if best:
                parts.append(f"For the {best['setup_name']} idea: stop {_money(best['stop'])}, invalidation {_money(best['invalidation'])}. "
                             "The stop sits just beyond the structure that defines the idea - if price gets there, the reason for the trade is gone.")
                parts.append(best["education"]["how_it_fails"])
            elif pos and pos.get("stop_loss"):
                parts.append(f"Your position's stop is {_money(pos['stop_loss'])}.")
            else:
                lv = [l for l in snap.get("levels", []) if l.get("side") == "below"][-2:]
                parts.append("No active setup, so there's no planned stop. Nearest levels below price: "
                             + (", ".join(f"{l['label']} {_money(l['price'])}" for l in lv) or "none found") +
                             ". A stop normally goes just beyond the level that proves the idea wrong.")
        elif intent == "profit":
            if best:
                t = best["targets"]
                parts.append(f"Targets: T1 {_money(t['t1'])} (1R), T2 {_money(t['t2'])} ({best['reward_risk']}R), T3 {_money(t['t3'])}. "
                             "Many traders take partial profit at T1 and move the stop to breakeven.")
            else:
                lv = [l for l in snap.get("levels", []) if l.get("side") == "above"][:3]
                parts.append("No active plan. Levels above where sellers appeared before: " +
                             (", ".join(f"{l['label']} {_money(l['price'])}" for l in lv) or "none found") + ".")
        elif intent == "fake_breakout":
            bo = [s for s in sigs if s["setup"] in ("level_breakout", "orb_long", "level_breakdown", "orb_short")]
            if not bo:
                parts.append(f"I don't see a breakout setup on {sym} right now.")
            else:
                s = bo[0]
                v = s["volume"]
                parts.append(f"{s['setup_name']}: state '{s['state']}'. Volume on the breakout bar {v['signal_bar_vol_ratio']}x average, RVOL {v['rvol']}.")
                parts.append("Signs of a FAKE breakout: low volume, a long wick back under the level, or a close back below it. "
                             f"Here the breakout is invalidated by a close beyond {_money(s['invalidation'])}.")
        elif intent == "why_moving":
            parts.append("I don't have a news feed connected, so I can't tell you the reason, and I won't guess. Here's what the data shows instead:")
            v = snap.get("volume", {})
            se = snap.get("session", {})
            if se.get("pdc") and snap.get("price"):
                parts.append(f"Price {_money(snap['price'])} vs yesterday's close {_money(se['pdc'])} ({100 * (snap['price'] / se['pdc'] - 1):+.2f}%), "
                             f"relative volume {v.get('rvol')}x.")
            parts.append("Unusually high relative volume usually means news or an event. Check a news site before trading it.")
        elif intent == "better":
            top = (ctx.get("scanner") or [])[:5]
            if not top:
                parts.append("The scanner hasn't produced results yet (it runs during premarket and market hours).")
            else:
                parts.append("Top-ranked scanner candidates: " + "; ".join(
                    f"{r['symbol']} ({r['action']}, score {r['rank_score']})" for r in top))
        elif intent == "market":
            m = ctx.get("market") or {}
            parts.append(f"Market (SPY) bias: {m.get('bias', 'unknown')}; SPY change {m.get('spy_change_pct')}%; "
                         f"above VWAP: {m.get('spy_above_vwap')}." + (" HIGH-RISK: " + " ".join(m.get("reasons", [])) if m.get("high_risk") else ""))
        elif intent == "missing":
            opp = [f for f in snap.get("factors", []) if f["direction"] != (snap.get("bias", {}).get("label"))][:4]
            parts.append("Evidence against the current read: " + ("; ".join(f"{f['factor']}: {f['why']}" for f in opp) or "none notable") + ".")
            if best and best["risks"]:
                parts.append("Setup risks: " + " ".join(best["risks"]))
            parts.append("Also: earnings or news timing, which I can't see.")
        if intent == "explain" or len(parts) <= (1 if cav else 0):
            known = set(ctx.get("known_terms") or [])
            for sec in explain_chart(snap, level, known):
                parts.append(f"{sec['heading']}: {sec['body']}")
        if ctx.get("screen") and ctx["screen"].get("discrepancy"):
            parts.insert(0, "Heads up: " + ctx["screen"]["discrepancy"])
        return "\n\n".join(p for p in parts if p)


def _slim(ctx: dict) -> dict:
    """Trim the context for the LLM (no huge arrays)."""
    out = dict(ctx)
    a = dict(out.get("analysis") or {})
    a.pop("chart", None)
    a["levels"] = (a.get("levels") or [])[:12]
    out["analysis"] = a
    if out.get("signals"):
        out["signals"] = {**out["signals"], "signals": out["signals"].get("signals", [])[:4]}
    out["glossary"] = {k: GLOSSARY[k] for k in ("VWAP", "R", "RSI", "ATR", "stop loss") if k in GLOSSARY}
    return out
