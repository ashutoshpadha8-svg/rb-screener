#!/usr/bin/env python3
"""
SIZING A + MERGE CHECKS (30 Sep 2026, after Codex fixes 1-3 were merged into
our v5 code) -- mocks only: no network, no token, NO real order.
Run:  cd ~/RB_Screener && python3 tests/test_sizing_a.py

  1) sizing A: slot = account value / 20 (RB), Amount column still wins
  2) v5 intent ledger (strategy/leg/price/tracked) -> Codex position_data
  3) sync writes a real fill price into an int column (pandas 3 crash)
  4) research backtest default stays NAV/N (all CLAUDE.md numbers)
"""
import os
import sys
import tempfile

import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tests"))
import test_execution as tv                                    # noqa: E402
import momentum_screener as ms                                  # noqa: E402
import strategy_lab as lab                                      # noqa: E402
from position_sizing import NAV_DIV_SLOTS                       # noqa: E402

ba, at = tv.ba, tv.at
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          "" if cond else "  <- " + str(detail)))


def main():
    print("1) sizing A: slot = account value / 20")
    at.ba.ordered_today = lambda *a, **k: False
    at._sectors = lambda: {}
    rows = pd.DataFrame([{"Ticker": "XYZ", "act": "BUY",
                          "Strategy Overlap": "W+TT only", "Amount (Rs)": ""}])
    empty = pd.DataFrame(columns=at.COLUMNS)
    new, _ = at.plan(rows, {"XYZ": (100.0, "x")}, empty,
                     slot=ms.slot_for(350000))
    check("Rs 3.5 L account -> Rs 17,500 slot -> 175 shares @ 100",
          len(new) == 1 and new[0]["shares"] == 175, new)
    new, _ = at.plan(rows, {"XYZ": (100.0, "x")}, empty)
    check("no account value -> Rs 10,000 default -> 100 shares",
          len(new) == 1 and new[0]["shares"] == 100, new)
    check("slot_for(None) = Rs 10,000", ms.slot_for(None) == 10000.0)
    rows2 = rows.assign(**{"Amount (Rs)": "5000"})
    new, _ = at.plan(rows2, {"XYZ": (100.0, "x")}, empty,
                     slot=ms.slot_for(350000))
    check("Amount column still wins (Rs 5,000 -> 50)", new and
          new[0]["shares"] == 50, new)

    print("2) v5 intent ledger is read into the new form")
    d = tempfile.mkdtemp()
    ba.ORDER_LOG = os.path.join(d, "orders_log.csv")
    pd.DataFrame([
        {"tag": "RB260930BAAAAAAAA", "created": "x", "date": "2026-09-30",
         "symbol": "ABC", "side": "BUY", "qty": "7", "product": "CNC",
         "state": "UNKNOWN", "order_id": "", "status": "", "note": "",
         "strategy": "Momentum", "leg": "momentum_qty", "price": "101.5",
         "tracked": ""},
        {"tag": "RB260930BBBBBBBBB", "created": "x", "date": "2026-09-30",
         "symbol": "DEF", "side": "BUY", "qty": "3", "product": "CNC",
         "state": "ACCEPTED", "order_id": "55", "status": "", "note": "",
         "strategy": "W+TT", "leg": "swing_qty", "price": "50",
         "tracked": "1"}]).to_csv(ba._intents_file(), index=False)
    li = ba.load_intents().set_index("symbol")
    import json
    pdata = json.loads(li.loc["ABC", "position_data"] or "{}")
    check("v5 BUY -> position_data (Momentum, momentum_qty 7, price 101.5)",
          pdata.get("strategy") == "Momentum" and
          pdata.get("momentum_qty") == 7 and pdata.get("entry_price") == 101.5,
          pdata)
    check("v5 tracked=1 -> position_saved=1",
          li.loc["DEF", "position_saved"] == "1")
    check("untracked v5 momentum BUY reserves a slot",
          ba.buy_reservations(pd.DataFrame(columns=at.COLUMNS)) == ["ABC"])

    print("3) sync: fill price into a column read as int (pandas 3)")
    store = {"sp": pd.DataFrame([{
        "symbol": "ABC", "swing_qty": 10, "investing_qty": 0,
        "momentum_qty": 0, "entry_price": 100, "entry_date": "2026-09-30",
        "strategy": "W+TT", "mode": "LIVE", "product": "CNC",
        "order_id": "7770", "note": "AMO pending", "intent_tag": "",
        "ordered_qty": 10, "filled_qty_confirmed": 0, "fill_avg_price": 0,
        "fill_avg_qty": 0, "price_pending": 1}])}
    at.read_split = lambda: store["sp"].copy()
    at.write_split = lambda x: store.__setitem__("sp", x.copy())
    at.recover_buys = lambda sess, sp=None: at.read_split()
    at._mark_saved = lambda rows: None
    at.ba.check_order_status = lambda *a, **k: {
        "status": "TRADED", "filled_qty": 10, "avg_price": 101.5, "raw": "T"}
    try:
        at.sync(None)
        r = store["sp"].iloc[0]
        check("sync stores 10 @ 101.5", float(r["swing_qty"]) == 10 and
              abs(float(r["entry_price"]) - 101.5) < 1e-9, r.to_dict())
    except Exception as e:
        check("sync stores 10 @ 101.5", False, "%s: %s" % (type(e).__name__, e))

    print("4) research backtest default = NAV / N")
    import inspect
    dflt = inspect.signature(lab.run_rank).parameters["allocation_mode"].default
    check("strategy_lab.run_rank allocation_mode default = NAV/N",
          dflt == NAV_DIV_SLOTS, dflt)

    bad = [n for n, ok in RESULTS if not ok]
    print("\n%d / %d passed%s" % (len(RESULTS) - len(bad), len(RESULTS),
                                  "" if not bad else " -- FAILED: " +
                                  "; ".join(bad)))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
