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
    check("bill / funds", mc.classify("Bill for NSE trade 123") ==
          "_trade" and mc.classify("Funds added via UPI") == "_money")
    check("balance rows + dividend not charges",
          mc.classify("CLOSING BALANCE") == "_balance" and
          mc.classify("Dividend Received in Trading Ledger") ==
          "Dividend (income)")
    check("Dhan's real narrations", mc.classify(
        "MTF Interest MTF Interest for Period  24/09/2026 To 30/09/2026 Clt")
        == "MTF interest" and mc.classify("Margin Interest Margin Interest "
                                          "for Period") == "Other interest"
        and mc.classify("DP Transaction Charges Charges for Sell / Pledge / "
                        "Unpledge in your Demat Account") == "Pledge charges")

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

    print("6) v26: Dhan's money from the last interest entry, balance, money")
    led2 = mc.ledger_rows([
        {"narration": "MTF Interest MTF Interest for Period  16/09/2026 To "
         "23/09/2026 Clt", "voucherdate": "Sep 24, 2026", "debit": "791.36",
         "credit": "0"},
        {"narration": "MTF Interest MTF Interest for Period  24/09/2026 To "
         "30/09/2026 Clt", "voucherdate": "Oct 01, 2026", "debit": "653.34",
         "credit": "0"},
        {"narration": "Funds added UPI", "voucherdate": "Sep 02, 2026",
         "debit": "0", "credit": "50000"},
        {"narration": "Funds withdrawn NEFT", "voucherdate": "Sep 05, 2026",
         "debit": "20000", "credit": "0"},
        {"narration": "CLOSING BALANCE", "voucherdate": "Oct 07, 2026",
         "debit": "0", "credit": "10590.43"}])
    fd, per, txt = mc.funded_from_interest(led2)
    want = round(653.34 / 7 * 365 / 0.1249, 2)
    check("funded = 653.34 / 7 days x 365 / 12.49%% = %s" % want,
          fd == want and per == round(653.34 / 7, 2) and
          txt == "2026-09-24 -> 2026-09-30", (fd, per, txt))
    check("closing balance +10,590.43", mc.closing_balance(led2) == 10590.43)
    check("money added 50,000 / withdrawn 20,000",
          mc.money_in_out(led2) == (50000.0, 20000.0))
    check("charges ignore balance + money rows", set(mc.charges(led2)) ==
          {"MTF interest"}, mc.charges(led2))
    check("no interest rows -> None", mc.funded_from_interest(
        mc.ledger_rows(api[3:]))[0] is None)

    print("7) v26: FIFO over MTF trades")
    t2 = [{"symbol": "AAA", "side": "BUY", "qty": 10, "price": 100,
           "date": "2024-05-01", "charges": 5},
          {"symbol": "AAA", "side": "BUY", "qty": 10, "price": 120,
           "date": "2024-06-01", "charges": 5},
          {"symbol": "AAA", "side": "SELL", "qty": 15, "price": 90,
           "date": "2024-07-01", "charges": 7},
          {"symbol": "BBB", "side": "SELL", "qty": 3, "price": 50,
           "date": "2024-07-01", "charges": 1},
          {"symbol": "CCC", "side": "SELL", "qty": 4, "price": 60,
           "date": "2024-08-01", "charges": 1},
          {"symbol": "CCC", "side": "BUY", "qty": 4, "price": 50,
           "date": "2024-08-01", "charges": 1}]
    r = mc.fifo(t2)
    check("bought 2,200 + 200 / sold 1,350 + 150 + 240",
          r["bought"] == 2400 and r["sold"] == 1740, r)
    check("realised AAA 10x(90-100) + 5x(90-120) = -250, CCC same day +40",
          r["realised"] == -250 + 40, r)
    check("open AAA 5 @ 120 since 2024-06-01", r["open"].get("AAA") ==
          {"qty": 5, "avg": 120.0, "first": "2024-06-01"}, r["open"])
    check("BBB sold without a buy -> short list", r["short"] == {"BBB": 3},
          r["short"])
    check("charges summed 20", r["charges"] == 20, r)

    bad = [n for n, ok in RESULTS if not ok]
    print("\n%d / %d passed%s" % (len(RESULTS) - len(bad), len(RESULTS),
                                  "" if not bad else " -- FAILED: " +
                                  "; ".join(bad)))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
