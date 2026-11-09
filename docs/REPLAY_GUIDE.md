# Replay guide (futures)

Replay plays a past session bar by bar so you can practise or test automation without waiting for the market.
Futures > **Replay**.

1. Pick the contract (from the product buttons), a **date** and the **bar timeframe**: 1-minute, 5-minute, or auto (1-minute
   when available). Yahoo's 1-minute history goes back about 7 days, 5-minute about 60.
2. Optional: **Run automation in replay**, approved strategies only or including experimental ones. Automated replay trades are
   labelled `replay-auto`; yours are `replay`.
3. **Start**, then **Step**, or **Play** with pause and speed controls.

Rules that keep it honest:
- Only bars up to the replay clock are visible; signals, levels and the decision pipeline never see a future bar.
- Orders fill with the same simulator rules as live practice (slippage, fees, partial fills, flat time, loss limits).
- Replay has its own simulated account and storage, separate from the practice account and from evidence.
- Replay survives a restart: position, orders and clock are saved.

**Review** lists every replay trade across sessions with net result and R (when the entry had a bracket stop), measures
automated and manual replay trades separately, and runs the journal's mistake checks (no stop, chasing, overtrading).
