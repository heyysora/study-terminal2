"""Plain-language layer: the one place that decides which words the interface uses.

Display only. Nothing here changes a decision, a status value, a limit or stored data: it turns values the app already produced
into words a beginner can read, and keeps the original text so it is always one click away.

`python -m app.plain` prints the word list as JSON; frontend/src/plain.json is that output (test_plain.py fails if they differ).
"""
from __future__ import annotations

import json
import re

# ---- what the app is telling you to do -------------------------------------------------------------------------------------------
# Every "don't trade" outcome reads WAIT. Ideas read as practice ideas, because Study Terminal only ever practises.
ACTIONS: dict[str, dict] = {
    "WAIT": {"word": "WAIT", "tone": "wait"},
    "NO TRADE": {"word": "WAIT", "tone": "wait"},
    "NO_TRADE": {"word": "WAIT", "tone": "wait"},
    "WATCH ONLY": {"word": "WAIT", "tone": "wait"},
    "WATCH_ONLY": {"word": "WAIT", "tone": "wait"},
    "WAIT FOR CONFIRMATION": {"word": "WAIT", "tone": "wait"},
    "REJECTED": {"word": "WAIT", "tone": "wait"},
    "INVALIDATED": {"word": "WAIT", "tone": "wait"},
    "BLOCKED": {"word": "STOPPED", "tone": "stop"},
    "LONG": {"word": "PRACTICE IDEA: UP", "tone": "idea"},
    "SHORT": {"word": "PRACTICE IDEA: DOWN", "tone": "idea"},
    "APPROVED": {"word": "PRACTICE IDEA", "tone": "idea"},
    "EXIT": {"word": "CLOSE THE PRACTICE TRADE", "tone": "exit"},
}

# ---- how fresh the prices are ----------------------------------------------------------------------------------------------------
# level: ok / slow / bad. The underlying status values are untouched: trading rules depend on them.
STATUSES: dict[str, dict] = {
    "realtime": {"word": "Working", "level": "ok", "explain": "Prices are arriving live."},
    "near_realtime": {"word": "Working", "level": "ok", "explain": "Prices are arriving within a few seconds."},
    "polling": {"word": "Working", "level": "ok", "explain": "Prices are checked every few seconds."},
    "screen_capture": {"word": "Working", "level": "ok", "explain": "Study Terminal is reading your chart from the screen."},
    "delayed": {"word": "Old prices (delayed)", "level": "slow", "explain": "These prices are several minutes behind the real market. They are fine for learning, not for timing a trade."},
    "historical": {"word": "Past prices", "level": "slow", "explain": "These are prices from the past, not from right now."},
    "replay": {"word": "Replay of a past day", "level": "slow", "explain": "You are replaying an earlier day. Nothing here is happening now."},
    "cached": {"word": "Saved earlier", "level": "slow", "explain": "The newest prices couldn't be fetched, so an earlier copy is shown."},
    "reconcile": {"word": "Catching up", "level": "slow", "explain": "Study Terminal is filling in prices it missed."},
    "stale": {"word": "Chart isn't updating", "level": "bad", "explain": "The prices have stopped changing, so they can't be trusted right now."},
    "unreadable": {"word": "Can't read the chart", "level": "bad", "explain": "Study Terminal can see the chart window but can't read the numbers on it."},
    "disconnected": {"word": "Can't find the chart", "level": "bad", "explain": "The chart window is closed, hidden or minimized."},
    "unavailable": {"word": "No prices", "level": "bad", "explain": "No prices are arriving."},
    "stopped": {"word": "Not watching", "level": "off", "explain": "Watching is turned off. Nothing is being read."},
    "paused": {"word": "Paused", "level": "off", "explain": "Watching is paused."},
}

# ---- how a value on the Visual Monitor was obtained -------------------------------------------------------------------------------
SOURCE_CLASSES: dict[str, str] = {
    "DIRECTLY_READ": "Read from the chart",
    "CALCULATED_FROM_CALIBRATION": "Worked out from the chart",
    "VISUALLY_ESTIMATED": "Estimated from the picture",
    "UNAVAILABLE": "Couldn't read",
}

# ---- terms: technical word -> everyday words + a one-line explanation -------------------------------------------------------------
TERMS: dict[str, dict] = {
    "market_structure": {"technical": "Market structure", "simple": "Market direction", "explain": "Whether price has been making higher highs (going up), lower lows (going down) or neither."},
    "mtf": {"technical": "Multi-timeframe agreement", "simple": "Do the charts agree?", "explain": "Whether the short-term chart and the bigger chart point the same way."},
    "volatility": {"technical": "Volatility", "simple": "How fast is the market moving?", "explain": "How big the price swings are right now."},
    "reward_risk": {"technical": "Reward/risk (R)", "simple": "Possible gain vs. possible loss", "explain": "How much you could gain for every $1 you could lose. 2 means $2 gained per $1 risked."},
    "stop": {"technical": "Stop loss", "simple": "Exit-if-wrong price", "explain": "The price where the plan gives up and takes a small loss so it can't become a big one."},
    "target": {"technical": "Target", "simple": "Take-the-gain price", "explain": "The price where the plan takes its profit."},
    "entry": {"technical": "Entry", "simple": "Start price", "explain": "The price where the practice trade would begin."},
    "drawdown": {"technical": "Drawdown", "simple": "Money lost from your best point", "explain": "How far the account has dropped from its highest value."},
    "expectancy": {"technical": "Expectancy", "simple": "Average result per trade", "explain": "What a trade made or lost on average, counting wins and losses together."},
    "profit_factor": {"technical": "Profit factor", "simple": "Money won for every $1 lost", "explain": "Total winnings divided by total losses. Above 1 means winnings were bigger."},
    "slippage": {"technical": "Slippage", "simple": "Price slip", "explain": "The small difference between the price you wanted and the price you actually got."},
    "mll": {"technical": "Maximum Loss Limit", "simple": "Money left before the account fails", "explain": "If the account drops below this line, the trading firm closes it."},
    "dll": {"technical": "Daily loss limit", "simple": "Most you can lose today", "explain": "Once today's losses reach this amount, new practice trades are stopped until tomorrow."},
    "open_risk": {"technical": "Open risk", "simple": "At risk right now", "explain": "What you would lose if every open practice trade hit its exit-if-wrong price."},
    "paper": {"technical": "Paper trading / simulator", "simple": "Practice", "explain": "Pretend trading with pretend money. Nothing is sent to a real account."},
    "validated": {"technical": "Validated strategy", "simple": "Tested idea", "explain": "A trading idea that kept working on days it had never seen during testing."},
    "walk_forward": {"technical": "Walk-forward / out-of-sample", "simple": "Tested on days it hadn't seen", "explain": "The idea is tuned on older days, then checked on later days it wasn't tuned on."},
    "evidence_tier": {"technical": "Evidence tier", "simple": "How well tested is this idea?", "explain": "How much independent testing supports the idea."},
    "data_confidence": {"technical": "Data confidence", "simple": "How sure am I that I'm reading the chart right?", "explain": "High, medium or low. This is about reading the chart, not about the trade working."},
    "vwap": {"technical": "VWAP", "simple": "Today's average price", "explain": "The average price paid today, weighted by how much traded. Above it, buyers have been in control."},
    "ema": {"technical": "EMA", "simple": "Moving average", "explain": "A smoothed line of recent prices. It shows the general direction."},
    "rth": {"technical": "RTH", "simple": "Main trading hours", "explain": "The busiest part of the trading day, when the stock market is open."},
    "calibration": {"technical": "Calibration", "simple": "Check chart settings", "explain": "Making sure Study Terminal lines up the prices on your chart correctly."},
    "contract": {"technical": "Contract", "simple": "Contract", "explain": "One unit of a futures market. More contracts means bigger gains and bigger losses."},
    "tick": {"technical": "Tick", "simple": "Smallest price step", "explain": "The smallest amount the price can move."},
    "bias": {"technical": "Bias", "simple": "Which way it's leaning", "explain": "Whether the signs point more up, more down, or neither."},
    "flatten": {"technical": "Flatten", "simple": "Close everything", "explain": "Close every open practice trade."},
    "automation": {"technical": "Automation", "simple": "Watching", "explain": "Study Terminal checking the market for you on a timer."},
}

# ---- inline replacements for sentences that come from deeper in the app (alerts, errors, unmatched reasons) -------------------------
# [pattern, replacement, flags] - flags "i" = ignore case
SIMPLIFY: list[list[str]] = [
    [r"\bRTH\b", "main trading hours", "i"],
    [r"\bpaper[- ]trading\b", "practice trading", "i"],
    [r"\bpaper (account|position|order|trade|simulator|equity)", r"practice \1", "i"],
    [r"\bthe simulator\b", "the practice account", "i"],
    [r"\bsimulated\b", "practice", "i"],
    [r"\bsim balance\b", "practice money", "i"],
    [r"\bis stale\b", "isn't updating", "i"],
    [r"\bstale\b", "not updating", "i"],
    [r"\breward[-/ ]to[-/ ]risk\b|\breward/risk\b|\brisk/reward\b", "possible gain vs. possible loss", "i"],
    [r"\bvalidated strategy\b", "tested idea", "i"],
    [r"\bwalk-forward\b|\bout-of-sample\b", "tested on unseen days", "i"],
    [r"\bslippage\b", "price slip", "i"],
    [r"\bflattened\b", "closed", "i"],
    [r"\bflatten\b", "close", "i"],
    [r"\bEMERGENCY STOP\b", "Stop everything", ""],
    [r"\bautomation orders\b", "practice orders the app placed", "i"],
    [r"\bmini-equivalent contracts\b", "contracts (counting 10 micros as 1)", "i"],
    [r"\bcalibration\b", "chart settings check", "i"],
    [r"\brisk engine\b", "your limits", "i"],
    [r"\bLONG\b", "UP", ""],
    [r"\bSHORT\b", "DOWN", ""],
    [r"the last break of structure was (up|down)", r"price last pushed \1 through a recent turning point", "i"],
    [r"\bbreak of structure\b|\bBOS\b", "push through a recent turning point", "i"],
    [r"\bIBL\b", "the first hour's low", ""],
    [r"\bIBH\b", "the first hour's high", ""],
    [r"\bVWAP\b", "today's average price", ""],
    [r"\bbullish\b", "leaning up", "i"],
    [r"\bbearish\b", "leaning down", "i"],
]

# ---- why the app says WAIT ----------------------------------------------------------------------------------------------------------
# (pattern on the original reason, kind, headline, what to do). Headline/do may use \1 etc. from the pattern.
REASONS: list[list[str]] = [
    # chart reading
    [r"another tab is open", "chart", "Your browser is showing a different tab, so I'm not looking.", "Switch back to the TopstepX tab. For privacy, nothing else is ever read."],
    [r"window is minimized", "chart", "The TopstepX window is minimized, so I can't see it.", "Open the window again. It can sit behind other windows, but not minimized."],
    [r"Another window covers the chart", "chart", "Another window is covering your chart.", "Move the other window off the chart."],
    [r"Layout changed|layout changed|capture region is outside|calibration|Recalibrate", "chart", "Your chart looks different from when it was set up.", "Check chart settings and select the chart area again."],
    [r"Chart frozen", "chart", "Your chart has stopped moving.", "Check that TopstepX is connected and not paused or in replay."],
    [r"^STALE\b", "chart", "Your chart isn't updating.", "Check that TopstepX is open and the chart is moving. Study Terminal starts again by itself when it does."],
    [r"^DISCONNECTED\b", "chart", "I can't find your chart window.", "Open TopstepX in Microsoft Edge and don't minimize it."],
    [r"^UNREADABLE\b|^The chart couldn't be read", "chart", "I can't read your chart right now.", "Make sure nothing is covering the chart. If it keeps happening, check chart settings."],
    [r"^(PAUSED|STOPPED)\b", "chart", "Watching is turned off.", "Turn watching on to get a suggestion."],
    [r"^Chart doesn't match its setup: (.+)$", "chart", r"\1", "Switch the TopstepX chart back, or set up a new chart for this market."],
    [r"^Instrument uncertain", "chart", "I'm not sure which market this chart shows.", "Make sure the market name (for example MNQ) is visible at the top of the chart."],
    [r"^Timeframe uncertain", "chart", "I'm not sure how much time each candle on this chart covers.", "Make sure the timeframe (for example 5m) is visible at the top of the chart."],
    [r"^Current price can't be read", "chart", "I can't read the current price on your chart.", "Make sure the price scale on the right side of the chart is visible."],
    [r"^Only (\d+) candles readable", "chart", r"I can only see \1 candles, which isn't enough to judge.", "Zoom the chart out a little so more candles are visible."],
    [r"^Candle bodies", "chart", "I can't make out the recent candles clearly.", "Zoom in a little, or check the candle colors in chart settings."],
    [r"recognition confidence is low", "chart", "I'm not confident I'm reading your chart correctly.", "Check chart settings."],
    # data
    [r"^Data incomplete", "data", "I don't have enough of the chart yet to judge.", "Nothing to do. This fills in after the market has been open for a while."],
    [r"^Market data failed validation", "data", "The prices I received don't look right, so I'm not using them.", "Nothing to do. I check again every few minutes."],
    [r"^No decisions on delayed data", "data", "I only have old (delayed) prices, so I won't suggest a trade from them.", "Connect your TopstepX chart so I can see current prices."],
    [r"^No decisions on (\w+) data", "data", "I don't have current prices right now.", "Connect your TopstepX chart, or wait until the market is open."],
    [r"^Market data is too old|^Market data is [\d.,]+ s old", "data", "The last price I saw is too old to act on.", "Nothing to do if the market is closed. Otherwise check that your chart is updating."],
    # contract
    [r"has expired\.$|^Past the roll date", "market", "This chart shows an old contract that traders have moved on from.", "Switch your TopstepX chart to the current contract."],
    # time of day
    [r"^Outside RTH", "time", "It's outside the main trading hours.", "Nothing to do. Come back during the main trading hours."],
    [r"^Too close to the flat-by time", "time", "It's too close to the end of the trading day to start something new.", "Nothing to do. Try again tomorrow."],
    [r"isn't trading right now", "time", "This market is closed right now.", "Nothing to do. It reopens after the break, weekend or holiday."],
    # market conditions
    [r"^Extreme volatility", "market", "The market is moving too wildly right now.", "Wait for it to calm down."],
    [r"^Move already extended", "market", "The move has already happened. Jumping in late is risky.", "Wait for the next clear chance."],
    [r"^Price is near a key level", "market", "Price is close to an important level. I'm waiting to see what it does there.", "Keep watching. I'll tell you if a plan forms."],
    [r"^No setup|^No active setup", "market", "Nothing worth trading right now.", "That's normal. Most of the time the right move is to wait."],
    [r"intraday range is unusually wide", "market", "Prices are swinging around a lot today.", "Be extra careful: moves can reverse quickly."],
    [r"^Against the 15-minute", "market", "The bigger chart points the other way.", "Wait until the short-term and bigger charts agree."],
    [r"invalidated before entry", "market", "The idea I was watching stopped making sense before it started.", "Nothing to do. I'm looking for the next one."],
    [r"^Entry is gone", "market", "The good starting price has already passed.", "Don't chase it. Wait for the next chance."],
    # testing
    [r"^Potential (LONG|SHORT) setup", "testing", "I noticed a possible move, but this kind of idea hasn't passed testing yet.", "You can watch how it plays out. It isn't a suggestion to trade."],
    [r"isn't a validated strategy", "testing", "This kind of idea hasn't passed testing yet, so it's for watching only.", "You can watch how it plays out. It isn't a suggestion to trade."],
    # your limits
    [r"^Reward/risk too low|^Reward-to-risk to the first target is ([\d.]+); your minimum is ([\d.]+)", "risk", "The possible gain is too small for the possible loss.", "Wait for a better chance."],
    [r"^Even one contract would exceed", "risk", "Even the smallest trade would risk more than your limits allow.", "Wait for a trade with a closer exit-if-wrong price."],
    [r"^This trade risks \$([\d,]+(?:\.\d+)?) .*per-trade limit is \$([\d,]+(?:\.\d+)?)", "risk", r"This trade could lose $\1 and your limit is $\2 per trade.", "Wait for a smaller trade, or review your limits in Settings."],
    [r"^Open risk would be \$([\d,]+(?:\.\d+)?); your limit is \$([\d,]+(?:\.\d+)?)", "risk", r"With this trade you would have $\1 at risk and your limit is $\2.", "Close a practice trade first, or wait."],
    [r"Maximum Loss Limit", "risk", "If this trade lost, the account would fail.", "Wait. Protecting the account comes first."],
    [r"Daily Loss Limit|your own daily limit", "risk", "This trade could lose more than you have left to lose today.", "Stop for today, or wait for a smaller trade."],
    [r"the limit is (\d+(?:\.\d+)?)", "risk", r"That would be more contracts than your limit of \1.", "Use fewer contracts."],
    [r"^A stop loss is required", "risk", "Every practice trade needs an exit-if-wrong price.", "Add one before placing the trade."],
    [r"^Risk checks couldn't run", "risk", "I couldn't check this trade against your limits, so the answer is wait.", "Nothing to do. I'll check again."],
    [r"^Costs are too large", "risk", "Fees would eat too much of this trade.", "Wait for a trade with more room."],
    [r"^Expected slippage", "risk", "The price is jumping around too much to get a fair starting price.", "Wait for calmer prices."],
    # good news
    [r"passed every check", "idea", "This plan passed every check.", "You can practice it. It is not a promise that it will work."],
    [r"^Stop [\d.,]+ reached", "exit", "The price reached the plan's exit-if-wrong price.", "Close the practice trade. A small loss is part of the plan."],
    [r"^Target 2 [\d.,]+ reached", "exit", "The price reached the plan's take-the-gain price.", "Close the practice trade."],
]

_REASONS = [(re.compile(p, re.I), k, h, d) for p, k, h, d in REASONS]
_SIMPLIFY = [(re.compile(p, re.I if f == "i" else 0), r) for p, r, f in SIMPLIFY]


def simplify(text: str | None) -> str:
    """Replace known jargon inside a sentence. Unknown words are left exactly as they are."""
    out = text or ""
    for rx, rep in _SIMPLIFY:
        out = rx.sub(rep, out)
    return out


def plain_reason(reason: str | None) -> dict:
    """A reason the app already produced -> headline + what to do. The original is always returned too."""
    raw = (reason or "").strip()
    for rx, kind, head, do in _REASONS:
        m = rx.search(raw)
        if m:
            try:
                head = m.expand(head) if "\\" in head else head
            except (re.error, IndexError):
                pass
            return {"headline": head, "do": do, "kind": kind, "original": raw, "matched": True}
    return {"headline": simplify(raw) or "No reason was recorded.", "do": "", "kind": "other", "original": raw, "matched": False}


def plain_action(action: str | None) -> dict:
    a = ACTIONS.get((action or "").upper().strip())
    return dict(a) if a else {"word": "WAIT", "tone": "wait"}


def plain_status(status: str | None) -> dict:
    s = STATUSES.get((status or "").lower())
    return dict(s) if s else {"word": "No prices", "level": "bad", "explain": "No prices are arriving."}


def confidence_word(x: float | None) -> str:
    """How sure the app is that it read the chart correctly. Not a chance of winning."""
    if x is None:
        return "Unknown"
    return "High" if x >= 0.8 else "Medium" if x >= 0.6 else "Low"


def export() -> dict:
    return {"actions": ACTIONS, "statuses": STATUSES, "source_classes": SOURCE_CLASSES, "terms": TERMS, "simplify": SIMPLIFY,
            "reasons": REASONS}


if __name__ == "__main__":
    print(json.dumps(export(), indent=1, sort_keys=True))
