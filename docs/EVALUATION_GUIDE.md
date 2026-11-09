# Topstep evaluation practice

Study Terminal can apply a Topstep account's rules to its **own simulator** so you can practise an evaluation.
**It does not enforce anything on your real Topstep account, can't see it, and can't change it.**

## Set up

1. Futures > **Rules**: pick a preset (Trading Combine or Express Funded, 50K / 100K / 150K).
2. Compare every number with your Topstep dashboard and edit anything that differs. Presets are starting points with sources
   and the date they were checked; Topstep changes its rules.
3. Press **Confirm**. Until then every warning says the rules are unconfirmed.
4. Optionally set personal limits stricter than the firm's (they're checked separately and reported separately).

## What is tracked

| Item | Notes |
|---|---|
| Maximum Loss Limit | End-of-day trailing from the session-close balance; locks at the starting balance. Breach = account failed in the simulator. |
| Daily Loss Limit | Only if your account has one; soft lockout until the next trade date. |
| Profit target | Progress shown. |
| Consistency | Best day as a share of the target (50% in Combine presets). |
| Trading days / winning days | Days traded; for Express Funded presets, winning days of at least $150 (5 needed) as used for payouts. |
| Position size | Mini-equivalent contracts, 10 micros = 1 mini. Express Funded's Scaling Plan tiers aren't bundled: enter your tier as Max contracts. |
| Flat time | 15:10 CT, earlier on shortened sessions; no new entries after 15:08 CT. |

The Risk panel shows each limit, the room left, warnings at 50/75/90% and an **evaluation status** (in progress; target
reached; target reached but consistency or trading days not met yet; failed on the Maximum Loss Limit or daily loss limit). Blocks stop new simulated entries; they never touch a real account.

## Practising

- Live practice needs a fillable feed (TopstepX API data) or delayed practice turned on.
- Replay works any time and uses the same rules.
- Save a set of limits as a **profile** to switch between accounts.

## Not verified

How Topstep computes the end-of-day balance at the exact flat moment, holiday trade-date merges, and Scaling Plan tiers were
not checked against a real account. See [LIMITATIONS.md](LIMITATIONS.md).
