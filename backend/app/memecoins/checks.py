"""Rug-risk checks for a Solana memecoin, in plain words. Fixed written rules (listed below), not a black box, and never "safe":
the best result is "fewer red flags", because most new memecoins still lose most of their value.

  Who can create more tokens   mint authority still set            -> danger
  Who can freeze your tokens   freeze authority still set          -> danger
  Special token rules          Token-2022 permanent delegate       -> danger (someone can move tokens out of any wallet)
                               transfer fee / default-frozen / non-transferable -> danger, transfer hook -> caution
  Money in the pool            under $10,000 -> danger, under $50,000 -> caution
  Age                          under 1 hour -> danger, under 24 hours -> caution
  Biggest holders              top 10 (pool left out where it can be identified) over 50% -> danger, over 30% -> caution
  Selling vs buying (1 hour)   sells more than 2x buys -> caution
  Website and social links     none listed on DexScreener -> caution
  pump.fun stage               still on the starting curve -> caution (shown only for pump.fun tokens)
"""
from __future__ import annotations

import time


def _item(key: str, name: str, level: str, text: str) -> dict:
    return {"key": key, "name": name, "level": level, "text": text}


def checks(pair: dict | None, mint: dict | None, holders: list[dict] | None = None, supply_ui: float | None = None,
           mint_error: str | None = None, holders_error: str | None = None, now_ms: float | None = None) -> dict:
    out: list[dict] = []
    if mint:
        out.append(_item("mint", "Who can create more tokens", "danger" if mint.get("mint_authority") else "ok",
                         "Someone can still create more of this token, which would water down what you hold."
                         if mint.get("mint_authority") else "No one can create more of this token."))
        out.append(_item("freeze", "Who can freeze your tokens", "danger" if mint.get("freeze_authority") else "ok",
                         "Someone can freeze tokens in your wallet so you can't sell them."
                         if mint.get("freeze_authority") else "No one can freeze your tokens."))
        ext = mint.get("extensions") or {}
        bad = []
        if "permanentDelegate" in ext and (ext["permanentDelegate"] or {}).get("delegate"):
            bad.append(("danger", "Someone can move tokens out of any wallet (permanent delegate)."))
        if "transferFeeConfig" in ext:
            bad.append(("danger", "A fee is taken on every transfer, including when you sell."))
        if "nonTransferable" in ext:
            bad.append(("danger", "These tokens can't be transferred."))
        if (ext.get("defaultAccountState") or {}).get("accountState") == "frozen":
            bad.append(("danger", "New holders start frozen."))
        if "transferHook" in ext and (ext["transferHook"] or {}).get("programId"):
            bad.append(("caution", "Every transfer runs extra code chosen by the creator (transfer hook)."))
        out.append(_item("rules", "Special token rules", max((b[0] for b in bad), key=["ok", "caution", "danger"].index) if bad else "ok",
                         " ".join(b[1] for b in bad) if bad else "No special rules that could trap your tokens."))
    else:
        out.append(_item("mint", "Token record", "unknown", mint_error or "Couldn't read the token's record on Solana."))
    if pair:
        liq = (pair.get("liquidity") or {}).get("usd")
        if liq is None:
            out.append(_item("liquidity", "Money in the pool", "unknown", "The pool size isn't known."))
        else:
            lvl = "danger" if liq < 10_000 else "caution" if liq < 50_000 else "ok"
            out.append(_item("liquidity", "Money in the pool", lvl, f"${liq:,.0f} in the trading pool. "
                             + ("Even small sells move the price a lot." if lvl != "ok" else "Enough that a small trade won't move it much.")))
        created = pair.get("pairCreatedAt")
        if created:
            hours = ((now_ms or time.time() * 1000) - created) / 3_600_000
            lvl = "danger" if hours < 1 else "caution" if hours < 24 else "ok"
            age = f"{hours * 60:.0f} minutes" if hours < 1 else f"{hours:.0f} hours" if hours < 48 else f"{hours / 24:.0f} days"
            out.append(_item("age", "Age", lvl, f"Trading for {age}. " + ("Most rug pulls happen in the first hours." if lvl != "ok" else "")))
        tx = (pair.get("txns") or {}).get("h1") or {}
        b, s = tx.get("buys") or 0, tx.get("sells") or 0
        if b + s >= 10:
            lvl = "caution" if s > 2 * b else "ok"
            out.append(_item("flow", "Selling vs buying (last hour)", lvl, f"{b} buys, {s} sells in the last hour."
                             + (" Many more people are selling." if lvl != "ok" else "")))
    if pair:
        info = pair.get("info") or {}
        n = len(info.get("websites") or []) + len(info.get("socials") or [])
        out.append(_item("links", "Website and social links", "ok" if n else "caution",
                         f"{n} link{'s' if n != 1 else ''} listed. Links are easy to fake, so this only rules out the laziest tokens." if n
                         else "No website or social account is listed. Tokens with nothing behind them are common throwaways."))
        if pair.get("dexId") == "pumpfun":
            out.append(_item("stage", "pump.fun stage", "caution",
                             "Still on pump.fun's starting curve. Most tokens never leave it, and there's no normal trading pool yet."))
        elif pair.get("dexId") == "pumpswap":
            out.append(_item("stage", "pump.fun stage", "ok", "Moved from pump.fun's starting curve to a PumpSwap trading pool."))
    if holders:
        pool = (pair or {}).get("pairAddress")
        rest = [h for h in holders if h.get("owner") != pool and h.get("account") != pool]
        left_out = len(rest) < len(holders)
        if supply_ui:
            top10 = sum((h.get("ui") or 0) for h in rest[:10]) / supply_ui * 100
            lvl = "danger" if top10 > 50 else "caution" if top10 > 30 else "ok"
            out.append(_item("holders", "Biggest holders", lvl, f"The 10 biggest holders own {top10:.0f}% of all tokens"
                             + (" (the trading pool is left out)." if left_out else
                                " (this may include the trading pool, which couldn't be told apart).")))
    elif holders_error:
        out.append(_item("holders", "Biggest holders", "unknown", holders_error))
    levels = [i["level"] for i in out]
    if "danger" in levels:
        verdict, tone = "High risk", "danger"
    elif "caution" in levels:
        verdict, tone = "Risky", "caution"
    else:
        verdict, tone = "Fewer red flags", "ok"
    say = {"danger": "At least one check is a serious red flag. Many tokens like this go to zero.",
           "caution": "Some checks are worrying. Use small sizes and a stop.",
           "ok": "No red flags in these checks, but memecoins can still drop 90% in minutes. These checks can't see who the creator is."}[tone]
    return {"verdict": verdict, "tone": tone, "say": say, "items": out,
            "unknown": [i["name"] for i in out if i["level"] == "unknown"],
            "note": "Checks use public data that can be incomplete. Not a promise about any token."}


def price_impact(usd: float, liquidity_usd: float | None, side: str = "buy") -> float | None:
    """Estimated price impact (fraction) for a trade of `usd` against a constant-product pool holding half its value in each side."""
    if not liquidity_usd or liquidity_usd <= 0:
        return None
    q = liquidity_usd / 2
    return usd / q if side == "buy" else usd / (q + usd)
