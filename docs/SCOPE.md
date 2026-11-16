# What Study Terminal is for, and what is deliberately not being built

Study Terminal is meant to be exceptionally good at three things:

1. **Seeing the market** — reading your TopstepX chart correctly, or saying plainly that it cannot.
2. **Recognising a genuinely good opportunity** — and recognising far more often that there isn't one.
3. **Telling you in time** — while the opportunity still exists, with the numbers that described it still true.

Everything in the app should be traceable to one of those. This file records what is being left out on purpose, so
that "we never got to it" and "we decided against it" don't blur together over time.

## The thing that decides all of this

**No strategy has passed out-of-sample testing.** NQ and MNQ are inconclusive; ES and MES lose money out of sample.
That single fact is the most important one in the project, and it governs what is worth building next.

It means the bottleneck is not the number of patterns the app can name. It is that the patterns it already names
have not been shown to predict anything. Adding more detectors does not move that; it moves in the opposite
direction, because every additional detector is another way to find a shape in noise, and more ways to search the
same data make a false positive easier to come by, not harder.

## Deliberately not built (yet)

Asked for across the expansion briefs, and declined for now:

| Asked for | Why not yet |
|---|---|
| Liquidity sweeps, break of structure, change of character, fair value gaps, displacement | Each needs a precise, testable definition, and then evidence it improves results out of sample. Without that they are chart vocabulary, not signals. The brief's own rule — "test whether the new capability actually improves results rather than assuming it does" — is the rule being followed here. |
| Volume profile | Needs reliable volume. Screen capture does not give reliable volume. Building it on what the picture shows would mean inventing precision that isn't there. |
| Order-book depth, bid/ask movement, trade direction, order flow | Not visible in a chart screenshot, and there is no free feed for the TopstepX contracts. The brief says "do not invent order-flow information from candlestick screenshots", and that is exactly right. |
| Market-regime strategy selection | Classifying a regime is easy; showing that switching strategy by regime improves out-of-sample results is the hard part, and it is the only part that matters. With no strategy validated in the first place, there is nothing to switch between. |
| News-driven regime detection | Would need a paid news feed with reliable timestamps. The $0/month rule stands. |
| More indicators (additional EMAs, oscillators, composite scores) | The app already computes more than has been shown to be useful. Another one is another free parameter. |

None of this is permanent. The route back for any row is the same: a precise definition, a test that can fail, and
out-of-sample evidence it helps. The machinery to do that already exists (walk-forward plus an untouched holdout,
re-run weekly). What is missing is the evidence, not the code.

## What is worth building instead

In priority order, all three serving the list at the top:

1. **Proof the pipeline works on the user's own machine** — done: the acceptance test checks the price read off the
   pixels against the price TopstepX writes into its own tab name, and refuses to claim success otherwise.
2. **Speed where it changes an outcome** — a full chart read is 3.5x faster, and a stop being hit is announced on
   the next price read rather than the next full one. Entries deliberately still wait for a full read.
3. **Not alerting when the alert would be wrong** — an entry whose price has already run past is not sent.
4. **Evidence that any strategy works at all** — the weekly out-of-sample run. This is the one that would change
   what the app is for, and nothing else on this list substitutes for it.

## The honest summary

Study Terminal today is a careful pair of eyes on a chart with trustworthy plumbing and no validated edge. The
plumbing is worth getting right, and that is most of what has been built. But a faster, better-instrumented way to
produce signals that have not been shown to work is still a way to produce signals that have not been shown to
work, and no amount of engineering in the first half of that sentence fixes the second.
