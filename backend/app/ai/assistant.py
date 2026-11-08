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
    ("mistakes", r"\bmistakes?\b|\bwhat am i doing wrong\b|\brepeat(ing)?\b|\bbad habits?\b"),
    ("best_strategy", r"\b(which|what|best|worst)\b.*\b(strateg\w*|setups?)\b.*\b(perform|work|best|worst|win|lose|losing)|\bmy (best|worst) (strateg\w*|setups?)"),
    ("why_invalid", r"\bwhy\b.*\b(invalid|cancel|gone|disappear|no longer|expired|stopp?ed out)"),
    ("why_signal", r"\bwhy\b.*\b(signal|setup|alert)\b.*\b(appear|fire|trigger|show|there)|\bwhy (is there|did i get) (a|this) (signal|setup|alert)"),
    ("rr", r"\b(risk[/ ]?(to[ -])?reward|reward[/ ]?(to[ -])?risk|r:r|rr\b|how much (could|can|would) i (lose|make))"),
    ("too_late", r"\b(too late|late|chas\w*|missed)\b"),
    ("fake_breakout", r"\b(fake|false)\b.*\bbreak|\bbreakout\b.*\b(real|fake|confirm)|\bconfirmed\b.*\bbreak"),
    ("why_moving", r"\bwhy\b.*\b(moving|up|down|running|dump|pump|drop|fall|rall)|\bnews\b|\bcatalyst"),
    ("better", r"\b(better|other|another)\b.*\b(opportunit|setup|stock|trade)"),
    ("missing", r"\b(missing|blind spot|overlook)"),
    ("market", r"\b(market|spy|conditions|overall)\b"),
    ("invalidate", r"\binvalid"),
    ("stop", r"\bstop\b"),
    ("profit", r"\b(take profit|target|profits?)\b"),
    ("exit", r"\b(sell|exit|close|cover|hold)\b"),
    ("short", r"\bshort\b"),
    ("entry", r"\b(buy|long|enter|entry|get in)\b"),
    ("explain", r"\b(explain|what.*(happening|going on|see|suggest)|chart)\b"),
]
NO_SYMBOL_INTENTS = {"mistakes", "best_strategy", "better", "market"}

LABELS = {"fact": "Observed", "interpretation": "Interpretation", "evidence": "Historical evidence",
          "uncertainty": "Uncertainty", "hypothetical": "If you", "data": "Data", "plan": "Plan (from the signal engine)"}


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


class Answer:
    """An answer made of labelled parts, so you can always tell what was observed, what is the app's reading
    of it, what the historical record says, what is unknown, and what is only a scenario."""

    def __init__(self):
        self.parts: list[dict] = []

    def add(self, kind: str, text: str | None) -> None:
        if text:
            self.parts.append({"kind": kind, "label": LABELS[kind], "text": text})

    def __len__(self) -> int:
        return len(self.parts)

    def text(self) -> str:
        return "\n\n".join(f"{p['label']}: {p['text']}" for p in self.parts)


def _ev_text(cal: dict | None) -> str:
    if not cal:
        return "No out-of-sample test of this setup yet."
    ci = cal.get("avg_r_ci95")
    base = cal.get("note") or ""
    if cal.get("trades") and ci and "interval" not in base:
        base += f" (95% interval {ci[0]:+.2f}R to {ci[1]:+.2f}R)"
    return base or cal.get("tier_text", "")


class Assistant:
    def __init__(self, provider: LLMProvider | None = None, provider_desc: str = "Built-in explanations"):
        self.provider = provider or NoLLM()
        self.provider_desc = provider_desc

    async def ask(self, question: str, ctx: dict[str, Any], image_png: bytes | None = None, level: str = "beginner") -> dict:
        intent = classify(question)
        ans = self.rule_answer_parts(intent, question, ctx, level)
        base = {"intent": intent, "grounded_in": [k for k, v in ctx.items() if v], "sections": ans.parts}
        if isinstance(self.provider, NoLLM):
            return {"answer": ans.text(), "engine": self.provider_desc, **base}
        try:
            slim = json.dumps(_slim(ctx), default=str)[:60_000]
            text = await self.provider.complete(f"{question}\n\n(User level: {level}.)", slim, image_png)
            return {"answer": text, "engine": self.provider_desc, "built_in_answer": ans.text(), **base}
        except Exception as e:
            log.warning("LLM failed: %s", e)
            return {"answer": ans.text(), "engine": f"Built-in (AI provider failed: {str(e)[:120]})", **base}

    def _futures(self, a: Answer, intent: str, ctx: dict) -> None:
        """Futures answers: same labelled structure, futures facts (contract, ticks, dollars per contract, prop limits)."""
        fu = ctx["futures"]
        sig, lv, data, spec = fu.get("signal") or {}, fu.get("levels") or {}, fu.get("data") or {}, fu.get("spec") or {}
        code = (fu.get("contract") or {}).get("code") or ctx.get("symbol")
        a.add("data", f"{code} data: {data.get('status', 'unknown')}. {data.get('reason', '')}".strip())
        risk = (ctx.get("futures_account") or {}).get("risk") or {}
        off, per, met = risk.get("official", {}), risk.get("personal", {}), risk.get("metrics", {})
        best = sig.get("signal") or (sig.get("watch") or sig.get("study_only") or [None])[0]
        if intent in ("risk", "rr", "stop", "invalidate", "entry", "short", "too_late", "why_signal", "exit", "general", "explain"):
            a.add("fact", f"Signal: {sig.get('action', 'NO TRADE')}. " + " ".join((sig.get("reasons") or [])[:2]))
        if best:
            a.add("plan", f"{best['setup']} ({best['direction']}): entry {best['entry']:g}, stop {best['stop']:g} ({best.get('stop_ticks')} ticks, "
                          f"${best.get('risk_per_contract_usd', 0):,.2f} per contract with slippage and fees), target {best['target']:g} "
                          f"({best.get('reward_risk')}R). Invalidation: {best['invalidation']}")
            a.add("evidence", f"Tested evidence: {best.get('evidence_short', 'untested')}. "
                              + ("" if best.get("tradeable_evidence") else "That's why it's watch-only, not a trade."))
            if best.get("suggested_contracts") is not None:
                a.add("plan", f"Size from your limits: {best['suggested_contracts']} contract(s). {best.get('sizing_note', '')}")
            for p_ in (best.get("risk_check") or {}).get("problems", [])[:3]:
                a.add("uncertainty", p_)
        elif sig.get("developing"):
            a.add("interpretation", " ".join(sig["developing"][:2]))
        if lv:
            a.add("fact", f"Levels: VWAP {lv.get('vwap') or '-'}, previous day {lv.get('prev_day_high') or '-'} / {lv.get('prev_day_low') or '-'}, "
                          f"overnight {lv.get('overnight_high') or '-'} / {lv.get('overnight_low') or '-'}, trend {lv.get('trend')}.")
        if spec:
            a.add("fact", f"{spec.get('root')}: tick {spec.get('tick_size')} = ${spec.get('tick_value')}; 1 point = ${spec.get('point_value')} per contract.")
        if off:
            bits = []
            if off.get("mll_remaining") is not None:
                bits.append(f"${off['mll_remaining']:,.2f} above the Maximum Loss Limit")
            if off.get("dll_remaining") is not None:
                bits.append(f"${off['dll_remaining']:,.2f} left of the Daily Loss Limit")
            if per.get("daily_loss_remaining") is not None:
                bits.append(f"${per['daily_loss_remaining']:,.2f} left of your own daily limit")
            if bits:
                a.add("fact", "Simulator account: " + "; ".join(bits) + f". Day P&L ${met.get('day_pnl', 0):,.2f}.")
            for b in risk.get("blocks", [])[:2]:
                a.add("uncertainty", "Blocked: " + b["text"])
            if not off.get("confirmed"):
                a.add("uncertainty", "Your prop-firm rules aren't confirmed against your account yet, so these limits may not match it.")
        a.add("uncertainty", "Study Terminal can't see or change your real Topstep account; everything here is analysis and simulation.")

    def rule_answer(self, intent: str, question: str, ctx: dict, level: str) -> str:
        return self.rule_answer_parts(intent, question, ctx, level).text()

    # ------------------------------------------------------------------

    def rule_answer_parts(self, intent: str, question: str, ctx: dict, level: str) -> Answer:
        a = Answer()
        if ctx.get("futures"):
            self._futures(a, intent, ctx)
            return a
        sym = ctx.get("symbol")
        if intent in NO_SYMBOL_INTENTS and intent in ("mistakes", "best_strategy"):
            (self._mistakes if intent == "mistakes" else self._best_strategy)(a, ctx)
            return a
        if not sym and intent not in NO_SYMBOL_INTENTS:
            a.add("uncertainty", "Tell me which symbol you mean, or open a chart / turn on screen monitoring so I can see what you're "
                                 "looking at. I won't guess.")
            return a
        cav = data_caveat(ctx) if sym else None
        a.add("data", cav)
        sig = ctx.get("signals") or {}
        best = sig.get("best")
        watch = sig.get("watch")
        sigs = sig.get("signals") or []
        snap = ctx.get("analysis") or {}
        pos = ctx.get("position")
        adv = ctx.get("position_advice")
        n0 = len(a)

        if intent in ("entry", "short", "too_late"):
            want = "short" if intent == "short" else "long"
            cands = [s for s in sigs if s["direction"] == want and s["action"] != "NO TRADE"]
            if intent == "too_late":
                cands = cands or [s for s in sigs if s["action"] != "NO TRADE"]
            if not cands:
                a.add("fact", f"No active {want} setup on {sym} right now.")
                a.add("interpretation", "So the answer is NO TRADE. " + " ".join(sig.get("reasons", [])[:2]))
            else:
                s = cands[0]
                a.add("fact", f"{s['setup_name']} on the {s['timeframe']} chart, state '{s['state']}': {s['state_reason']}")
                if s.get("tradeable"):
                    a.add("interpretation", f"{s['action']}. The setup has reliable out-of-sample evidence and is triggering now.")
                else:
                    a.add("interpretation", f"NO TRADE as a real decision: it's labelled {s['action']} (watch only) because the setup has "
                                            "no proven edge. It's worth watching to learn from, not acting on with real money.")
                a.add("evidence", _ev_text((s.get("confidence") or {}).get("historical")))
                if s["state"] == "extended" or intent == "too_late":
                    a.add("interpretation", "Are you late? " + (
                        "Yes: price is past the entry window. Entering now means a worse price for the same stop, so a smaller "
                        "reward for the same risk. Skip it." if s["state"] == "extended" else
                        "Not yet: price is still inside the planned entry window." if s["state"] == "confirmed" else
                        "It hasn't triggered, so you're early, not late. Wait for the trigger."))
                a.add("hypothetical", f"practice it on paper: entry {_money(s['entry_range'][0])}-{_money(s['entry_range'][1])}, stop "
                                      f"{_money(s['stop'])}, invalidation {_money(s['invalidation'])}, targets {_money(s['targets']['t1'])} / "
                                      f"{_money(s['targets']['t2'])}. {s['education']['money']}")
                a.add("plan", "Confirmation needed first: " + s["confirmation"])
                if s["risks"]:
                    a.add("uncertainty", " ".join(s["risks"][:3]))
                a.add("uncertainty", f"Checklist score {s['confidence']['setup_quality']['score']}/100 counts boxes ticked; it is not a "
                                     "probability of winning. Any single trade can fail.")
        elif intent == "exit":
            if not pos:
                a.add("fact", f"You have no paper position in {sym}. Nothing to sell or hold.")
            else:
                a.add("fact", f"You're {pos['side']} {abs(pos['qty'])} shares at {_money(pos['avg_price'])}; unrealized "
                              f"{_money(pos['unrealized_pnl'])}; stop {_money(pos.get('stop_loss'))}, target {_money(pos.get('take_profit'))}.")
                if adv:
                    a.add("interpretation", f"{adv['action']}: " + " ".join(adv["reasons"]))
                    for x in adv.get("alerts", []):
                        a.add("fact", x["text"])
                a.add("uncertainty", "Nothing changes automatically: any exit or stop change is your call.")
        elif intent in ("stop", "invalidate"):
            s = best or watch
            if s:
                a.add("plan", f"For the {s['setup_name']} idea: stop {_money(s['stop'])}, invalidation {_money(s['invalidation'])}.")
                a.add("interpretation", "The stop sits just beyond the structure that defines the idea. If price gets there, the reason "
                                        "for the trade is gone. " + s["education"]["how_it_fails"])
            elif pos and pos.get("stop_loss"):
                a.add("fact", f"Your position's stop is {_money(pos['stop_loss'])}.")
            else:
                lv = [x for x in snap.get("levels", []) if x.get("side") == "below"][-2:]
                a.add("fact", "No active setup, so there's no planned stop. Nearest levels below price: "
                              + (", ".join(f"{x['label']} {_money(x['price'])}" for x in lv) or "none found") + ".")
                a.add("interpretation", "A stop normally goes just beyond the level that proves the idea wrong.")
        elif intent == "rr":
            s = best or watch
            if not s:
                a.add("fact", f"No active setup on {sym}, so there's no planned risk/reward to measure.")
            else:
                ps = s["position_size"]
                rr = s["reward_risk"]
                a.add("plan", f"{s['setup_name']}: risk {_money(ps['risk_dollars'])} ({ps['risk_pct']}% of {_money(ps['equity'])}) on "
                              f"{ps['shares']} shares, entry {_money(s['trigger'])} to stop {_money(s['stop'])}; target {_money(s['targets']['t2'])} "
                              f"is {rr}R away.")
                if rr:
                    a.add("interpretation", f"At {rr}:1 you need to win more than {100 / (1 + rr):.0f}% of trades like this to break even "
                                            "before costs. A good ratio only matters if the setup also wins often enough.")
                a.add("evidence", _ev_text((s.get("confidence") or {}).get("historical")))
        elif intent == "fake_breakout":
            bo = [s for s in sigs if s["setup"] in ("level_breakout", "orb_long", "level_breakdown", "orb_short")]
            if not bo:
                a.add("fact", f"I don't see a breakout setup on {sym} right now.")
            else:
                s = bo[0]
                v = s["volume"]
                a.add("fact", f"{s['setup_name']}: state '{s['state']}'. Breakout bar volume {v['signal_bar_vol_ratio']}x its 20-bar "
                              f"average; relative volume {v['rvol']}x.")
                conf = s["state"] == "confirmed"
                a.add("interpretation", ("Confirmed by the engine's rules: price traded through the trigger and is inside the entry window. "
                                         if conf else f"Not confirmed ({s['state']}). ")
                      + f"A close back beyond {_money(s['invalidation'])} would make it a failed breakout.")
                a.add("uncertainty", "Fake breakouts typically show low volume, a long wick back under the level, or a close back below it. "
                                     "Confirmation reduces but doesn't remove that risk.")
                a.add("evidence", _ev_text((s.get("confidence") or {}).get("historical")))
        elif intent == "why_signal":
            s = best or watch or (sigs[0] if sigs else None)
            if not s:
                a.add("fact", f"There's no current signal on {sym}.")
            else:
                q = s["confidence"]["setup_quality"]
                passed = [c["check"] for c in q["checks"] if c["passed"]]
                a.add("fact", f"{s['setup_name']} was detected on the bar closing {s['detected_at']} ({s['timeframe']}). Rule checks passed: "
                              + (", ".join(passed) or "none") + ".")
                a.add("fact", "Supporting readings: " + ("; ".join(f"{f['factor']}: {f['why']}" for f in s["supporting_indicators"][:4])
                                                         or "none beyond the setup rule itself") + ".")
                a.add("interpretation", s["education"]["what"] + " " + s["education"]["why"])
                a.add("evidence", _ev_text((s.get("confidence") or {}).get("historical")))
        elif intent == "why_invalid":
            log_rows = [r for r in (ctx.get("signal_log") or []) if r["state"] in ("invalidated", "expired", "extended")]
            cur = [s for s in sigs if s["state"] in ("invalidated", "expired", "extended")]
            if cur:
                for s in cur[:2]:
                    a.add("fact", f"{s['setup_name']} ({s['timeframe']}) is '{s['state']}': {s['state_reason']}")
            elif log_rows:
                for r in log_rows[:3]:
                    d = r.get("detail") or {}
                    a.add("fact", f"{r['ts'][:16].replace('T', ' ')} UTC: {d.get('setup_name', r['setup'])} became '{r['state']}': "
                                  f"{d.get('state_reason', '')}")
            else:
                a.add("fact", f"No invalidated or expired signal for {sym} in the recent signal log.")
            a.add("interpretation", "Invalidated means price did the thing that proves the idea wrong; expired means it never triggered in "
                                    "time; extended means it ran too far past the entry to chase.")
        elif intent == "why_moving":
            cat = ctx.get("catalysts") or {}
            news = [n for n in (cat.get("news") or []) if n["relevance"] != "low"][:4]
            if news:
                for n in news:
                    a.add("fact", f"{n['source']}, {n['published'][:16].replace('T', ' ')} UTC: \"{n['headline']}\" "
                                  f"[{ {'confirmed': 'reported', 'speculative': 'UNCONFIRMED', 'opinion': 'opinion'}.get(n['certainty'], n['certainty'])}]")
            elif cat.get("news_error") or cat.get("disabled"):
                a.add("uncertainty", cat.get("news_error") or "News monitoring is turned off, so I can't tell you the reason, and I won't guess.")
            else:
                a.add("uncertainty", f"I don't have any relevant headlines for {sym} loaded right now, so I can't tell you the reason, and I "
                                     "won't guess.")
            for n in (cat.get("events") or {}).get("notes", []):
                a.add("fact", n["text"])
            v, se = snap.get("volume", {}), snap.get("session", {})
            if se.get("pdc") and snap.get("price"):
                a.add("fact", f"Price {_money(snap['price'])} vs yesterday's close {_money(se['pdc'])} "
                              f"({100 * (snap['price'] / se['pdc'] - 1):+.2f}%), relative volume {v.get('rvol')}x.")
            a.add("interpretation", "A headline is a possible reason, not a proven one. Price can also move on flows, sector moves or "
                                    "news that isn't on Yahoo's feed. Good news doesn't mean buy and bad news doesn't mean short.")
        elif intent == "better":
            top = (ctx.get("scanner") or [])[:5]
            if not top:
                a.add("fact", "The scanner hasn't produced results yet (it runs during premarket and market hours).")
            else:
                a.add("fact", "Top-ranked scanner candidates: " + "; ".join(f"{r['symbol']} ({r['action']}, score {r['rank_score']})" for r in top))
                a.add("uncertainty", "Rank weights are judgment calls, not tested probabilities.")
        elif intent == "market":
            m = ctx.get("market") or {}
            a.add("fact", f"SPY bias {m.get('bias', 'unknown')}; SPY change {m.get('spy_change_pct')}%; above VWAP: {m.get('spy_above_vwap')}.")
            if m.get("high_risk"):
                a.add("interpretation", "High-risk conditions: " + " ".join(m.get("reasons", [])) + " These thresholds are rules of thumb.")
            for e in (ctx.get("calendar") or [])[:3]:
                a.add("fact", f"Scheduled: {e['event']} {e['date']} {e['time_et']} ET ({e['source']}).")
        elif intent == "missing":
            opp = [f for f in snap.get("factors", []) if f["direction"] != (snap.get("bias", {}).get("label"))][:4]
            a.add("fact", "Evidence against the current read: " + ("; ".join(f"{f['factor']}: {f['why']}" for f in opp) or "none notable") + ".")
            s = best or watch
            if s and s["risks"]:
                a.add("uncertainty", "Setup risks: " + " ".join(s["risks"][:4]))
            notes = ((ctx.get("catalysts") or {}).get("events") or {}).get("notes", [])
            a.add("uncertainty", " ".join(n["text"] for n in notes) or "No scheduled event or earnings flagged for this symbol in the next days.")
        if intent == "explain" or len(a) <= n0:
            known = set(ctx.get("known_terms") or [])
            for sec in explain_chart(snap, level, known):
                a.add("interpretation" if sec["heading"] in ("Weight of evidence",) else "fact", f"{sec['heading']}: {sec['body']}")
            s = best or watch
            if s:
                a.add("interpretation", f"Active idea: {s['setup_name']} ({s['action']}, {s['state']}).")
                a.add("evidence", _ev_text((s.get("confidence") or {}).get("historical")))
        if ctx.get("screen") and ctx["screen"].get("discrepancy"):
            a.parts.insert(0, {"kind": "data", "label": LABELS["data"], "text": "Heads up: " + ctx["screen"]["discrepancy"]})
        return a

    @staticmethod
    def _mistakes(a: Answer, ctx: dict) -> None:
        j = ctx.get("journal") or {}
        ms = j.get("mistakes") or []
        n = j.get("closed_trades", 0)
        if not n:
            a.add("fact", "Your journal has no closed paper trades yet, so there's nothing to analyze.")
            return
        a.add("fact", f"From your journal: {n} closed paper trades.")
        if not ms:
            a.add("interpretation", "No recurring mistakes detected by the journal's rules.")
        for m in ms[:4]:
            cmp = f"; your trades without mistakes averaged {m['avg_r_clean_trades']:+.2f}R" if m.get("avg_r_clean_trades") is not None else ""
            a.add("fact", f"{m['label']}: {m['count']} trades ({m['share_pct']}%), net {_money(m['net_pnl'])}, average "
                          f"{(m['avg_r'] if m['avg_r'] is not None else 0):+.2f}R{cmp}.")
        if ms:
            a.add("interpretation", f"The costliest pattern is '{ms[0]['label']}'. Fixing one habit at a time works better than fixing all of them.")
        if n < 30:
            a.add("uncertainty", f"{n} trades is a small sample: a couple more trades can change this picture.")

    @staticmethod
    def _best_strategy(a: Answer, ctx: dict) -> None:
        j = ctx.get("journal") or {}
        rows = [r for r in (j.get("by_strategy") or []) if r["trades"]]
        if rows:
            a.add("fact", "Your paper trades by strategy: " + "; ".join(
                f"{r['bucket']} {r['trades']} trades, {_money(r['net_pnl'])}, avg {(r['avg_r'] if r['avg_r'] is not None else 0):+.2f}R"
                for r in rows[:6]) + ".")
            if j.get("closed_trades", 0) < 30:
                a.add("uncertainty", "Your own sample is small, so these rankings can flip quickly.")
        else:
            a.add("fact", "You don't have closed paper trades by strategy yet.")
        cal = ctx.get("calibration") or {}
        if cal:
            ranked = sorted(cal.items(), key=lambda kv: -(kv[1].get("avg_r") if kv[1].get("avg_r") is not None else -9))
            a.add("evidence", "Backtested out-of-sample (walk-forward): " + "; ".join(
                f"{k.split('|')[0]} {k.split('|')[1] if k.count('|') > 1 else ''} ({k.split('|')[-1]}): {v.get('avg_r', v.get('expectancy_r', 0)):+.3f}R "
                f"over {v.get('trades', 0)} trades, {v.get('tier', '?')}" for k, v in ranked[:6]) + ".")
            if not any(v.get("tier") == "reliable" for v in cal.values()):
                a.add("interpretation", "None of the setups has a reliable out-of-sample edge yet. The 'best' one is the least bad, not a proven winner.")
        else:
            a.add("evidence", "No walk-forward test has been run yet (Backtest page).")


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
