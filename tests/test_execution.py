#!/usr/bin/env python3
"""
EXECUTION SAFETY TESTS (30 Sep 2026, Codex milestone 1) -- mocks only, no
network, no token, NO real order. Run:  python3 tests/test_execution.py

Pass condition: in timeout / partial-fill / cancellation / crash / holiday /
full-portfolio scenarios there is never a duplicate order or a limit breach.
"""
import os
import sys
import tempfile
import datetime as dt

import pandas as pd
import requests

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import broker_api as ba                                         # noqa: E402
import daily_screener as ds                                     # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          "" if cond else "  <- " + detail))


class Resp(object):
    def __init__(self, code, js):
        self.status_code, self._js = code, js
        self.text = str(js)

    def json(self):
        return self._js


class FakeDhan(object):
    """Fake Dhan server. post_mode: 'ok' | 'timeout_after_accept' |
    'timeout_before' ; book: dict tag -> order (what the broker really has);
    book_down: order book unreadable."""

    def __init__(self, post_mode="ok", book_down=False):
        self.post_mode, self.book_down = post_mode, book_down
        self.posts, self.book, self.n = 0, {}, 100

    def __call__(self, method, url, **kw):
        path = url.replace(ba.DHAN_BASE, "")
        if method == "POST" and path == "/orders":
            self.posts += 1
            body = kw.get("json") or {}
            self.n += 1
            oid = str(self.n)
            if self.post_mode != "timeout_before":
                self.book[body["correlationId"]] = {
                    "orderId": oid, "orderStatus": "PENDING"}
            if self.post_mode.startswith("timeout"):
                raise requests.ReadTimeout("reply lost")
            return Resp(200, {"orderId": oid, "orderStatus": "PENDING"})
        if method == "GET" and path.startswith("/orders/external/"):
            if self.book_down:
                raise requests.ConnectionError("down")
            tag = path.rsplit("/", 1)[1]
            if tag in self.book:
                return Resp(200, self.book[tag])
            return Resp(404, {"errorType": "Order", "errorCode": "DH-404",
                              "errorMessage": "not found"})
        if method == "GET" and path.startswith("/orders/"):
            oid = path.rsplit("/", 1)[1]
            o = next((o for o in self.book.values() if o["orderId"] == oid),
                     None)
            return Resp(200, o) if o else Resp(404, {"errorCode": "DH-404",
                                                     "errorMessage": "nf"})
        if method == "GET" and path.startswith("/trades/"):
            return Resp(200, [])
        raise AssertionError("unexpected call %s %s" % (method, path))


def setup(fake):
    ba.ORDER_LOG = tempfile.mktemp(suffix=".csv")
    ba.requests.request = fake
    ba.time.sleep = lambda s: None
    ba.verify_identity = lambda sess: (True, "ok")
    ba.symbol_map = lambda sess: {"ABC": {"id": "1", "tsym": "ABC-EQ"},
                                  "XYZ": {"id": "2", "tsym": "XYZ-EQ"}}
    ds.market_open = lambda: False
    s = ba.Session("DHAN", "x", client_id="1100000000")
    return s


def send(sess, sym="ABC", side="BUY"):
    """What rbtrack does for one order: guard -> intent -> send -> log."""
    if ba.ordered_today(sym, side, sess=sess):
        return "BLOCKED"
    ba.log_intent(sym, side, 1, "CNC", sess)
    ok, res, st = ba.place_amo_order(sym, 1, False, sess=sess, side=side)
    ba.log_order({"date": dt.date.today().isoformat(), "broker": "DHAN",
                  "client_id": sess.client_id, "time": "", "symbol": sym,
                  "qty": 1, "side": side, "product": "CNC", "type": "MARKET",
                  "ok": ok, "order_id": res if ok else "", "status": st,
                  "error": "" if ok else res})
    return "OK" if ok else res


def main():
    print("1) timeout AFTER the broker accepted the order")
    f = FakeDhan("timeout_after_accept")
    s = setup(f)
    r1 = send(s)
    r2 = send(s)                               # rbtrack run again
    check("one POST only", f.posts == 1, "posts=%d" % f.posts)
    check("found in the book -> OK", r1 == "OK", r1)
    check("second run blocked", r2 == "BLOCKED", r2)

    print("2) timeout BEFORE the broker got it (book has no order)")
    f = FakeDhan("timeout_before")
    s = setup(f)
    r1 = send(s)
    check("reported not placed", "not placed" in r1, r1)
    f.post_mode = "ok"
    r2 = send(s)
    check("re-run may send once", r2 == "OK" and f.posts == 2,
          "%s posts=%d" % (r2, f.posts))
    check("third run blocked", send(s) == "BLOCKED")

    print("3) timeout and the order book is unreachable")
    f = FakeDhan("timeout_after_accept", book_down=True)
    s = setup(f)
    r1 = send(s)
    check("status UNKNOWN", "STATUS UNKNOWN" in r1, r1)
    check("re-run blocked (book still down)", send(s) == "BLOCKED")
    check("one POST only", f.posts == 1, "posts=%d" % f.posts)

    print("4) rbtrack crashed after writing the intent (mid-send)")
    f = FakeDhan("ok")
    s = setup(f)
    ba.log_intent("ABC", "BUY", 1, "CNC", s)   # no result row after it
    f.book[ba.order_tag("ABC", "BUY")] = {"orderId": "7",
                                          "orderStatus": "PENDING"}
    check("orphan intent + order in book -> blocked",
          ba.ordered_today("ABC", sess=s))
    f.book.clear()
    check("orphan intent + empty book -> free", not ba.ordered_today(
        "ABC", sess=s))
    check("orphan intent, no broker check -> blocked",
          ba.ordered_today("ABC"))

    print("5) accepted order later CANCELLED / REJECTED")
    f = FakeDhan("ok")
    s = setup(f)
    send(s, side="SELL")
    real = ba.check_order_status
    ba.check_order_status = lambda oid, sess=None: {"status": "CANCELLED"}
    check("cancelled SELL does not block the exit",
          not ba.sold_recently("ABC", sess=s))
    ba.check_order_status = lambda oid, sess=None: {"status": "PENDING"}
    check("pending SELL blocks a second SELL", ba.sold_recently("ABC",
                                                                  sess=s))
    ba.check_order_status = real

    print("6) partial fill")
    import auto_tracker_update as at
    sp = pd.DataFrame([{"symbol": "ABC", "swing_qty": 10, "investing_qty": 0,
                        "momentum_qty": 0, "entry_price": 100.0,
                        "entry_date": "2026-09-30", "strategy": "W+TT",
                        "mode": "LIVE", "product": "CNC", "order_id": "5501",
                        "note": "AMO pending"}])
    store = {"sp": sp}
    at.read_split = lambda: store["sp"].copy()
    at.write_split = lambda d: store.__setitem__("sp", d)
    fills = iter([{"status": "PENDING", "filled_qty": 3, "avg_price": 101.0,
                   "raw": "PART"},
                  {"status": "CANCELLED", "filled_qty": 3,
                   "avg_price": 101.0, "raw": "CANCELLED"}])
    at.ba.check_order_status = lambda oid, sess=None: next(fills)
    at.sync(None)
    d = store["sp"].iloc[0]
    check("partial: qty 3, still pending", d["swing_qty"] == 3 and
          "pending" in d["note"], "%s %s" % (d["swing_qty"], d["note"]))
    at.sync(None)
    d = store["sp"].iloc[0]
    check("rest cancelled: qty 3 kept, closed", d["swing_qty"] == 3 and
          "filled" in d["note"], "%s %s" % (d["swing_qty"], d["note"]))
    ba.check_order_status = real

    print("7) holiday on the rebalance day")
    import nse_calendar as nc
    import portfolio as pf
    nc._mem = {"2026-11-02"}                   # pretend Mon 2 Nov closed
    check("last trading day before (Fri 30 Oct) = window",
          pf.rebal_window("2026-10-30"))
    check("holiday itself not a trading day",
          not nc.is_trading_day(dt.date(2026, 11, 2)))
    check("first trading day = Tue 3 Nov",
          nc.first_trading_day(2026, 11) == dt.date(2026, 11, 3) and
          pf.rebal_window("2026-11-03"))
    check("Thu 29 Oct not in window", not pf.rebal_window("2026-10-29"))

    print("8) 20 positions + 4 per industry at order time")
    held = ["H%02d" % i for i in range(19)]
    sp = pd.DataFrame({"symbol": held, "swing_qty": 0, "investing_qty": 0,
                       "momentum_qty": 10, "entry_price": 1.0,
                       "entry_date": "2026-09-01", "strategy": "Momentum",
                       "mode": "LIVE", "product": "CNC", "order_id": "",
                       "note": ""})
    at.ba.sold_recently = lambda sym, **k: sym == "H17"   # SELL sent
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
    check("5th Fin refused, 20 max (1 slot freed by the SELL)",
          got == ["A", "B"], "%s | %s" % (got, skip))

    print("9) rebalance plan counts kept holdings per industry")
    import momentum_screener as ms
    import numpy as np
    syms = ["S%02d" % i for i in range(1, 61)]
    full = pd.DataFrame({"symbol": syms, "rank": range(1, 61),
                         "score": np.linspace(5, 0, 60),
                         "sector": ["Fin" if i % 2 == 0 else "O%d" % (i % 9)
                                    for i in range(60)], "price": 100.0})
    top = full.head(20).assign(shares=100, amount=10000)
    keep = ["S25", "S27", "S29", "S31"]          # 4 Fin holdings, rank <= 40
    ms.momentum_positions = lambda: pd.DataFrame(
        {"symbol": keep, "mode": "LIVE", "qty": 10, "entry": 90.0})
    plan = ms.rebalance_plan(top, full)
    buys = [r for r in plan if r["Section"] == "BUY"]
    fin = sum(1 for r in plan if r["Section"] in ("BUY", "HOLD") and
              r["Sector"] == "Fin")
    check("16 BUY for 16 free slots", len(buys) == 16, str(len(buys)))
    check("Fin total stays 4", fin == 4, str(fin))

    bad = [n for n, ok in RESULTS if not ok]
    print("\n%d / %d passed%s" % (len(RESULTS) - len(bad), len(RESULTS),
                                  "" if not bad else " -- FAILED: " +
                                  ", ".join(bad)))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
