from datetime import date, datetime

import pytest

from app.futures import contracts as fc
from app.futures.sessions import FuturesClock


def utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@pytest.mark.parametrize("root,tick,tv,mult", [
    ("ES", "0.25", 12.50, 50), ("MES", "0.25", 1.25, 5), ("NQ", "0.25", 5.00, 20), ("MNQ", "0.25", 0.50, 2),
    ("YM", "1", 5.00, 5), ("MYM", "1", 0.50, 0.5), ("RTY", "0.10", 5.00, 50), ("M2K", "0.10", 0.50, 5),
    ("CL", "0.01", 10.00, 1000), ("GC", "0.10", 10.00, 100),
])
def test_specs_match_cme(root, tick, tv, mult):
    p = fc.get(root)
    assert p.tick_size == tick and p.tick_value == tv and p.multiplier == mult
    # tick value must equal tick size x point value: catches a typo in either
    assert float(p.tick) * p.multiplier == pytest.approx(tv)
    assert p.sources and p.verified_on and not p.user_defined


def test_micro_ratio():
    for m, big in (("MES", "ES"), ("MNQ", "NQ"), ("MYM", "YM"), ("M2K", "RTY")):
        assert fc.get(m).micro_of == big and fc.get(m).mini_equivalent == 0.1
        assert fc.get(m).tick_value * 10 == pytest.approx(fc.get(big).tick_value)


def test_tick_rounding_is_exact():
    es, cl, ym = fc.get("ES"), fc.get("CL"), fc.get("YM")
    assert fc.round_to_tick(6012.13, es) == 6012.25
    assert fc.round_to_tick(6012.12, es) == 6012.0
    assert fc.round_to_tick(6012.12, es, "up") == 6012.25
    assert fc.round_to_tick(70.105, cl) == 70.11
    assert fc.round_to_tick(0.1 + 0.2, cl) == 0.3
    assert fc.round_to_tick(44012.6, ym, "down") == 44012


def test_ticks_and_pnl():
    es, nq, cl, gc = fc.get("ES"), fc.get("NQ"), fc.get("CL"), fc.get("GC")
    assert fc.ticks_between(6000, 6001.25, es) == 5
    assert fc.pnl_usd(6000, 6001.25, 2, +1, es) == 125.0
    assert fc.pnl_usd(6000, 6001.25, 2, -1, es) == -125.0
    assert fc.pnl_usd(21000, 20990, 1, +1, nq) == -200.0          # 10 points x $20
    assert fc.pnl_usd(70.00, 70.25, 3, +1, cl) == 750.0            # 25 ticks x $10 x 3
    assert fc.pnl_usd(2400.0, 2398.5, 1, -1, gc) == 150.0          # short gains 15 ticks x $10


def test_size_for_risk_includes_costs_and_never_rounds_up():
    mes = fc.get("MES")
    r = fc.size_for_risk(500, 6000, 5996, mes, slippage_ticks=1, round_turn_cost=1.22)
    assert r["stop_ticks"] == 16 and r["total_usd"] == pytest.approx(22.47)
    assert r["contracts"] == 22 and r["risk_usd"] <= 500
    es = fc.get("ES")
    r = fc.size_for_risk(150, 6000, 5996, es)            # one ES risks $200
    assert r["contracts"] == 0 and "budget" in r["reason"]
    r = fc.size_for_risk(10_000, 6000, 5996, es, max_contracts=3)
    assert r["contracts"] == 3


def test_equity_expiration_and_roll():
    z26 = fc.Contract("ES", 2026, 12)
    assert z26.last_trade == date(2026, 12, 18)       # third Friday
    assert z26.roll == date(2026, 12, 14)             # CME: Monday before the third Friday
    m26 = fc.Contract("ES", 2026, 6)
    assert m26.last_trade == date(2026, 6, 18)        # Juneteenth (Fri June 19) moves expiry to Thursday
    assert m26.roll == date(2026, 6, 15)


def test_cl_and_gc_expiration_rules():
    # CLZ26: Nov 25 2026 is a business day -> 3 business days before = Fri Nov 20
    assert fc.Contract("CL", 2026, 12).last_trade == date(2026, 11, 20)
    # CLF27: Dec 25 is a holiday -> 4 business days before = Mon Dec 21
    assert fc.Contract("CL", 2027, 1).last_trade == date(2026, 12, 21)
    # GCZ26: third-last business day of December 2026
    assert fc.Contract("GC", 2026, 12).last_trade == date(2026, 12, 29)
    # GC active month rolls on the First Position Date (2 business days before the month's first business day)
    assert fc.Contract("GC", 2026, 12).roll == date(2026, 11, 27)


def test_front_contract_roll_boundaries():
    assert fc.front_contract("ES", date(2026, 12, 11)).code == "ESZ26"
    assert fc.front_contract("ES", date(2026, 12, 14)).code == "ESH27"
    assert fc.front_contract("GC", date(2026, 11, 26)).code == "GCZ26"
    assert fc.front_contract("GC", date(2026, 11, 27)).code == "GCG27"
    assert fc.front_contract("CL", date(2026, 11, 16)).code == "CLZ26"
    assert fc.front_contract("CL", date(2026, 11, 17)).code == "CLF27"
    assert [c.code for c in fc.next_contracts("NQ", date(2026, 11, 8), 3)] == ["NQZ26", "NQH27", "NQM27"]


@pytest.mark.parametrize("text,root,code,cont", [
    ("ESZ6", "ES", "ESZ26", False), ("ESZ26", "ES", "ESZ26", False), ("ESZ2026", "ES", "ESZ26", False),
    ("/ES", "ES", None, True), ("/MNQZ6", "MNQ", "MNQZ26", False), ("ES1!", "ES", None, True), ("NQ=F", "NQ", None, True),
    ("ESZ26.CME", "ES", "ESZ26", False), ("CON.F.US.ENQ.Z25", "NQ", "NQZ25", False), ("CME_MINI:MESH2027", "MES", "MESH27", False),
    ("M2KZ6", "M2K", "M2KZ26", False), ("CLF7", "CL", "CLF27", False), ("GCG27.CMX", "GC", "GCG27", False),
])
def test_parse_symbol(text, root, code, cont):
    p = fc.parse_symbol(text, date(2026, 11, 8))
    assert p and p.root == root and (p.contract.code if p.contract else None) == code and p.continuous == cont


@pytest.mark.parametrize("text", ["AAPL", "SPY", "ESX", "", "QQQ", "TSLA 359.40", "ZZZZZ1!"])
def test_parse_symbol_rejects_non_futures(text):
    assert fc.parse_symbol(text, date(2026, 11, 8)) is None


def test_single_digit_year_resolves_forward():
    assert fc.parse_symbol("ESH5", date(2026, 11, 8)).contract.year == 2035   # H5 in late 2026 can't be 2025 (expired a year+)
    assert fc.parse_symbol("ESZ5", date(2026, 1, 5)).contract.year == 2025


def test_user_products_are_flagged(tmp_path):
    f = tmp_path / "futures_products.json"
    f.write_text('[{"root":"MGC","name":"Micro Gold","exchange":"COMEX","calendar":"COMEX","tick_size":"0.10","tick_value":1.0,'
                 '"multiplier":10,"months":"GJMQVZ","expiry_rule":"gc_third_last","roll_rule":"gc_first_position_day","group":"metals"}]')
    try:
        assert fc.load_user_products(f) == ["MGC"]
        p = fc.get("MGC")
        assert p.user_defined and p.verified_on == "user"
        assert fc.parse_symbol("MGCZ6", date(2026, 11, 8)).root == "MGC"
    finally:
        fc._USER.clear()


def test_sessions_trade_date_and_states():
    clk = FuturesClock(fc.get("ES"))
    # Sunday 17:30 CT (23:30Z, CST) is Monday's session, before RTH
    s = clk.state(utc("2026-11-08T23:30:00Z"))
    assert s["state"] == "overnight" and s["trade_date"] == "2026-11-09"
    assert clk.state(utc("2026-11-09T15:00:00Z"))["state"] == "rth"           # 09:00 CT
    assert clk.state(utc("2026-11-09T21:30:00Z"))["state"] == "post"          # 15:30 CT
    assert clk.state(utc("2026-11-09T22:30:00Z"))["state"] == "closed"        # 16:30 CT maintenance break
    assert clk.trade_date_of(utc("2026-11-09T23:05:00Z")) == date(2026, 11, 10)  # 17:05 CT Monday -> Tuesday
    assert clk.state(utc("2026-11-07T15:00:00Z"))["state"] == "closed"        # Saturday


def test_sessions_dst_shift():
    clk = FuturesClock(fc.get("ES"))
    # Summer (CDT, UTC-5): RTH opens 13:30Z; winter (CST, UTC-6): 14:30Z
    assert clk.is_rth(utc("2026-07-14T13:31:00Z")) and not clk.is_rth(utc("2026-07-14T13:29:00Z"))
    assert clk.is_rth(utc("2026-12-01T14:31:00Z")) and not clk.is_rth(utc("2026-12-01T13:31:00Z"))
    w = clk.window(date(2026, 11, 2))  # first Monday after the Nov 1 DST change: open Sunday 17:00 CST
    assert w.open.isoformat().startswith("2026-11-01T17:00:00-06:00")


def test_sessions_holiday_early_close_and_closed_days():
    clk = FuturesClock(fc.get("ES"))
    w = clk.window(date(2026, 11, 26))             # Thanksgiving: abbreviated session
    assert w.early_close and w.close.hour == 12
    assert clk.window(date(2026, 12, 25)) is None  # Christmas: closed
    assert clk.state(utc("2026-11-26T18:30:00Z"))["state"] == "closed"
