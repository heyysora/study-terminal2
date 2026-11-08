"""Futures support: contract specs, sessions, levels, signals, prop-firm risk and a futures paper simulator.

Kept separate from the equity code paths on purpose: a futures contract has a tick size, a dollar value
per tick, an expiration and a 23-hour session, and none of the stock assumptions (shares, 9:30-16:00,
cash buying power) carry over.
"""
