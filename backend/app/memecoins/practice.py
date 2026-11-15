"""Memecoin PRACTICE account: pretend dollars, modelled costs, real prices from DexScreener. It can't touch a wallet.

Costs are estimates and on the pessimistic side:
  - price impact from the pool's size (constant-product pool, half its value on each side): buying $X moves the average price up
    by about X / (pool / 2); selling moves it down by about X / (pool / 2 + X);
  - a trading fee (default 1%, editable) and a network fee per trade (default $0.05, editable).
Exit plan (optional, set when buying): at the target sell only part (for example half), move the stop up to the buy price so the
rest can't turn into a loss on a normal move, and let a trailing stop follow the price up. A trailing stop only ever moves up.
A stop is required on every buy. Stops and targets are checked about every 20 seconds and fill at the price seen then, after
impact, so a fast drop fills BELOW the stop, as it would for real. Memecoin prices can jump 50% between checks.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select

from ..db.models import MemeFill, MemeNote, MemePlan, MemePosition
from .checks import price_impact


@dataclass
class MemeCosts:
    start_usd: float = 500.0
    fee_pct: float = 1.0
    network_fee_usd: float = 0.05
    max_trade_pct: float = 10.0       # of practice equity per buy


class MemePractice:
    def __init__(self, db, costs: MemeCosts | None = None):
        self.db, self.costs = db, costs or MemeCosts()

    # ---------------- state ----------------
    def fills(self, limit: int = 200) -> list[dict]:
        with self.db.session() as s:
            rows = s.scalars(select(MemeFill).order_by(MemeFill.id.desc()).limit(limit)).all()
            return [{"id": f.id, "ts": f.ts.isoformat(), "token": f.token, "symbol": f.symbol, "side": f.side, "qty": f.qty,
                     "price_usd": f.price_usd, "usd": round(f.usd, 2), "fee_usd": round(f.fee_usd, 2),
                     "impact_pct": round(f.impact_pct, 2), "reason": f.reason} for f in rows]

    def positions(self) -> list[dict]:
        with self.db.session() as s:
            plans = {x.token: x for x in s.scalars(select(MemePlan)).all()}
            notes = {x.token: x for x in s.scalars(select(MemeNote)).all()}
            out = []
            for p in s.scalars(select(MemePosition)).all():
                pl, nt = plans.get(p.token), notes.get(p.token)
                trail_stop = pl.high_price * (1 - pl.trail_pct / 100) if pl and pl.trail_pct and pl.high_price else None
                out.append({"token": p.token, "symbol": p.symbol, "name": p.name, "qty": p.qty, "cost_usd": round(p.cost_usd, 2),
                            "stop_price": p.stop_price, "target_price": p.target_price, "opened_at": p.opened_at.isoformat(), "url": p.url,
                            "take_fraction": pl.take_fraction if pl else 1.0, "trail_pct": pl.trail_pct if pl else None,
                            "high_price": pl.high_price if pl else None, "took_profit": bool(pl and pl.took_profit),
                            "active_stop": max(p.stop_price, trail_stop) if trail_stop else p.stop_price,
                            "why": nt.why if nt else "", "lesson": nt.lesson if nt else ""})
            return out

    # ---------------- journal (your words only) ----------------
    def set_note(self, token: str, why: str | None = None, lesson: str | None = None) -> dict:
        with self.db.session() as s:
            n = s.get(MemeNote, token)
            if not n:
                n = MemeNote(token=token)
                s.add(n)
            if why is not None:
                n.why = why.strip()[:600]
            if lesson is not None:
                n.lesson = lesson.strip()[:600]
            n.updated_at = datetime.now(timezone.utc)
            return {"token": token, "why": n.why, "lesson": n.lesson}

    def journal(self) -> dict:
        """Finished practice trades, one per token, from the recorded fills. Reasons and lessons are only ever what you typed."""
        with self.db.session() as s:
            fills = s.scalars(select(MemeFill).order_by(MemeFill.id)).all()
            notes = {x.token: x for x in s.scalars(select(MemeNote)).all()}
            open_tokens = {p.token for p in s.scalars(select(MemePosition)).all()}
        by: dict[str, list] = {}
        for f in fills:
            by.setdefault(f.token, []).append(f)
        rows = []
        for tok, fl in by.items():
            if tok in open_tokens:
                continue
            spent = sum(f.usd + f.fee_usd for f in fl if f.side == "buy")
            got = sum(f.usd - f.fee_usd for f in fl if f.side == "sell")
            sells = [f for f in fl if f.side == "sell"]
            if not sells or spent <= 0:
                continue
            n = notes.get(tok)
            rows.append({"token": tok, "symbol": fl[0].symbol, "opened": fl[0].ts.isoformat(), "closed": sells[-1].ts.isoformat(),
                         "spent_usd": round(spent, 2), "got_back_usd": round(got, 2), "pnl_usd": round(got - spent, 2),
                         "pnl_pct": round((got - spent) / spent * 100, 1), "exits": [f.reason for f in sells],
                         "minutes_held": round((sells[-1].ts - fl[0].ts).total_seconds() / 60),
                         "why": n.why if n and n.why else None, "lesson": n.lesson if n and n.lesson else None})
        rows.sort(key=lambda r: r["closed"], reverse=True)
        wins = [r for r in rows if r["pnl_usd"] > 0]
        by_exit: dict[str, dict] = {}
        for r in rows:
            k = r["exits"][-1]
            d = by_exit.setdefault(k, {"trades": 0, "pnl_usd": 0.0})
            d["trades"] += 1
            d["pnl_usd"] = round(d["pnl_usd"] + r["pnl_usd"], 2)
        return {"trades": rows, "count": len(rows), "wins": len(wins), "losses": len(rows) - len(wins),
                "total_pnl_usd": round(sum(r["pnl_usd"] for r in rows), 2), "by_exit": by_exit,
                "no_reason_written": sum(1 for r in rows if not r["why"]),
                "note": "Numbers come from your practice fills. 'Why I bought' and 'What I learned' are only ever what you typed; "
                        "the app never guesses them."}

    def cash(self) -> float:
        with self.db.session() as s:
            fl = s.scalars(select(MemeFill)).all()
        return self.costs.start_usd + sum((f.usd if f.side == "sell" else -f.usd) - f.fee_usd for f in fl)

    def summary(self, pairs: dict[str, dict] | None = None) -> dict:
        pairs = pairs or {}
        cash = self.cash()
        pos = []
        value = 0.0
        for p in self.positions():
            pr = pairs.get(p["token"])
            mid = float(pr["priceUsd"]) if pr and pr.get("priceUsd") else None
            liq = (pr or {}).get("liquidity", {}).get("usd") if pr else None
            gross = mid * p["qty"] if mid else None
            imp = price_impact(gross, liq, "sell") if gross else None
            if_sold = (gross * (1 - imp) * (1 - self.costs.fee_pct / 100) - self.costs.network_fee_usd) if gross and imp is not None else None
            value += if_sold or 0
            pos.append({**p, "price_usd": mid, "value_usd": round(gross, 2) if gross else None, "if_sold_now_usd": round(if_sold, 2) if if_sold else None,
                        "pnl_usd": round(if_sold - p["cost_usd"], 2) if if_sold is not None else None,
                        "change_m5": ((pr or {}).get("priceChange") or {}).get("m5")})
        eq = cash + value
        return {"cash_usd": round(cash, 2), "positions": pos, "equity_usd": round(eq, 2), "start_usd": self.costs.start_usd,
                "pnl_usd": round(eq - self.costs.start_usd, 2), "costs": self.costs.__dict__,
                "note": "Pretend money. Prices are real (DexScreener); fees and price impact are estimates. Study Terminal can't touch a wallet."}

    # ---------------- trading (pretend) ----------------
    def preview_buy(self, pair: dict, usd: float, stop_pct: float, target_pct: float | None = None,
                    take_fraction: float = 1.0, trail_pct: float | None = None) -> dict:
        errors, warnings = [], []
        if not (0.1 <= take_fraction <= 1.0):
            errors.append("Sell between 10% and 100% of the position at the target.")
        if take_fraction < 1.0 and not target_pct:
            errors.append("Selling part at a target needs a target.")
        if trail_pct is not None and not (5 <= trail_pct <= 90):
            errors.append("Set the trailing stop between 5% and 90% under the highest price.")
        mid = float(pair["priceUsd"]) if pair.get("priceUsd") else None
        liq = (pair.get("liquidity") or {}).get("usd")
        cash = self.cash()
        eq = self.summary({})["equity_usd"]
        if not mid or not liq:
            errors.append("No price or pool size for this token right now, so it can't be practised.")
        if usd <= 0:
            errors.append("Enter an amount above $0.")
        fee = usd * self.costs.fee_pct / 100 + self.costs.network_fee_usd
        if usd + fee > cash + 1e-9:
            errors.append(f"Not enough practice cash: ${cash:,.2f} available.")
        if usd > eq * self.costs.max_trade_pct / 100 + 1e-9:
            errors.append(f"That's more than {self.costs.max_trade_pct:g}% of your practice account (${eq * self.costs.max_trade_pct / 100:,.2f}).")
        if not (5 <= stop_pct <= 90):
            errors.append("Set a stop between 5% and 90% below your buy price. Every memecoin practice buy needs one.")
        imp = price_impact(usd, liq, "buy") if liq else None
        if imp is not None and imp > 0.05:
            warnings.append(f"Your buy alone would move the price about {imp * 100:.1f}%. The pool is small for this size.")
        if imp is not None and imp > 0.25:
            errors.append("This buy would move the price more than 25%. Use a smaller amount.")
        fill = mid * (1 + (imp or 0)) if mid else None
        qty = usd / fill if fill else 0
        stop = fill * (1 - stop_pct / 100) if fill else None
        target = fill * (1 + target_pct / 100) if fill and target_pct else None
        loss_at_stop = None
        if stop and liq:
            back = stop * qty
            loss_at_stop = usd + fee - (back * (1 - price_impact(back, liq, "sell")) * (1 - self.costs.fee_pct / 100) - self.costs.network_fee_usd)
        return {"ok": not errors, "errors": errors, "warnings": warnings, "mid_price": mid, "fill_price": fill, "impact_pct": round((imp or 0) * 100, 2),
                "qty": qty, "fee_usd": round(fee, 2), "stop_price": stop, "target_price": target,
                "loss_at_stop_usd": round(loss_at_stop, 2) if loss_at_stop is not None else None,
                "take_fraction": take_fraction, "trail_pct": trail_pct, "plan_text": plan_text(stop_pct, target_pct, take_fraction, trail_pct),
                "note": "If the price drops fast it can fill well below your stop. Memecoins can also stop trading entirely."}

    def buy(self, pair: dict, usd: float, stop_pct: float, target_pct: float | None = None, now: datetime | None = None,
            take_fraction: float = 1.0, trail_pct: float | None = None) -> dict:
        pv = self.preview_buy(pair, usd, stop_pct, target_pct, take_fraction, trail_pct)
        if not pv["ok"]:
            return pv
        tok = pair["baseToken"]
        now = now or datetime.now(timezone.utc)
        with self.db.session() as s:
            s.add(MemeFill(ts=now, token=tok["address"], symbol=tok.get("symbol", "?"), side="buy", qty=pv["qty"], price_usd=pv["fill_price"],
                           usd=usd, fee_usd=pv["fee_usd"], impact_pct=pv["impact_pct"], reason="you"))
            p = s.get(MemePosition, tok["address"])
            if p:
                p.qty += pv["qty"]
                p.cost_usd += usd + pv["fee_usd"]
                p.stop_price, p.target_price = pv["stop_price"], pv["target_price"]
            else:
                s.add(MemePosition(token=tok["address"], symbol=tok.get("symbol", "?"), name=tok.get("name", ""), qty=pv["qty"],
                                   cost_usd=usd + pv["fee_usd"], stop_price=pv["stop_price"], target_price=pv["target_price"],
                                   opened_at=now, url=pair.get("url", "")))
            pl = s.get(MemePlan, tok["address"])
            if not pl:
                pl = MemePlan(token=tok["address"])
                s.add(pl)
            pl.take_fraction, pl.trail_pct, pl.high_price, pl.took_profit = take_fraction, trail_pct, pv["fill_price"], 0
        return {**pv, "done": True}

    def sell(self, pair: dict, token: str, fraction: float = 1.0, reason: str = "you", now: datetime | None = None) -> dict:
        with self.db.session() as s:
            p = s.get(MemePosition, token)
            if not p:
                return {"ok": False, "errors": ["You don't hold this token in practice."]}
            mid = float(pair["priceUsd"]) if pair and pair.get("priceUsd") else None
            liq = ((pair or {}).get("liquidity") or {}).get("usd")
            if not mid or not liq:
                return {"ok": False, "errors": ["No price or pool right now, so it can't be sold. (For real, you might be stuck too.)"]}
            fraction = min(max(fraction, 0.0), 1.0)
            qty = p.qty * fraction
            gross = mid * qty
            imp = price_impact(gross, liq, "sell")
            got = gross * (1 - imp)
            fee = got * self.costs.fee_pct / 100 + self.costs.network_fee_usd
            cost_part = p.cost_usd * fraction
            s.add(MemeFill(ts=now or datetime.now(timezone.utc), token=token, symbol=p.symbol, side="sell", qty=qty, price_usd=got / qty if qty else mid,
                           usd=got, fee_usd=fee, impact_pct=round(imp * 100, 2), reason=reason))
            if fraction >= 0.9999:
                s.execute(delete(MemePosition).where(MemePosition.token == token))
                s.execute(delete(MemePlan).where(MemePlan.token == token))
            else:
                p.qty -= qty
                p.cost_usd -= cost_part
            return {"ok": True, "done": True, "qty": qty, "received_usd": round(got - fee, 2), "impact_pct": round(imp * 100, 2),
                    "pnl_usd": round(got - fee - cost_part, 2), "reason": reason}

    def check_exits(self, pairs: dict[str, dict]) -> list[dict]:
        """Sell practice positions whose stop, trailing stop or target was reached. Returns what happened."""
        done = []
        for p in self.positions():
            pr = pairs.get(p["token"])
            if not pr or not pr.get("priceUsd"):
                continue
            px = float(pr["priceUsd"])
            if p["trail_pct"] and (p["high_price"] is None or px > p["high_price"]):       # the trailing stop only ever moves up
                with self.db.session() as s:
                    pl = s.get(MemePlan, p["token"])
                    if pl:
                        pl.high_price = px
                p["high_price"] = px
            trail_stop = p["high_price"] * (1 - p["trail_pct"] / 100) if p["trail_pct"] and p["high_price"] else None
            if px <= p["stop_price"]:
                done.append({"symbol": p["symbol"], **self.sell(pr, p["token"], 1.0, "stop")})
            elif trail_stop is not None and px <= trail_stop:
                done.append({"symbol": p["symbol"], **self.sell(pr, p["token"], 1.0, "trailing stop")})
            elif p["target_price"] and px >= p["target_price"]:
                part = p["take_fraction"] if 0 < p["take_fraction"] < 1 else 1.0
                r = self.sell(pr, p["token"], part, "target")
                if r.get("ok") and part < 1:
                    with self.db.session() as s:              # part sold: no second target; the stop moves up to the buy price
                        pos, pl = s.get(MemePosition, p["token"]), s.get(MemePlan, p["token"])
                        if pos:
                            pos.target_price = None
                            pos.stop_price = max(pos.stop_price, pos.cost_usd / pos.qty if pos.qty else pos.stop_price)
                        if pl:
                            pl.took_profit = 1
                    r["kept_fraction"] = round(1 - part, 2)
                done.append({"symbol": p["symbol"], **r})
        return done


def plan_text(stop_pct: float, target_pct: float | None, take_fraction: float = 1.0, trail_pct: float | None = None) -> str:
    """The exit plan in one plain sentence."""
    parts = [f"Sell everything if it drops {stop_pct:g}% below your buy price."]
    if target_pct:
        if take_fraction < 1:
            parts.append(f"If it rises {target_pct:g}%, sell {take_fraction * 100:g}% and move the stop up to your buy price for the rest.")
        else:
            parts.append(f"If it rises {target_pct:g}%, sell everything.")
    if trail_pct:
        parts.append(f"A trailing stop follows {trail_pct:g}% under the highest price it reaches and never moves down.")
    return " ".join(parts)
