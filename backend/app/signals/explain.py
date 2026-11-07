"""Beginner-first explanations for each setup. Every term is defined the first time it's used,
and money examples come before ratios."""
from __future__ import annotations

SETUP_EDU = {
    "vwap_reclaim": {
        "what": "Price was trading below VWAP and just closed back above it.",
        "why": "VWAP is the average price everyone paid today, weighted by how many shares traded at each price. "
               "When price climbs back above it, the average buyer today goes from losing to winning, and many "
               "traders treat VWAP as the line between 'buyers in control' and 'sellers in control'.",
        "confirm": "Enter only if price trades above the reclaim candle's high. That shows buyers are following through, not just poking above VWAP.",
        "fail": "If price closes back below VWAP, the reclaim failed. Those failures often drop fast because the buyers who just bought are now losing.",
    },
    "vwap_rejection": {
        "what": "Price was above VWAP and just closed back below it.",
        "why": "VWAP is today's volume-weighted average price. Losing it means the average buyer today is now underwater, which can turn buyers into sellers.",
        "confirm": "Enter only if price trades below the rejection candle's low.",
        "fail": "A close back above VWAP cancels the idea.",
    },
    "orb_long": {
        "what": "Price broke above the opening range: the high of the first 15 minutes of the session.",
        "why": "The first minutes of the day set a battle zone. Breaking out of it with strong volume often starts the day's trend.",
        "confirm": "Enter above the breakout candle's high, with volume clearly above normal.",
        "fail": "Falling back inside the opening range means the breakout was false. Those are common in choppy markets.",
    },
    "orb_short": {
        "what": "Price broke below the opening range low (the low of the first 15 minutes).",
        "why": "Breaking out of the opening range on heavy volume often starts the day's trend, in this case down.",
        "confirm": "Enter below the breakdown candle's low on above-normal volume.",
        "fail": "Climbing back inside the opening range cancels it.",
    },
    "level_breakout": {
        "what": "Price closed above a resistance level (yesterday's high, the premarket high, or a recent swing high) on strong volume.",
        "why": "Resistance is a price where sellers showed up before. Closing above it on heavy volume suggests those sellers are used up.",
        "confirm": "Enter above the breakout candle's high. Even better if a retest of the level holds.",
        "fail": "A close back below the level is a 'fake breakout'. Buyers who chased are trapped and often sell quickly.",
    },
    "level_breakdown": {
        "what": "Price closed below a support level (yesterday's low, the premarket low, or a recent swing low) on strong volume.",
        "why": "Support is a price where buyers stepped in before. Breaking it on volume suggests those buyers are gone.",
        "confirm": "Enter below the breakdown candle's low.",
        "fail": "A close back above the level cancels the breakdown.",
    },
    "trend_pullback_long": {
        "what": "In an uptrend, price dipped to the 21 EMA and printed a bullish candle.",
        "why": "In an uptrend (higher highs and higher lows) dips are where trend traders buy. The 21 EMA, a moving average that weights recent prices more, often acts as that dip level.",
        "confirm": "Enter above the pullback candle's high, which shows the trend is resuming.",
        "fail": "A close below the 50 EMA means the trend is breaking down, not pulling back.",
    },
    "trend_pullback_short": {
        "what": "In a downtrend, price bounced to the 21 EMA and printed a bearish candle.",
        "why": "In a downtrend (lower highs and lower lows) bounces are where trend traders short.",
        "confirm": "Enter below the bounce candle's low.",
        "fail": "A close above the 50 EMA means the downtrend is breaking.",
    },
    "failed_breakdown": {
        "what": "Price dipped below a known low, then closed back above it (a 'liquidity sweep').",
        "why": "Many traders keep stop-loss orders just under obvious lows. When price runs those stops and immediately recovers, it shows buyers absorbed all that forced selling.",
        "confirm": "Enter above the sweep candle's high.",
        "fail": "A new low below the sweep candle means sellers are still in control.",
    },
    "failed_breakout": {
        "what": "Price poked above a known high, then closed back below it.",
        "why": "Breakout buyers bought the poke above the high. Closing back below traps them, and their selling can push price down.",
        "confirm": "Enter below the sweep candle's low.",
        "fail": "A new high above the sweep candle cancels it.",
    },
}

GLOSSARY_INLINE = {
    "R": "R is how much you lose if the stop is hit. If you risk $50, then 1R = $50 and a 2R target makes $100.",
    "stop": "A stop loss is a pre-set exit that caps the loss if the trade goes wrong.",
    "ATR": "ATR (Average True Range) is how much the stock typically moves per bar. It's used to size stops sensibly.",
}


def money_example(direction: str, entry: float, stop: float, t2: float, qty: int) -> str:
    risk = abs(entry - stop) * qty
    reward = abs(t2 - entry) * qty
    verb = "buy" if direction == "long" else "short"
    return (f"In dollars: {verb} {qty} shares near ${entry:,.2f}. If the stop at ${stop:,.2f} is hit you lose about ${risk:,.0f}. "
            f"If the second target at ${t2:,.2f} is reached you make about ${reward:,.0f}. "
            f"That's ${reward / risk if risk else 0:.1f} of potential reward for every $1 risked.")
