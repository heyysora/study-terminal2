"""Learning center content. Style rules: one concept per section, define every term at first
use, dollars before formulas, no stacked jargon. Quizzes check understanding, not memorization."""
from __future__ import annotations


def L(id, title, module, level, minutes, prereq, sections, terms, quiz, exercise=None):
    return {"id": id, "title": title, "module": module, "level": level, "minutes": minutes, "prerequisites": prereq,
            "sections": [{"heading": h, "body": b} for h, b in sections], "key_terms": terms, "quiz": quiz,
            "exercise": exercise}


def Q(q, options, answer, explain):
    return {"q": q, "options": options, "answer": answer, "explain": explain}


LESSONS = [
    L("basics", "How day trading actually works", "core", "beginner", 8, [], [
        ("What a trade is", "A trade is buying something hoping to sell it higher (going long), or selling it first hoping to buy it back lower (going short). Day trading means every trade is closed the same day, so nothing is held overnight."),
        ("Where profit comes from", "If you buy 10 shares at $50 and sell at $52, you make $2 x 10 = $20. If you sell at $49 instead, you lose $1 x 10 = $10. That's all profit and loss (P&L) is: price change times shares."),
        ("The uncomfortable truth", "Most beginner day traders lose money. Prices move randomly much of the time, and every trade has costs: slippage (getting a slightly worse price than you wanted) and sometimes commissions. A trader needs an edge, a repeatable situation where the odds or payoffs favor them, just to break even."),
        ("Why paper trading first", "Paper trading uses fake money with real prices. It lets you practice the mechanics and find out whether your decisions have an edge, without paying tuition to the market."),
    ], ["long", "short", "P&L", "slippage", "edge", "paper trading"], [
        Q("You buy 20 shares at $30 and sell at $31.50. What's your P&L before costs?", ["$1.50", "$30", "$15", "$31.50"], 1, "$1.50 gain per share x 20 shares = $30."),
        Q("What is an 'edge'?", ["A stock near its high", "A repeatable situation where odds or payoffs favor you", "A fast internet connection", "A type of order"], 1, "Without an edge, costs make you lose slowly even if you're 'right' half the time."),
        Q("Day trading means...", ["Trading only on weekdays", "Closing every position the same day", "Holding for exactly one day", "Trading once per day"], 1, "Day trades open and close within the same session."),
    ]),
    L("candles", "Reading candlesticks", "core", "beginner", 10, ["basics"], [
        ("One candle = one time period", "On a 5-minute chart, each candle shows 5 minutes of trading: where price opened, the highest and lowest it traded, and where it closed (OHLC)."),
        ("Body and wicks", "The thick body spans open to close. Green means it closed higher than it opened; red means lower. The thin lines (wicks) show how far price traveled beyond the body before being pushed back."),
        ("What wicks tell you", "A long lower wick means sellers pushed price down but buyers pushed it back up: rejection of lower prices. A long upper wick means the opposite."),
        ("Patterns worth knowing", "Hammer: long lower wick after a drop. Shooting star: long upper wick after a rise. Engulfing: a candle whose body swallows the previous body, a shift in control. Doji: open equals close, indecision. Inside bar: range inside the prior candle, a pause. A pattern alone is weak; a pattern at a key level, with volume, is information."),
    ], ["OHLC", "body", "wick", "hammer", "shooting star", "engulfing", "doji", "inside bar"], [
        Q("A candle opens at $10, trades down to $9.20, and closes at $9.95. What does the long lower wick suggest?", ["Sellers in full control", "Buyers rejected the lower prices", "Nothing", "The stock will gap up"], 1, "Price was pushed down to $9.20 and bought back up near the open."),
        Q("A bullish engulfing candle is most meaningful when...", ["It appears anywhere", "It forms at support with strong volume", "Volume is very low", "It's the first candle of the day"], 1, "Context (level + volume) turns a pattern into evidence."),
    ], {"type": "spot_setup"}),
    L("ta", "Technical analysis without the hype", "core", "beginner", 8, ["candles"], [
        ("What it is", "Technical analysis studies price and volume to estimate where supply and demand sit. It doesn't predict the future; it organizes evidence."),
        ("Indicators are summaries", "Every indicator is just a calculation on past prices. RSI, MACD and moving averages often say the same thing in different ways, so ten agreeing indicators can really be one piece of evidence counted ten times."),
        ("Combine different kinds of evidence", "Better: combine different types. Trend (moving averages, market structure), location (support, resistance, VWAP), participation (volume), and timing (a candle that confirms). That's how this app scores setups."),
    ], ["indicator", "supply and demand", "confluence"], [
        Q("Why is 'RSI, Stochastic and ROC all say oversold' weak evidence?", ["They're always wrong", "They're computed from the same prices, so mostly redundant", "They only work on daily charts", "They're too slow"], 1, "Momentum oscillators largely measure the same thing."),
    ]),
    L("sr", "Support and resistance", "core", "beginner", 10, ["candles"], [
        ("Support", "Support is a price area where buyers have stepped in before, so falls tend to pause there. Example: a stock bounced at $48 three times this week. $48 is support."),
        ("Resistance", "Resistance is a price area where sellers have shown up before. If a stock failed at $55 twice, $55 is resistance."),
        ("Why levels work at all", "Traders remember prices. People who bought at $55 and watched it drop may sell when it returns to $55 just to break even, and that creates real selling there."),
        ("Breaks and flips", "When resistance breaks on strong volume, it often becomes support on a retest. Many 'breakouts' fail, though, so confirmation matters."),
        ("Key day-trading levels", "Previous day high and low, premarket high and low, the opening range, and VWAP. The app marks all of these on charts."),
    ], ["support", "resistance", "retest", "previous day high/low", "premarket high/low"], [
        Q("A stock failed at $72 twice this week. Today it closes at $72.80 on 3x normal volume. Now $72 is...", ["Irrelevant", "Possible new support on a retest", "Guaranteed support", "Still resistance"], 1, "Broken resistance often flips to support, but it isn't guaranteed."),
        Q("Which of these is NOT a level the app marks?", ["Previous day high", "Opening range", "Your average account balance", "Premarket low"], 2, ""),
    ]),
    L("vwap", "VWAP: today's fair price", "core", "beginner", 10, ["sr"], [
        ("What it is", "VWAP (volume-weighted average price) is the average price of every share traded today, with prices that traded more shares counting more. It resets each morning."),
        ("A dollar example", "If 100 shares traded at $10 and 300 shares at $11, VWAP = (100x10 + 300x11) / 400 = $10.75. Most shares changed hands near $11, so VWAP leans toward $11."),
        ("Why traders care", "Above VWAP, the average buyer today is in profit, so they tend to hold or add. Below VWAP, the average buyer is losing, so they tend to sell into bounces. Large funds also measure their execution against VWAP."),
        ("Reclaims and rejections", "A VWAP reclaim is price closing back above VWAP after being below it. A rejection is failing at VWAP from below, or losing it from above. These are among the app's setups."),
    ], ["VWAP", "VWAP reclaim", "VWAP rejection"], [
        Q("200 shares trade at $20 and 200 at $22. VWAP?", ["$20", "$21", "$22", "$42"], 1, "Equal volume at each price, so it's the plain average: $21."),
        Q("Price is below VWAP all morning. On average, today's buyers are...", ["In profit", "Losing", "Break-even", "Unknown"], 1, ""),
    ], {"type": "find_vwap"}),
    L("ma", "Moving averages", "core", "beginner", 8, ["ta"], [
        ("What they are", "A moving average is the average closing price over the last N candles, updated every candle. A 9-period average uses the last 9 closes."),
        ("SMA vs EMA", "A simple moving average (SMA) weights every candle equally. An exponential moving average (EMA) weights recent candles more, so it reacts faster."),
        ("The stack", "When the 9 EMA is above the 21, which is above the 50, recent prices keep beating older prices. That's an uptrend 'stack'. The reverse is a downtrend stack."),
        ("Dynamic support", "In trends, pullbacks often stall near the 21 EMA. That's the idea behind the trend-pullback setup."),
    ], ["SMA", "EMA", "EMA stack", "pullback"], [
        Q("Which reacts faster to new prices?", ["20 SMA", "20 EMA", "Both equally", "Neither"], 1, "EMAs weight recent prices more."),
        Q("9 EMA < 21 EMA < 50 EMA suggests...", ["Uptrend", "Downtrend", "No information", "High volume"], 1, ""),
    ]),
    L("rsi_macd", "RSI and MACD", "core", "intermediate", 10, ["ma"], [
        ("RSI", "RSI (Relative Strength Index) compares the size of recent up moves with recent down moves on a 0-100 scale. Above 70 means the last ~14 candles were unusually strong; below 30, unusually weak."),
        ("The common mistake", "'RSI below 30, so buy' loses money in downtrends, because RSI can stay low while price keeps falling. Treat RSI as context, not a trigger."),
        ("MACD", "MACD is the gap between a fast and a slow EMA. Its histogram shows whether that gap is growing (momentum accelerating) or shrinking (momentum fading)."),
        ("Divergence", "If price makes a lower low but RSI makes a higher low, selling momentum is fading: a bullish divergence. It's a warning sign, not an entry signal."),
    ], ["RSI", "overbought", "oversold", "MACD", "histogram", "divergence"], [
        Q("RSI is 25 and the stock is in a steady downtrend. The best reading is...", ["Strong buy", "Selling is strong; oversold can stay oversold", "Sell everything", "RSI is broken"], 1, ""),
        Q("A shrinking MACD histogram means...", ["Momentum accelerating", "Momentum fading", "Volume rising", "A gap up"], 1, ""),
    ]),
    L("volume", "Volume and relative volume", "core", "beginner", 8, ["vwap"], [
        ("Volume", "Volume is how many shares traded. Price moves on high volume involve more participants, so they are more likely to be real."),
        ("Relative volume (RVOL)", "RVOL compares volume so far today with what's normal for this time of day. RVOL 2.0 at 10:30 means twice the usual volume by 10:30. The app computes it time-of-day aware."),
        ("Reading it", "A breakout on low RVOL is suspect. A breakout on RVOL above 2 has fuel. Very high RVOL usually means news, so be careful."),
        ("A data caveat", "Free data from Yahoo comes from a partial source, and premarket volume shows as 0. The app labels volume as approximate."),
    ], ["volume", "relative volume", "RVOL"], [
        Q("A stock breaks resistance with RVOL 0.6. That's...", ["Strong confirmation", "Weak participation; more likely to fail", "Irrelevant", "A short signal"], 1, ""),
    ]),
    L("structure", "Market structure", "core", "intermediate", 10, ["sr"], [
        ("Swings", "A swing high is a peak with lower highs on both sides; a swing low is the reverse. The app needs 3 candles on each side, so a swing is confirmed 3 candles later. It's never known in real time."),
        ("Trends defined", "Uptrend: higher highs AND higher lows. Downtrend: lower highs AND lower lows. Anything else is a range."),
        ("Trend changes", "An uptrend is in trouble when price makes a lower low. It's confirmed broken when the next high is also lower."),
        ("Liquidity sweeps", "Many traders put stop orders just below obvious lows. A dip below that low that snaps back above it is a 'sweep': stops were triggered and absorbed. That's the failed-breakdown setup."),
    ], ["swing high", "swing low", "higher high", "lower low", "range", "liquidity sweep"], [
        Q("Swing highs at $50, $52, $51 and swing lows at $48, $49, $47. What happened?", ["Uptrend intact", "The uptrend broke: a lower high and then a lower low", "Nothing can be said", "A gap"], 1, "The last high ($51) is below $52 and the last low ($47) is below $49: the uptrend failed and a downtrend may be starting."),
    ]),
    L("momentum", "Momentum trading", "core", "intermediate", 8, ["volume", "structure"], [
        ("The idea", "Stocks that are moving strongly on heavy volume tend to keep moving in the short term, until they don't."),
        ("Finding them", "The scanner looks for big % moves, high RVOL, enough liquidity, and a clean setup."),
        ("Don't chase", "If the entry was $20.00 and the stock is already $20.80, your stop is much farther away for the same idea. The app labels these 'extended' and says NO TRADE."),
    ], ["momentum", "chasing", "extended"], [
        Q("A setup triggered at $40.00 with a stop at $39.50. The price is now $41.20. Best action?", ["Buy now", "Skip: it's extended; risk per share has more than tripled", "Short it", "Double the size"], 1, "Entering at $41.20 means $1.70 of risk per share instead of $0.50."),
    ]),
    L("breakouts", "Breakout trading", "core", "intermediate", 10, ["sr", "volume"], [
        ("Opening range breakout", "The opening range is the high and low of the first 15 minutes. A close above it with strong volume can start the day's trend."),
        ("Level breakouts", "A close above the previous day high, the premarket high, or a swing high, on strong volume."),
        ("Fake breakouts", "Many breakouts fail: price pops above the level, then closes back below, trapping buyers. That's why the app waits for a trigger above the breakout candle and invalidates on a close back under the level."),
    ], ["opening range", "breakout", "fake breakout", "trigger"], [
        Q("Price breaks above yesterday's high, then closes back below it two candles later. This is...", ["A confirmed breakout", "A failed (fake) breakout", "A doji", "Irrelevant"], 1, ""),
    ]),
    L("reversals", "Reversal trading", "core", "intermediate", 8, ["structure", "rsi_macd"], [
        ("Why reversals are hard", "You're betting against the current move. Trends often go further than looks reasonable."),
        ("Better reversal evidence", "A liquidity sweep of a key low that snaps back, a reclaim of VWAP, divergence, and a structure change (a higher low). The more of these line up, the better."),
        ("Tight invalidation", "Reversals must be cut fast: if price makes a new low, the idea is wrong."),
    ], ["reversal", "counter-trend"], [
        Q("Which is the strongest reversal evidence?", ["RSI under 30 alone", "Sweep of the day's low + VWAP reclaim + higher low", "A red candle", "A news headline"], 1, ""),
    ]),
    L("shorting", "Short selling", "core", "intermediate", 10, ["basics"], [
        ("How it works", "You borrow shares, sell them at $50, buy them back later at $47, return them, and keep the $3 per share."),
        ("Unlimited risk", "If you buy at $50 the most you can lose is $50 per share. If you short at $50 there's no ceiling: a squeeze to $80 costs $30 per share. Stops are not optional."),
        ("Borrowing costs and limits", "Brokers charge a fee to borrow shares, some stocks can't be borrowed at all, and after a 10% drop a short-sale restriction (SSR) can limit shorting. This app has no broker, so it can't check these. It simulates a fee and warns you on every short."),
    ], ["short", "borrow", "short squeeze", "SSR", "borrow fee"], [
        Q("You short 100 shares at $20 and the stock rises to $26. Your loss before costs?", ["$6", "$600", "$2,600", "$0"], 1, "$6 x 100 = $600."),
        Q("What's the maximum possible loss on a short with no stop?", ["The share price", "Unlimited", "Half the price", "Zero"], 1, ""),
    ]),
    L("liquidity", "Liquidity and spreads", "core", "intermediate", 6, ["basics"], [
        ("Liquidity", "Liquidity is how easily you can buy or sell without moving the price. SPY trades tens of millions of shares a day; a tiny stock might trade 50,000."),
        ("The spread", "The bid is the best price buyers offer; the ask is the best price sellers want. The gap between them is the spread. On thin stocks it can be 10 cents or more, and that is a cost every time you enter and exit."),
        ("Why the scanner filters it", "The scanner requires a minimum average volume and dollar volume so your stops actually fill near where you set them."),
    ], ["liquidity", "bid", "ask", "spread", "dollar volume"], [
        Q("Bid $5.00, ask $5.12. You buy then immediately sell 1,000 shares. Spread cost?", ["$12", "$120", "$1.20", "$0"], 1, "$0.12 x 1,000 = $120."),
    ]),
    L("risk", "Risk management", "core", "beginner", 10, ["basics"], [
        ("Decide the loss first", "Before entering, decide where you're wrong (the stop) and how much money that costs. Example: buy at $50, stop at $49, 100 shares = $100 at risk."),
        ("R: thinking in risk units", "Call the money at risk '1R'. If you risk $100, a $200 win is +2R and a full loss is -1R. Measuring in R makes trades comparable."),
        ("Reward to risk", "Risking $100 to make $200 is 2:1. At 2:1 you can be wrong more than half the time and still make money: win 40 trades x $200 and lose 60 x $100, and you're up $2,000 before costs."),
        ("Daily limits", "The app's defaults: risk 0.5% of the account per trade, stop trading after losing 2% in a day or 3 losses in a row. Big losses come from a bad day compounding, not from one trade."),
    ], ["stop loss", "R", "reward:risk", "daily loss limit"], [
        Q("Account $20,000, risk 0.5% per trade. Max loss per trade?", ["$10", "$100", "$1,000", "$200"], 1, "0.5% of $20,000 = $100."),
        Q("Win rate 35%, average win +2.5R, average loss -1R. Profitable before costs?", ["Yes", "No", "Can't tell", "Only on Fridays"], 0, "35 x 2.5 = 87.5R won vs 65R lost: +22.5R per 100 trades."),
    ]),
    L("sizing", "Position sizing", "core", "beginner", 8, ["risk"], [
        ("Size from the stop, not from conviction", "Shares = money you're willing to lose / risk per share. Risking $125 with a stop $2.50 away = 50 shares. A stop $0.50 away = 250 shares."),
        ("Why it matters", "Same dollar risk on every trade means no single trade can wreck the account, whether the stock is $5 or $500."),
        ("Check buying power", "250 shares of a $200 stock is $50,000 of exposure. The app also caps exposure and buying power."),
    ], ["position size", "risk per share", "exposure"], [
        Q("You'll risk $100. Entry $40, stop $39.20. Shares?", ["100", "125", "80", "40"], 1, "$0.80 risk per share; $100 / $0.80 = 125."),
    ]),
    L("psychology", "Trading psychology", "core", "beginner", 8, ["risk"], [
        ("Revenge trading", "After a loss, the urge to win it back fast leads to bigger, worse trades. That's why the app pauses new entries after 3 losses in a row."),
        ("FOMO", "Fear of missing out makes people chase extended moves. The 'extended' label exists for this."),
        ("Moving stops", "Widening a stop to avoid taking a loss turns small losses into big ones. The app never moves your stop for you; only you can."),
        ("Process over outcome", "A good trade can lose and a bad trade can win. Judge decisions by whether you followed your plan."),
    ], ["revenge trading", "FOMO", "process"], [
        Q("You followed your plan exactly and the trade hit its stop. That was...", ["A bad trade", "A good trade with a losing outcome", "Proof the strategy is broken", "A reason to double size"], 1, ""),
    ]),
    L("options", "Options basics (separate module)", "options", "intermediate", 12, ["risk"], [
        ("What an option is", "An option is a contract giving the right, not the obligation, to buy (call) or sell (put) 100 shares at a set price (the strike) before a date (expiration)."),
        ("A dollar example", "A $50 call on XYZ costs $2.00, which is $200 for the contract. If XYZ is $55 at expiration, the call is worth $5.00 ($500): a $300 profit. If XYZ is $49, it expires worthless and you lose $200."),
        ("Time decay", "Options lose value every day as expiration nears, all else equal. Being right slowly can still lose money."),
        ("Why this app doesn't trade options", "Options add leverage, time decay and volatility pricing. Learn the stock mechanics first; the app's signals and simulator are stock-only."),
    ], ["option", "call", "put", "strike", "expiration", "premium", "time decay"], [
        Q("You buy one $30 call for $1.50. At expiration the stock is $31. P&L?", ["+$100", "-$50", "+$50", "-$150"], 1, "Worth $1.00 at expiration ($31 - $30) vs $1.50 paid: -$0.50 x 100 = -$50."),
    ]),
]

GLOSSARY = {
    "ATR": "Average True Range: how much a stock typically moves per candle, including gaps. Used to size stops sensibly.",
    "ask": "The lowest price a seller is currently willing to accept.",
    "backtest": "Testing a strategy on historical data as if trading it at the time.",
    "bid": "The highest price a buyer is currently willing to pay.",
    "Bollinger Bands": "Lines 2 standard deviations above and below a 20-period average; wide bands mean high volatility.",
    "borrow fee": "What a broker charges to lend shares for shorting.",
    "bracket order": "An entry order with an attached stop loss and profit target; when one exit fills the other cancels.",
    "breakout": "Price closing beyond a level it previously couldn't pass.",
    "candlestick": "A chart bar showing open, high, low and close for one period.",
    "confirmation": "Evidence that a setup is working before you enter, e.g. price trading above a trigger.",
    "consolidation": "A tight sideways range where price pauses.",
    "day trade": "A position opened and closed the same day.",
    "divergence": "Price and an oscillator moving in opposite directions, a sign of fading momentum.",
    "doji": "A candle whose open and close are nearly equal: indecision.",
    "drawdown": "The drop from an account's peak value to a later low.",
    "EMA": "Exponential moving average; weights recent prices more than older ones.",
    "engulfing": "A candle whose body fully covers the previous candle's body.",
    "entry range": "The prices where a planned entry still makes sense; above it the trade is 'extended'.",
    "expectancy": "Average profit or loss per trade, over many trades.",
    "extended": "Price has run too far past the planned entry; chasing it worsens risk:reward.",
    "fake breakout": "A breakout that quickly falls back inside the level, trapping buyers.",
    "gap": "When a candle opens well above or below the prior close.",
    "hammer": "A candle with a long lower wick after a decline: buyers rejected lower prices.",
    "higher high": "A swing high above the previous swing high.",
    "higher low": "A swing low above the previous swing low.",
    "invalidation": "The price that proves a trade idea wrong.",
    "liquidity": "How easily shares trade without moving the price.",
    "liquidity sweep": "A quick move through an obvious high or low that triggers stops and then reverses.",
    "long": "Owning shares to profit if the price rises.",
    "lower high": "A swing high below the previous swing high.",
    "lower low": "A swing low below the previous swing low.",
    "MACD": "The difference between a fast and a slow EMA; its histogram shows momentum speeding up or fading.",
    "market order": "Buy or sell immediately at the best available price.",
    "limit order": "Buy at or below (sell at or above) a set price; may not fill.",
    "stop order": "Becomes a market order when a set price trades; used for stop losses and breakout entries.",
    "momentum": "The speed and persistence of a price move.",
    "opening range": "The high and low of the first minutes of the session (15 minutes in this app).",
    "out-of-sample": "Data a strategy wasn't tuned on; the honest test of whether it works.",
    "overfitting": "Tuning a strategy so closely to past data that it fails on new data.",
    "paper trading": "Simulated trading with fake money and real prices.",
    "position size": "How many shares you trade, set from the dollar risk and the stop distance.",
    "premarket": "Trading before the 09:30 ET open (from 04:00 ET).",
    "profit factor": "Gross profits divided by gross losses. Above 1 means profitable.",
    "pullback": "A temporary move against the trend.",
    "R": "Your risk unit: the dollars you lose if the stop is hit. +2R = twice your risk gained.",
    "range": "Price moving sideways between support and resistance without a trend.",
    "relative volume": "Volume compared with what's normal for that time of day (RVOL).",
    "resistance": "A price area where selling has repeatedly stopped advances.",
    "retest": "Price returning to a broken level to check whether it now holds.",
    "reward:risk": "Potential profit divided by potential loss for a trade.",
    "RSI": "Relative Strength Index: 0-100 measure of recent up moves vs down moves.",
    "Sharpe ratio": "Return divided by volatility of returns; higher means smoother returns.",
    "short": "Selling borrowed shares to profit if the price falls.",
    "short squeeze": "Shorts rushing to buy back shares, pushing the price sharply higher.",
    "slippage": "The difference between the price you expected and the price you got.",
    "SMA": "Simple moving average: the plain average of the last N closes.",
    "spread": "The gap between bid and ask.",
    "SSR": "Short-sale restriction (Rule 201): after a 10% drop from the prior close, short sales are only allowed above the best bid for the rest of that day and the next.",
    "stop loss": "A pre-set exit that caps the loss on a trade.",
    "support": "A price area where buying has repeatedly stopped declines.",
    "swing high": "A peak with lower highs on both sides.",
    "swing low": "A trough with higher lows on both sides.",
    "trend": "A sustained direction: higher highs/lows (up) or lower highs/lows (down).",
    "trigger": "The price that must trade for a planned entry to happen.",
    "VWAP": "Volume-weighted average price for the day; above it, today's average buyer is in profit.",
    "walk-forward": "Testing that repeatedly tunes on one period and tests on the next, unseen period.",
    "win rate": "Percentage of trades that made money. Meaningless without the average win and loss.",
}
