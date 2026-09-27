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


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            n += 1
            print("ok", name)
    print("%d tests passed" % n)
