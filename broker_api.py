#!/usr/bin/env python3
"""
BROKER API  --  one adapter for Dhan, Angel One (SmartAPI), Zerodha (Kite)
=========================================================================

Every live script talks to a broker ONLY through this file. The active
broker / client / token come from account.py (token.txt), so the
scripts never know which broker is behind them.

STATUS (be honest about it):
  DHAN     prices + history + holdings: in daily use.  AMO orders: code
           written from the v2 docs, NOT yet used on a real order.
  ANGEL    written from the SmartAPI docs, NEVER run against the real API.
  ZERODHA  written from the Kite Connect v3 docs, NEVER run against the
           real API. Kite historical candles need the paid add-on; without
           it the gap-fill is skipped (free source + live price only).
  -> first real use of ANY broker: ONE row, ONE share, then check the
     broker's order book.

PUBLIC FUNCTIONS
  get_live_price(symbol, broker=None, token=None, sess=None)   -> float|None
  live_prices(sess, symbols)                                    -> {SYM: ltp}
  daily_bars(sess, symbol, frm, to)                             -> DataFrame
  holdings(sess)                                  -> [{symbol, qty, avg_price}]
  available_funds(sess)                           -> (rupees|None, error)
  place_amo_order(symbol, quantity, is_mtf, broker=None, token=None,  (side BUY/SELL)
                  sess=None, order_type="MARKET", price=0.0)
                                                  -> (ok, order_id|error, status)
  check_order_status(order_id, broker=None, token=None, sess=None)
                          -> {"status", "filled_qty", "avg_price", "raw"}
  verify_identity(sess)   -> (ok, message)   (orders are refused if not ok)
  refresh(sess, frames, bm, want, warns)  gap-fill + live prices for screens

CREDENTIALS (Angel / Zerodha only; Dhan needs just the token)
  Either as extra lines in token.txt ("API Key:", "MPIN:",
  "TOTP Secret:", "API Secret:") or in the file below; the txt wins.
  accounts/<BROKER>_<CLIENT_ID>/credentials.json -- created as a template
  the first time you activate such an account. Never printed, never in git.
    ANGEL:   {"api_key": "...", "mpin": "...", "totp_secret": "..."}
             Token line in token.txt: paste a jwtToken, OR write AUTO
             and the script logs in itself (client code + MPIN + TOTP).
    ZERODHA: {"api_key": "...", "api_secret": "..."}
             Daily: open the login URL (python3 broker_api.py zerodha-url),
             log in, copy request_token from the redirect URL, then
             python3 broker_api.py zerodha-login REQUEST_TOKEN
             -> writes the access token into token.txt for you.

COMMAND LINE
  python3 broker_api.py check      who am I + funds + one live price (no orders)
  python3 broker_api.py zerodha-url
  python3 broker_api.py zerodha-login REQUEST_TOKEN
"""

import os
import math
import re
import sys
import json
import time
import hmac
import base64
import struct
import hashlib
import datetime as dt

import pandas as pd
import requests

import daily_screener as ds

BROKERS = ("DHAN", "ANGEL", "ZERODHA")
LABEL = {"DHAN": "Dhan", "ANGEL": "Angel One", "ZERODHA": "Zerodha"}
UNTESTED = {"ANGEL", "ZERODHA"}
_ALIASES = {"DHAN": "DHAN", "ANGEL": "ANGEL", "ANGELONE": "ANGEL",
            "ANGELBROKING": "ANGEL", "SMARTAPI": "ANGEL",
            "ZERODHA": "ZERODHA", "KITE": "ZERODHA"}
INDEX = "NIFTY 50"                     # benchmark key used by the screens
ORDER_LOG = os.path.join(ds.DATA, "orders_log.csv")   # routed per account

DHAN_BASE = "https://api.dhan.co/v2"
DHAN_SCRIP_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
DHAN_SCRIP_FILE = os.path.join(ds.DATA, "_dhan_scrip_master.csv")
ANGEL_BASE = "https://apiconnect.angelone.in"
ANGEL_SCRIP_URL = ("https://margincalculator.angelbroking.com/OpenAPI_File/"
                   "files/OpenAPIScripMaster.json")
ANGEL_SCRIP_FILE = os.path.join(ds.DATA, "_angel_scrip_master.json")
KITE_BASE = "https://api.kite.trade"
KITE_LOGIN = "https://kite.zerodha.com/connect/login?v=3&api_key=%s"
KITE_SCRIP_FILE = os.path.join(ds.DATA, "_kite_instruments_nse.csv")

CRED_TEMPLATE = {
    "ANGEL": {"api_key": "", "mpin": "", "totp_secret": "",
              "_help": "SmartAPI app key; your 4-digit MPIN; the TOTP secret "
                       "shown when you enable TOTP (base32 text, not the "
                       "6-digit code). Keep this file private."},
    "ZERODHA": {"api_key": "", "api_secret": "",
                "_help": "From developers.kite.trade (Kite Connect app). "
                         "Keep this file private."},
}


class BrokerError(Exception):
    pass


class AuthError(BrokerError):
    """Token rejected / expired / API access not enabled."""


def norm_broker(text):
    key = re.sub(r"[^A-Z]", "", str(text or "").upper())
    return _ALIASES.get(key, "")


# ================================================================== tokens
def jwt_payload(tok):
    try:
        part = str(tok).replace("Bearer ", "").split(".")[1]
        part += "=" * (-len(part) % 4)
        d = json.loads(base64.urlsafe_b64decode(part))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def dhan_client_id(tok):
    return str(jwt_payload(tok).get("dhanClientId") or "")


def token_expiry(tok):
    exp = jwt_payload(tok).get("exp")
    try:
        return dt.datetime.fromtimestamp(int(exp), ds.IST) if exp else None
    except (TypeError, ValueError):
        return None


def looks_like_jwt(v):
    v = str(v).replace("Bearer ", "")
    return v.count(".") == 2 and len(v) > 40 and " " not in v


def totp_now(secret, t=None, step=30, digits=6):
    """RFC 6238 TOTP (what Google Authenticator shows), stdlib only."""
    s = re.sub(r"\s", "", secret).upper()
    key = base64.b32decode(s + "=" * (-len(s) % 8))
    counter = int((time.time() if t is None else t) // step)
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    code = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** digits
    return str(code).zfill(digits)


# ================================================================== session
class Session(object):
    """Broker + client + token (+ credentials file for Angel/Zerodha)."""

    def __init__(self, broker, token, client_id="", creds_file=None,
                 extra=None):
        self.broker = norm_broker(broker)
        if not self.broker:
            raise BrokerError("unknown broker '%s' (use DHAN, ANGEL or "
                              "ZERODHA)" % broker)
        self.token = (token or "").strip()
        self.client_id = str(client_id or "").strip().upper()
        if self.broker == "DHAN" and not self.client_id:
            self.client_id = dhan_client_id(self.token)
        self.creds_file = creds_file
        self._creds = None
        self._extra = dict(extra or {})  # keys written in token.txt
        self._jwt = None                 # Angel session token (memory only)
        self._verified = None

    @property
    def label(self):
        return LABEL[self.broker]

    @property
    def creds(self):
        if self._creds is None:
            self._creds = {}
            if self.creds_file and os.path.exists(self.creds_file):
                try:
                    self._creds = json.load(open(self.creds_file))
                except ValueError:
                    raise BrokerError("credentials.json is not valid JSON")
            self._creds.update({k: v for k, v in self._extra.items() if v})
        return self._creds

    def need(self, *keys):
        miss = [k for k in keys if not str(self.creds.get(k) or "").strip()]
        if miss:
            raise BrokerError("fill %s in token.txt (or %s)"
                              % (", ".join(miss), self.creds_file or
                                 "credentials.json"))
        return [str(self.creds[k]).strip() for k in keys]

    # -------------------------------------------------------- headers
    def headers(self):
        if self.broker == "DHAN":
            return {"access-token": self.token, "client-id": self.client_id,
                    "Content-Type": "application/json",
                    "Accept": "application/json"}
        if self.broker == "ANGEL":
            key, = self.need("api_key")
            return {"Authorization": "Bearer " + self.angel_jwt(),
                    "Content-Type": "application/json",
                    "Accept": "application/json", "X-UserType": "USER",
                    "X-SourceID": "WEB", "X-ClientLocalIP": "127.0.0.1",
                    "X-ClientPublicIP": "127.0.0.1",
                    "X-MACAddress": "00:00:00:00:00:00", "X-PrivateKey": key}
        key, = self.need("api_key")
        if not self.token:
            raise AuthError("no Zerodha access token -- run "
                            "python3 broker_api.py zerodha-login REQUEST_TOKEN")
        return {"X-Kite-Version": "3",
                "Authorization": "token %s:%s" % (key, self.token)}

    def angel_jwt(self):
        """Pasted jwtToken, or log in with client code + MPIN + TOTP."""
        if self._jwt:
            return self._jwt
        if looks_like_jwt(self.token):
            self._jwt = self.token.replace("Bearer ", "")
            return self._jwt
        key, mpin, secret = self.need("api_key", "mpin", "totp_secret")
        r = requests.post(
            ANGEL_BASE + "/rest/auth/angelbroking/user/v1/loginByPassword",
            headers={"Content-Type": "application/json",
                     "Accept": "application/json", "X-UserType": "USER",
                     "X-SourceID": "WEB", "X-ClientLocalIP": "127.0.0.1",
                     "X-ClientPublicIP": "127.0.0.1",
                     "X-MACAddress": "00:00:00:00:00:00", "X-PrivateKey": key},
            json={"clientcode": self.client_id, "password": mpin,
                  "totp": totp_now(secret)}, timeout=30)
        j = _json(r)
        if not j.get("status") or not (j.get("data") or {}).get("jwtToken"):
            raise AuthError("Angel login failed: %s" % (j.get("message") or
                                                        r.status_code))
        self._jwt = j["data"]["jwtToken"].replace("Bearer ", "")
        return self._jwt


def _json(r):
    try:
        return r.json()
    except ValueError:
        return {"raw": r.text[:300]}


# Angel historical API: 3 requests/sec and 180/min (SmartAPI rate limits).
# Going over returns HTTP 403 "exceeding access rate" -- NOT a bad token.
_RATE = {"getCandleData": (0.36, 170)}          # min gap s, max per 60 s
_hits = {}


def _throttle(path):
    for key, (gap, per_min) in _RATE.items():
        if key in path:
            h = _hits.setdefault(key, [])
            now = time.time()
            h[:] = [t for t in h if now - t < 60]
            if len(h) >= per_min:
                time.sleep(60 - (now - h[0]) + 0.5)
            if h and time.time() - h[-1] < gap:
                time.sleep(gap - (time.time() - h[-1]))
            h.append(time.time())


def _rate_limited(r):
    try:
        t = r.text.lower()
    except Exception:
        t = ""
    return r.status_code == 429 or (r.status_code == 403 and (
        "access rate" in t or "exceeding" in t or "rate limit" in t))


def _call(sess, method, path, body=None, params=None, form=None, retries=2,
          once=False):
    """HTTP to the session's broker. Returns the useful 'data' part.
    Raises AuthError (401/403, bad token) or BrokerError (anything else).
    once=True (ORDER placement): a network error after the request may have
    reached the broker is NOT retried -- a retry could place the order twice
    (Codex review 30 Sep). Only 'could not connect' and an explicit
    rate-limit reply (= broker refused it) are retried."""
    base = {"DHAN": DHAN_BASE, "ANGEL": ANGEL_BASE,
            "ZERODHA": KITE_BASE}[sess.broker]
    retries = max(retries, 5)
    for attempt in range(retries + 1):
        _throttle(path)
        try:
            r = requests.request(method, base + path, headers=sess.headers(),
                                 json=body, params=params, data=form,
                                 timeout=30)
        except requests.RequestException as e:
            if once and not isinstance(e, requests.ConnectTimeout):
                raise BrokerError(
                    "ORDER STATUS UNKNOWN (%s) -- the broker may have received "
                    "it. Check the order book in the app before trying again; "
                    "rbtrack will not re-send it today." % type(e).__name__)
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise BrokerError("network error: %s" % e)
        if _rate_limited(r) and attempt < retries:     # too fast, not a bad
            time.sleep(min(30, 2 ** (attempt + 1)))      # token: wait, retry
            continue
        break
    if _rate_limited(r):
        raise BrokerError("rate limit (%s): too many requests, try again in a "
                          "minute" % getattr(sess, "label", sess.broker))
    if once and r.status_code >= 500:            # server error AFTER it got
        raise BrokerError("ORDER STATUS UNKNOWN (HTTP %d) -- the broker may "   # the order
                          "have accepted it." % r.status_code)
    j = _json(r)
    if r.status_code in (401, 403):
        raise AuthError("HTTP %d -- token expired/invalid or API access not "
                        "enabled: %s" % (r.status_code, _err(j)))
    if sess.broker == "DHAN":
        if r.status_code >= 400 or (isinstance(j, dict) and
                                    (j.get("errorCode") or j.get("errorType"))):
            msg = _err(j)
            # DH-901 / 'Invalid Token': revoked (e.g. a new token was made in
            # web.dhan.co) even if the JWT date says it is still valid
            if "DH-901" in msg or "token" in msg.lower():
                raise AuthError("HTTP %d: %s" % (r.status_code, msg))
            raise BrokerError("HTTP %d: %s" % (r.status_code, msg))
        return j
    if sess.broker == "ANGEL":
        if not isinstance(j, dict) or j.get("status") is False or r.status_code >= 400:
            code = str(j.get("errorcode", "")) if isinstance(j, dict) else ""
            if code in ("AG8001", "AG8002", "AG8003", "AB1010"):
                raise AuthError("Angel token rejected: %s" % _err(j))
            if once and r.status_code < 400 and not isinstance(j, dict):
                raise BrokerError("ORDER STATUS UNKNOWN (malformed Angel envelope)")
            raise BrokerError("HTTP %d: %s" % (r.status_code, _err(j)))
        # Empty is known only after an explicit successful envelope. Missing
        # status/data or contradictory error fields are not an empty portfolio.
        if j.get("status") is not True or "data" not in j or j.get("errorcode") not in (None, "", 0, "0"):
            prefix = "ORDER STATUS UNKNOWN" if once else "Invalid Angel response"
            raise BrokerError("%s (success/status/data/errorcode unverified)" % prefix)
        data = j["data"]
        empty_paths = {"/rest/secure/angelbroking/order/v1/getPosition",
                       "/rest/secure/angelbroking/order/v1/getOrderBook"}
        if data is None and method == "GET" and path in empty_paths:
            return []
        return data
    if not isinstance(j, dict) or j.get("status") == "error" or \
            r.status_code >= 400:
        if isinstance(j, dict) and j.get("error_type") == "TokenException":
            raise AuthError("Zerodha token rejected: %s" % _err(j))
        raise BrokerError("HTTP %d: %s" % (r.status_code, _err(j)))
    return j.get("data")


def _err(d):
    if isinstance(d, dict):
        parts = [d.get(k) for k in ("errorType", "errorCode", "errorMessage",
                                    "errorcode", "message", "error_type",
                                    "raw") if d.get(k)]
        return " ".join(str(p) for p in parts)[:300]
    return str(d)[:300]


def _resolve(broker=None, token=None, sess=None):
    """sess, or the active account's session, or a bare Session."""
    if sess is not None:
        return sess
    import account
    acc = account._active
    if acc is not None and acc.session is not None and \
            (broker is None or norm_broker(broker) == acc.broker) and \
            (token is None or token == acc.token):
        return acc.session
    if broker is None or token is None:
        raise BrokerError("no active account -- call account.activate()")
    return Session(broker, token)


# ================================================================== symbols
_MAPS = {}


def _stale(path, days=7):
    return (not os.path.exists(path) or
            time.time() - os.path.getmtime(path) > days * 86400)


def _download(url, path, what, headers=None):
    try:
        print("  downloading %s (once a week) ..." % what)
        r = requests.get(url, headers=headers, timeout=180)
        if r.status_code == 200 and len(r.content) > 1000:
            open(path, "wb").write(r.content)
        else:
            print("  ! %s download failed (HTTP %d)" % (what, r.status_code))
    except requests.RequestException as e:
        print("  ! could not download %s: %s" % (what, e))


def symbol_map(sess):
    """{NSE SYMBOL: {"id": broker instrument id, "tsym": broker symbol}}."""
    if sess.broker in _MAPS:
        return _MAPS[sess.broker]
    out = {}
    if sess.broker == "DHAN":
        if _stale(DHAN_SCRIP_FILE):
            _download(DHAN_SCRIP_URL, DHAN_SCRIP_FILE, "Dhan scrip master")
        if os.path.exists(DHAN_SCRIP_FILE):
            sm = pd.read_csv(DHAN_SCRIP_FILE, low_memory=False)
            c = {k.upper(): k for k in sm.columns}
            need = ["SEM_EXM_EXCH_ID", "SEM_SEGMENT", "SEM_TRADING_SYMBOL",
                    "SEM_SMST_SECURITY_ID"]
            if all(n in c for n in need):
                m = sm[(sm[c["SEM_EXM_EXCH_ID"]] == "NSE") &
                       (sm[c["SEM_SEGMENT"]] == "E")]
                if "SEM_SERIES" in c:
                    m = m[m[c["SEM_SERIES"]].isin(["EQ", "BE"])]
                for s, i in zip(m[c["SEM_TRADING_SYMBOL"]].astype(str),
                                m[c["SEM_SMST_SECURITY_ID"]].astype(str)):
                    out[s.upper()] = {"id": i, "tsym": s.upper()}
                if "SEM_TICK_SIZE" in c:
                    for _, row in m.iterrows():
                        try: out[str(row[c["SEM_TRADING_SYMBOL"]]).upper()]["tick"] = float(row[c["SEM_TICK_SIZE"]])/100
                        except (ValueError, TypeError): pass
            else:
                print("  ! Dhan scrip master format changed -- fill disabled")
        out[INDEX] = {"id": "13", "tsym": INDEX}
    elif sess.broker == "ANGEL":
        if _stale(ANGEL_SCRIP_FILE):
            _download(ANGEL_SCRIP_URL, ANGEL_SCRIP_FILE, "Angel scrip master")
        if os.path.exists(ANGEL_SCRIP_FILE):
            # EQ first; BE (trade-for-trade) only when no EQ line exists
            for x in json.load(open(ANGEL_SCRIP_FILE)):
                s = str(x.get("symbol", ""))
                if x.get("exch_seg") != "NSE" or not s.endswith(("-EQ", "-BE")):
                    continue
                key = s[:-3].upper()
                if s.endswith("-EQ") or key not in out:
                    out[key] = {"id": str(x.get("token")), "tsym": s}
                    try: out[key]["tick"] = float(x.get("tick_size"))/100
                    except (ValueError, TypeError): pass
        out[INDEX] = {"id": "99926000", "tsym": "Nifty 50"}
    else:
        if _stale(KITE_SCRIP_FILE):
            try:
                hdr = sess.headers()
            except BrokerError:
                hdr = None
            _download(KITE_BASE + "/instruments/NSE", KITE_SCRIP_FILE,
                      "Zerodha instrument list", headers=hdr)
        if os.path.exists(KITE_SCRIP_FILE):
            k = pd.read_csv(KITE_SCRIP_FILE, low_memory=False)
            k = k[(k["segment"] == "NSE") & (k["instrument_type"] == "EQ")]
            for s, i in zip(k["tradingsymbol"].astype(str),
                            k["instrument_token"].astype(str)):
                out[s.upper()] = {"id": i, "tsym": s.upper()}
            if "tick_size" in k:
                for _, row in k.iterrows():
                    try: out[str(row["tradingsymbol"]).upper()]["tick"] = float(row["tick_size"])
                    except (ValueError, TypeError): pass
        out[INDEX] = {"id": "256265", "tsym": "NIFTY 50"}
    _MAPS[sess.broker] = out
    return out


def symbol_id(sess, symbol):
    x = symbol_map(sess).get(str(symbol).upper())
    return x["id"] if x else None


# ================================================================== prices
def _frame(rows, idx):
    idx = (pd.to_datetime(idx, utc=True).tz_convert("Asia/Kolkata")
           .normalize().tz_localize(None))
    df = pd.DataFrame(rows, index=idx,
                      columns=["Open", "High", "Low", "Close", "Volume"])
    df.index.name = "Date"
    return df[~df.index.duplicated(keep="last")].astype(float)


def daily_bars(sess, symbol, frm, to):
    """Unadjusted daily OHLCV from the broker, or None."""
    sym = str(symbol).upper()
    sid = symbol_id(sess, sym)
    if not sid:
        return None
    if sess.broker == "DHAN":
        idx = sym == INDEX
        body = {"securityId": str(sid),
                "exchangeSegment": "IDX_I" if idx else "NSE_EQ",
                "instrument": "INDEX" if idx else "EQUITY", "expiryCode": 0,
                "oi": False, "fromDate": frm.isoformat(),
                "toDate": to.isoformat()}
        j = _call(sess, "POST", "/charts/historical", body=body)
        if not isinstance(j, dict) or not j.get("timestamp"):
            return None
        rows = list(zip(j["open"], j["high"], j["low"], j["close"],
                        j["volume"]))
        return _frame(rows, pd.to_datetime(j["timestamp"], unit="s", utc=True))
    if sess.broker == "ANGEL":
        d = _call(sess, "POST",
                  "/rest/secure/angelbroking/historical/v1/getCandleData",
                  body={"exchange": "NSE", "symboltoken": str(sid),
                        "interval": "ONE_DAY",
                        "fromdate": frm.strftime("%Y-%m-%d 09:00"),
                        "todate": to.strftime("%Y-%m-%d 15:30")})
    else:
        d = _call(sess, "GET", "/instruments/historical/%s/day" % sid,
                  params={"from": frm.strftime("%Y-%m-%d 00:00:00"),
                          "to": to.strftime("%Y-%m-%d 23:59:59")})
        d = (d or {}).get("candles")
    if not d:
        return None
    return _frame([r[1:6] for r in d], [r[0] for r in d])


def live_prices(sess, symbols):
    """{SYMBOL: last traded price} for NSE equities."""
    m = symbol_map(sess)
    syms = [str(s).upper() for s in symbols if str(s).upper() in m]
    out = {}
    if sess.broker == "DHAN":
        ids = {m[s]["id"]: s for s in syms}
        keys = [int(i) for i in ids]
        for i in range(0, len(keys), 900):
            j = _call(sess, "POST", "/marketfeed/ltp",
                      body={"NSE_EQ": keys[i:i + 900]})
            for k, v in ((j or {}).get("data", {}).get("NSE_EQ", {})).items():
                p = v.get("last_price") if isinstance(v, dict) else None
                if p and str(k) in ids:
                    out[ids[str(k)]] = float(p)
            time.sleep(1.1)
    elif sess.broker == "ANGEL":
        ids = {m[s]["id"]: s for s in syms}
        keys = list(ids)
        for i in range(0, len(keys), 50):
            d = _call(sess, "POST", "/rest/secure/angelbroking/market/v1/quote/",
                      body={"mode": "LTP",
                            "exchangeTokens": {"NSE": keys[i:i + 50]}})
            for x in (d or {}).get("fetched", []):
                t = str(x.get("symbolToken"))
                if t in ids and x.get("ltp"):
                    out[ids[t]] = float(x["ltp"])
            time.sleep(1.1)
    else:
        for i in range(0, len(syms), 500):
            chunk = syms[i:i + 500]
            d = _call(sess, "GET", "/quote/ltp",
                      params=[("i", "NSE:" + m[s]["tsym"]) for s in chunk])
            for s in chunk:
                v = (d or {}).get("NSE:" + m[s]["tsym"])
                if v and v.get("last_price"):
                    out[s] = float(v["last_price"])
            time.sleep(1.1)
    return out


def get_live_price(symbol, broker=None, token=None, sess=None):
    sess = _resolve(broker, token, sess)
    return live_prices(sess, [symbol]).get(str(symbol).upper())


# ------------------------------------------------------------------ NSE bhavcopy
# ONE file per day holds every stock's OHLCV (unadjusted, same as broker bars).
# 4 missing days = 4 downloads instead of ~500 broker calls per missing stretch.
BHAV_URL = ("https://nsearchives.nseindia.com/content/cm/"
            "BhavCopy_NSE_CM_0_0_0_%s_F_0000.csv.zip")
BHAV_DIR = os.path.join(ds.DATA, "_bhav")
BHAV_SERIES = ("EQ", "BE", "BZ")


def _bhav_day(d):
    """{SYMBOL: (O, H, L, C, V)} for one session, or None (holiday / not out
    yet / blocked). Downloads once, kept in data/_bhav/."""
    import io
    import zipfile
    tag = d.strftime("%Y%m%d")
    path = os.path.join(BHAV_DIR, tag + ".csv.zip")
    if not os.path.exists(path):
        r = None
        for hdr in (ds.NSE_HDRS, {"User-Agent": "Mozilla/5.0"},
                    ds.NSE_HDRS):           # NSE refuses one or the other
            try:
                r = requests.get(BHAV_URL % tag, headers=hdr, timeout=30)
            except requests.RequestException:
                r = None
            if r is not None and r.status_code == 200 and \
                    r.content[:2] == b"PK":
                break
            time.sleep(1.5)
        if r is None or r.status_code != 200 or r.content[:2] != b"PK":
            return None
        os.makedirs(BHAV_DIR, exist_ok=True)
        with open(path, "wb") as f:
            f.write(r.content)
    try:
        with zipfile.ZipFile(path) as z:
            t = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])))
    except Exception:
        return None
    t = t[t["SctySrs"].isin(BHAV_SERIES)]
    return {str(r.TckrSymb).upper(): (r.OpnPric, r.HghPric, r.LwPric, r.ClsPric,
                                      r.TtlTradgVol) for r in t.itertuples()}


def bhav_fill(frames, want, warns=None):
    """Fill the days the free source is missing from NSE's daily bhavcopy.
    Returns how many stocks got at least one day. Never raises."""
    warns = warns if warns is not None else []
    behind = [s for s, f in frames.items() if f.index[-1].date() < want]
    if not behind:
        return 0
    start = min(frames[s].index[-1].date() for s in behind) + \
        dt.timedelta(days=1)
    start = max(start, want - dt.timedelta(days=21))   # a lag, not history
    days, d = [], start
    while d <= want:
        if d.weekday() < 5:
            days.append(d)
        d += dt.timedelta(days=1)
    got = {}
    for d in days:
        try:
            t = _bhav_day(d)
        except Exception:
            t = None
        if t:
            got[d] = t
    if not got:
        return 0
    filled, skipped = set(), set()
    for s in behind:
        f = frames[s]
        add = []
        prev = float(f["Close"].iloc[-1])
        for d in sorted(got):
            if pd.Timestamp(d) <= f.index[-1] or s in skipped:
                continue
            row = got[d].get(s.upper())
            if not row:
                continue
            o, h, l, c, v = (float(x) for x in row)
            if not c > 0:
                continue
            if not 0.6 < c / prev < 1.4:          # split / bonus: adjusted
                skipped.add(s)                    # history vs raw price
                warns.append("%s: %.0f%% gap vs NSE bhavcopy -- possible "
                             "split/bonus, fill skipped" % (s, (c / prev - 1)
                                                            * 100))
                break
            add.append((pd.Timestamp(d), o, h, l, c, v))
            prev = c
        if add:
            a = pd.DataFrame([x[1:] for x in add], index=[x[0] for x in add],
                             columns=["Open", "High", "Low", "Close", "Volume"])
            a.index.name = f.index.name
            frames[s] = pd.concat([f, a])
            filled.add(s)
    return len(filled)


# Broker bars fetched today are kept on disk, so the 2nd screen of the same
# scan (momentum after W+TT) does not ask the broker for all 500 stocks again.
_FILL = {"path": None, "bars": {}, "dirty": False}


def _fill_cache_open(sess, want):
    tag = "%s_%s_%s_%s" % (sess.broker, want, ds.now_ist().date(),
                           "open" if ds.market_open() else "closed")
    path = os.path.join(ds.DATA, "_broker_fill", tag + ".pkl")
    if _FILL["path"] == path:
        return
    _FILL.update(path=path, bars={}, dirty=False)
    try:
        _FILL["bars"] = pd.read_pickle(path)
    except Exception:
        pass
    d = os.path.dirname(path)                 # keep only today's caches
    try:
        for f in os.listdir(d):
            if f.endswith(".pkl") and str(ds.now_ist().date()) not in f:
                os.remove(os.path.join(d, f))
    except OSError:
        pass


def _fill_cache_save():
    if _FILL["path"] and _FILL["dirty"]:
        try:
            os.makedirs(os.path.dirname(_FILL["path"]), exist_ok=True)
            pd.to_pickle(_FILL["bars"], _FILL["path"])
            _FILL["dirty"] = False
        except Exception:
            pass


def gap_fill(df, sess, symbol, want, warns, name):
    """Append sessions missing from the free history. Skips if a split /
    bonus is suspected (broker candles are unadjusted)."""
    last = df.index[-1].date()
    if last >= want:
        return df
    frm = last + dt.timedelta(days=1)
    to = ds.now_ist().date() + dt.timedelta(days=1)
    key = (symbol, frm.isoformat())
    if key in _FILL["bars"]:              # fetched earlier today (other scan)
        add = _FILL["bars"][key]
    else:
        add = daily_bars(sess, symbol, frm, to)
        time.sleep(0.25 if sess.broker == "DHAN" else 0.35)
        _FILL["bars"][key] = add
        _FILL["dirty"] = True
    if add is None or add.empty:
        return df
    add = add[add.index > df.index[-1]]
    if ds.market_open():                 # today's bar is incomplete
        add = add[add.index.date < ds.now_ist().date()]
    if add.empty:
        return df
    jump = add["Close"].iloc[0] / df["Close"].iloc[-1]
    if jump > 1.4 or jump < 0.6:
        warns.append("%s: %.0f%% gap between sources -- possible split/"
                     "bonus, %s fill skipped" % (name, (jump - 1) * 100,
                                                 sess.label))
        return df
    return pd.concat([df, add])


def refresh(sess, frames, bm=None, want=None, warns=None, every=10):
    """Shared step of every screen: fill days the free source is missing,
    then today's live prices. Never stops the screen -- on any broker
    problem it says so and returns what it has.
    Returns (frames, bm, {frame key: live price})."""
    warns = warns if warns is not None else []
    want = want or ds.last_expected_session()
    live = {}
    behind = [s for s, f in frames.items() if f.index[-1].date() < want]
    if behind:                              # fast path: NSE daily file
        n = bhav_fill(frames, want, warns)
        if n:
            print("  NSE bhavcopy: %d stock(s) filled (daily files, fast)" % n)
        behind = [s for s, f in frames.items()
                  if f.index[-1].date() < want]
    try:
        if behind or (bm is not None and bm.index[-1].date() < want):
            print("  source is behind -- filling missing days from %s ..."
                  % sess.label)
            _fill_cache_open(sess, want)
            try:
                if bm is not None:
                    bm = gap_fill(bm, sess, INDEX, want, warns, "NIFTY")
                m = symbol_map(sess)
                fails = []
                for i, s in enumerate(behind, 1):
                    if i % every == 0 or i == len(behind):
                        sys.stdout.write("\r    %3d/%d" % (i, len(behind)))
                        sys.stdout.flush()
                    if s.upper() not in m:
                        warns.append("%s: not in the %s symbol list, not "
                                     "filled" % (s, sess.label))
                        continue
                    try:                  # one stock failing (rate limit,
                        frames[s] = gap_fill(frames[s], sess, s.upper(),
                                             want, warns, s)
                    except AuthError:     # bad data) never stops the rest
                        raise
                    except BrokerError as e:
                        fails.append(s)
                        if len(fails) >= 40 and len(fails) > i // 2:
                            print("\n  ! too many %s errors (%s) -- stopping "
                                  "the fill." % (sess.label, e))
                            break
                        time.sleep(5)
                print()
                _fill_cache_save()
                if fails:
                    print("  ! %d stock(s) could not be filled from %s: %s"
                          % (len(fails), sess.label, ", ".join(
                              f.upper() for f in fails[:15])))
            except AuthError:
                raise
            except BrokerError as e:
                print("\n  ! %s history fill failed (%s) -- continuing with "
                      "the free source." % (sess.label, e))
        still = [s for s, f in frames.items() if f.index[-1].date() < want]
        if still:
            msg = ("%d of %d stocks still end before %s (not filled) -- their "
                   "signals / momentum ranks can be WRONG. Run again later."
                   % (len(still), len(frames), want))
            print("  !!! " + msg)
            warns.append(msg)
        print("  fetching today's prices from %s ..." % sess.label)
        ltp = live_prices(sess, list(frames))
        live = {s: ltp[s.upper()] for s in frames if s.upper() in ltp}
    except AuthError as e:
        print("\n*** %s refused the request (%s)." % (sess.label, e))
        print("*** Check: token copied fully / not expired / data API "
              "access active on the account.")
        print("*** Continuing WITHOUT the broker -- prices may be OLD. ***\n")
        live = {}
    except Exception as e:
        print("\n  ! %s price step failed (%s). Continuing without it."
              % (sess.label, e))
        live = {}
    return frames, bm, live


# ================================================================== account
def whoami(sess):
    """Client ID as the BROKER reports it for this token."""
    if sess.broker == "DHAN":
        return dhan_client_id(sess.token) or None
    if sess.broker == "ANGEL":
        d = _call(sess, "GET", "/rest/secure/angelbroking/user/v1/getProfile")
        return str((d or {}).get("clientcode") or "").upper() or None
    d = _call(sess, "GET", "/user/profile")
    return str((d or {}).get("user_id") or "").upper() or None


def verify_identity(sess):
    """(ok, message): the token really belongs to the active client ID.
    Dhan: the ID is signed into the token. Angel/Zerodha: asks the broker."""
    if sess._verified is not None:
        return sess._verified
    try:
        who = whoami(sess)
    except BrokerError as e:
        return False, "could not confirm the account (%s)" % e
    if not who:
        res = (False, "broker did not report a client ID")
    elif who.upper() != sess.client_id.upper():
        res = (False, "token belongs to %s, active account is %s -- STOP"
               % (who, sess.client_id))
    else:
        res = (True, "token confirmed for %s %s" % (sess.label, who))
    sess._verified = res
    return res


def holdings(sess):
    """[{symbol, qty, avg_price}] of the demat account."""
    def number(value):
        try: n = float(value or 0)
        except (TypeError, ValueError): raise BrokerError("Invalid numeric holdings/position response")
        if not math.isfinite(n): raise BrokerError("Non-finite holdings/position response")
        return n
    out = []
    if sess.broker == "DHAN":
        try:
            d = _call(sess, "GET", "/holdings")
        except AuthError:
            raise
        except BrokerError as e:
            if "1111" in str(e) or "No holdings" in str(e):
                d = []
            else:
                raise
        d = d.get("data", []) if isinstance(d, dict) else d
        if not isinstance(d, list):
            raise BrokerError("invalid Dhan holdings response; holdings unknown")
        for h in d:
            if not isinstance(h, dict): raise BrokerError("Invalid holding row")
            q = number(h.get("totalQty") or h.get("availableQty") or 0)
            if q > 0:
                out.append({"symbol": str(h.get("tradingSymbol") or
                                          h.get("symbol") or "").upper(),
                            "qty": q,
                            "avg_price": number(h.get("avgCostPrice") or 0),
                            # Do not substitute totalQty when availableQty is explicitly zero.
                            "sellable_qty": max(0, number(h.get("availableQty") or 0)),
                            "sellable_by_product": {"CNC": max(0, number(h.get("availableQty") or 0))},
                            "_collateral": number(h.get("collateralQty") or 0)})
    elif sess.broker == "ANGEL":
        d = _call(sess, "GET", "/rest/secure/angelbroking/portfolio/v1/getHolding")
        if not isinstance(d, list):
            raise BrokerError("invalid Angel holdings response; holdings unknown")
        for h in d:
            if not isinstance(h, dict): raise BrokerError("Invalid holding row")
            q = number(h.get("quantity") or 0) + number(h.get("t1quantity") or 0)
            if q > 0:
                out.append({"symbol": re.sub(r"-EQ$", "", str(
                    h.get("tradingsymbol") or "").upper()), "qty": q,
                    "avg_price": number(h.get("averageprice") or 0),
                    # Conservative settled delivery quantity; no guess about T1/MTF.
                    "sellable_qty": max(0, number(h.get("quantity") or 0) -
                                        number(h.get("collateralquantity") or 0)),
                    "sellable_by_product": {"CNC": max(0, number(h.get("quantity") or 0) -
                                               number(h.get("collateralquantity") or 0))}
                    if str(h.get("product") or "DELIVERY").upper() in ("DELIVERY", "CNC") else
                    {"MTF": max(0, number(h.get("quantity") or 0) - number(h.get("collateralquantity") or 0))}
                    if str(h.get("product")).upper() in ("MARGIN", "MTF") else {}})
    else:
        d = _call(sess, "GET", "/portfolio/holdings")
        if not isinstance(d, list):
            raise BrokerError("invalid Kite holdings response; holdings unknown")
        for h in d:
            if not isinstance(h, dict): raise BrokerError("Invalid holding row")
            q = number(h.get("quantity") or 0) + number(h.get("t1_quantity") or 0) + number((h.get("mtf") or {}).get("quantity") or 0)
            if q > 0:
                out.append({"symbol": str(h.get("tradingsymbol") or "").upper(),
                            "qty": q,
                            "avg_price": number(h.get("average_price") or 0),
                            "sellable_qty": max(0, number(h.get("quantity") or 0) -
                                number(h.get("used_quantity") or 0) - number(h.get("collateral_quantity") or 0)),
                            "sellable_by_product": {
                                "CNC": max(0, number(h.get("quantity") or 0) - number(h.get("used_quantity") or 0)
                                           - number(h.get("collateral_quantity") or 0)),
                                "MTF": max(0, number((h.get("mtf") or {}).get("quantity") or 0)
                                           - number((h.get("mtf") or {}).get("used_quantity") or 0))}})
    # MTF can live in positions rather than the delivery holdings endpoint.
    if sess.broker in ("DHAN", "ANGEL"):
        path = "/positions" if sess.broker == "DHAN" else "/rest/secure/angelbroking/order/v1/getPosition"
        positions = _call(sess, "GET", path)
        if sess.broker == "ANGEL" and positions is None:  # only Angel empty positions
            positions = []     # positions (an error raises inside _call)
        if not isinstance(positions, list):
            raise BrokerError("positions unavailable; MTF/holding exposure unknown")
        by = {h["symbol"]: h for h in out}
        for pos in positions:
            if not isinstance(pos, dict): raise BrokerError("Invalid position row")
            prod = str(pos.get("productType") or pos.get("producttype") or "").upper()
            exchange = str(pos.get("exchangeSegment") or pos.get("exchange") or "").upper()
            if prod not in ("MTF", "MARGIN") or exchange not in ("NSE_EQ", "NSE"):
                continue
            q = number(pos.get("netQty") or pos.get("netqty") or 0)
            if q <= 0:
                continue
            sym = re.sub(r"-(EQ|BE)$", "", str(pos.get("tradingSymbol") or pos.get("tradingsymbol") or "").upper())
            if not sym:
                raise BrokerError("MTF position symbol missing")
            avg = number(pos.get("costPrice") or pos.get("buyavgprice") or pos.get("buyAvg") or 0)
            h = by.setdefault(sym, {"symbol": sym, "qty": 0, "avg_price": 0,
                                    "sellable_qty": 0, "sellable_by_product": {"CNC": 0}})
            product_qty = h.setdefault("sellable_by_product", {"CNC": h.get("sellable_qty", 0)})
            if sess.broker == "DHAN" and h.get("_collateral", 0) > 0:
                raise BrokerError("Overlapping collateral/MTF quantities require broker verification")
            old = product_qty.get("MTF", 0)
            add = max(0, q-old)
            total = h["qty"] + add
            h["avg_price"] = (h["qty"]*h["avg_price"] + add*avg)/total if total else 0
            h["qty"] = total
            product_qty["MTF"] = max(old,q)
            h["sellable_qty"] = sum(product_qty.values())
        out = list(by.values())
    for h in out:
        if not h["symbol"] or h["qty"] < 0 or h["qty"] != int(h["qty"]):
            raise BrokerError("Invalid holding symbol/quantity")
        for q in h.get("sellable_by_product", {}).values():
            if q < 0 or q != int(q): raise BrokerError("Invalid sellable quantity")
        h.pop("_collateral", None)
    return out


def account_value(sess):
    """(demat value at LTP + free cash, note) -- the base for the per-stock
    slot (sizing A, 30 Sep 2026: slot = account value / 20, like the
    backtest). (None, reason) when the broker cannot say."""
    try:
        cash, err = available_funds(sess)
        if cash is None:
            return None, "funds not read (%s)" % err
        hold = holdings(sess)
        ltp = live_prices(sess, [h["symbol"] for h in hold]) if hold else {}
        val = sum(float(h["qty"]) * float(ltp.get(h["symbol"]) or
                                          h.get("avg_price") or 0)
                  for h in hold)
        return float(cash) + val, "cash Rs %s + holdings Rs %s" % (
            format(int(cash), ","), format(int(val), ","))
    except Exception as e:
        return None, "%s" % type(e).__name__


def available_funds(sess):
    """(rupees available for new buys, error text)."""
    try:
        if sess.broker == "DHAN":
            d = _call(sess, "GET", "/fundlimit")
            val = d.get("availabelBalance", d.get("availableBalance"))
        elif sess.broker == "ANGEL":
            d = _call(sess, "GET", "/rest/secure/angelbroking/user/v1/getRMS")
            val = (d or {}).get("availablecash")
        else:
            d = _call(sess, "GET", "/user/margins/equity")
            a = (d or {}).get("available", {})
            val = a.get("live_balance", a.get("cash"))
        import math
        value = float(val)
        if not math.isfinite(value) or value < 0:
            return None, "funds balance is invalid"
        return value, ""
    except BrokerError as e:
        return None, str(e)
    except (TypeError, ValueError):
        return None, "funds reply had no balance field"


def trades(sess, frm, to=None):
    """Executed trades (BUY and SELL) between two dates, for the journal:
    [{symbol, side, qty, price, date}]. Read-only.
      Dhan    GET /v2/trades/{from}/{to}/{page}  (any past dates)
      Angel   getTradeBook, Zerodha /trades      (TODAY only -- run rb on the
                                                  day you sell)
    Any problem -> [] (the journal then asks for the price)."""
    to = to or dt.date.today()
    ids = {}
    try:
        ids = {str(v["id"]): k for k, v in symbol_map(sess).items()}
    except Exception:
        pass

    def clean(sym, sid=None):
        if sid is not None and str(sid) in ids:
            return ids[str(sid)]
        return re.sub(r"-(EQ|BE)$", "", str(sym or "").upper())

    def day(v):
        m = re.search(r"(\d{4}-\d{2}-\d{2})", str(v or ""))
        if m:
            return m.group(1)
        for f in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y"):
            try:
                return dt.datetime.strptime(str(v), f).date().isoformat()
            except ValueError:
                pass
        return to.isoformat()

    out = []
    try:
        if sess.broker == "DHAN":
            for page in range(20):
                d = _call(sess, "GET", "/trades/%s/%s/%d" % (
                    pd_date(frm), pd_date(to), page))
                d = d.get("data", d) if isinstance(d, dict) else d
                if not d:
                    break
                for x in d:
                    if "EQ" not in str(x.get("exchangeSegment", "EQ")):
                        continue
                    out.append({"symbol": clean(x.get("tradingSymbol"),
                                                x.get("securityId")),
                                "side": str(x.get("transactionType")).upper(),
                                "qty": float(x.get("tradedQuantity") or 0),
                                "price": float(x.get("tradedPrice") or 0),
                                "date": day(x.get("exchangeTime") or
                                            x.get("createTime"))})
        elif sess.broker == "ANGEL":
            d = _call(sess, "GET",
                      "/rest/secure/angelbroking/order/v1/getTradeBook")
            for x in d or []:
                out.append({"symbol": clean(x.get("tradingsymbol"),
                                            x.get("symboltoken")),
                            "side": str(x.get("transactiontype")).upper(),
                            "qty": float(x.get("fillsize") or 0),
                            "price": float(x.get("fillprice") or 0),
                            "date": to.isoformat()})
        else:
            d = _call(sess, "GET", "/trades")
            for x in d or []:
                out.append({"symbol": clean(x.get("tradingsymbol")),
                            "side": str(x.get("transaction_type")).upper(),
                            "qty": float(x.get("quantity") or 0),
                            "price": float(x.get("average_price") or 0),
                            "date": day(x.get("fill_timestamp"))})
    except BrokerError:
        return []
    return [x for x in out if x["qty"] > 0 and x["price"] > 0]


def pd_date(d):
    return d.isoformat() if hasattr(d, "isoformat") else str(d)[:10]


def mtf_leverage(sess, symbol, price):
    """(leverage, note) the broker gives this stock under MTF, e.g. 4.55.
    Read-only margin calculators, no order is placed:
      Dhan    POST /v2/margincalculator  productType MTF  -> leverage
      Angel   POST .../margin/v1/batch   productType MARGIN -> totalMarginRequired
      Zerodha POST /margins/orders       product MTF -> leverage / total
    Anything unverified -> (None, why); callers block MTF, with no guessed leverage."""
    if sess is None:
        return None, "no broker session"
    x = symbol_map(sess).get(str(symbol).upper())
    if not x or not price or not math.isfinite(float(price)) or price <= 0:
        return None, "not in the %s symbol list / no price" % sess.label
    qty = max(1, int(100000 // price))       # ~Rs 1 lakh -> precise ratio
    value = qty * float(price)
    lev, margin = None, None
    try:
        if sess.broker == "DHAN":
            d = _call(sess, "POST", "/margincalculator", body={
                "dhanClientId": sess.client_id, "exchangeSegment": "NSE_EQ",
                "transactionType": "BUY", "quantity": qty,
                "productType": "MTF", "securityId": str(x["id"]),
                "price": float(price), "triggerPrice": 0.0})
            raw = str(d.get("leverage", "")).strip()
            match = re.fullmatch(r"(?:1\s*:\s*)?(\d+(?:\.\d+)?)", raw)
            lev = float(match.group(1)) if match else None
            margin = d.get("totalMargin")
            if lev == 0:
                return 0.0, "%s explicitly reports MTF 0x (not available)" % sess.label
        elif sess.broker == "ANGEL":
            d = _call(sess, "POST",
                      "/rest/secure/angelbroking/margin/v1/batch", body={
                          "positions": [{"exchange": "NSE", "qty": qty,
                                         "price": float(price),
                                         "productType": "MARGIN",
                                         "token": str(x["id"]),
                                         "tradeType": "BUY",
                                         "orderType": "MARKET"}]})
            margin = (d or {}).get("totalMarginRequired")
        else:
            d = _call(sess, "POST", "/margins/orders", body=[{
                "exchange": "NSE", "tradingsymbol": x["tsym"],
                "transaction_type": "BUY", "variety": "regular",
                "product": "MTF", "order_type": "MARKET", "quantity": qty,
                "price": 0, "trigger_price": 0}])
            d = d[0] if isinstance(d, list) and d else {}
            lev = d.get("leverage")
            margin = d.get("total")
    except (BrokerError, TypeError, ValueError, AttributeError, KeyError, IndexError) as e:
        return None, "%s margin calculator: %s" % (sess.label, e)
    try:
        lev = float(lev) if lev else None
        if not lev or not 1.05 <= lev <= 10:        # MTF is never ~1x
            m = float(margin or 0)
            lev = value / m if m > 0 else None
    except (TypeError, ValueError):
        lev = None
    if not lev or not 1.05 <= lev <= 10:
        return None, "%s gave no usable MTF leverage" % sess.label
    return round(lev, 2), "%s MTF %.2fx" % (sess.label, lev)


# ================================================================== orders
def place_amo_order(symbol, quantity, is_mtf, broker=None, token=None,
                    sess=None, order_type="MARKET", price=0.0, side="BUY",
                    tag=None):
    """BUY, NSE cash, After Market Order for the next open.
    is_mtf=False -> delivery (Dhan CNC / Angel DELIVERY / Kite CNC)
    is_mtf=True  -> margin trading (Dhan MTF / Angel MARGIN / Kite MTF)
    side="SELL" only from rbtrack's Sell sheet (AUTO SELL ON + typed
    "YES SELL"); selling from the demat needs DDPI/POA at the broker.
    tag = the intent's own id (new_intent) -> sent as Dhan correlationId /
    Angel ordertag / Kite tag, so a lost reply can be found in the book.
    Returns (ok, order_id or error text, status); status UNKNOWN = the reply
    was lost and the book did not show the order (it may still be placed)."""
    try:
        sess = _resolve(broker, token, sess)
    except BrokerError as e:
        return False, str(e), "ERROR"
    sym = str(symbol).upper()
    from order_inputs import quantity as parse_quantity
    try:
        qty = parse_quantity(quantity, "order Qty") or 0
    except ValueError as error:
        return False, str(error), "ERROR"
    side = str(side).upper()
    tag = tag or new_tag(side)
    if side not in ("BUY", "SELL"):
        return False, "side %s not allowed" % side, "ERROR"
    if qty < 1:
        return False, "quantity must be >= 1", "ERROR"
    if order_type not in ("MARKET", "LIMIT"):
        return False, "order type %s not allowed" % order_type, "ERROR"
    if ds.market_open():
        return False, "market is open -- AMOs only after 15:30", "ERROR"
    ok, msg = verify_identity(sess)
    if not ok:
        return False, "identity check failed: %s" % msg, "ERROR"
    x = symbol_map(sess).get(sym)
    if not x or sym == INDEX:
        return False, "%s not in the %s symbol list" % (sym, sess.label), \
            "ERROR"
    lim = 0.0
    if order_type == "LIMIT":
        try:
            from execution_safety import finite_positive
            lim = finite_positive(price, "limit price")
            tick = finite_positive(x.get("tick"), "broker instrument tick")
            if abs(lim/tick - round(lim/tick)) > 1e-6:
                return False, "Limit price does not match broker instrument tick", "ERROR"
        except ValueError as error:
            return False, str(error), "ERROR"
    try:
        if sess.broker == "DHAN":
            body = {"dhanClientId": sess.client_id,
                    "correlationId": tag,
                    "transactionType": side, "exchangeSegment": "NSE_EQ",
                    "productType": "MTF" if is_mtf else "CNC",
                    "orderType": order_type, "validity": "DAY",
                    "securityId": str(x["id"]), "quantity": qty,
                    "disclosedQuantity": 0, "price": lim, "triggerPrice": 0.0,
                    "afterMarketOrder": True, "amoTime": "OPEN"}
            d = _call(sess, "POST", "/orders", body=body, once=True)
            status = str(d.get("orderStatus", "")).upper()
            oid = str(d.get("orderId") or "").strip()
            if status == "REJECTED":
                return False, "order rejected (%s)" % (
                    d.get("omsErrorDescription") or _err(d)), "REJECTED"
            if not oid:
                raise BrokerError("ORDER STATUS UNKNOWN (reply without an "
                                  "order id)")
            return True, oid, status
        if sess.broker == "ANGEL":
            # SmartAPI treats after-hours NORMAL orders as AMO.
            body = {"variety": "NORMAL", "tradingsymbol": x["tsym"],
                    "symboltoken": str(x["id"]), "transactiontype": side,
                    "exchange": "NSE", "ordertype": order_type,
                    "producttype": "MARGIN" if is_mtf else "DELIVERY",
                    "duration": "DAY", "price": "%.2f" % lim, "squareoff": "0",
                    "stoploss": "0", "quantity": str(qty),
                    "ordertag": tag}
            d = _call(sess, "POST",
                      "/rest/secure/angelbroking/order/v1/placeOrder", body=body,
                      once=True)
            oid = str((d or {}).get("orderid") or "")
            if not oid:
                raise BrokerError("ORDER STATUS UNKNOWN (reply without an "
                                  "order id)")
            return True, oid, "AMO"
        form = {"tradingsymbol": x["tsym"], "exchange": "NSE",
                "transaction_type": side, "order_type": order_type,
                "quantity": qty, "product": "MTF" if is_mtf else "CNC",
                "validity": "DAY", "tag": tag}
        if order_type == "LIMIT":
            form["price"] = lim
        d = _call(sess, "POST", "/orders/amo", form=form, once=True)
        oid = str((d or {}).get("order_id") or "")
        if not oid:
            raise BrokerError("ORDER STATUS UNKNOWN (reply without an "
                              "order id)")
        return True, oid, "AMO"
    except (TypeError, ValueError, AttributeError, KeyError) as e:
        # A malformed success reply cannot prove that the POST was rejected.
        found, oid, st = find_order_by_tag(sess, tag)
        if found:
            return True, oid, st or "AMO"
        return False, "ORDER STATUS UNKNOWN (malformed reply: %s)" % type(e).__name__, "UNKNOWN"
    except BrokerError as e:
        if "STATUS UNKNOWN" in str(e):          # reply lost: ask the book
            time.sleep(3)
            found, oid, st = find_order_by_tag(sess, tag)
            if found:
                return True, oid, st or "AMO"
            # not in the book (yet) is NOT proof it was never placed (the
            # book can lag; Kite's book is per day) -> stays UNKNOWN
            return False, str(e), "UNKNOWN"
        return False, str(e), "ERROR"


_STATUS = {"TRADED": "TRADED", "COMPLETE": "TRADED", "REJECTED": "REJECTED",
           "CANCELLED": "CANCELLED", "EXPIRED": "EXPIRED"}


def pending_orders(sess):
    """Stocks with open or filled orders in the current broker book, including manual orders."""
    if sess.broker == "DHAN":
        rows = _call(sess, "GET", "/orders")
        if isinstance(rows, dict):rows = rows.get("data")
    elif sess.broker == "ANGEL":
        rows = _call(sess, "GET", "/rest/secure/angelbroking/order/v1/getOrderBook")
        if rows is None:       # status true + "data": null = no orders today
            rows = []
    else:
        rows = _call(sess, "GET", "/orders")
    if not isinstance(rows, list):
        raise BrokerError("order book unavailable/invalid")
    names = {str(x["id"]): s for s, x in symbol_map(sess).items()}
    pending = set()
    for row in rows:
        status = str(row.get("orderStatus") or row.get("status") or row.get("orderstatus") or "").upper()
        if not status:
            raise BrokerError("order book contains an order with unknown status")
        if status in _STATUS and _STATUS[status] != "TRADED":
            continue
        sym = row.get("tradingSymbol") or row.get("tradingsymbol") or names.get(str(row.get("securityId") or row.get("symboltoken")))
        if not sym:
            raise BrokerError("open broker order cannot be mapped to a stock")
        pending.add(re.sub(r"-(EQ|BE)$", "", str(sym).upper()))
    return pending


def check_order_status(order_id, broker=None, token=None, sess=None):
    """{"status": TRADED/REJECTED/CANCELLED/EXPIRED/PENDING/None,
        "filled_qty": int, "avg_price": float|None, "raw": broker text}"""
    out = {"status": None, "filled_qty": 0, "avg_price": None, "raw": ""}
    try:
        sess = _resolve(broker, token, sess)
        oid = str(order_id).split(".")[0]
        if sess.broker == "DHAN":
            d = _call(sess, "GET", "/orders/%s" % oid)
            d = (d[0] if d else {}) if isinstance(d, list) else d
            raw = str(d.get("orderStatus", "")).upper()
            q, avg = 0, None
            try:
                t = _call(sess, "GET", "/trades/%s" % oid)
                rows = t if isinstance(t, list) else [t]
                q = sum(int(r.get("tradedQuantity") or 0) for r in rows if r)
                v = sum(int(r.get("tradedQuantity") or 0) *
                        float(r.get("tradedPrice") or 0) for r in rows if r)
                avg = v / q if q else None
            except BrokerError:
                pass
            oq = int(float(d.get("filledQty") or 0))  # the order's own count
            if oq > q:                               # (trade book can lag)
                q = oq
                # A price for fewer trades cannot price the larger filledQty.
                # Keep reconciliation pending until a full cumulative average arrives.
                avg = float(d.get("averageTradedPrice") or 0) or None
        elif sess.broker == "ANGEL":
            book = _call(sess, "GET",
                         "/rest/secure/angelbroking/order/v1/getOrderBook")
            d = next((o for o in book or [] if str(o.get("orderid")) == oid),
                     {})
            raw = str(d.get("status") or d.get("orderstatus") or "").upper()
            q = int(float(d.get("filledshares") or 0))
            avg = float(d.get("averageprice") or 0) or None
        else:
            hist = _call(sess, "GET", "/orders/%s" % oid) or [{}]
            d = hist[-1]
            raw = str(d.get("status") or "").upper()
            q = int(d.get("filled_quantity") or 0)
            avg = float(d.get("average_price") or 0) or None
        out.update(raw=raw, filled_qty=q, avg_price=avg if q else None,
                   status=_STATUS.get(raw, "PENDING" if raw else None))
    except BrokerError as e:
        out["raw"] = "error: %s" % e
    return out


def new_tag(side="BUY"):
    """A NEW id for every order intent (<= 20 chars, letters/digits):
    RB + yymmdd + B|S + 8 random (17 chars). Two orders for the same stock on the same
    day (CNC + MTF, a replacement) never share a tag; the SAME intent keeps
    its tag for any recovery lookup."""
    import secrets
    abc = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "RB%s%s%s" % (dt.date.today().strftime("%y%m%d"),
                         str(side).upper()[:1],
                         "".join(secrets.choice(abc) for _ in range(8)))


def find_order_by_tag(sess, tag):
    """(True, order_id, status) if the broker has an order with our tag,
    (False, '', '') if the book was read and has none, (None, '', '') if the
    book could not be read (then nobody can say -> treat as placed)."""
    try:
        if sess.broker == "DHAN":
            try:
                d = _call(sess, "GET", "/orders/external/%s" % tag, retries=1)
            except BrokerError as e:
                if "404" in str(e) or "not found" in str(e).lower():
                    return False, "", ""
                raise
            d = (d[0] if d else {}) if isinstance(d, list) else (d or {})
            oid = str(d.get("orderId") or "")
            st = str(d.get("orderStatus") or "").upper()
        elif sess.broker == "ANGEL":
            book = _call(sess, "GET",
                         "/rest/secure/angelbroking/order/v1/getOrderBook")
            d = next((o for o in book or [] if str(o.get("ordertag")) == tag),
                     {})
            oid = str(d.get("orderid") or "")
            st = str(d.get("status") or d.get("orderstatus") or "").upper()
        else:
            book = _call(sess, "GET", "/orders")
            d = next((o for o in book or [] if str(o.get("tag")) == tag), {})
            oid = str(d.get("order_id") or "")
            st = str(d.get("status") or "").upper()
        if not oid:
            return False, "", ""
        return True, oid, _STATUS.get(st, "PENDING" if st else "")
    except Exception:
        return None, "", ""


# ------------------------------------------------------------ intent ledger
# data/order_intents.csv (per account, next to orders_log.csv): one row per
# order we MEANT to send, written BEFORE the POST. States:
#   INTENT    written, no result saved (crash / save failed) -> unresolved
#   UNKNOWN   reply lost, book did not show it                -> unresolved
#   ACCEPTED  broker gave an order id
#   REJECTED  broker said no (nothing placed)
#   CLOSED    broker later reported REJECTED / CANCELLED / EXPIRED
#   DONE      TRADED, position durably saved, older than the guard window
#   NOT_PLACED  RB checked the broker app and cleared it (rbtrack --resolve)
# Unresolved rows block that stock+side on EVERY later day until the book
# shows the order or RB resolves it by hand -- an empty book never clears it.
INTENT_COLS = ["tag", "created", "date", "symbol", "side", "qty", "product",
               "state", "order_id", "status", "note", "position_data",
               "position_saved", "filled_qty", "avg_price", "avg_qty"]
UNRESOLVED = ("INTENT", "UNKNOWN")


def _intents_file():
    return os.path.join(os.path.dirname(ORDER_LOG), "order_intents.csv")


def load_intents():
    p = _intents_file()
    if not os.path.exists(p):
        return pd.DataFrame(columns=INTENT_COLS)
    d = pd.read_csv(p, dtype=str).fillna("")
    for c in INTENT_COLS:
        if c not in d:
            d[c] = ""
    if "tracked" in d and len(d):          # v5 ledger (strategy/leg/price/
        d = d.apply(_from_v5, axis=1)      # tracked) -> position_data
    if len(d):
        from order_inputs import quantity
        states = set(UNRESOLVED) | {"ACCEPTED", "REJECTED", "CLOSED", "DONE", "NOT_PLACED"}
        if d["tag"].eq("").any() or d["tag"].duplicated().any() or not d["state"].isin(states).all() or not d["side"].isin(["BUY", "SELL"]).all():
            raise BrokerError("Intent ledger identity/state invalid; orders blocked for manual review")
        try:
            if any(not quantity(q, "intent Qty") for q in d["qty"]):
                raise ValueError("zero intent Qty")
        except ValueError as error:
            raise BrokerError("Intent ledger quantity invalid; orders blocked: %s" % error)
    return d[INTENT_COLS]


def _from_v5(r):
    """One v5 intent row (30 Sep, before Codex fixes 1-3) in the new form:
    tracked=1 -> position_saved=1; strategy/leg/price -> position_data, so a
    lost-reply BUY from v5 can still be rebuilt. No strategy -> left empty
    (recover_buys then keeps it blocked + reserved for a manual check)."""
    if str(r.get("tracked", "")) == "1" and not r["position_saved"]:
        r["position_saved"] = "1"
    if r["side"] == "BUY" and not r["position_data"] and r.get("strategy"):
        leg = r.get("leg") if r.get("leg") in (
            "swing_qty", "investing_qty", "momentum_qty") else "swing_qty"
        row = {"symbol": r["symbol"], "swing_qty": 0, "investing_qty": 0,
               "momentum_qty": 0, "entry_price": float(r.get("price") or 0),
               "entry_date": r["date"], "strategy": r["strategy"],
               "mode": "LIVE", "product": r["product"] or "CNC",
               "order_id": "", "note": "AMO pending (v5 intent %s)" % r["tag"]}
        row[leg] = int(float(r["qty"] or 0))
        r["position_data"] = json.dumps(row)
    return r


def _save_intents(d):
    p = _intents_file()
    tmp = p + ".tmp"
    with open(tmp, "w", newline="") as f:
        d.to_csv(f, index=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def new_intent(symbol, side, qty, product, position=None):
    """Save the intent (state INTENT) and return its tag. Call BEFORE the
    order is sent, inside rbtrack's lock."""
    d = load_intents()
    tag = new_tag(side)
    while tag in set(d["tag"]):
        tag = new_tag(side)
    row = {"tag": tag, "created": ds.now_ist().strftime("%Y-%m-%d %H:%M:%S"),
           "date": dt.date.today().isoformat(), "symbol": str(symbol).upper(),
           "side": str(side).upper(), "qty": str(int(qty)),
           "product": product, "state": "INTENT", "order_id": "",
           "status": "", "note": "", "position_saved": "",
           "filled_qty": "0", "avg_price": "", "avg_qty": "0", "position_data":
           json.dumps(position, allow_nan=False, default=lambda x:
                      x.item() if hasattr(x, "item") else str(x)) if position else ""}
    _save_intents(pd.concat([d, pd.DataFrame([row])], ignore_index=True))
    return tag


def update_intent(tag, **kw):
    d = load_intents()
    m = d["tag"] == tag
    for k, v in kw.items():
        d.loc[m, k] = str(v)
    _save_intents(d)


def resolve_intent(tag, placed, order_id=""):
    """rbtrack --resolve TAG placed|not-placed [ORDER_ID]: RB looked in the
    broker app. Only way an unresolved intent is cleared without the book."""
    d = load_intents()
    if not (d["tag"] == tag).any():
        return False
    update_intent(tag, state="ACCEPTED" if placed else "NOT_PLACED",
                  order_id=order_id, note="resolved by hand %s"
                  % dt.date.today())
    return True


def open_intents():
    d = load_intents()
    return d[d["state"].isin(UNRESOLVED)]


def buy_reservations(sp):
    """Untracked BUY exposure, including legacy intents lacking strategy data.

    Durable position_saved survives subsequent position closure. An order
    matching a split row is already counted there, including a pending BUY.
    """
    orders = set(sp.get("order_id", pd.Series(dtype=str)).fillna("").astype(str))
    out = []
    for _, r in load_intents().iterrows():
        if r["side"] != "BUY" or r["position_saved"] == "1":
            continue
        if r["order_id"] and r["order_id"] in orders:
            continue
        if r["state"] in ("NOT_PLACED", "REJECTED"):
            continue
        if r["state"] == "CLOSED" and r["filled_qty"] and float(r["filled_qty"]) <= 0:
            continue
        try:
            data = json.loads(r["position_data"] or "{}")
        except (ValueError, TypeError):
            data = {}
        if data.get("strategy", "Momentum").lower() == "momentum":
            out.append(r["symbol"])
    return list(dict.fromkeys(out))


def intent_blocks(symbol, side="BUY", days=0, sess=None):
    """True if the ledger says an order for symbol+side may be live:
    - any UNRESOLVED intent, any date (the book is asked first when sess is
      given; found -> ACCEPTED; not found -> still unresolved = block)
    - an ACCEPTED intent while pending on any date, or a recent completed
      order inside `days` (0 = today)
    - a filled BUY until its position has been durably recorded, including
      partial fills on a cancelled order and legacy final records."""
    d = load_intents()
    m = (d["symbol"] == str(symbol).upper()) & (d["side"] == side.upper())
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    block = False
    for _, r in d[m].iterrows():
        st = r["state"]
        if st in ("DONE", "CLOSED") and r["side"] == "BUY" and r["position_saved"] != "1":
            if st == "CLOSED" and r["filled_qty"] and float(r["filled_qty"]) == 0:
                continue
            st = "ACCEPTED"       # inspect legacy final records with untracked exposure
        if st in UNRESOLVED:
            found = None
            if sess is not None:
                found, oid, bst = find_order_by_tag(sess, r["tag"])
                if found:
                    update_intent(r["tag"], state="ACCEPTED", order_id=oid,
                                  status=bst, note="found in the book")
                    st, r = "ACCEPTED", dict(r, order_id=oid, date=r["date"])
            if st in UNRESOLVED:
                block = True
                continue
        if st == "ACCEPTED":
            recent = str(r["date"]) >= since
            if sess is None or not r["order_id"]:
                block = True
                continue
            order = check_order_status(r["order_id"], sess=sess)
            bst = order.get("status")
            q = max(int(float(r["filled_qty"] or 0)), order.get("filled_qty", 0))
            update_intent(r["tag"], filled_qty=q,
                          avg_price=order.get("avg_price") or r["avg_price"],
                          avg_qty=order.get("filled_qty", 0) if order.get("avg_price")
                          else r["avg_qty"])
            if r["side"] == "BUY" and q > 0 and r["position_saved"] != "1":
                block = True      # fill exists, but recovery has not committed a position
                continue
            if bst in ("REJECTED", "CANCELLED", "EXPIRED"):
                update_intent(r["tag"], state="CLOSED", status=bst)
                continue
            if bst == "TRADED":
                if r["side"] == "BUY" and r["position_saved"] != "1":
                    block = True
                    continue
                if not recent:
                    update_intent(r["tag"], state="DONE", status=bst)
                block = block or recent
                continue
            block = True          # PENDING / unknown: live on any day
    return block


def log_order(row):
    exists = os.path.exists(ORDER_LOG)
    df = pd.DataFrame([row])
    if exists:                    # keep the file's own column order (an
        try:                      # extra/missing field would break the csv)
            cols = list(pd.read_csv(ORDER_LOG, nrows=0).columns)
            df = df.reindex(columns=cols)
        except Exception:
            pass
    df.to_csv(ORDER_LOG, mode="a", header=not exists, index=False)


def _log_side(d):
    return d["side"].fillna("BUY").astype(str).str.upper() if "side" in d \
        else pd.Series(["BUY"] * len(d), index=d.index)


def _still_live(rows, sess):
    """orders_log rows (history, also from before the intent ledger) that
    still count as placed: accepted ones unless the broker now says REJECTED
    / CANCELLED / EXPIRED; a lost-reply row (no order id) always counts."""
    for _, r in rows.iterrows():
        oid = str(r.get("order_id", "") or "").split(".")[0]
        if not oid or oid == "nan" or sess is None:
            return True
        st = check_order_status(oid, sess=sess).get("status")
        if st not in ("REJECTED", "CANCELLED", "EXPIRED"):
            return True
    return False


def _placed(d):
    """Accepted rows. Lost replies are handled by the intent ledger (it stays
    blocked until the book or RB resolves it -- also on later days)."""
    return d["ok"] == True                                      # noqa


def _log_rows(symbol, side, since):
    if not os.path.exists(ORDER_LOG):
        return pd.DataFrame()
    d = pd.read_csv(ORDER_LOG)
    return d[(d["symbol"] == symbol) & (d["date"].astype(str) >= since) &
             _placed(d) & (_log_side(d) == side)]


def ordered_today(symbol, side="BUY", sess=None):
    """True if an order for symbol+side may be live: an unresolved intent
    (any day) or an order placed today that the broker has not rejected /
    cancelled (sess given -> broker asked)."""
    if intent_blocks(symbol, side, 0, sess):
        return True
    today = dt.date.today().isoformat()
    return _still_live(_log_rows(symbol, side, today), sess)


def sold_recently(symbol, days=4, sess=None):
    """True if a SELL may be live: unresolved intent, or placed in the last
    days (demat still shows the shares until settlement) and not rejected /
    cancelled by the broker."""
    if intent_blocks(symbol, "SELL", days, sess):
        return True
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    return _still_live(_log_rows(symbol, "SELL", since), sess)


# ================================================================== CLI
def _cli():
    import account
    a = sys.argv[1:]
    cmd = a[0] if a else "check"
    if cmd == "zerodha-url":
        acc = account.activate()
        if acc.broker != "ZERODHA":
            sys.exit("Active account is %s, not ZERODHA." % acc.broker)
        key, = acc.session.need("api_key")
        print("Open this, log in, then copy request_token=... from the "
              "address bar:\n  " + KITE_LOGIN % key)
        return
    if cmd == "zerodha-login":
        if len(a) < 2:
            sys.exit("usage: python3 broker_api.py zerodha-login REQUEST_TOKEN")
        acc = account.activate()
        if acc.broker != "ZERODHA":
            sys.exit("Active account is %s, not ZERODHA." % acc.broker)
        key, secret = acc.session.need("api_key", "api_secret")
        rt = a[1].strip()
        chk = hashlib.sha256((key + rt + secret).encode()).hexdigest()
        r = requests.post(KITE_BASE + "/session/token",
                          headers={"X-Kite-Version": "3"},
                          data={"api_key": key, "request_token": rt,
                                "checksum": chk}, timeout=30)
        d = (_json(r) or {}).get("data") or {}
        if not d.get("access_token"):
            sys.exit("Zerodha login failed: %s" % _err(_json(r)))
        if str(d.get("user_id", "")).upper() != acc.cid:
            sys.exit("Zerodha says this login is %s, active account is %s -- "
                     "nothing written." % (d.get("user_id"), acc.cid))
        account.write_token_file("ZERODHA", acc.cid, acc.name,
                                 d["access_token"])
        print("Access token saved in token.txt for %s (valid till ~06:00 "
              "tomorrow)." % acc.cid)
        return
    acc = account.activate()
    s = acc.session
    if s is None:
        sys.exit("No usable token.")
    ok, msg = verify_identity(s)
    print("  identity: %s" % msg)
    f, err = available_funds(s)
    print("  funds: %s" % ("Rs %s" % format(int(f), ",") if f is not None
                           else "? (%s)" % err))
    try:
        print("  RELIANCE live price: %s" % get_live_price("RELIANCE", sess=s))
    except BrokerError as e:
        print("  live price failed: %s" % e)
    print("  (no orders were placed)")


if __name__ == "__main__":
    _cli()
