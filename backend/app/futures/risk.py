"""Prop-firm rules and personal risk limits for futures, evaluated against the futures paper account.

Two separate layers, never merged:
  * PropRules     - what the firm says (Topstep or any other). Comes from an editable preset with sources.
                    `confirmed` stays False until you confirm the numbers against your own account.
  * PersonalRisk  - your own, usually tighter, limits.

Study Terminal applies both to its own simulator: it warns as limits get close and blocks new paper
entries once one is hit. It has no connection that could enforce anything on a real Topstep account, and
every message that blocks or warns says so.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, time, timedelta
from pathlib import Path

from .contracts import CT, ProductSpec, parse_hhmm

PRESETS_FILE = Path(__file__).with_name("prop_presets.json")
SIM_ONLY = "Applies to Study Terminal's simulator only; it cannot enforce rules on your real Topstep account."


def load_presets() -> dict:
    return json.loads(PRESETS_FILE.read_text(encoding="utf-8"))


@dataclass
class PropRules:
    preset_id: str = "topstep_tc_50k"
    firm: str = "Topstep"
    account_type: str = "trading_combine"
    label: str = "Topstep Trading Combine 50K"
    account_size: float = 50000
    starting_balance: float = 50000
    max_loss_limit: float | None = 2000
    mll_type: str = "eod_trailing"          # eod_trailing | intraday_trailing | static
    mll_lock_balance: float | None = 50000  # trailing stops once the floor reaches this
    daily_loss_limit: float | None = None
    dll_behavior: str = "soft_lockout"      # soft_lockout | account_fail
    profit_target: float | None = 3000
    consistency_pct: float | None = 50
    consistency_basis: str = "profit_target"
    max_minis: float | None = 5
    micro_ratio: float = 10
    flat_by_ct: str | None = "15:10"
    no_new_entries_after_ct: str | None = "15:08"
    trade_day_start_ct: str = "17:00"
    scaling_plan: bool = False
    confirmed: bool = False
    confirmed_at: str | None = None
    enabled: bool = True

    @classmethod
    def from_dict(cls, d: dict | None) -> "PropRules":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in names})

    @classmethod
    def from_preset(cls, preset_id: str) -> "PropRules":
        p = next((x for x in load_presets()["presets"] if x["id"] == preset_id), None)
        if not p:
            raise KeyError(f"No preset {preset_id}")
        return cls.from_dict({**p, "preset_id": preset_id, "confirmed": False})

    def to_dict(self) -> dict:
        return asdict(self)

    def initial_floor(self) -> float | None:
        if self.max_loss_limit is None:
            return None
        return self.starting_balance - self.max_loss_limit


@dataclass
class PersonalRisk:
    enabled: bool = True
    max_risk_per_trade_usd: float | None = 200
    max_daily_loss_usd: float | None = 500
    max_contracts: float | None = None       # mini-equivalent; None = use firm limit
    max_consecutive_losses: int | None = 3
    daily_profit_target_usd: float | None = None   # stop taking new trades once reached (optional)
    min_reward_risk: float | None = 1.5
    max_open_risk_usd: float | None = None
    require_stop: bool = True
    rth_only: bool = False
    no_trade_windows_ct: list[list[str]] = field(default_factory=list)   # [["08:25","08:35"], ...]
    warn_at: list[float] = field(default_factory=lambda: [0.5, 0.75, 0.9])
    max_trades_per_session: int | None = 6
    max_slippage_ticks: float | None = 4          # refuse entries whose expected slippage exceeds this
    event_block_minutes: int | None = 15          # no new entries this many minutes before/after a high-impact release
    max_data_age_seconds: float | None = 180      # live data older than this blocks entries (fillable data only)

    @classmethod
    def from_dict(cls, d: dict | None) -> "PersonalRisk":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in names})

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AccountSnapshot:
    """What the risk layer needs from an account. Built by the futures paper engine (or entered by hand)."""
    now: datetime
    trade_date: str | None
    balance: float                 # realized, net of fees
    unrealized: float
    day_pnl: float                 # net, realized + unrealized, current trade date
    mll_floor: float | None
    daily_results: dict[str, float]  # closed trade dates -> net P&L (today excluded)
    consecutive_losses: int
    open_mini_equivalent: float
    open_risk_usd: float | None    # None if any open position lacks a stop
    unprotected: list[str]
    locks: dict
    rth: bool = True
    session_close: datetime | None = None          # today's actual close (earlier on holidays)
    trades_today: int = 0                          # entries already taken this trade date
    events: list = field(default_factory=list)     # [(name, datetime)] upcoming high-impact releases

    @property
    def equity(self) -> float:
        return self.balance + self.unrealized


def next_eod_floor(rules: PropRules, floor: float | None, eod_balance: float) -> float | None:
    """End-of-day trailing: the floor follows the best end-of-day balance minus the MLL, never moves down,
    and stops at the lock balance."""
    if rules.max_loss_limit is None or floor is None:
        return floor
    if rules.mll_type == "static":
        return floor
    cand = eod_balance - rules.max_loss_limit
    new = max(floor, cand)
    if rules.mll_lock_balance is not None:
        new = min(new, max(floor, rules.mll_lock_balance))
    return round(new, 2)


def next_intraday_floor(rules: PropRules, floor: float | None, equity_high: float) -> float | None:
    if rules.mll_type != "intraday_trailing" or floor is None or rules.max_loss_limit is None:
        return floor
    new = max(floor, equity_high - rules.max_loss_limit)
    if rules.mll_lock_balance is not None:
        new = min(new, max(floor, rules.mll_lock_balance))
    return round(new, 2)


def next_trade_day_start(now: datetime, start_ct: str = "17:00") -> datetime:
    t = now.astimezone(CT)
    st = parse_hhmm(start_ct)
    cand = datetime.combine(t.date(), st, tzinfo=CT)
    if t >= cand:
        cand += timedelta(days=1)
    while cand.weekday() == 5:   # Saturday -> Sunday evening
        cand += timedelta(days=1)
    if cand.weekday() == 4:      # Friday 17:00 is not an open; next is Sunday
        cand += timedelta(days=2)
    return cand


def effective_flat(rules: PropRules, now: datetime, session_close: datetime | None) -> tuple[datetime | None, datetime | None, str]:
    """(flat_by, no_new_entries_after, why) for the trade date containing `now`. Topstep: flat by the firm's time or
    the product's own close, whichever comes first, so holiday early closes pull the flat time earlier."""
    now_ct = now.astimezone(CT)
    flat = stop_new = None
    why = ""
    if rules.enabled and rules.flat_by_ct:
        flat = datetime.combine(now_ct.date(), parse_hhmm(rules.flat_by_ct), tzinfo=CT)
        lead = (flat - datetime.combine(now_ct.date(), parse_hhmm(rules.no_new_entries_after_ct or rules.flat_by_ct), tzinfo=CT))
        why = f"{rules.firm} flat-by {rules.flat_by_ct} CT"
        if session_close is not None and session_close.astimezone(CT).date() == now_ct.date():
            close_flat = session_close.astimezone(CT) - timedelta(minutes=2)
            if close_flat < flat:
                flat, why = close_flat, f"early close today ({session_close.astimezone(CT):%H:%M} CT): flat 2 minutes before"
        stop_new = flat - max(lead, timedelta(minutes=2))
    return flat, stop_new, why


def mini_equivalent(spec: ProductSpec, qty: int, rules: PropRules) -> float:
    if spec.micro_of:
        return qty / (rules.micro_ratio or 10)
    return float(qty)


def _in_window(t: time, win: list[str]) -> bool:
    a, b = parse_hhmm(win[0]), parse_hhmm(win[1])
    return a <= t < b if a <= b else (t >= a or t < b)


class RiskEngine:
    def __init__(self, rules: PropRules, personal: PersonalRisk):
        self.rules, self.personal = rules, personal

    # ---------------- account status ----------------

    def evaluate(self, s: AccountSnapshot) -> dict:
        r, p = self.rules, self.personal
        warnings: list[dict] = []
        blocks: list[dict] = []
        now_ct = s.now.astimezone(CT)
        reset_at = next_trade_day_start(s.now, r.trade_day_start_ct).isoformat()

        def warn(code, text, level="medium"):
            warnings.append({"code": code, "level": level, "text": text})

        def block(code, text, scope, until=None, review=False):
            blocks.append({"code": code, "text": text, "scope": scope, "until": until, "needs_review": review})

        m: dict = {"balance": round(s.balance, 2), "equity": round(s.equity, 2), "unrealized": round(s.unrealized, 2),
                   "day_pnl": round(s.day_pnl, 2), "trade_date": s.trade_date, "open_risk_usd": s.open_risk_usd,
                   "open_mini_equivalent": round(s.open_mini_equivalent, 2)}
        official: dict = {"firm": r.firm, "label": r.label, "confirmed": r.confirmed, "enabled": r.enabled}
        if r.enabled:
            # Maximum Loss Limit (watched in real time on equity, including unrealized P&L)
            if r.max_loss_limit is not None and s.mll_floor is not None:
                room = s.equity - s.mll_floor
                official.update({"mll_floor": round(s.mll_floor, 2), "mll_remaining": round(room, 2),
                                 "mll_used_pct": round(100 * (1 - room / r.max_loss_limit), 1) if r.max_loss_limit else None,
                                 "mll_locked": r.mll_lock_balance is not None and s.mll_floor >= r.mll_lock_balance})
                if room <= 0 or s.locks.get("mll_breached"):
                    block("mll_breached", f"Maximum Loss Limit reached (floor ${s.mll_floor:,.2f}). On a real Topstep account this ends "
                          "the account. The simulated account stays locked until you reset it.", "official", review=True)
                else:
                    used = 1 - room / r.max_loss_limit
                    for th in sorted(p.warn_at, reverse=True):
                        if used >= th:
                            warn("mll_near", f"{used:.0%} of your Maximum Loss Limit is used: ${room:,.2f} left before the floor "
                                 f"at ${s.mll_floor:,.2f}.", "high" if th >= 0.75 else "medium")
                            break
            # Daily Loss Limit (optional on Topstep Combine/XFA)
            if r.daily_loss_limit:
                left = r.daily_loss_limit + s.day_pnl
                official.update({"dll": r.daily_loss_limit, "dll_remaining": round(left, 2)})
                if left <= 0 or (s.trade_date and s.locks.get("dll_hit") == s.trade_date):
                    fail = r.dll_behavior == "account_fail"
                    block("dll_hit", f"Daily Loss Limit (${r.daily_loss_limit:,.0f}) reached for this trade date. "
                          + ("This account type treats it as a failure." if fail else "New entries are blocked until the next session at 5:00 PM CT."),
                          "official", None if fail else reset_at, review=fail)
                else:
                    used = -s.day_pnl / r.daily_loss_limit if s.day_pnl < 0 else 0
                    for th in sorted(p.warn_at, reverse=True):
                        if used >= th:
                            warn("dll_near", f"{used:.0%} of today's Daily Loss Limit is used (${left:,.2f} left).", "high" if th >= 0.75 else "medium")
                            break
            # Position limit
            if r.max_minis:
                official.update({"max_minis": r.max_minis, "max_micros": r.max_minis * r.micro_ratio})
            # Profit target and consistency
            profit = s.equity - r.starting_balance
            if r.profit_target:
                official.update({"profit": round(profit, 2), "profit_target": r.profit_target,
                                 "target_progress_pct": round(100 * profit / r.profit_target, 1)})
            if r.consistency_pct:
                days = {**s.daily_results, **({s.trade_date: s.day_pnl} if s.trade_date else {})}
                best = max(days.values(), default=0.0)
                base = r.profit_target if r.consistency_basis == "profit_target" and r.profit_target else max(profit, 0)
                pct = 100 * best / base if base else None
                official.update({"best_day": round(best, 2), "best_day_pct": round(pct, 1) if pct is not None else None,
                                 "consistency_ok": pct is None or pct <= r.consistency_pct})
                if pct is not None and pct > r.consistency_pct:
                    warn("consistency", f"Your best day (${best:,.2f}) is {pct:.0f}% of the {'profit target' if r.consistency_basis == 'profit_target' else 'total profit'}; "
                         f"the consistency target is {r.consistency_pct:.0f}% or less. More trading days are needed before it counts.", "low")
            # Flat time (earlier of the firm's time and the product's close, e.g. holiday early halts)
            flat, stop_new, why = effective_flat(r, s.now, s.session_close)
            if flat and s.trade_date:
                if now_ct < flat:
                    mins = (flat - now_ct).total_seconds() / 60
                    official["minutes_to_flat"] = round(mins, 1)
                    official["flat_by"] = flat.isoformat()
                    official["flat_reason"] = why
                    if now_ct >= stop_new:
                        block("flat_window", f"Positions must be flat by {flat:%H:%M} CT ({why}). No new entries until the next session.",
                              "official", reset_at)
                    elif mins <= 20:
                        warn("flat_soon", f"{mins:.0f} minutes until you must be flat ({flat:%H:%M} CT, {why}).", "high" if mins <= 10 else "medium")
                elif now_ct.time() < parse_hhmm(r.trade_day_start_ct) and now_ct.weekday() < 5:
                    block("after_flat", f"Past the flat-by time ({flat:%H:%M} CT, {why}); trading resumes at {r.trade_day_start_ct} CT.",
                          "official", reset_at)
            if s.locks.get("reset_required"):
                block("reset_required", s.locks["reset_required"], "official", review=True)
            if s.locks.get("flat_violation") and s.locks["flat_violation"] == s.trade_date:
                warn("flat_violation", "A position was still open after the flat-by time on this trade date. On a real Topstep account that "
                     "breaks the trading-hours rule.", "high")
        # ---------------- personal ----------------
        personal: dict = {"enabled": p.enabled}
        if p.enabled:
            if p.max_daily_loss_usd:
                left = p.max_daily_loss_usd + s.day_pnl
                personal["daily_loss_remaining"] = round(left, 2)
                if left <= 0 or (s.trade_date and s.locks.get("personal_daily") == s.trade_date):
                    block("personal_daily_loss", f"Your own daily loss limit (${p.max_daily_loss_usd:,.0f}) is reached. "
                          "Done for today; this resets at the next session.", "personal", reset_at)
                elif s.day_pnl < 0:
                    used = -s.day_pnl / p.max_daily_loss_usd
                    for th in sorted(p.warn_at, reverse=True):
                        if used >= th:
                            warn("personal_daily_near", f"{used:.0%} of your own daily loss limit used (${left:,.2f} left).",
                                 "high" if th >= 0.75 else "medium")
                            break
            if p.max_consecutive_losses and (s.consecutive_losses >= p.max_consecutive_losses or s.locks.get("consecutive")):
                block("consecutive_losses", f"{s.consecutive_losses} losses in a row today (your limit is {p.max_consecutive_losses}). "
                      "Take a break; review the trades in the journal, then unlock with a note or wait for the next session.",
                      "personal", reset_at, review=True)
            if p.daily_profit_target_usd and s.day_pnl >= p.daily_profit_target_usd:
                block("profit_target_day", f"You reached your daily profit goal (${p.daily_profit_target_usd:,.0f}). Your rule is to stop here.",
                      "personal", reset_at)
            if p.max_trades_per_session and s.trades_today >= p.max_trades_per_session:
                block("max_trades", f"{s.trades_today} entries already this session (your limit is {p.max_trades_per_session}).", "personal", reset_at)
            if p.event_block_minutes:
                for name, when in s.events:
                    mins = (when - s.now).total_seconds() / 60
                    if -p.event_block_minutes <= mins <= p.event_block_minutes:
                        block("event_window", f"{name} {'in ' + str(int(mins)) + ' min' if mins > 0 else str(int(-mins)) + ' min ago'}: no new entries "
                              f"within {p.event_block_minutes} minutes of a high-impact release (your setting).", "personal")
                    elif 0 < mins <= 60:
                        warn("event_soon", f"{name} in {int(mins)} minutes.", "medium")
            if p.max_open_risk_usd and s.open_risk_usd is not None:
                personal["open_risk_remaining"] = round(p.max_open_risk_usd - s.open_risk_usd, 2)
            t = now_ct.time()
            for win in p.no_trade_windows_ct:
                if _in_window(t, win):
                    block("no_trade_window", f"Inside your no-trade window {win[0]}-{win[1]} CT.", "personal")
            if p.rth_only and not s.rth:
                block("rth_only", "Your settings allow entries during regular hours only.", "personal")
        if s.unprotected:
            warn("no_stop", f"Open position without a stop: {', '.join(s.unprotected)}. Risk to your loss limits is undefined.", "high")
        cap = self.max_contracts_mini()
        m["max_mini_equivalent"] = cap
        m["remaining_mini_equivalent"] = None if cap is None else round(max(cap - s.open_mini_equivalent, 0), 2)
        return {"metrics": m, "official": official, "personal": personal, "warnings": warnings, "blocks": blocks,
                "blocked": bool(blocks), "sim_only_note": SIM_ONLY, "reset_at": reset_at}

    def max_contracts_mini(self) -> float | None:
        caps = []
        if self.rules.enabled and self.rules.max_minis:
            caps.append(self.rules.max_minis)
        if self.personal.enabled and self.personal.max_contracts:
            caps.append(self.personal.max_contracts)
        return min(caps) if caps else None

    # ---------------- pre-trade ----------------

    def check_entry(self, s: AccountSnapshot, spec: ProductSpec, qty: int, entry: float | None, stop: float | None,
                    targets: list[float], round_turn_cost: float, slippage_ticks: float, side: int,
                    status: dict | None = None) -> dict:
        """Problems that block this paper entry, warnings that don't, and the largest size each limit allows."""
        from .contracts import risk_per_contract

        st = status or self.evaluate(s)
        problems = [b["text"] for b in st["blocks"]]
        warns = []
        limits: dict = {}
        p, r = self.personal, self.rules
        add_me = mini_equivalent(spec, qty, r)
        cap = self.max_contracts_mini()
        if cap is not None:
            free = cap - s.open_mini_equivalent
            per = mini_equivalent(spec, 1, r)
            limits["position_limit"] = int(max(free, 0) / per + 1e-9)
            if add_me > free + 1e-9:
                problems.append(f"{qty} {spec.root} would put you at {s.open_mini_equivalent + add_me:g} mini-equivalent contracts; the limit is {cap:g}"
                                + (f" ({cap * r.micro_ratio:g} micros)" if spec.micro_of else "") + ".")
        if stop is None:
            if p.enabled and p.require_stop:
                problems.append("A stop loss is required.")
            return {"ok": not problems, "problems": problems, "warnings": warns, "limits": limits, "risk": None, "sim_only_note": SIM_ONLY}
        if entry is None:
            return {"ok": not problems, "problems": problems + ["No price to measure risk against."], "warnings": warns,
                    "limits": limits, "risk": None, "sim_only_note": SIM_ONLY}
        if (side > 0 and stop >= entry) or (side < 0 and stop <= entry):
            problems.append("The stop is on the wrong side of the entry.")
        if p.enabled and p.max_slippage_ticks is not None and slippage_ticks > p.max_slippage_ticks:
            problems.append(f"Expected slippage ({slippage_ticks:g} ticks) is above your maximum ({p.max_slippage_ticks:g}).")
        per = risk_per_contract(entry, stop, spec, slippage_ticks, round_turn_cost)
        total = per["total_usd"] * qty
        risk = {**per, "contracts": qty, "trade_risk_usd": round(total, 2)}
        if targets:
            t1 = targets[0]
            reward_ticks = abs(round((t1 - entry) / float(spec.tick)))
            rr = reward_ticks / per["stop_ticks"] if per["stop_ticks"] else None
            risk["reward_risk"] = round(rr, 2) if rr is not None else None
            if p.enabled and p.min_reward_risk and rr is not None and rr < p.min_reward_risk:
                problems.append(f"Reward-to-risk to the first target is {rr:.2f}; your minimum is {p.min_reward_risk:g}.")
        if p.enabled and p.max_risk_per_trade_usd:
            limits["per_trade_risk"] = int(p.max_risk_per_trade_usd // per["total_usd"]) if per["total_usd"] else 0
            if total > p.max_risk_per_trade_usd + 1e-9:
                problems.append(f"This trade risks ${total:,.2f} with slippage and fees; your per-trade limit is ${p.max_risk_per_trade_usd:,.0f}.")
        if p.enabled and p.max_open_risk_usd:
            if s.open_risk_usd is None:
                problems.append("An open position has no stop, so total open risk can't be measured.")
            elif s.open_risk_usd + total > p.max_open_risk_usd:
                problems.append(f"Open risk would be ${s.open_risk_usd + total:,.2f}; your limit is ${p.max_open_risk_usd:,.0f}.")
        o = st["official"]
        if "mll_remaining" in o and total >= o["mll_remaining"]:
            problems.append(f"If the stop is hit, this trade alone (${total:,.2f}) would take you through the Maximum Loss Limit "
                            f"(${o['mll_remaining']:,.2f} left).")
        elif "mll_remaining" in o and total >= 0.5 * o["mll_remaining"]:
            warns.append(f"This trade's stop would use {100 * total / o['mll_remaining']:.0f}% of the room left above your Maximum Loss Limit.")
        if "dll_remaining" in o and total >= o["dll_remaining"]:
            problems.append(f"The stop loss (${total:,.2f}) is bigger than what's left of the Daily Loss Limit (${o['dll_remaining']:,.2f}).")
        pdl = st["personal"].get("daily_loss_remaining")
        if pdl is not None and total > pdl:
            problems.append(f"The stop loss (${total:,.2f}) is bigger than what's left of your own daily limit (${pdl:,.2f}).")
        if not r.confirmed and r.enabled:
            warns.append("Your prop-firm rules haven't been confirmed against your account yet (Settings > Futures risk).")
        if r.enabled and r.max_minis and add_me + s.open_mini_equivalent >= r.max_minis:
            warns.append("This is your firm's maximum position size. Topstep treats purposefully taking max size into major news as prohibited.")
        return {"ok": not problems, "problems": problems, "warnings": warns, "limits": limits, "risk": risk, "sim_only_note": SIM_ONLY}
