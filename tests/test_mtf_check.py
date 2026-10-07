#!/usr/bin/env python3
"""
MTF CHECK v29 (7 Oct 2026) -- Codex's v27 review turned into required
behaviour. Mocked data only: no network, no token, NO order.
Run: python3 tests/test_mtf_check.py
"""
import argparse
import datetime as dt
import os
import sys
import tempfile

import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import broker_api as ba                                          # noqa: E402
import mtf_check as mc                                           # noqa: E402

RESULTS = []
TODAY = dt.date(2026, 10, 7)
U, E, V = mc.UNKNOWN, mc.ESTIMATED, mc.VERIFIED


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          "" if cond else "  <- " + str(detail)))


def tr(sym="AAA", side="BUY", qty=10, price=1000, ts="2026-09-01 10:00:00",
       product="MTF", tid=None, exch="NSE_EQ", charges=0):
    t = {"symbol": sym, "side": side, "qty": float(qty), "price": float(price),
         "ts": mc._ts(ts), "product": product, "exch": exch,
         "tid": tid or "", "oid": "", "isin": "", "charges": charges,
         "charges_ok": True}
    t["date"] = t["ts"].date().isoformat() if t["ts"] else None
    return t


def led(*rows):
    return mc.ledger_rows([{"narration": n, "voucherdate": d, "debit": de,
                            "credit": c} for n, d, de, c in rows])


def args(**k):
    a = argparse.Namespace(frm="2024-04-01", ledger=None, rate=mc.MTF_RATE,
                           loan=None, unpaid_interest=None, own_cash=None)
    for x, v in k.items():
        setattr(a, x, v)
    return a


def run(trades, demat, prices, ledger=None, fail_ledger=False,
        fail_demat=False, positions=None, **k):
    """build() with every broker call mocked."""
    mc.dhan_trades = lambda *a, **kw: (list(trades), {"complete": True,
                                                      "notes": []})

    def L(*a, **kw):
        if fail_ledger:
            raise RuntimeError("synthetic ledger failure")
        return ledger if ledger is not None else led()
    mc.dhan_ledger = L

    def H(sess):
        if fail_demat:
            raise RuntimeError("synthetic holdings failure")
        return [{"symbol": s, "qty": q, "avg_price": 0} for s, q in
                demat.items()]
    ba.holdings = H
    ba.live_prices = lambda s, x: {k2: v for k2, v in prices.items()
                                   if k2 in x}
    mc.last_closes = lambda syms: {}
    mc.mtf_positions = lambda sess: dict(positions or {})
    return mc.build(args(**k), object(), TODAY, dt.date(2024, 4, 1))


def main():
    print("1) values carry a status; UNKNOWN never becomes 0")
    t = mc.total([mc.Num(100), mc.Num(None), mc.Num(50, E)])
    check("total with an UNKNOWN part = UNKNOWN, partial 150",
          not t.known and t.status == U and t.partial == 150, t)
    t2 = mc.total([mc.Num(100), mc.Num(-30, E)])
    check("total of known + estimated = ESTIMATED 70", t2.value == 70 and
          t2.status == E, t2)
    check("NaN / inf is UNKNOWN", not mc.Num(float("nan")).known and
          not mc.Num(float("inf")).known)
    check("rs(UNKNOWN) shows the known part", mc.rs(t) ==
          "UNKNOWN (known part Rs 150)", mc.rs(t))

    print("2) F1: past interest = AVERAGE balance, not today's loan")
    wk = 150000 * mc.MTF_RATE * 7 / 365
    lg = led(("MTF Interest MTF Interest for Period  24/09/2026 To "
              "30/09/2026 Clt", "Oct 01, 2026", wk, 0))
    avg, day, txt, end = mc.avg_interest_balance(lg)
    check("diagnostic avg balance = 150,000 for that week",
          round(avg) == 150000 and end == dt.date(2026, 9, 30), avg)
    trades = [tr(qty=100, price=1000, ts="2026-09-01 10:00:00")]
    R = run(trades, {"AAA": 100}, {"AAA": 950.0}, ledger=lg, loan=75000)
    check("--loan 75,000 is what the exit uses (not 150,000)",
          R["loan"].value == 75000 and R["exit"].known and
          round(R["exit"].value + 75000 + R["unpaid"].value +
                R["fees"].value) == 95000, (R["loan"], R["exit"]))
    R0 = run(trades, {"AAA": 100}, {"AAA": 950.0}, ledger=lg)
    check("no --loan -> loan, own money, exit cash UNKNOWN",
          not R0["loan"].known and not R0["own"].known and
          not R0["exit"].known, (R0["loan"], R0["exit"]))
    check("zero rate -> no inverse balance", mc.avg_interest_balance(
        lg, 0)[0] is None)

    print("3) F2 + demo: unpaid interest + fees; paid interest NOT again")
    R = run(trades, {"AAA": 100}, {"AAA": 950.0}, ledger=lg, loan=75000,
            unpaid_interest=400)
    fees = R["fees"].value
    check("exit cash = 95,000 - 75,000 - 400 - sell fees",
          abs(R["exit"].value - (95000 - 75000 - 400 - fees)) < 0.01,
          (R["exit"], fees))
    check("ledger-paid interest is in the period P&L, not in exit cash",
          R["paid"].value == round(wk, 2) and
          abs(R["period"].value - (-5000 - round(wk, 2) - 400 - fees)) < 0.01,
          (R["paid"], R["period"]))
    check("own money = cost - loan = 25,000", R["own"].value == 25000)
    demo = mc.total([mc.Num(95000), -mc.Num(75000), -mc.Num(400),
                     -mc.Num(120)])
    check("Codex demo: 95,000 - 75,000 - 400 - 120 = 19,480",
          demo.value == 19480)

    print("4) F3: missing quote / failed ledger -> UNKNOWN, exit code 2")
    R = run(trades, {"AAA": 100}, {}, ledger=lg, loan=75000)
    check("no price -> value, exit cash, period UNKNOWN",
          not R["val"].known and not R["exit"].known and
          not R["period"].known, (R["val"], R["exit"]))
    R = run(trades + [tr("BBB", qty=10, price=100)], {"AAA": 100, "BBB": 10},
            {"AAA": 950.0}, ledger=lg, loan=75000)
    check("one quote missing -> total UNKNOWN with partial 95,000",
          not R["val"].known and R["val"].partial == 95000, R["val"])
    R = run(trades, {"AAA": 100}, {"AAA": 950.0}, fail_ledger=True,
            loan=75000)
    check("ledger failure -> paid interest UNKNOWN (not 0), report "
          "INCOMPLETE", not R["paid"].known and not R["period"].known and
          R["ok"] is False, (R["paid"], R["ok"]))

    print("5) F4: inventory reconciled, nothing phantom or dropped")
    R = run(trades, {}, {"AAA": 950.0}, ledger=lg)
    check("history lot but demat EMPTY -> not valued, totals UNKNOWN",
          not R["rows"] and not R["val"].known and any(
              r["Symbol"] == "AAA" and r["Status"] == U for r in R["rec"]),
          R["rec"])
    R = run(trades, {"AAA": 100, "BBB": 5}, {"AAA": 950.0, "BBB": 1.0},
            ledger=lg, positions={"BBB": 5})
    check("current MTF position BBB without history -> UNKNOWN row, open "
          "totals UNKNOWN (not silently dropped)",
          any(r["Symbol"] == "BBB" and r["Status"] == U for r in R["rec"])
          and not R["val"].known and R["val"].partial == 95000, R["rec"])
    R = run(trades, {"AAA": 100, "ZZZ": 3}, {"AAA": 950.0}, ledger=lg)
    check("CNC demat stock with no MTF trade -> 'NOT MTF', totals still "
          "known", any(r["Symbol"] == "ZZZ" and r["Status"] == "NOT MTF"
                       for r in R["rec"]) and R["val"].value == 95000,
          R["rec"])
    R = run(trades, {"AAA": 60}, {"AAA": 950.0}, ledger=lg)
    check("demat 60 < MTF lots 100 -> UNKNOWN (no full-lot average)",
          not R["rows"] and not R["val"].known, R["rec"])
    R = run(trades, {"AAA": 120}, {"AAA": 950.0}, ledger=lg)
    check("demat 120 > MTF lots 100 -> MTF 100 valued, ESTIMATED",
          R["rows"][0]["Qty"] == 100 and any(
              r["Status"] == E for r in R["rec"]), R["rec"])

    R = run([], {"TCS": 52}, {"TCS": 2660.0}, ledger=lg)
    check("ledger charged MTF interest last week but no MTF lot found -> "
          "inventory UNKNOWN, never 'no position / unpaid 0'",
          not R["val"].known and not R["period"].known and
          any(r["Symbol"] == "?" for r in R["rec"]), (R["val"], R["rec"]))

    print("6) F5: exact execution time, uncovered sells")
    f = mc.fifo([tr("CCC", "SELL", 4, 60, "2024-08-01 09:30:00"),
                 tr("CCC", "BUY", 4, 50, "2024-08-01 14:00:00")], TODAY)
    check("morning SELL uncovered, afternoon BUY stays OPEN (4 @ 50)",
          f["lots"]["CCC"][0][1:3] == [4.0, 50.0] and
          f["uncovered"] == {"CCC": 4.0} and not f["realised"].known,
          (f["lots"], f["uncovered"], f["realised"]))
    f = mc.fifo([tr("A", "BUY", 10, 100, "2024-05-01 10:00:00"),
                 tr("A", "BUY", 10, 120, "2024-06-01 10:00:00"),
                 tr("A", "SELL", 15, 90, "2024-07-01 10:00:00")], TODAY)
    check("covered FIFO: realised -250 VERIFIED, 5 @ 120 open",
          f["realised"].value == -250 and f["realised"].status == V and
          f["lots"]["A"][0][1:3] == [5.0, 120.0], f)
    f = mc.fifo([tr("A", ts=None)], TODAY)
    check("trade without a time -> invalid, not dated at window end",
          f["invalid"] == 1 and not f["lots"], f)
    f = mc.fifo([tr("A", ts="2026-12-01 10:00:00")], TODAY)
    check("future-dated trade -> invalid", f["invalid"] == 1)

    print("7) F6: interest by LOT days")
    lots = [["2026-06-29", 10, 1000, 0], ["2026-09-27", 10, 1000, 0]]
    li = mc.lot_interest(lots, 0.75, mc.MTF_RATE, TODAY)
    check("10x1000 @100 days + 10x1000 @10 days = 282.31 (not 513.29)",
          li.value == 282.31 and li.status == E, li)
    check("no funded share -> lot interest UNKNOWN",
          not mc.lot_interest(lots, None, mc.MTF_RATE, TODAY).known)

    print("8) F7: account-wide items stay out of the MTF result")
    lg2 = led(("MTF Interest for Period 24/09/2026 To 30/09/2026",
               "Oct 01, 2026", wk, 0),
              ("Dividend Received in Trading Ledger", "Sep 05, 2026", 0, 100),
              ("DP Charges for sale of ZZZ", "Sep 06, 2026", 20, 0))
    Ra = run(trades, {"AAA": 100}, {"AAA": 950.0}, ledger=lg, loan=75000,
             unpaid_interest=0)
    Rb = run(trades, {"AAA": 100}, {"AAA": 950.0}, ledger=lg2, loan=75000,
             unpaid_interest=0)
    check("CNC dividend 100 + DP 20 do NOT change the MTF period P&L",
          Ra["period"].value == Rb["period"].value and
          "Dividend (income)" in Rb["unalloc"] and "DP charges" in
          Rb["unalloc"], (Ra["period"], Rb["unalloc"]))
    check("no 'all products net' figure any more", "net" not in Rb)

    print("9) F8: dates, numbers, duplicates")
    check("05/10/2026 = 5 Oct (day first)", mc.parse_date("05/10/2026") ==
          dt.date(2026, 10, 5))
    check("Dhan API 'Sep 24, 2026'", mc.parse_date("Sep 24, 2026") ==
          dt.date(2026, 9, 24))
    a = tr(tid="T1")
    kept, drop = mc.dedupe([a, dict(a), dict(a, exch="BSE_EQ")])
    check("replayed execution dropped, same id on another exchange kept",
          len(kept) == 2 and drop == 1, (len(kept), drop))
    bad = led(("MTF Interest for Period 01/09/2026 To 07/09/2026",
               "Sep 08, 2026", "abc", 0))
    ch = mc.charges(bad)
    check("unreadable amount -> that bucket UNKNOWN", not ch["MTF interest"]
          .known, ch)
    dup = mc.ledger_rows([{"narration": "MTF Interest x", "voucherdate":
                           "Oct 01, 2026", "debit": 10, "credit": 0,
                           "vouchernumber": "V1"}] * 2)
    check("duplicate voucher counted once", len(dup) == 1)
    pt = mc.parse_trade({"securityId": "9", "tradingSymbol": "AAA-EQ",
                         "transactionType": "BUY", "tradedQuantity": 5,
                         "tradedPrice": 10, "exchangeTime":
                         "2026-09-01 10:15:00", "productType": "",
                         "exchangeSegment": "NSE_EQ", "exchangeTradeId":
                         "X9", "stt": 1, "stampDuty": 0.5})
    check("parse_trade keeps time, id, blank product, charges 1.5",
          pt["ts"] == dt.datetime(2026, 9, 1, 10, 15) and pt["tid"] == "X9"
          and pt["product"] == "" and pt["charges"] == 1.5 and
          pt["symbol"] == "AAA", pt)

    print("10) classifier (real Dhan narrations) + Excel")
    check("Dhan narrations", mc.classify(
        "MTF Interest MTF Interest for Period  24/09/2026 To 30/09/2026 Clt")
        == "MTF interest" and mc.classify("Margin Interest for Period") ==
        "Other interest" and mc.classify("DP Transaction Charges Charges "
                                          "for Sell / Pledge / Unpledge")
        == "Pledge charges" and mc.classify("CLOSING BALANCE") == "_balance"
        and mc.classify("Funds added via UPI") == "_money")
    blank = [dict(tr(qty=100, price=1000), product="")]
    R = run(blank, {"AAA": 100}, {"AAA": 950.0}, ledger=lg, loan=75000)
    check("blank product taken as MTF only when no MTF label, ESTIMATED",
          R["guessed"] and R["rec"][0]["Status"] == E and R["rows"], R["rec"])
    d = tempfile.mkdtemp()
    f = os.path.join(d, "l.xlsx")
    pd.DataFrame([["Ledger", None, None, None],
                  ["Date", "Narration", "Debit", "Credit"],
                  ["05/09/2026", "MTF Int. for Aug", 99.0, 0]]).to_excel(
        f, index=False, header=False)
    L2 = mc.read_ledger_file(f)
    check("downloaded file: header found, date day-first, 99",
          mc.charges(L2)["MTF interest"].value == 99 and
          L2["date"].iloc[0] == dt.date(2026, 9, 5), L2)

    bad_ = [n for n, ok in RESULTS if not ok]
    print("\n%d / %d passed%s" % (len(RESULTS) - len(bad_), len(RESULTS),
                                  "" if not bad_ else " -- FAILED: " +
                                  "; ".join(bad_)))
    sys.exit(1 if bad_ else 0)


if __name__ == "__main__":
    main()
