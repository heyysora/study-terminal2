"""Home: answers five questions in plain words from what the rest of the app already knows.

Read-only. It combines existing status dictionaries; it doesn't evaluate the market, change limits or start anything.
  1. Is Study Terminal working?        2. What is the market doing?        3. Should I practice a trade or wait?
  4. How much could I lose?            5. What should I do next?
"""
from __future__ import annotations

from .plain import confidence_word, plain_action, plain_reason, plain_status, simplify

LEVEL_ORDER = {"ok": 0, "off": 1, "attention": 2, "bad": 3}
HEALTH_WORD = {"ok": "Working", "off": "Not watching", "attention": "Needs attention", "bad": "Not working"}


def _check(cid: str, name: str, level: str, text: str, do: str = "", link: str | None = None, button: str | None = None) -> dict:
    return {"id": cid, "name": name, "level": level, "text": text, "do": do, "link": link, "button": button}


def _money(v) -> str:
    return "—" if v is None else f"{'-' if v < 0 else ''}${abs(float(v)):,.0f}"


def _hhmm(iso: str | None) -> str | None:
    return iso[11:16] if iso and len(iso) >= 16 else None


# ---------------------------------------------------------------- 1. health

def health(*, trades: str, db_ok: bool, monitor: dict | None, visual: dict | None, automation: dict | None, profiles: int,
           backup: dict | None, engine_error: str | None = None) -> dict:
    checks: list[dict] = []
    if engine_error:
        checks.append(_check("engine", "Study Terminal", "bad", "Part of Study Terminal failed to answer.",
                             "Quit Study Terminal from the tray icon and open it again."))
    checks.append(_check("engine_db", "Saved data", "ok" if db_ok else "bad",
                         "Your saved data is readable." if db_ok else "Study Terminal can't read its saved data.",
                         "" if db_ok else "Quit Study Terminal from the tray icon and open it again. If it keeps happening, restore a backup."))
    if backup and backup.get("error"):
        checks.append(_check("backup", "Backup", "attention", "The automatic backup before this update didn't finish.",
                             "Copy your Study Terminal data folder somewhere safe (Settings shows where it is)."))
    if trades == "futures":
        charts = list(((visual or {}).get("charts") or {}).values())
        vstate = (visual or {}).get("state", "stopped")
        if profiles == 0:
            checks.append(_check("chart", "Your chart", "off", "No chart is connected yet.", "Connect your TopstepX chart so I can see the market.",
                                 "#/visual/setup", "Connect my chart"))
        elif vstate != "running":
            checks.append(_check("chart", "Your chart", "off", "I'm not watching your chart right now." if vstate == "stopped" else "Watching your chart is paused.",
                                 "Turn watching on.", "#/visual", "Start watching"))
        elif not charts:
            checks.append(_check("chart", "Your chart", "attention", "Watching is on, but no chart is switched on.", "Open chart settings and switch a chart on.", "#/visual"))
        else:
            worst = None
            for c in charts:
                ps = plain_status(c.get("status"))
                name = (c.get("profile") or {}).get("name") or "your chart"
                if ps["level"] == "ok":
                    ck = _check("chart", "Your chart", "ok", f"I can see {name} and it's updating.")
                else:
                    r = plain_reason(f"{str(c.get('status', '')).upper()}: {c.get('reason') or ''}")
                    ck = _check("chart", "Your chart", "bad", r["headline"], r["do"], "#/visual", "Check my chart")
                    ck["detail"] = c.get("reason")
                if worst is None or LEVEL_ORDER[ck["level"]] > LEVEL_ORDER[worst["level"]]:
                    worst = ck
            checks.append(worst)
    else:
        m = monitor or {}
        if not m.get("monitoring_enabled", True):
            checks.append(_check("prices", "Prices", "off", "Price checking is paused.", "Turn it back on in Settings."))
        elif m.get("healthy"):
            checks.append(_check("prices", "Prices", "ok", "Stock prices are arriving."))
        else:
            checks.append(_check("prices", "Prices", "bad", "Stock prices aren't arriving.",
                                 "Check your internet connection. Study Terminal keeps trying by itself.") | {"detail": m.get("health_reason")})
    a = automation or {}
    if a.get("status") == "emergency_stopped":
        em = a.get("emergency") or {}
        checks.append(_check("stopped", "Stop everything", "attention", "Everything is stopped.",
                             "When you're ready, write one sentence about why you stopped, then start again.", "#/home", None)
                      | {"detail": em.get("reason"), "at": em.get("at")})
    worst = max(checks, key=lambda c: (LEVEL_ORDER[c["level"]], c["id"] == "stopped"))
    lvl = worst["level"]
    sentence = worst["text"] if lvl != "ok" else next((c["text"] for c in checks if c["id"] in ("chart", "prices")), "Everything is running.")
    return {"level": lvl, "word": HEALTH_WORD[lvl], "sentence": sentence, "do": worst["do"] if lvl != "ok" else "",
            "link": worst.get("link") if lvl != "ok" else None, "button": worst.get("button") if lvl != "ok" else None, "checks": checks}


# ---------------------------------------------------------------- 2. market

def _live_chart(visual: dict | None) -> dict | None:
    if (visual or {}).get("state") != "running":
        return None
    for c in ((visual or {}).get("charts") or {}).values():
        if c.get("status") == "screen_capture" and c.get("recommendation"):
            return c
    return None


def market(*, trades: str, visual: dict | None, signals_market: dict | None) -> dict:
    if trades == "futures":
        c = _live_chart(visual)
        if not c:
            return {"known": False, "sentence": "I can't tell right now, because I can't see a chart that is updating.",
                    "details": [], "source": None, "as_of": None}
        rec = c["recommendation"]
        a = rec.get("analysis") or {}
        label = (a.get("bias") or {}).get("label")
        name = rec.get("contract") or "The market"
        sentence = {"bullish": f"{name} is leaning up.", "bearish": f"{name} is leaning down."}.get(label, f"{name} isn't clearly going up or down.")
        details = []
        pos = (a.get("vwap") or {}).get("position")
        if pos in ("above", "below"):
            details.append(f"Price is {pos} today's average price.")
        if a.get("structure"):
            details.append(f"Recent swings: {simplify(str(a['structure']))}.")
        if rec.get("observed_price") is not None:
            details.append(f"Last price I read: {rec['observed_price']}.")
        return {"known": True, "sentence": sentence, "details": details, "as_of": rec.get("captured_at"),
                "source": "Read from your TopstepX chart on screen. It is what the chart shows, not an official exchange feed.",
                "confidence": confidence_word(rec.get("data_confidence"))}
    m = signals_market or {}
    bias = m.get("bias")
    if not bias:
        return {"known": False, "sentence": "I don't have enough prices yet to say.", "details": [], "source": None, "as_of": None}
    chg = m.get("spy_change_pct")
    lean = {"bullish": "leaning up", "bearish": "leaning down"}.get(bias)
    if chg is not None:                                   # lead with what actually happened today; the trend reading is a detail
        sentence = (f"The stock market is {'up' if chg > 0 else 'down'} {abs(chg):.2f}% today." if abs(chg) >= 0.05
                    else "The stock market is about flat today.")
        details = ["Measured by the S&P 500 fund (SPY)."] + ([f"The recent swings on the chart are {lean}."] if lean else [])
    else:
        sentence = f"The stock market is {lean or 'not clearly going up or down'} today."
        details = []
    return {"known": True, "sentence": sentence,
            "details": details + [simplify(r) for r in (m.get("reasons") or [])[:2]],
            "source": "From free market prices, which can be a little behind.", "as_of": None}


# ---------------------------------------------------------------- 3. practice a trade or wait

def _plan(rec: dict, point_value: float | None) -> dict | None:
    if rec.get("entry") is None or rec.get("stop") is None:
        return None
    qty = rec.get("suggested_contracts") or 1
    pts = abs(float(rec["entry"]) - float(rec["stop"]))
    tgt = rec.get("target_2") or rec.get("target_1") or rec.get("target")
    lose = round(pts * point_value * qty, 2) if point_value else None
    gain = round(abs(float(tgt) - float(rec["entry"])) * point_value * qty, 2) if point_value and tgt is not None else None
    return {"direction": "up" if rec.get("direction") == "long" else "down", "start_price": rec["entry"], "exit_if_wrong": rec["stop"],
            "take_gain": tgt, "contracts": qty, "could_lose_usd": lose, "could_gain_usd": gain,
            "gain_per_dollar_risked": rec.get("reward_risk"), "cancelled_if": simplify(rec.get("invalidation")) or None,
            "note": "Dollar amounts are before fees and price slip."}


def decision(*, trades: str, visual: dict | None, decisions: list[dict], signals_summary: list[dict] | None, point_value_of=None) -> dict:
    wait_note = "Waiting is a decision too. Most of the time it is the right one."
    if trades == "futures":
        c = _live_chart(visual)
        if c:
            rec = c["recommendation"]
            act = plain_action(rec.get("action"))
            r = plain_reason(rec.get("reason"))
            pv = point_value_of(rec.get("contract")) if point_value_of else None
            plan = _plan(rec, pv) if act["tone"] == "idea" or rec.get("potential") else None
            return {"word": act["word"], "tone": act["tone"], "headline": r["headline"], "do": r["do"], "original": r["original"],
                    "contract": rec.get("contract"), "as_of": rec.get("captured_at"), "plan": plan,
                    "watch_only": bool(rec.get("potential")) and act["tone"] == "wait",
                    "basis": "your chart on screen", "confidence": confidence_word(rec.get("data_confidence")),
                    "confidence_note": "This is how sure I am that I'm reading the chart correctly. It is not the chance of winning.",
                    "note": wait_note if act["tone"] == "wait" else "Practice only. It is not a promise that it will work."}
        charts = list(((visual or {}).get("charts") or {}).values())
        if (visual or {}).get("state") == "running" and charts:      # a chart is connected but can't be trusted right now
            bad = charts[0]
            r = plain_reason(f"{str(bad.get('status', '')).upper()}: {bad.get('reason') or ''}")
            return {"word": "WAIT", "tone": "wait", "headline": f"{r['headline']} So I'm not suggesting anything.", "do": r["do"],
                    "original": r["original"], "contract": (bad.get("recommendation") or {}).get("contract"), "as_of": bad.get("last_capture_at"),
                    "plan": None, "watch_only": False, "basis": "your chart on screen", "note": wait_note}
        if decisions:
            d = decisions[0]
            act = plain_action(d.get("outcome"))
            r = plain_reason(d.get("reason"))
            return {"word": "WAIT", "tone": "wait", "headline": r["headline"] if act["tone"] == "wait" else
                    "I can't see a chart that is updating, so I'm not suggesting anything.",
                    "do": r["do"] if act["tone"] == "wait" else "Connect your chart.", "original": r["original"], "contract": d.get("contract"),
                    "as_of": d.get("evaluated_at"), "plan": None, "watch_only": False, "basis": "background price check", "note": wait_note}
        return {"word": "WAIT", "tone": "wait", "headline": "I haven't looked at the market yet.", "do": "Connect your chart and turn watching on.",
                "original": "", "contract": None, "as_of": None, "plan": None, "watch_only": False, "basis": None, "note": wait_note}
    ideas = [s for s in (signals_summary or []) if plain_action(s.get("action"))["tone"] == "idea"]
    if ideas:
        s = ideas[0]
        act = plain_action(s.get("action"))
        return {"word": act["word"], "tone": "idea", "headline": f"{s['symbol']}: {simplify(s.get('setup') or 'a possible trade')}.",
                "do": "Open the chart to see the plan before practicing it.", "original": "; ".join(s.get("reasons") or []),
                "contract": s["symbol"], "as_of": None, "plan": None, "watch_only": False, "basis": "stock prices",
                "note": "Practice only. It is not a promise that it will work.", "link": f"#/chart/{s['symbol']}"}
    return {"word": "WAIT", "tone": "wait", "headline": "Nothing worth trading right now.", "do": "That's normal. Keep watching.",
            "original": "", "contract": None, "as_of": None, "plan": None, "watch_only": False, "basis": "stock prices", "note": wait_note}


# ---------------------------------------------------------------- 4. how much could I lose

def risk(*, trades: str, futures_account: dict | None, stock_account: dict | None) -> dict:
    if trades == "futures":
        r = (futures_account or {}).get("risk") or {}
        m, o, p = r.get("metrics") or {}, r.get("official") or {}, r.get("personal") or {}
        cands = [(p.get("daily_loss_remaining"), "your own daily limit"), (o.get("dll_remaining"), "the firm's daily loss limit"),
                 (o.get("mll_remaining"), "the amount left before the account fails")]
        cands = [(v, why) for v, why in cands if v is not None]
        left, why = min(cands, key=lambda x: x[0]) if cands else (None, None)
        blocks = [plain_reason(b.get("text")) | {"until": b.get("until")} for b in r.get("blocks") or []]
        return {"account": "Practice account (pretend money)", "practice_money": m.get("balance"), "today": m.get("day_pnl"),
                "at_risk_now": m.get("open_risk_usd"), "can_lose_today": left, "can_lose_today_from": why,
                "left_before_account_fails": o.get("mll_remaining"), "trades_today": m.get("trades_today"),
                "new_trades": "stopped" if r.get("blocked") else "allowed", "stopped_why": blocks,
                "warnings": [simplify(w.get("text")) for w in r.get("warnings") or []],
                "limits_confirmed": bool(o.get("confirmed")) or not o.get("enabled", True), "rules_name": o.get("label"),
                "note": "These limits protect your practice account. Study Terminal can't see or control your real TopstepX account."}
    a = stock_account or {}
    lim = a.get("daily_loss_limit")
    left = None if lim is None else round(max(0.0, float(lim) + min(0.0, float(a.get("day_pnl") or 0))), 2)
    return {"account": "Practice account (pretend money)", "practice_money": a.get("equity"), "today": a.get("day_pnl"),
            "at_risk_now": None, "open_trades": a.get("open_positions"), "can_lose_today": left, "can_lose_today_from": "your daily limit",
            "left_before_account_fails": None, "trades_today": None, "new_trades": "stopped" if a.get("daily_loss_limit_hit") else "allowed",
            "stopped_why": ([{"headline": "You reached the most you can lose today.", "do": "Stop for today. New practice trades open again tomorrow.",
                              "original": "Daily loss limit reached.", "kind": "risk", "matched": True}] if a.get("daily_loss_limit_hit") else []),
            "warnings": [], "limits_confirmed": True, "rules_name": None, "note": "Pretend money only."}


# ---------------------------------------------------------------- setup guide + 5. next step

def setup_guide(*, trades: str, trades_chosen: bool, profiles: int, chart_seen: bool, limits_confirmed: bool, prices_ok: bool,
                dismissed: bool) -> dict:
    steps = [{"id": "choose", "title": "Choose what you want to practice", "done": trades_chosen,
              "text": "Futures (with your TopstepX chart) or stocks. You can change this later in Settings.", "link": None, "button": None}]
    if trades == "futures":
        steps += [
            {"id": "connect", "title": "Connect your chart", "done": profiles > 0, "link": "#/visual/setup", "button": "Connect my chart",
             "text": "Open TopstepX in Microsoft Edge, then show Study Terminal where the chart is. It only looks; it never clicks anything."},
            {"id": "watch", "title": "Let Study Terminal read your chart", "done": chart_seen, "link": "#/visual", "button": "Start watching",
             "text": "Turn watching on and wait until it says it can see your chart."},
            {"id": "limits", "title": "Confirm your loss limits", "done": limits_confirmed, "link": "#/futures", "button": "Check my limits",
             "text": "Check that the limits match your TopstepX account, so practice feels like the real thing."},
        ]
    else:
        steps += [{"id": "prices", "title": "Check that prices are arriving", "done": prices_ok, "link": None, "button": None,
                   "text": "This happens by itself when you're connected to the internet."}]
    done = all(s["done"] for s in steps)
    nxt = next((s["id"] for s in steps if not s["done"]), None)
    return {"steps": steps, "done": done, "dismissed": dismissed, "show": not done and not dismissed, "current": nxt,
            "progress": f"{sum(1 for s in steps if s['done'])} of {len(steps)} done"}


def next_step(*, trades: str, health_: dict, setup: dict, risk_: dict, decision_: dict, automation: dict | None) -> dict:
    def step(title, text, link=None, button=None, kind="info"):
        return {"title": title, "text": text, "link": link, "button": button, "kind": kind}
    by = {c["id"]: c for c in health_["checks"]}
    if by.get("engine") or by.get("engine_db", {}).get("level") == "bad":
        c = by.get("engine") or by["engine_db"]
        return step("Restart Study Terminal", c["do"], kind="fix")
    if (automation or {}).get("status") == "emergency_stopped":
        return step("Everything is stopped", "Nothing is being watched or practiced. When you're ready, write one sentence about why you "
                    "stopped and start again.", "#/home", None, "restart")
    if not setup["done"]:
        s = next(x for x in setup["steps"] if not x["done"])
        return step(s["title"], s["text"], s["link"], s["button"], "setup")
    ch = by.get("chart") or by.get("prices")
    if ch and ch["level"] in ("bad", "attention", "off"):
        return step("Fix this first" if ch["level"] == "bad" else "Turn watching on", f"{ch['text']} {ch['do']}".strip(), ch.get("link"), ch.get("button"), "fix")
    if risk_["new_trades"] == "stopped":
        w = (risk_["stopped_why"] or [{}])[0]
        return step("Stop for now", f"{w.get('headline', 'You reached one of your limits.')} {w.get('do', '')}".strip(), kind="stop")
    if decision_["tone"] == "idea":
        return step("Look at the practice plan", "Read the plan first: where it starts, where it gives up, and how much it could lose. "
                    "Then decide whether to practice it.", decision_.get("link") or ("#/visual" if trades == "futures" else "#/chart"),
                    "See the plan", "idea")
    if decision_["tone"] == "exit":
        return step("Close the practice trade", decision_["headline"], "#/futures" if trades == "futures" else "#/paper", "Open my practice account", "idea")
    return step("Keep watching", "There's nothing to do right now. I'll tell you when something changes.", kind="ok")


def recent(decisions: list[dict], n: int = 3) -> list[dict]:
    out = []
    for d in decisions[:n]:
        act = plain_action(d.get("outcome"))
        r = plain_reason(d.get("reason"))
        verb = {"wait": "Waited", "idea": "Found a practice idea", "exit": "Closed", "stop": "Stopped"}[act["tone"]]
        out.append({"at": d.get("last_seen") or d.get("evaluated_at"), "time": _hhmm(str(d.get("last_seen") or d.get("evaluated_at") or "")),
                    "contract": d.get("contract"), "sentence": f"{verb}. {r['headline']}", "original": r["original"]})
    return out


def build(*, trades: str, db_ok: bool, monitor: dict | None, visual: dict | None, automation: dict | None, profiles: int,
          futures_account: dict | None, stock_account: dict | None, decisions: list[dict], signals: dict | None, backup: dict | None,
          trades_chosen: bool, chart_seen: bool, setup_dismissed: bool, ui_mode: str, point_value_of=None, engine_error: str | None = None) -> dict:
    h = health(trades=trades, db_ok=db_ok, monitor=monitor, visual=visual, automation=automation, profiles=profiles, backup=backup,
               engine_error=engine_error)
    mk = market(trades=trades, visual=visual, signals_market=(signals or {}).get("market"))
    dc = decision(trades=trades, visual=visual, decisions=decisions, signals_summary=(signals or {}).get("summary"),
                  point_value_of=point_value_of)
    rk = risk(trades=trades, futures_account=futures_account, stock_account=stock_account)
    stopped = (automation or {}).get("status") == "emergency_stopped"
    if stopped:                                    # nothing is suggested while everything is stopped
        dc = {**dc, "word": "STOPPED", "tone": "stop", "headline": "Everything is stopped, so I'm not suggesting anything.",
              "do": "Start again when you're ready.", "plan": None}
    sg = setup_guide(trades=trades, trades_chosen=trades_chosen, profiles=profiles, chart_seen=chart_seen,
                     limits_confirmed=rk["limits_confirmed"], prices_ok=bool((monitor or {}).get("healthy")), dismissed=setup_dismissed)
    return {
        "mode": {"practice": True, "label": "PRACTICE MODE", "short": "No real money",
                 "note": "Everything here uses pretend money. Study Terminal can't place, change or cancel real orders.", "live_locked": True},
        "ui_mode": ui_mode, "trades": trades, "stopped": stopped, "emergency": (automation or {}).get("emergency") if stopped else None,
        "health": h, "market": mk, "decision": dc, "risk": rk, "setup": sg,
        "next": next_step(trades=trades, health_=h, setup=sg, risk_=rk, decision_=dc, automation=automation),
        "recent": recent(decisions) if trades == "futures" else [],
        "backup": backup,
    }
