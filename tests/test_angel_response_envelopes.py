"""Actual HTTP envelope fixtures: only successful Angel empties are empty."""
import contextlib
import io
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import broker_api as ba
POS='/rest/secure/angelbroking/order/v1/getPosition'
BOOK='/rest/secure/angelbroking/order/v1/getOrderBook'
HOLD='/rest/secure/angelbroking/portfolio/v1/getHolding'

class Response:
    status_code=200
    text='fixture'
    headers={}
    def __init__(self,payload,status=200):self.payload=payload;self.status_code=status
    def json(self):return self.payload

class AngelEnvelopeTests(unittest.TestCase):
    def call(self,payload,path=POS,status=200,once=False,method='GET'):
        sess=NS(broker='ANGEL',label='Angel fixture',headers=lambda:{})
        with patch.object(ba.requests,'request',return_value=Response(payload,status)),patch.object(ba,'_throttle'):
            return ba._call(sess,method,path,once=once)

    def test_successful_empty_positions_and_orders(self):
        for path in (POS,BOOK):
            self.assertEqual(self.call(dict(status=True,errorcode='',data=None),path),[])

    def test_successful_populated_list_preserved(self):
        data=[dict(tradingsymbol='ABC-EQ',netqty='5')]
        self.assertEqual(self.call(dict(status=True,errorcode='',data=data)),data)

    def test_missing_status_never_empty(self):
        for payload in ({},{'data':None},{'data':[],'errorcode':''}):
            with self.assertRaises(ba.BrokerError):self.call(payload)

    def test_missing_data_never_empty(self):
        with self.assertRaises(ba.BrokerError):self.call(dict(status=True,errorcode=''))

    def test_false_and_string_status_never_empty(self):
        for value in (False,None,'true',1):
            with self.assertRaises(ba.BrokerError):self.call(dict(status=value,data=None))

    def test_success_with_errorcode_not_empty(self):
        with self.assertRaises(ba.BrokerError):self.call(dict(status=True,data=None,errorcode='AB9999'))

    def test_auth_and_server_errors_not_empty(self):
        for status in (401,403,500):
            with self.assertRaises(ba.BrokerError):self.call(dict(status=True,errorcode='',data=None),status=status)
        with self.assertRaises(ba.AuthError):self.call(dict(status=False,errorcode='AG8001',data=None))

    def test_holdings_null_still_unknown(self):
        payload=dict(status=True,errorcode='',data=None)
        sess=NS(broker='ANGEL',label='fixture',headers=lambda:{})
        with patch.object(ba.requests,'request',return_value=Response(payload)),patch.object(ba,'_throttle'):
            with self.assertRaises(ba.BrokerError):ba.holdings(sess)

    def test_dhan_null_positions_not_empty(self):
        with patch.object(ba,'_call',side_effect=[[dict(tradingSymbol='ABC',totalQty=5,availableQty=5)],None]):
            with self.assertRaises(ba.BrokerError):ba.holdings(NS(broker='DHAN'))

    def test_positions_null_keeps_delivery_holdings(self):
        values=[Response(dict(status=True,errorcode='',data=[dict(tradingsymbol='ABC-EQ',quantity=5,product='DELIVERY')])),Response(dict(status=True,errorcode='',data=None))]
        sess=NS(broker='ANGEL',label='fixture',headers=lambda:{})
        with patch.object(ba.requests,'request',side_effect=values),patch.object(ba,'_throttle'):
            hold=ba.holdings(sess)
        self.assertEqual(hold[0]['qty'],5);self.assertEqual(hold[0]['sellable_by_product'],{'CNC':5})

    def test_empty_order_book_is_no_pending(self):
        sess=NS(broker='ANGEL',label='fixture',headers=lambda:{})
        with patch.object(ba.requests,'request',return_value=Response(dict(status=True,errorcode='',data=None))),patch.object(ba,'_throttle'),patch.object(ba,'symbol_map',return_value={}):
            self.assertEqual(ba.pending_orders(sess),set())

    def test_missing_order_status_stays_unknown(self):
        sess=NS(broker='ANGEL',label='fixture',headers=lambda:{})
        with patch.object(ba.requests,'request',return_value=Response(dict(status=True,errorcode='',data=None))),patch.object(ba,'_throttle'):
            status=ba.check_order_status('fake',sess=sess)
            self.assertIsNone(status['status'])
            self.assertEqual(ba.find_order_by_tag(sess,'fake'),(False,'',''))
        # The durable intent remains unresolved; absence in book proves no fill.

    def test_ambiguous_order_envelope_unknown_not_rejected(self):
        for payload in ({'data':None},{'status':True}):
            with self.assertRaisesRegex(ba.BrokerError,'ORDER STATUS UNKNOWN'):
                self.call(payload,path='/rest/secure/angelbroking/order/v1/placeOrder',once=True,method='POST')

    def test_null_trade_book_no_sales_not_fake_sales(self):
        sess=NS(broker='ANGEL',label='fixture',headers=lambda:{})
        with patch.object(ba.requests,'request',return_value=Response(dict(status=True,errorcode='',data=None))),patch.object(ba,'_throttle'),patch.object(ba,'symbol_map',return_value={}):
            self.assertEqual(ba.trades(sess,'2026-10-06','2026-10-06'),[])

if __name__=='__main__':unittest.main()
