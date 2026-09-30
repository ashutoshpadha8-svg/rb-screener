#!/usr/bin/env python3
"""
EXECUTION SAFETY TESTS (30 Sep 2026, Codex milestone 1 + review of it) --
mocks only: no network, no token, NO real order.
Run:  cd ~/RB_Screener && python3 tests/test_execution.py

Pass condition: timeout / delayed book / next day / crash / save failure /
two processes / partial fills / cancel / holiday / full portfolio -> never a
second order for the same intent, never a limit breach.
"""
import os
import sys
import subprocess
import tempfile
import datetime as dt

import pandas as pd
import requests

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import broker_api as ba                                         # noqa: E402
import daily_screener as ds                                     # noqa: E402
import auto_tracker_update as at                                # noqa: E402

RESULTS = []
REAL = {"check_order_status": ba.check_order_status,
        "update_intent": ba.update_intent}


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          "" if cond else "  <- " + str(detail)))


class Resp(object):
    def __init__(self, code, js):
        self.status_code, self._js, self.text = code, js, str(js)

    def json(self):
        return self._js


class FakeDhan(object):
    """post: 'ok' | 'reject' | 'lost_after_accept' | 'lost_before'.
    show: the order book shows accepted orders (False = book lags / empty).
    book_down: the book cannot be read at all."""

    def __init__(self, post="ok", show=True, book_down=False):
        self.post, self.show, self.book_down = post, show, book_down
        self.posts, self.orders, self.n = 0, {}, 100

    def __call__(self, method, url, **kw):
        path = url.replace(ba.DHAN_BASE, "")
        if method == "POST" and path == "/orders":
            self.posts += 1
            body = kw.get("json") or {}
            if self.post == "reject":
                return Resp(400, {"errorType": "Order", "errorCode": "DH-906",
                                  "errorMessage": "RMS rejected"})
            self.n += 1
            oid = str(self.n)
            if self.post != "lost_before":
                self.orders[body["correlationId"]] = {
                    "orderId": oid, "orderStatus": "PENDING"}
            if self.post.startswith("lost"):
                raise requests.ReadTimeout("reply lost")
            return Resp(200, {"orderId": oid, "orderStatus": "PENDING"})
        if method == "GET" and path.startswith("/orders/external/"):
            if self.book_down:
                raise requests.ConnectionError("down")
            tag = path.rsplit("/", 1)[1]
            if self.show and tag in self.orders:
                return Resp(200, self.orders[tag])
            return Resp(404, {"errorCode": "DH-404", "errorMessage": "nf"})
        if method == "GET" and path.startswith("/orders/"):
            oid = path.rsplit("/", 1)[1]
            o = next((o for o in self.orders.values() if o["orderId"] == oid),
                     None)
            return Resp(200, o) if o else Resp(404, {"errorCode": "DH-404",
                                                     "errorMessage": "nf"})
        if method == "GET" and path.startswith("/trades/"):
            return Resp(200, [])
        raise AssertionError("unexpected call %s %s" % (method, path))


def fresh(fake):
    d = tempfile.mkdtemp()
    ba.ORDER_LOG = os.path.join(d, "orders_log.csv")
    ba.requests.request = fake
    ba.time.sleep = lambda s: None
    ba.verify_identity = lambda sess: (True, "ok")
    ba.symbol_map = lambda sess: {"ABC": {"id": "1", "tsym": "ABC-EQ"}}
    ba.check_order_status = REAL["check_order_status"]
    ba.update_intent = REAL["update_intent"]
    ds.market_open = lambda: False
    return ba.Session("DHAN", "x", client_id="1100000000")


def run(sess, side="BUY", product="CNC"):
    """One rbtrack attempt: guard -> send_one (intent, POST, save)."""
    blocked = ba.sold_recently("ABC", sess=sess) if side == "SELL" else \
        ba.ordered_today("ABC", side, sess=sess)
    if blocked:
        return "BLOCKED"
    ok, res, st = at.send_one(sess, "ABC", 1, product, side)
    return "OK" if ok else st


def age_ledger(days):
    d = ba.load_intents()
    d["date"] = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    ba._save_intents(d)


def main():
    print("1) reply lost AFTER the broker accepted, book shows it")
    f = FakeDhan("lost_after_accept")
    s = fresh(f)
    r1, r2 = run(s), run(s)
    check("found by tag -> OK", r1 == "OK", r1)
    check("re-run blocked, 1 POST", r2 == "BLOCKED" and f.posts == 1,
          "%s posts=%d" % (r2, f.posts))

    print("2) reply lost, book EMPTY at first, order appears later")
    f = FakeDhan("lost_after_accept", show=False)
    s = fresh(f)
    r1 = run(s)
    check("status UNKNOWN (empty book is not 'not placed')", r1 == "UNKNOWN",
          r1)
    check("re-run blocked, still 1 POST", run(s) == "BLOCKED" and
          f.posts == 1, "posts=%d" % f.posts)
    f.show = True
    check("book shows it later -> still blocked", run(s) == "BLOCKED")
    st = ba.load_intents()["state"].tolist()
    check("intent turned ACCEPTED from the book", st == ["ACCEPTED"], st)

    print("3) UNKNOWN is NOT cleared by the next day / an empty day book")
    f = FakeDhan("lost_before", show=False)
    s = fresh(f)
    run(s)
    age_ledger(1)                               # 'tomorrow', Kite-like book
    check("next day still blocked", run(s) == "BLOCKED" and f.posts == 1,
          "posts=%d" % f.posts)
    age_ledger(5)
    check("5 days later still blocked", run(s) == "BLOCKED")
    tag = ba.open_intents()["tag"].iloc[0]
    ba.resolve_intent(tag, placed=False)       # RB checked the app
    f.post = "ok"
    check("after --resolve not-placed: one new order", run(s) == "OK" and
          f.posts == 2, "posts=%d" % f.posts)

    print("4) every intent gets its own tag")
    f = FakeDhan("ok")
    s = fresh(f)
    t1 = ba.new_intent("ABC", "BUY", 1, "CNC")
    t2 = ba.new_intent("ABC", "BUY", 1, "MTF")
    tags = {ba.new_tag("BUY") for _ in range(2000)}
    check("CNC and MTF intents differ", t1 != t2, (t1, t2))
    check("2000 tags, no repeat, <= 20 chars", len(tags) == 2000 and
          max(len(t) for t in tags) <= 20)
    f.orders[t2] = {"orderId": "900", "orderStatus": "PENDING"}
    check("lookup finds only its own intent",
          ba.find_order_by_tag(s, t2)[0] is True and
          ba.find_order_by_tag(s, t1)[0] is False)

    print("5) broker accepted, then saving the result FAILED")
    f = FakeDhan("ok")
    s = fresh(f)

    def boom(*a, **k):
        raise OSError("disk full")
    ba.update_intent = boom
    run(s)
    ba.update_intent = REAL["update_intent"]
    check("intent left open", len(ba.open_intents()) == 1)
    check("next run finds it by tag -> blocked, 1 POST",
          run(s) == "BLOCKED" and f.posts == 1, "posts=%d" % f.posts)

    print("6) two rbtrack processes at the same time")
    lockdir = os.path.dirname(ba.ORDER_LOG)
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import fcntl,sys,time;f=open(sys.argv[1],'w');"
         "fcntl.flock(f,fcntl.LOCK_EX);print('ok',flush=True);time.sleep(5)",
         os.path.join(lockdir, "rbtrack.lock")], stdout=subprocess.PIPE)
    holder.stdout.readline()
    check("second process refused", at.take_lock() is False)
    holder.kill()
    holder.wait()
    check("free again after the first ends", at.take_lock() is True)

    print("7) partial fills are not double-counted (3 -> 3 -> 6, cancel)")
    sp = pd.DataFrame([{"symbol": "ABC", "swing_qty": 10, "investing_qty": 0,
                        "momentum_qty": 0, "entry_price": 100.0,
                        "entry_date": "2026-09-30", "strategy": "W+TT",
                        "mode": "LIVE", "product": "CNC", "order_id": "5501",
                        "note": "AMO pending"}])
    store = {"sp": sp}
    at.read_split = lambda: store["sp"].copy()
    at.write_split = lambda d: store.__setitem__("sp", d)
    seq = iter([("PENDING", 3), ("PENDING", 3), ("PENDING", 6),
                ("CANCELLED", 6), ("CANCELLED", 6)])

    def fill(oid, sess=None):
        st, q = next(seq)
        return {"status": st, "filled_qty": q, "avg_price": 101.0, "raw": st}
    at.ba.check_order_status = fill
    got = []
    for _ in range(5):                         # 5 syncs = restarts too
        at.sync(None)
        got.append(int(store["sp"].iloc[0]["swing_qty"]))
    check("qty 3,3,6 then stays 6", got[:3] == [3, 3, 6] and
          got[3] == 6, got)
    check("closed after cancel, re-sync changes nothing",
          "filled" in store["sp"].iloc[0]["note"] and got[4] == 6,
          store["sp"].iloc[0]["note"])
    ba.check_order_status = REAL["check_order_status"]

    print("8) cancelled / rejected orders free the stock, pending ones don't")
    f = FakeDhan("ok")
    s = fresh(f)
    run(s, side="SELL")
    f.orders[list(f.orders)[0]]["orderStatus"] = "PENDING"
    check("pending SELL blocks a 2nd SELL", run(s, side="SELL") == "BLOCKED")
    f.orders[list(f.orders)[0]]["orderStatus"] = "CANCELLED"
    check("cancelled SELL -> exit can be sent again",
          run(s, side="SELL") == "OK" and f.posts == 2, "posts=%d" % f.posts)
    f2 = FakeDhan("reject")
    s = fresh(f2)
    check("broker reject -> no block", run(s) != "BLOCKED" and
          run(s) != "BLOCKED" and f2.posts == 2)

    print("9) holiday on the rebalance day")
    import nse_calendar as nc
    import portfolio as pf
    nc._mem = {"2026-11-02"}
    check("Fri 30 Oct = last trading day -> window", pf.rebal_window(
        "2026-10-30"))
    check("1st trading day = Tue 3 Nov", nc.first_trading_day(2026, 11) ==
          dt.date(2026, 11, 3) and pf.rebal_window("2026-11-03"))
    check("Thu 29 Oct not in window", not pf.rebal_window("2026-10-29"))

    print("10) 20 positions + 4 per industry at order time")
    held = ["H%02d" % i for i in range(19)]
    sp = pd.DataFrame({"symbol": held, "swing_qty": 0, "investing_qty": 0,
                       "momentum_qty": 10, "entry_price": 1.0,
                       "entry_date": "2026-09-01", "strategy": "Momentum",
                       "mode": "LIVE", "product": "CNC", "order_id": "",
                       "note": ""})
    sold, ordered = at.ba.sold_recently, at.ba.ordered_today
    at.ba.sold_recently = lambda sym, **k: sym == "H17"
    at.ba.ordered_today = lambda *a, **k: False
    sec = {h: ("Fin" if i < 4 else "S%d" % i) for i, h in enumerate(held)}
    sec.update(NF="Fin", A="X", B="Y", C="Z")
    at._sectors = lambda: sec
    rows = pd.DataFrame({"Ticker": ["NF", "A", "B", "C"], "act": "BUY",
                         "Strategy Overlap": "Momentum only",
                         "Amount (Rs)": ""})
    new, skip = at.plan(rows, {t: (100.0, "x") for t in
                               ("NF", "A", "B", "C")}, sp)
    got = [n["symbol"] for n in new]
    check("5th Fin refused, max 20 (SELL-sent frees 1)", got == ["A", "B"],
          "%s | %s" % (got, skip))
    at.ba.sold_recently, at.ba.ordered_today = sold, ordered

    print("11) rebalance plan counts kept holdings per industry")
    import momentum_screener as ms
    import numpy as np
    syms = ["S%02d" % i for i in range(1, 61)]
    full = pd.DataFrame({"symbol": syms, "rank": range(1, 61),
                         "score": np.linspace(5, 0, 60),
                         "sector": ["Fin" if i % 2 == 0 else "O%d" % (i % 9)
                                    for i in range(60)], "price": 100.0})
    top = full.head(20).assign(shares=100, amount=10000)
    keep = ["S25", "S27", "S29", "S31"]
    ms.momentum_positions = lambda: pd.DataFrame(
        {"symbol": keep, "mode": "LIVE", "qty": 10, "entry": 90.0})
    plan = ms.rebalance_plan(top, full)
    buys = [r for r in plan if r["Section"] == "BUY"]
    fin = sum(1 for r in plan if r["Section"] in ("BUY", "HOLD") and
              r["Sector"] == "Fin")
    check("16 BUY for 16 free slots, Fin stays 4", len(buys) == 16 and
          fin == 4, "%d buys, %d Fin" % (len(buys), fin))

    bad = [n for n, ok in RESULTS if not ok]
    print("\n%d / %d passed%s" % (len(RESULTS) - len(bad), len(RESULTS),
                                  "" if not bad else " -- FAILED: " +
                                  ", ".join(bad)))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
