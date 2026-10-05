#!/usr/bin/env python3
"""
BUY PLANNER + CAP MIX TESTS (5 Oct 2026) -- temp files / mocks only: no
network, no token, NO order.
Run:  cd ~/RB_Screener && python3 tests/test_planner.py
"""
import os
import sys
import tempfile

import pandas as pd
from openpyxl import Workbook

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import buy_planner as bp                                        # noqa: E402
import momentum_screener as ms                                  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          "" if cond else "  <- " + str(detail)))


SAMPLE = [("STLTECH", "M", 955.4, True, None),
          ("CUPID", "M", 312.5, True, None),
          ("WELCORP", "M", 2605.8, True, None),
          ("HFCL", "M", 238.4, True, None),
          ("INFY", "L", 1500.0, True, 2),
          ("LAURUSLABS", "L", 1980.0, True, None),
          ("SIGMAADV", "S", 1076.9, True, None),
          ("SHILPAMED", "S", 1047.2, True, None),
          ("KIRLOSENG", "S", 2304.2, False, None),
          ("DIVISLAB", "L", 9291.5, False, None)]


def rows(sample=SAMPLE):
    return [{"symbol": s, "cls": c, "price": p, "pick": k, "qty_you": q,
             "why": "Momentum #1"} for s, c, p, k, q in sample]


def main():
    print("1) distribute = the preview numbers")
    out, sm = bp.distribute(rows(), 30000)
    q = {r["symbol"]: r["final"] for r in out}
    check("INFY fixed at 2 (Rs 3,000), rest Rs 27,000", sm["fixed"] == 3000
          and sm["auto_pool"] == 27000, sm)
    check("Mid 60 / Large 25 / Small 15 of 27,000", [round(sm["eff"][c], 2)
                                                     for c in "MLS"] ==
          [0.6, 0.25, 0.15])
    check("final qty", q == {"STLTECH": 5, "CUPID": 13, "WELCORP": 2,
                             "HFCL": 17, "INFY": 2, "LAURUSLABS": 3,
                             "SIGMAADV": 1, "SHILPAMED": 1, "KIRLOSENG": 0,
                             "DIVISLAB": 0}, q)
    check("total 29,168 / bacha 832", round(sm["total"]) == 29168 and
          round(sm["left"]) == 832, sm)
    check("never over budget", sm["total"] <= 30000)

    print("2) changing one qty re-splits the rest")
    r2 = rows()
    r2[0]["qty_you"] = 1                      # STLTECH only 1
    out2, sm2 = bp.distribute(r2, 30000)
    q2 = {r["symbol"]: r["final"] for r in out2}
    check("STLTECH 1, others get more", q2["STLTECH"] == 1 and
          q2["CUPID"] >= q["CUPID"] and q2["HFCL"] >= q["HFCL"], q2)
    check("still within budget", sm2["total"] <= 30000)

    print("3) a class with no YES gives its share to the top class present")
    r3 = [r for r in rows() if r["cls"] != "M"]
    _, sm3 = bp.distribute(r3, 30000)
    check("no Mid -> Large gets 60+25 = 85%", round(sm3["eff"]["L"], 2) ==
          0.85 and round(sm3["eff"]["S"], 2) == 0.15, sm3["eff"])
    r4 = rows() + [{"symbol": "ODD", "cls": "?", "price": 10.0,
                    "pick": True, "qty_you": None}]
    out4, _ = bp.distribute(r4, 30000)
    odd = [r for r in out4 if r["symbol"] == "ODD"][0]
    check("unknown class gets 0 (no +1 either)", odd["final"] == 0, odd)
    _, sm5 = bp.distribute(rows(), None)
    check("no budget -> only your own Qty rows (INFY 2 = 3,000)",
          sm5["total"] == 3000, sm5)
    r6 = rows()
    r6[4]["qty_you"] = 30                     # INFY 30 x 1500 > budget
    _, sm6 = bp.distribute(r6, 30000)
    check("fixed qty above budget -> auto rows get 0, total = fixed",
          sm6["auto_pool"] == 0 and sm6["total"] == 45000, sm6)

    print("4) sheet: write -> read back -> rbtrack rows")
    d = tempfile.mkdtemp()
    path = os.path.join(d, "Portfolio_TEST.xlsx")
    wb = Workbook()
    wb.active.title = "Dashboard"
    sl = [{"symbol": s, "why": "Momentum #%d" % (i + 1), "overlap": "",
           "mom_rank": i + 1, "rs_rank": None, "cls": c, "price": p}
          for i, (s, c, p, k, qq) in enumerate(SAMPLE)]
    picks = {s: ("YES" if k else "NO", qq) for s, c, p, k, qq in SAMPLE}
    bp.write_sheet(wb, {"cash": 50000, "hold_value": 35591,
                        "hold_cost": 47601, "realised": -1200},
                   sl, {"money_added": 100000, "budget": 30000,
                        "shares": None}, picks, "TEST", gold={"STLTECH"})
    wb.save(path)
    inp, back = bp.read_sheet(path)
    check("inputs read back", inp["budget"] == 30000 and
          inp["money_added"] == 100000 and
          round(inp["shares"]["M"], 2) == 0.6, inp)
    check("rows + picks read back", [(r["symbol"], r["pick"], r["qty_you"])
                                     for r in back][:5] ==
          [("STLTECH", True, None), ("CUPID", True, None),
           ("WELCORP", True, None), ("HFCL", True, None),
           ("INFY", True, 2)], back[:5])
    outb, _ = bp.distribute(back, inp["budget"], inp["shares"])
    check("same qty from the sheet's inputs", {r["symbol"]: r["final"]
                                               for r in outb} == q)
    try:
        from pycel import ExcelCompiler
        x = ExcelCompiler(filename=path)
        sheet = {x.evaluate("%s!B%d" % (bp.SHEET, r)):
                 x.evaluate("%s!L%d" % (bp.SHEET, r))
                 for r in range(bp.R0, bp.R0 + len(SAMPLE))}
        check("Excel formulas give the SAME final qty as Python",
              sheet == q, sheet)
        check("Excel bacha = Python bacha", round(x.evaluate(
            "%s!M%d" % (bp.SHEET, bp.R0 + bp.NROWS + 1))) == 832)
    except ImportError:
        print("  (pycel not installed -- Excel formula check skipped)")
    import auto_tracker_update as at
    pr, _ = at.planner_rows(path)
    check("rbtrack planner rows: YES with qty only, act BUY",
          set(pr["Ticker"]) == {"STLTECH", "CUPID", "WELCORP", "HFCL",
                                "INFY", "LAURUSLABS", "SIGMAADV",
                                "SHILPAMED"} and (pr["act"] == "BUY").all())
    at.ba.ordered_today = lambda *a, **k: False
    at._sectors = lambda: {}
    at._mom_book = lambda sp, mode, sess: []
    empty = pd.DataFrame(columns=at.COLUMNS)
    px = {s: (p * 1.01, "live") for s, c, p, k, qq in SAMPLE}
    new, skip = at.plan(pr, px, empty, slot=10000)
    got = {x["symbol"]: x["shares"] for x in new}
    check("plan() sends exactly the planner qty (not slot / price)",
          got == {k: v for k, v in q.items() if v}, (got, skip))

    print("5) cap mix in the momentum selection (fill_slots)")
    cands = ([("M%d" % i, "sec%d" % i, "M") for i in range(3)] +
             [("L%d" % i, "secL%d" % i, "L") for i in range(10)] +
             [("S%d" % i, "secS%d" % i, "S") for i in range(10)])
    cands.sort(key=lambda x: x[0][1:])       # mixed rank order
    picked, _ = ms.fill_slots(cands, 20)
    n = pd.Series([c for s, _, c in cands if s in picked]).value_counts()
    check("only 3 MID exist -> 3 M, LARGE takes the rest first",
          (n.get("M"), n.get("L"), n.get("S")) == (3, 10, 7), dict(n))
    many = [("M%02d" % i, "m%d" % i, "M") for i in range(30)] + \
        [("L%02d" % i, "l%d" % i, "L") for i in range(30)] + \
        [("S%02d" % i, "s%d" % i, "S") for i in range(30)]
    picked, _ = ms.fill_slots(many, 20)
    n = pd.Series([s[0] for s in picked]).value_counts()
    check("plenty of each -> 12 / 5 / 3", (n.get("M"), n.get("L"),
                                           n.get("S")) == (12, 5, 3), dict(n))
    picked, _ = ms.fill_slots(many, 5, cls_count={"M": 12, "L": 2})
    n = pd.Series([s[0] for s in picked]).value_counts()
    check("held 12 M + 2 L, 5 free -> 3 L + 2 S", (n.get("L"), n.get("S"))
          == (3, 2), dict(n))
    sec = [("A%d" % i, "SAME", "M") for i in range(8)] + \
        [("B%d" % i, "b%d" % i, "M") for i in range(20)]
    picked, sk = ms.fill_slots(sec, 20)
    check("sector cap 4 still applies", sum(p.startswith("A")
                                            for p in picked) == 4 and sk)
    picked_live, _ = ms.fill_slots(many, 20)
    check("live fill_slots = backtest targets (12/5/3 from the same list)",
          pd.Series([s[0] for s in picked_live]).value_counts().to_dict() ==
          {"M": 12, "L": 5, "S": 3})

    bad = [n for n, ok in RESULTS if not ok]
    print("\n%d / %d passed%s" % (len(RESULTS) - len(bad), len(RESULTS),
                                  "" if not bad else " -- FAILED: " +
                                  "; ".join(bad)))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
