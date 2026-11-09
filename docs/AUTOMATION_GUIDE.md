# Automation guide (futures)

Open **Automation Center** (the default page in futures mode). Everything it does is simulated: Study Terminal never
sends an order to TopstepX or any broker, and it can't enforce limits on your real Topstep account.

## Modes

| Mode | What happens |
|---|---|
| **A · Assisted** (default) | The app watches NQ, MNQ, ES and MES, runs the decision pipeline on every new completed bar and records the result. You place every simulated order yourself (Futures > Live > ticket). |
| **B · Automated paper** | Same monitoring, and the app enters and manages simulated trades by itself, but **only** for strategies that passed walk-forward validation (see below) and only inside every risk limit. No approval per trade. |
| **C · Live** | **Locked.** No order code exists. The panel shows the checklist of what would have to be true first; unlocking needs your explicit written authorization and an independently verified integration. |

**With the research shipped in 0.7.0, no strategy is validated, so Mode B approves nothing.** That is the intended
outcome of the evidence, not a fault. Decisions are still recorded so you can see what would have qualified.

## Controls

- **Start monitoring / Pause / Resume / Stop.** Monitoring starts with the app (setting `automation.autostart`, on by default)
  and resumes after a restart. Missed bars are reconciled before any new decision.
- **Evaluate now** runs one pass immediately.
- **Emergency stop** cancels every simulated working order, flattens simulated positions and stops automation. It stays on,
  even across restarts, until you write a short review note (what happened, what you checked) and clear it. A phone with the
  mobile companion can press it but can't clear it.
- **Contracts**: choose which of NQ, MNQ, ES, MES are monitored. **Research sandbox**: see below.

## The decision pipeline (13 steps, fixed order)

1 Market-data validation · 2 Contract validation · 3 Session validation · 4 Regime classification · 5 Setup identification ·
6 Multi-timeframe (15-min) confirmation · 7 Strategy performance validation · 8 Entry quality · 9 Risk/reward ·
10 Position size · 11 Prop-firm and personal risk · 12 Slippage and costs · 13 Final decision.

Outcomes: **APPROVED FOR PAPER TRADE**, **WATCH ONLY**, **WAIT FOR CONFIRMATION**, **REJECTED**, **INVALIDATED**, **NO TRADE**.
Every result is stored with each step's reasoning (Automation Center > Recent decisions; click a row). A decision's id is
derived from contract, setup, direction and bar time, so the same signal can never be entered twice.

Hard rules: only completed bars are used; no decision on data older than 180 s (configurable) or on delayed data;
no decision when the bar it would act on is old; costs must stay under 25% of the dollar risk; minimum 1.5R after costs.

## How a strategy becomes "validated"

Futures > Evidence > **Run research** does walk-forward testing: parameters are chosen only on earlier folds, then
judged on later ones, and a final chronological holdout is never touched during selection. A strategy/direction is
validated only if its out-of-sample tier is "reliable" **and** the holdout has at least 30 trades, average R above 0
and profit factor above 1.1. A quick backtest never validates anything.

## Trade management (Mode B and the sandbox)

Defaults (Automation config, per strategy or `default`): target 2R; take 50% off at 1R; stop to break-even at 1R;
trailing stop from 1.5R at 1.5 x ATR; exit after 120 minutes; unfilled entry cancelled after 2 bars; exit on invalidation.
Stops are only ever tightened, and every change is recorded with its reason.

## Research sandbox

A separate simulated account where experimental (not validated) strategies may trade so you can watch how they behave
forward. Its trades are labelled `sandbox`, never mixed with the practice account, and never count as evidence.

## Where to look when something happens

- Automation log (Automation Center) and the futures event log (Futures > Live > Risk).
- Alerts page (and desktop notifications) for entries, exits, blocks, gaps, emergency stops and upcoming releases.
- Journal > automated vs manual comparison.
