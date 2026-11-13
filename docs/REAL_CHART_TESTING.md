# Testing Study Terminal on your real TopstepX chart

Everything Study Terminal knows about reading charts so far comes from **synthetic** screenshots that were drawn by a script.
That proves the logic works, not that it reads your TopstepX chart correctly. This guide is how to find out, using the
**Chart check** screen (menu: Chart check). Every result is saved with the time, what Study Terminal read and how it got
each value, so the results can be reviewed later. Nothing here can trade.

## Before you start

1. Install the latest Study Terminal and open it.
2. Open TopstepX in **Microsoft Edge** with the chart you trade (for example MNQ, 5 minutes). Keep the window large and not covered.
3. In Study Terminal: Home > Connect my chart, set the chart up, then turn watching on and wait for the light to say **Working**.
4. Do the checks while the market is open. Futures trade Sunday 6 PM to Friday 5 PM New York time, with a daily break 5-6 PM.

## The checks

How each value is obtained is always shown next to it:

| Label | Meaning |
|---|---|
| read directly | Text read from the chart (contract, timeframe, the price box). |
| worked out from the price scale | Calculated from the price labels on the right side of the chart (for example where a line sits). |
| estimated from the picture | Measured from the drawing itself (candles, indicator lines). Small differences are expected. |
| not available | Study Terminal couldn't get it. This is recorded as "not available", never filled in. |

| Check | What you do | Passes when | How many |
|---|---|---|---|
| Contract | Compare the contract it read with the top of your chart | It matches | 1 |
| Timeframe | Compare the timeframe | It matches | 1 |
| Live price | Press "Read my chart now". It shows the exact picture it read and the number it got. Compare them | The number matches the price box in the picture | 20, spread over a session, in fast and quiet moments |
| Price scale | Compare the price labels it found with your chart | They match | 3 |
| Candles | Hover the last completed candle in TopstepX, type its open, high, low, close | Each within the shown allowance (2 ticks or 1.5 pixels of price) | 10 |
| Indicators | Type the VWAP / EMA values TopstepX shows | Each within the allowance; lines not set up show as not available | 5 |
| Resizing | Make the Edge window smaller, wait, put it back | It keeps reading correctly, or says "Check chart settings", and comes back | 1 |
| Zooming | Zoom the chart in, wait, zoom back | Same as resizing; then do one Live price check | 1 |
| Switching tabs | Click another Edge tab, then back | Within 15 s it says it can't read the chart (and captures nothing from the other tab), then recovers | 1 |
| Minimizing | Minimize Edge, then restore | Within 15 s it says it can't find the chart, then recovers | 1 |
| Frozen chart | Turn your internet off for 2 minutes, then back on | Within about 2 minutes it says the chart isn't updating and suggests nothing, then recovers | 1 |
| Closing TopstepX | Close the TopstepX tab, then open it again | It notices, then picks the chart up again by itself | 1 |
| Restarting | Quit Study Terminal from the tray and reopen | Watching starts again by itself; Stop everything stays on if it was on | 1 |

## Recording rules

- Only results from real screen capture count. If the app is using a test source, the Chart check says so and nothing counts.
- A check that fails stays failed in the record. Running it again adds a new result; it doesn't erase the old one.
- "Not available" is not the same as correct. It means that value can't be relied on.
- The live-price check compares the number with the picture it came from. It shows whether the reading is right; it doesn't
  measure how far behind the real market the TopstepX chart itself is.

## Sending results

The results are in your data folder (`%LOCALAPPDATA%\StudyTerminal\chart_checks\results.jsonl`, with the pictures next to
it). Send `results.jsonl` (and the pictures for any failed checks) and they can be reviewed and added to
`docs/STUDY_TERMINAL_READINESS_REPORT.md`.
