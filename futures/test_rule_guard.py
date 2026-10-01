"""Run: python3 test_rule_guard.py  (no API needed)"""
import datetime as dt

import rule_guard as g

CT = g.CT
MNQ = "CON.F.US.MNQ.Z26"
TICK = {"tick_size": 0.25, "tick_value": 0.5}
D = dt.date


def levels(alerts, key):
    return [a[0] for a in alerts if a[1].startswith(key)]


def test_trading_day_rollover():
    assert g.trading_day(dt.datetime(2026, 10, 6, 16, 59, tzinfo=CT)) == D(2026, 10, 6)
    assert g.trading_day(dt.datetime(2026, 10, 6, 17, 0, tzinfo=CT)) == D(2026, 10, 7)


def test_mll_trails_eod_and_locks():
    start, mll = 50000.0, 2000.0
    assert g.mll_floor({}, D(2026, 10, 7), start, mll) == 48000
    daily = {D(2026, 10, 5): 1000.0, D(2026, 10, 6): -500.0}
    assert g.mll_floor(daily, D(2026, 10, 7), start, mll) == 49000       # peak EOD 51000
    daily = {D(2026, 10, 5): 3000.0}
    assert g.mll_floor(daily, D(2026, 10, 7), start, mll) == 50000       # locked at start
    # today's P&L must not move the floor (EOD only)
    daily = {D(2026, 10, 7): 1500.0}
    assert g.mll_floor(daily, D(2026, 10, 7), start, mll) == 48000


def test_breach_on_unrealized():
    now = dt.datetime(2026, 10, 7, 10, 0, tzinfo=CT)
    snap = {"balance": 48500.0, "daily": {D(2026, 10, 6): -1500.0}, "orders": [],
            "positions": [dict(TICK, contract=MNQ, type=g.LONG, size=10, avg=20000.0, last=19970.0)]}  # -600
    assert g.BREACH in levels(g.evaluate(snap, now), "mll")


def test_size_limit_counts_minis_as_10():
    now = dt.datetime(2026, 10, 7, 10, 0, tzinfo=CT)
    nq = "CON.F.US.ENQ.Z26"
    snap = {"balance": 50000.0, "daily": {}, "orders": [],
            "positions": [dict(tick_size=0.25, tick_value=5.0, contract=nq, type=g.LONG, size=6, avg=1.0, last=1.0)]}
    assert g.BREACH in levels(g.evaluate(snap, now), "size")


def test_missing_stop_and_flat_time():
    snap = {"balance": 50000.0, "daily": {}, "orders": [],
            "positions": [dict(TICK, contract=MNQ, type=g.SHORT, size=2, avg=100.0, last=100.0)]}
    a = g.evaluate(snap, dt.datetime(2026, 10, 7, 15, 8, tzinfo=CT))
    assert g.DANGER in levels(a, "nostop")
    assert g.DANGER in levels(a, "time")
    a = g.evaluate(snap, dt.datetime(2026, 10, 7, 15, 12, tzinfo=CT))
    assert g.BREACH in levels(a, "time")


def test_consistency_raises_target():
    now = dt.datetime(2026, 10, 7, 12, 0, tzinfo=CT)
    snap = {"balance": 53100.0, "daily": {D(2026, 10, 5): 1100.0, D(2026, 10, 7): 2000.0}, "orders": [], "positions": []}
    a = g.evaluate(snap, now)
    assert not levels(a, "target")            # 3100 profit but best day 2000 -> need 3637
    snap["balance"] = 53700.0
    snap["daily"][D(2026, 10, 6)] = 600.0
    assert levels(g.evaluate(snap, now), "target") == [g.INFO]


def test_pretrade_blocks_trade_that_can_hit_mll():
    now = dt.datetime(2026, 10, 7, 10, 0, tzinfo=CT)
    snap = {"balance": 48300.0, "daily": {D(2026, 10, 6): -1700.0}, "orders": [], "positions": []}
    ok, reasons, _ = g.pretrade(snap, now, MNQ, 5, 40, 0.25, 0.5)     # risk ~$408, room $300
    assert not ok and any("MLL" in r for r in reasons)
    snap = {"balance": 50000.0, "daily": {}, "orders": [], "positions": []}
    ok, _, _ = g.pretrade(snap, now, MNQ, 3, 20, 0.25, 0.5)            # risk ~$125
    assert ok


def test_xfa_floor_scaling_and_payout_lock():
    r = g.make_rules("xfa", "50k", "standard")
    today = D(2026, 11, 6)
    assert g.account_limits({}, today, r) == (-2000.0, 20)
    daily = {D(2026, 11, 3): 1000.0, D(2026, 11, 4): 700.0}              # EOD 1700 -> floor -300, 30 micros
    assert g.account_limits(daily, today, r) == (-300.0, 30)
    daily[D(2026, 11, 5)] = 500.0                                          # EOD 2200 -> floor locks at 0, 50 micros
    assert g.account_limits(daily, today, r) == (0.0, 50)
    r2 = g.make_rules("xfa", "50k", "standard", payout_since=D(2026, 11, 4))
    assert g.account_limits({D(2026, 11, 3): 100.0}, today, r2)[0] == 0.0  # after payout MLL = 0


def test_xfa_scaling_100k_150k():
    today = D(2026, 11, 6)
    r = g.make_rules("xfa", "100k")
    assert g.account_limits({D(2026, 11, 3): 3200.0}, today, r)[1] == 100
    r = g.make_rules("xfa", "150k")
    assert g.account_limits({D(2026, 11, 3): 1000.0}, today, r)[1] == 30
    assert g.account_limits({D(2026, 11, 3): 4600.0}, today, r)[1] == 150


def test_xfa_consistency_early_warning():
    r = g.make_rules("xfa", "50k", "consistency")
    now = dt.datetime(2026, 11, 6, 10, 0, tzinfo=CT)
    snap = {"balance": 1000.0 + 560.0, "orders": [], "positions": [],
            "daily": {D(2026, 11, 4): 500.0, D(2026, 11, 5): 400.0, D(2026, 11, 6): 560.0}}   # max today = 600
    a = [x for x in g.evaluate(snap, now, r) if x[1] == "xfa_cons"]
    assert a and a[0][0] == g.WARN and "paas" in a[0][2]
    snap["daily"][D(2026, 11, 6)] = 700.0
    a = [x for x in g.evaluate(snap, now, r) if x[1] == "xfa_cons"]
    assert "> 40%" in a[0][2]


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            n += 1
            print("ok", name)
    print("%d tests passed" % n)
