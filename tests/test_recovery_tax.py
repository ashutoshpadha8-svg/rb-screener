"""Recovery, price and funding regressions. Fake HTTP/temp ledgers only.
Run: python3 tests/test_recovery_tax.py
"""
import copy
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tests"))
import test_execution as tv
import journal
import sip
import fusion_backtest as fb
import strategy_lab as lab
from position_sizing import slot_budget, whole_shares, FIXED_SLOT, NAV_DIV_SLOTS

ba, at = tv.ba, tv.at


def position(strategy="Momentum"):
    leg = "momentum_qty" if strategy == "Momentum" else "investing_qty" if strategy == "SIP" else "swing_qty"
    row = dict(symbol="ABC", swing_qty=0, investing_qty=0, momentum_qty=0,
               entry_price=100., entry_date="2026-09-30", strategy=strategy,
               mode="LIVE", product="CNC", order_id="", note="AMO pending",
               shares=10, lev=1.)
    row[leg] = 10
    return row


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = {"read": at.read_split, "write": at.write_split,
                      "sectors": at._sectors, "status": ba.check_order_status,
                      "update": ba.update_intent, "request": ba.requests.request,
                      "split": tv.at.ms.SPLIT_FILE, "log": ba.ORDER_LOG,
                      "dividends": journal.dividends_of}
        self.f = tv.FakeDhan("ok")
        self.s = tv.fresh(self.f)
        ba.ORDER_LOG = str(Path(self.tmp.name) / "orders_log.csv")
        tv.at.ms.SPLIT_FILE = str(Path(self.tmp.name) / "split.csv")
        self.store = {"sp": pd.DataFrame(columns=at.COLUMNS)}
        at.read_split = lambda: self.store["sp"].copy()
        at.write_split = lambda d: self.store.__setitem__("sp", d.copy())
        at._sectors = lambda: {"ABC": "Fin", "NEW": "Other", **{
            "H%02d" % i: "S%d" % i for i in range(19)}}
        journal.dividends_of = lambda sym: []

    def tearDown(self):
        at.read_split, at.write_split, at._sectors = self.saved["read"], self.saved["write"], self.saved["sectors"]
        ba.check_order_status, ba.update_intent = self.saved["status"], self.saved["update"]
        ba.requests.request, ba.ORDER_LOG = self.saved["request"], self.saved["log"]
        tv.at.ms.SPLIT_FILE = self.saved["split"]
        journal.dividends_of = self.saved["dividends"]
        self.tmp.cleanup()

    def send(self, lost=False, strategy="Momentum"):
        self.f.post = "lost_after_accept" if lost else "ok"
        self.f.show = not lost
        row = position(strategy)
        if strategy == "SIP":
            row.update(sip_id="P1", sip_period="2026-09", own=1000.)
        result = at.send_one(self.s, "ABC", 10, "CNC", "BUY", position=row)
        return row, result

    def broker_fill(self, qty=3, avg=101., status="TRADED"):
        self.f.show = True
        for row in self.f.orders.values():
            row.update(orderStatus=status, filledQty=qty, averageTradedPrice=avg)

    def test_metadata_exists_before_post(self):
        fake = self.f
        def request(method, url, **kwargs):
            if method == "POST":
                data = json.loads(ba.load_intents().iloc[0].position_data)
                self.assertEqual(data["strategy"], "Momentum")
                self.assertEqual(data["momentum_qty"], 10)
            return fake(method, url, **kwargs)
        ba.requests.request = request
        self.send()
        self.assertEqual(self.f.posts, 1)

    def test_lost_reply_recovers_completed_position_once(self):
        _, result = self.send(lost=True)
        self.assertEqual(result[2], "UNKNOWN")
        tv.age_ledger(1)
        self.broker_fill()
        at.recover_buys(self.s)
        at.recover_buys(self.s)
        self.assertEqual(len(self.store["sp"]), 1)
        self.assertEqual(self.store["sp"].iloc[0].momentum_qty, 3)
        self.assertEqual(self.store["sp"].iloc[0].entry_price, 101.)
        self.assertEqual(ba.load_intents().iloc[0].position_saved, "1")
        self.assertEqual(self.f.posts, 1)

    def test_lagging_dhan_trades_do_not_price_larger_order_fill(self):
        self.send()
        self.broker_fill(qty=6, avg=0., status="TRADED")
        fake = self.f
        def request(method, url, **kwargs):
            if method == "GET" and "/trades/" in url:
                return tv.Resp(200, [{"tradedQuantity": 3, "tradedPrice": 101.}])
            return fake(method, url, **kwargs)
        ba.requests.request = request
        oid = ba.load_intents().iloc[0].order_id
        status = ba.check_order_status(oid, sess=self.s)
        self.assertEqual(status["filled_qty"], 6)
        self.assertIsNone(status["avg_price"])
        at.recover_buys(self.s)
        row = self.store["sp"].iloc[0]
        self.assertEqual(row.momentum_qty, 6)
        self.assertEqual(row.price_pending, 1)
        self.assertIn("fill price pending", row.note)
        self.broker_fill(qty=6, avg=102., status="TRADED")
        at.sync(self.s)
        row = self.store["sp"].iloc[0]
        self.assertEqual(row.entry_price, 102.)
        self.assertEqual(row.price_pending, 0)

    def test_recovered_position_blocks_same_stock_and_21st(self):
        self.send(lost=True)
        self.broker_fill()
        others = []
        for i in range(19):
            row = position(); row["symbol"] = "H%02d" % i
            others.append(row)
        self.store["sp"] = pd.DataFrame(others)
        at.recover_buys(self.s)
        rows = pd.DataFrame({"Ticker": ["ABC", "NEW"], "act": "BUY",
                             "Strategy Overlap": "Momentum only", "Amount (Rs)": ""})
        new, _ = at.plan(rows, {"ABC": (101., "fake"), "NEW": (100., "fake")}, self.store["sp"], self.s)
        self.assertEqual(new, [])
        self.assertEqual(len(self.store["sp"]), 20)

    def test_crash_before_acceptance_result_is_saved(self):
        self.send()
        tag = ba.load_intents().iloc[0].tag
        ba.update_intent(tag, state="INTENT", order_id="", status="")
        self.broker_fill(qty=0, status="PENDING", avg=0.)
        at.recover_buys(self.s)
        self.assertEqual(len(self.store["sp"]), 1)
        self.assertEqual(self.store["sp"].iloc[0].momentum_qty, 10)  # provisional reservation
        self.assertTrue(ba.ordered_today("ABC", sess=self.s))
        self.assertEqual(self.f.posts, 1)

    def test_failed_split_write_keeps_guard_and_reservation(self):
        self.send(); self.broker_fill()
        def fail(d):
            raise OSError("simulated full disk")
        writer = at.write_split; at.write_split = fail
        with self.assertRaises(OSError):
            at.recover_buys(self.s)
        self.assertNotEqual(ba.load_intents().iloc[0].position_saved, "1")
        self.assertTrue(ba.ordered_today("ABC", sess=self.s))
        self.assertEqual(ba.buy_reservations(self.store["sp"]), ["ABC"])
        at.write_split = writer
        at.recover_buys(self.s)
        self.assertEqual(len(self.store["sp"]), 1)

    def test_crash_after_split_before_marker_does_not_duplicate(self):
        self.send(); self.broker_fill()
        updater = ba.update_intent
        def fail_marker(tag, **kwargs):
            if kwargs.get("position_saved") == "1":
                raise OSError("marker save failed")
            updater(tag, **kwargs)
        ba.update_intent = fail_marker
        with self.assertRaises(OSError):
            at.recover_buys(self.s)
        self.assertEqual(len(self.store["sp"]), 1)
        ba.update_intent = updater
        at.recover_buys(self.s)
        self.assertEqual(len(self.store["sp"]), 1)
        self.assertEqual(ba.load_intents().iloc[0].position_saved, "1")

    def test_legacy_filled_intent_without_strategy_is_not_guessed(self):
        at.send_one(self.s, "ABC", 10, "CNC", "BUY")
        self.broker_fill()
        tv.age_ledger(2)
        at.recover_buys(self.s)
        self.assertEqual(len(self.store["sp"]), 0)
        self.assertTrue(ba.ordered_today("ABC", sess=self.s))
        self.assertEqual(ba.buy_reservations(self.store["sp"]), ["ABC"])

    def test_legacy_done_does_not_release_untracked_fill(self):
        self.send(); self.broker_fill()
        tag = ba.load_intents().iloc[0].tag
        ba.update_intent(tag, state="DONE")
        self.assertTrue(ba.ordered_today("ABC", sess=self.s))
        at.recover_buys(self.s)
        self.assertEqual(len(self.store["sp"]), 1)

    def test_cancelled_partial_recovery_keeps_price_pending(self):
        self.send(); self.broker_fill(avg=None, status="CANCELLED")
        at.recover_buys(self.s)
        row = self.store["sp"].iloc[0]
        self.assertEqual(row.momentum_qty, 3)
        self.assertEqual(row.price_pending, 1)
        self.assertIn("fill price pending", row.note)
        self.broker_fill(avg=101., status="CANCELLED")
        at.sync(self.s)
        row = self.store["sp"].iloc[0]
        self.assertEqual(row.entry_price, 101.)
        self.assertEqual(row.price_pending, 0)
        self.assertNotIn("pending", row.note)

    def test_lagging_quantity_does_not_reverse_confirmed_fills(self):
        row, _ = self.send()
        row["order_id"] = next(iter(self.f.orders.values()))["orderId"]
        self.store["sp"] = pd.DataFrame([row])
        self.broker_fill(status="PENDING")
        at.sync(self.s)
        self.broker_fill(qty=0, avg=0., status="CANCELLED")
        at.sync(self.s)
        self.assertEqual(self.store["sp"].iloc[0].momentum_qty, 3)
        self.assertEqual(self.store["sp"].iloc[0].entry_price, 101.)

    def test_more_fills_without_new_average_retry_price(self):
        row, _ = self.send(); row["order_id"] = next(iter(self.f.orders.values()))["orderId"]
        self.store["sp"] = pd.DataFrame([row])
        self.broker_fill(qty=3, avg=100., status="PENDING"); at.sync(self.s)
        self.broker_fill(qty=6, avg=None); at.sync(self.s)
        self.assertEqual(self.store["sp"].iloc[0].price_pending, 1)
        self.broker_fill(qty=6, avg=102.); at.sync(self.s)
        self.assertEqual(self.store["sp"].iloc[0].entry_price, 102.)
        self.assertEqual(self.store["sp"].iloc[0].momentum_qty, 6)

    def test_delayed_price_reaches_existing_journal_cost_basis(self):
        self.send(strategy="W+TT"); self.broker_fill(avg=None, status="CANCELLED")
        at.recover_buys(self.s)
        j, _ = journal.sync(self.store["sp"], [{"symbol": "ABC", "qty": 3}], {}, {}, quiet=True)
        self.assertEqual(float(j.iloc[0].buy_price), 100.)
        self.broker_fill(avg=101., status="CANCELLED"); at.sync(self.s)
        j, _ = journal.sync(self.store["sp"], [{"symbol": "ABC", "qty": 3}], {}, {}, quiet=True)
        self.assertEqual(float(j.iloc[0].buy_price), 101.)
        self.assertEqual(float(j.iloc[0].qty), 3.)
        self.assertEqual(float(j.iloc[0].buy_fees), round(journal.fees("DHAN", "BUY", 303)[0], 2))

    def test_sip_recovery_log_is_idempotent(self):
        self.send(strategy="SIP"); self.broker_fill(qty=10)
        at.recover_buys(self.s); at.recover_buys(self.s)
        self.assertEqual(len(sip.load_log()), 1)
        self.assertEqual(len(self.store["sp"]), 1)
        self.assertEqual(self.store["sp"].iloc[0].investing_qty, 10)

    def test_already_recorded_then_closed_position_is_not_resurrected(self):
        self.send(); self.broker_fill(); at.recover_buys(self.s)
        self.store["sp"] = self.store["sp"].iloc[:0].copy()
        at.recover_buys(self.s)
        self.assertEqual(len(self.store["sp"]), 0)

    def test_manual_row_cannot_mark_unrelated_intent_as_saved(self):
        self.send(lost=True)
        at._mark_saved([position()])   # no broker order ID
        self.assertNotEqual(ba.load_intents().iloc[0].position_saved, "1")
        self.assertEqual(ba.buy_reservations(self.store["sp"]), ["ABC"])

    def test_legacy_closed_partial_fill_still_blocks(self):
        at.send_one(self.s, "ABC", 10, "CNC", "BUY")
        self.broker_fill(status="CANCELLED")
        tag = ba.load_intents().iloc[0].tag
        ba.update_intent(tag, state="CLOSED", filled_qty="")  # old schema had no fill count
        self.assertTrue(ba.ordered_today("ABC", sess=self.s))
        self.assertEqual(ba.buy_reservations(self.store["sp"]), ["ABC"])

    def test_cancelled_zero_fill_does_not_create_a_position(self):
        self.send(); self.broker_fill(qty=0, avg=0., status="CANCELLED")
        at.recover_buys(self.s)
        self.assertEqual(len(self.store["sp"]), 0)
        self.assertEqual(ba.load_intents().iloc[0].state, "CLOSED")
        self.assertFalse(ba.ordered_today("ABC", sess=self.s))

    def test_stale_average_for_three_cannot_finalize_six_fills(self):
        row, _ = self.send(); row["order_id"] = next(iter(self.f.orders.values()))["orderId"]
        self.store["sp"] = pd.DataFrame([row])
        self.broker_fill(qty=3, avg=100., status="PENDING"); at.sync(self.s)
        self.broker_fill(qty=6, avg=None, status="PENDING"); at.sync(self.s)
        self.broker_fill(qty=0, avg=0., status="CANCELLED"); at.sync(self.s)
        self.assertEqual(self.store["sp"].iloc[0].momentum_qty, 6)
        self.assertEqual(self.store["sp"].iloc[0].price_pending, 1)


class FundingTests(unittest.TestCase):
    def test_tax_preview_is_non_mutating_and_matches_payment(self):
        book = fb.TaxBook(False)
        book.cf_st = 1000.; book.cf_lt = 500.
        book.add(10000., 100); book.add(200000., 400); book.interest = 2000.
        before = copy.deepcopy(book.__dict__)
        due = book.due()
        self.assertEqual(book.__dict__, before)
        self.assertAlmostEqual(book.due(), due)
        self.assertAlmostEqual(book.settle(), due)

    def test_loss_offsets_are_included_in_reserve(self):
        book = fb.TaxBook(False)
        book.add(10000., 100); first = book.due()
        book.add(-5000., 100)
        self.assertAlmostEqual(book.due(), first/2)
        book.add(-5000., 100)
        self.assertEqual(book.due(), 0.)

    def test_live_default_and_research_fixed_budget_are_identical(self):
        self.assertEqual(slot_budget(200000,20), 10000.)
        self.assertEqual(slot_budget(200000,20,FIXED_SLOT,nav=400000), 10000.)
        self.assertEqual(slot_budget(200000,20,NAV_DIV_SLOTS,nav=400000), 20000.)
        self.assertEqual(tv.at.ms.shares_for(10000,333), whole_shares(10000,333))
        with self.assertRaises(ValueError):
            slot_budget(200000,20,NAV_DIV_SLOTS)

    def test_cost_aware_whole_shares_fit_the_budget(self):
        q = whole_shares(10000,333,.003)
        self.assertLessEqual(q*333*1.003,10000)
        self.assertGreater((q+1)*333*1.003,10000)

    def test_nav_engine_funds_tax_without_borrowing(self):
        cal = pd.bdate_range("2020-01-01", "2020-04-30")
        names = ["a","b","c","d"]
        close = pd.DataFrame(100., index=cal, columns=names)
        close.loc["2020-02-01":,["a","b"]] = 200.
        P = {k:close.copy() for k in ("Open","High","Low","Close")}
        S = pd.DataFrame(np.tile([4.,3.,2.,1.], (len(cal),1)), index=cal, columns=names)
        S.loc["2020-01-31":,:] = [1.,2.,4.,3.]
        curve,_ = lab.run_rank(P,S,2,1,buffer=1,tax=True,capital=20000,
                              cash_rate=0.,allocation_mode=NAV_DIV_SLOTS)
        self.assertTrue(np.isfinite(curve).all())
        self.assertGreater(curve.iloc[-1],20000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
