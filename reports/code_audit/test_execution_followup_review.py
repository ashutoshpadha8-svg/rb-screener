"""Follow-up regressions; fake HTTP and in-memory positions only. No real orders.

These are additional expectations, separate from the six original regressions.
Exit 1 means at least one expectation is not yet satisfied.
"""
import importlib.util
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "supplied_execution_tests", ROOT / "tests/test_execution.py")
tv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tv)
ba, at = tv.ba, tv.at
RESULTS = []


def check(name, condition, detail):
    RESULTS.append(bool(condition))
    print(("PASS " if condition else "FAIL ") + name + " | " + str(detail),
          flush=True)


def holdings(names):
    cols = ["symbol", "swing_qty", "investing_qty", "momentum_qty",
            "entry_price", "entry_date", "strategy", "mode", "product",
            "order_id", "note"]
    return pd.DataFrame([
        dict(symbol=s, swing_qty=0, investing_qty=0, momentum_qty=10,
             entry_price=100., entry_date="2026-09-01", strategy="Momentum",
             mode="LIVE", product="CNC", order_id="", note="")
        for s in names], columns=cols)


def actions(symbol):
    return pd.DataFrame([dict(Ticker=symbol, act="BUY",
                             **{"Strategy Overlap": "Momentum only",
                                "Amount (Rs)": ""})])


def main():
    # Lost reply means place_orders would not append an accepted split row.
    # On the next date it is discovered as fully executed, not still pending.
    f = tv.FakeDhan("lost_after_accept", show=False)
    sess = tv.fresh(f)
    assert tv.run(sess) == "UNKNOWN"
    tv.age_ledger(1)
    f.show = True
    for order in f.orders.values():
        order.update(orderStatus="TRADED", filledQty=1,
                     averageTradedPrice=101.)
    old_sectors = at._sectors
    at._sectors = lambda: {s: "S" + str(i) for i, s in enumerate(
        ["ABC", "NEW"] + ["H%02d" % i for i in range(19)])}
    proposed, _ = at.plan(actions("ABC"), {"ABC": (100., "fake")},
                          holdings([]), sess=sess)
    check("Recovered executed BUY must be tracked before another ABC BUY",
          len(proposed) == 0,
          dict(original_intent_state=ba.load_intents().iloc[0]["state"],
               original_broker_fill=1, tracked_ABC_rows=0,
               proposed_ABC_BUYs=len(proposed)))
    # Actual positions: 19 tracked names plus recovered, untracked ABC.
    proposed, _ = at.plan(actions("NEW"), {"NEW": (100., "fake")},
                          holdings(["H%02d" % i for i in range(19)]),
                          sess=sess)
    check("Recovered untracked BUY must reserve its portfolio slot",
          len(proposed) == 0,
          dict(actual_positions=20, proposed_BUYs=len(proposed),
               possible_total=20 + len(proposed)))
    at._sectors = old_sectors

    # A final partial fill arrives with a known quantity but no average yet.
    # Keep quantity immediately, then replace the provisional price later.
    sess = tv.fresh(tv.FakeDhan("ok"))
    store = {"sp": pd.DataFrame([dict(
        symbol="ABC", swing_qty=10, investing_qty=0, momentum_qty=0,
        entry_price=100., entry_date="2026-09-30", strategy="W+TT",
        mode="LIVE", product="CNC", order_id="5501", note="AMO pending")])}
    seq = iter([dict(status="CANCELLED", raw="CANCELLED", filled_qty=3,
                     avg_price=None),
                dict(status="CANCELLED", raw="CANCELLED", filled_qty=3,
                     avg_price=101.)])
    old_read, old_write = at.read_split, at.write_split
    old_status = ba.check_order_status
    at.read_split = lambda: store["sp"].copy()
    at.write_split = lambda frame: store.__setitem__("sp", frame.copy())
    ba.check_order_status = lambda *args, **kwargs: next(seq)
    at.sync(sess)
    at.sync(sess)
    row = store["sp"].iloc[0]
    check("Final fill without a price must accept the later real price",
          row["swing_qty"] == 3 and row["entry_price"] == 101.,
          dict(stored_qty=int(row["swing_qty"]),
               stored_price=float(row["entry_price"]), expected_price=101.,
               note=row["note"]))
    at.read_split, at.write_split = old_read, old_write
    ba.check_order_status = old_status
    print("\n%d/%d follow-up expectations passed" %
          (sum(RESULTS), len(RESULTS)), flush=True)
    sys.exit(0 if all(RESULTS) else 1)


if __name__ == "__main__":
    main()
