#!/usr/bin/env python3
"""
MTF CHECK (7 Oct 2026, RB) -- mocked data only: no network, no token,
NO order.  Run: python3 tests/test_mtf_check.py
"""
import datetime as dt
import os
import sys
import tempfile

import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import mtf_check as mc                                          # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          "" if cond else "  <- " + str(detail)))


def main():
    print("1) ledger narrations -> buckets")
    check("MTF interest", mc.classify("MTF Interest charged 01-Sep") ==
          "MTF interest")
    check("DPC = other interest", mc.classify("DPC charges") ==
          "Other interest")
    check("pledge", mc.classify("Pledge creation charges") ==
          "Pledge charges")
    check("DP", mc.classify("DP Charges for sale of XYZ") == "DP charges")
    check("bill / funds out", mc.classify("Bill for NSE trade 123") ==
          "_trade_or_money" and mc.classify("Funds added via UPI") ==
          "_trade_or_money")

    print("2) Dhan API rows -> charges (reversals subtracted)")
    api = [{"narration": "MTF Interest", "voucherdate": "Sep 01, 2026",
            "debit": "120.50", "credit": "0.00"},
           {"narration": "MTF Interest", "voucherdate": "Oct 01, 2026",
            "debit": "130.00", "credit": "0.00"},
           {"narration": "MTF Interest reversal", "voucherdate":
            "Oct 02, 2026", "debit": "0.00", "credit": "10.00"},
           {"narration": "Bill for trade", "voucherdate": "Sep 01, 2026",
            "debit": "50,000.00", "credit": "0.00"},
           {"narration": "DP Charges", "voucherdate": "Sep 03, 2026",
            "debit": "14.75", "credit": "0"}]
    led = mc.ledger_rows(api)
    ch = mc.charges(led)
    check("MTF interest 120.50 + 130 - 10 = 240.50 (3 rows)",
          ch.get("MTF interest") == (240.5, 3), ch)
    check("DP 14.75, bill left out", ch.get("DP charges") == (14.75, 1)
          and "_trade_or_money" not in ch, ch)
    check("dates parsed", led["date"].iloc[0] == dt.date(2026, 9, 1),
          led["date"].tolist())
    check("empty ledger -> no charges", mc.charges(mc.ledger_rows([])) == {})

    print("3) downloaded ledger file with title rows")
    d = tempfile.mkdtemp()
    f = os.path.join(d, "ledger.xlsx")
    pd.DataFrame([["Ledger statement", None, None, None],
                  ["Client X", None, None, None],
                  ["Date", "Narration", "Debit", "Credit"],
                  ["2026-09-01", "MTF Int. for Aug", 99.0, 0],
                  ["2026-09-02", "Funds withdrawn", 5000, 0]]).to_excel(
        f, index=False, header=False)
    ch2 = mc.charges(mc.read_ledger_file(f))
    check("file: header found, MTF Int. = 99", ch2.get("MTF interest") ==
          (99.0, 1), ch2)

    print("4) held since: FIFO over the qty still held")
    tr = [{"symbol": "AAA", "side": "BUY", "qty": 10, "date": "2025-06-01"},
          {"symbol": "AAA", "side": "BUY", "qty": 10, "date": "2025-09-01"},
          {"symbol": "AAA", "side": "SELL", "qty": 10, "date": "2025-12-01"},
          {"symbol": "BBB", "side": "BUY", "qty": 5, "date": "2026-01-01"}]
    check("AAA 10 held -> since the 2nd buy 2025-09-01",
          mc.held_since(tr, "AAA", 10) == "2025-09-01")
    check("BBB 8 held but history only 5 -> None (bought earlier)",
          mc.held_since(tr, "BBB", 8) is None)
    check("no trades -> None", mc.held_since([], "CCC", 1) is None)

    print("5) per-position maths")
    tab = mc.analyse([{"symbol": "AAA", "qty": 10, "avg": 1000.0},
                      {"symbol": "BBB", "qty": 8, "avg": 100.0}],
                     {"AAA": 900.0}, tr, dt.date(2026, 9, 1))
    a = tab.set_index("Symbol").loc["AAA"]
    days = (dt.date(2026, 9, 1) - dt.date(2025, 9, 1)).days
    want = round(10000 * 0.75 * 0.1249 * days / 365, 2)
    check("AAA P&L -1000 (-10%)", a["P&L (Rs)"] == -1000 and
          a["P&L %"] == -10.0, a)
    check("AAA interest est = 10000 x 75%% x 12.49%% x %d/365 = %s"
          % (days, want), a["Interest est. (Rs)"] == want, a)
    check("net = P&L - interest - sell cost", abs(
        a["Net after int+sell (Rs)"] - (-1000 - want -
                                        a["Sell cost today (Rs)"])) < 0.02, a)
    b = tab.set_index("Symbol").loc["BBB"]
    check("BBB no LTP / no date -> blanks, not 0", pd.isna(b["P&L (Rs)"])
          and pd.isna(b["Interest est. (Rs)"]) and
          b["Held since (est.)"] == "?", b)
    check("rs()", mc.rs(-1234.4) == "-Rs 1,234" and mc.rs(None) == "-")

    bad = [n for n, ok in RESULTS if not ok]
    print("\n%d / %d passed%s" % (len(RESULTS) - len(bad), len(RESULTS),
                                  "" if not bad else " -- FAILED: " +
                                  "; ".join(bad)))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
