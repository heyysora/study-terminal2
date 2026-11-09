# Paper trading guide

Study Terminal has two separate simulated accounts: the **stock paper account** (Paper trading page) and the
**futures practice account** (Futures > Live). Neither touches real money or any broker.

## Futures practice account

**Placing an order.** Futures > Live > ticket: market, limit or stop, optional bracket (stop and target). The preview shows
ticks, dollars per contract after fees and slippage, and every risk check. If a check fails, the order is refused and the
reason is shown.

**When orders fill.**
- Only on data that can honestly be filled: real-time, near-real-time or polling feeds, replay, and reconciliation of missed bars.
- **Not on delayed data** (Yahoo's futures data is about 10 minutes late) unless you turn on *delayed practice* in
  Futures > Data & simulator; those fills are labelled.
- Market and stop orders get 1 tick of slippage (configurable); one order can take at most 10% of a bar's volume (partial fills).
- Fees are per contract, round turn, from the bundled Topstep fee table (edit them in Data & simulator).

**Account rules** come from the selected preset (Futures > Rules) plus your personal limits:

| Rule | Default |
|---|---|
| Maximum Loss Limit (end-of-day trailing, from the session-close balance) | from preset (50K: $2,000) |
| Daily Loss Limit | off unless your account has it |
| Max contracts | preset (50K: 5 minis / 50 micros) and your own cap |
| Flat by | 15:10 CT (earlier on holiday sessions: session close minus 2 minutes) |
| Personal: risk per trade / daily loss / consecutive losses | $200 / $500 / 3 |
| Personal: min R:R / max trades per session / max slippage | 1.5 / 6 / 4 ticks |
| Personal: no entries around high-impact releases | 15 min before and after |
| Personal: max data age | 180 s |

Rules show as *unconfirmed* until you confirm them against your own Topstep dashboard. Changing any value removes the
confirmation. Changing the account size or starting balance on an account with trades requires a reset.

**What is saved.** Orders, fills, positions and the account state are stored after every change, so a restart doesn't lose
stops or brackets; bars missed while the app was closed are replayed in order first (labelled `reconcile`).

**Reset**: Futures > Data & simulator > Reset (asks for confirmation). Risk profiles let you save and load sets of limits.

## Stock paper account

Paper trading page: market, limit, stop and bracket orders, shorts, conservative fills, commissions, risk limits.
See [USER_GUIDE.md](USER_GUIDE.md#paper-trading).
