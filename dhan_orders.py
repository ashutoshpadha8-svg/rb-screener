#!/usr/bin/env python3
"""
DHAN ORDER HELPERS  --  used by auto_tracker_update.py
======================================================

Cash market only: productType CNC (delivery), NSE_EQ, BUY. No F&O, no
intraday, no selling from code.

Endpoints (DhanHQ v2 docs, checked 26 Sep 2026):
  POST /v2/orders            place order (afterMarketOrder + amoTime for AMO)
  GET  /v2/orders/{id}       order status
  GET  /v2/trades/{id}       fills (tradedQuantity, tradedPrice)
  GET  /v2/fundlimit         funds ("availabelBalance" -- Dhan's spelling)

Every call returns (ok, data_or_error_text). Nothing here prints the token.
"""

import os
import time
import datetime as dt

import pandas as pd
import requests

import daily_screener as ds

BASE = "https://api.dhan.co/v2"
ORDER_LOG = os.path.join(ds.DATA, "orders_log.csv")


def _headers(tok):
    return {"access-token": tok, "client-id": ds.CLIENT_ID,
            "Content-Type": "application/json", "Accept": "application/json"}


def _call(method, path, tok, body=None, retries=2):
    """HTTP with basic retry on rate limit / network errors."""
    for attempt in range(retries + 1):
        try:
            r = requests.request(method, BASE + path, headers=_headers(tok),
                                 json=body, timeout=30)
        except requests.RequestException as e:
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            return False, "network error: %s" % e
        if r.status_code == 429 and attempt < retries:
            time.sleep(3 * (attempt + 1))              # rate limited
            continue
        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text[:300]}
        if r.status_code in (401, 403):
            return False, ("HTTP %d -- token expired/invalid or Trading API "
                           "not enabled: %s" % (r.status_code, _err(data)))
        if r.status_code >= 400:
            return False, "HTTP %d: %s" % (r.status_code, _err(data))
        if isinstance(data, dict) and (data.get("errorCode") or
                                       data.get("errorType")):
            return False, _err(data)
        return True, data
    return False, "gave up after retries"


def _err(d):
    if isinstance(d, dict):
        return "%s %s %s" % (d.get("errorType", ""), d.get("errorCode", ""),
                             d.get("errorMessage", d.get("raw", "")))
    return str(d)[:300]


def available_funds(tok):
    ok, d = _call("GET", "/fundlimit", tok)
    if not ok:
        return None, d
    val = d.get("availabelBalance", d.get("availableBalance"))
    try:
        return float(val), ""
    except (TypeError, ValueError):
        return None, "fundlimit reply had no balance field"


def place_amo_buy(tok, security_id, qty, symbol, order_type="MARKET",
                  price=0.0, amo_time="OPEN"):
    """CNC delivery BUY as an After Market Order. Returns (ok, orderId or
    error text, status)."""
    body = {"dhanClientId": ds.CLIENT_ID,
            "correlationId": ("RB%s%s" % (dt.date.today().strftime("%y%m%d"),
                                          symbol))[:30],
            "transactionType": "BUY", "exchangeSegment": "NSE_EQ",
            "productType": "CNC", "orderType": order_type, "validity": "DAY",
            "securityId": str(security_id), "quantity": int(qty),
            "disclosedQuantity": 0,
            "price": float(price) if order_type == "LIMIT" else 0.0,
            "triggerPrice": 0.0, "afterMarketOrder": True, "amoTime": amo_time}
    ok, d = _call("POST", "/orders", tok, body)
    if not ok:
        return False, d, "ERROR"
    status = str(d.get("orderStatus", "")).upper()
    oid = str(d.get("orderId", ""))
    if status == "REJECTED" or not oid:
        return False, "order rejected (%s)" % (d.get("omsErrorDescription") or
                                              _err(d)), status or "REJECTED"
    return True, oid, status


def order_status(tok, order_id):
    ok, d = _call("GET", "/orders/%s" % order_id, tok)
    if not ok:
        return None
    if isinstance(d, list):
        d = d[0] if d else {}
    return str(d.get("orderStatus", "")).upper()


def fills(tok, order_id):
    """(quantity, average price) actually traded for an order."""
    ok, d = _call("GET", "/trades/%s" % order_id, tok)
    if not ok:
        return 0, None
    rows = d if isinstance(d, list) else [d]
    q = sum(int(r.get("tradedQuantity") or 0) for r in rows)
    v = sum(int(r.get("tradedQuantity") or 0) * float(r.get("tradedPrice") or 0)
            for r in rows)
    return q, (v / q if q else None)


def log_order(row):
    exists = os.path.exists(ORDER_LOG)
    pd.DataFrame([row]).to_csv(ORDER_LOG, mode="a", header=not exists,
                               index=False)


def ordered_today(symbol):
    """True if a BUY order for this symbol was accepted today already."""
    if not os.path.exists(ORDER_LOG):
        return False
    d = pd.read_csv(ORDER_LOG)
    today = dt.date.today().isoformat()
    return bool(((d["symbol"] == symbol) & (d["date"] == today) &
                 (d["ok"] == True)).any())       # noqa: E712
