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
  place_amo_order(symbol, quantity, is_mtf, broker=None, token=None,
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


def _call(sess, method, path, body=None, params=None, form=None, retries=2):
    """HTTP to the session's broker. Returns the useful 'data' part.
    Raises AuthError (401/403, bad token) or BrokerError (anything else)."""
    base = {"DHAN": DHAN_BASE, "ANGEL": ANGEL_BASE,
            "ZERODHA": KITE_BASE}[sess.broker]
    for attempt in range(retries + 1):
        try:
            r = requests.request(method, base + path, headers=sess.headers(),
                                 json=body, params=params, data=form,
                                 timeout=30)
        except requests.RequestException as e:
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise BrokerError("network error: %s" % e)
        if r.status_code == 429 and attempt < retries:
            time.sleep(3 * (attempt + 1))
            continue
        break
    j = _json(r)
    if r.status_code in (401, 403):
        raise AuthError("HTTP %d -- token expired/invalid or API access not "
                        "enabled: %s" % (r.status_code, _err(j)))
    if sess.broker == "DHAN":
        if r.status_code >= 400 or (isinstance(j, dict) and
                                    (j.get("errorCode") or j.get("errorType"))):
            raise BrokerError("HTTP %d: %s" % (r.status_code, _err(j)))
        return j
    if sess.broker == "ANGEL":
        if not isinstance(j, dict) or j.get("status") is False or \
                r.status_code >= 400:
            code = str(j.get("errorcode", "")) if isinstance(j, dict) else ""
            if code in ("AG8001", "AG8002", "AG8003", "AB1010"):
                raise AuthError("Angel token rejected: %s" % _err(j))
            raise BrokerError("HTTP %d: %s" % (r.status_code, _err(j)))
        return j.get("data")
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
            else:
                print("  ! Dhan scrip master format changed -- fill disabled")
        out[INDEX] = {"id": "13", "tsym": INDEX}
    elif sess.broker == "ANGEL":
        if _stale(ANGEL_SCRIP_FILE):
            _download(ANGEL_SCRIP_URL, ANGEL_SCRIP_FILE, "Angel scrip master")
        if os.path.exists(ANGEL_SCRIP_FILE):
            for x in json.load(open(ANGEL_SCRIP_FILE)):
                s = str(x.get("symbol", ""))
                if x.get("exch_seg") == "NSE" and s.endswith("-EQ"):
                    out[s[:-3].upper()] = {"id": str(x.get("token")),
                                           "tsym": s}
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


def gap_fill(df, sess, symbol, want, warns, name):
    """Append sessions missing from the free history. Skips if a split /
    bonus is suspected (broker candles are unadjusted)."""
    last = df.index[-1].date()
    if last >= want:
        return df
    frm = last + dt.timedelta(days=1)
    to = ds.now_ist().date() + dt.timedelta(days=1)
    add = daily_bars(sess, symbol, frm, to)
    time.sleep(0.25 if sess.broker == "DHAN" else 0.35)
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
    try:
        if behind or (bm is not None and bm.index[-1].date() < want):
            print("  source is behind -- filling missing days from %s ..."
                  % sess.label)
            try:
                if bm is not None:
                    bm = gap_fill(bm, sess, INDEX, want, warns, "NIFTY")
                m = symbol_map(sess)
                for i, s in enumerate(behind, 1):
                    if i % every == 0 or i == len(behind):
                        sys.stdout.write("\r    %3d/%d" % (i, len(behind)))
                        sys.stdout.flush()
                    if s.upper() not in m:
                        warns.append("%s: not in the %s symbol list, not "
                                     "filled" % (s, sess.label))
                        continue
                    frames[s] = gap_fill(frames[s], sess, s.upper(), want,
                                         warns, s)
                print()
            except AuthError:
                raise
            except BrokerError as e:
                print("\n  ! %s history fill failed (%s) -- continuing with "
                      "the free source." % (sess.label, e))
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
    out = []
    if sess.broker == "DHAN":
        try:
            d = _call(sess, "GET", "/holdings")
        except AuthError:
            raise
        except BrokerError as e:
            if "1111" in str(e) or "No holdings" in str(e):
                return []
            raise
        d = d.get("data", []) if isinstance(d, dict) else d
        for h in d or []:
            q = float(h.get("totalQty") or h.get("availableQty") or 0)
            if q > 0:
                out.append({"symbol": str(h.get("tradingSymbol") or
                                          h.get("symbol") or "").upper(),
                            "qty": q,
                            "avg_price": float(h.get("avgCostPrice") or 0)})
    elif sess.broker == "ANGEL":
        d = _call(sess, "GET", "/rest/secure/angelbroking/portfolio/v1/getHolding")
        for h in d or []:
            q = float(h.get("quantity") or 0) + float(h.get("t1quantity") or 0)
            if q > 0:
                out.append({"symbol": re.sub(r"-EQ$", "", str(
                    h.get("tradingsymbol") or "").upper()), "qty": q,
                    "avg_price": float(h.get("averageprice") or 0)})
    else:
        d = _call(sess, "GET", "/portfolio/holdings")
        for h in d or []:
            q = float(h.get("quantity") or 0) + float(h.get("t1_quantity") or 0)
            if q > 0:
                out.append({"symbol": str(h.get("tradingsymbol") or "").upper(),
                            "qty": q,
                            "avg_price": float(h.get("average_price") or 0)})
    return out


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
        return float(val), ""
    except BrokerError as e:
        return None, str(e)
    except (TypeError, ValueError):
        return None, "funds reply had no balance field"


# ================================================================== orders
def place_amo_order(symbol, quantity, is_mtf, broker=None, token=None,
                    sess=None, order_type="MARKET", price=0.0):
    """BUY, NSE cash, After Market Order for the next open.
    is_mtf=False -> delivery (Dhan CNC / Angel DELIVERY / Kite CNC)
    is_mtf=True  -> margin trading (Dhan MTF / Angel MARGIN / Kite MTF)
    Returns (ok, order_id or error text, status). Never sells."""
    try:
        sess = _resolve(broker, token, sess)
    except BrokerError as e:
        return False, str(e), "ERROR"
    sym = str(symbol).upper()
    qty = int(quantity)
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
    lim = float(price) if order_type == "LIMIT" else 0.0
    try:
        if sess.broker == "DHAN":
            body = {"dhanClientId": sess.client_id,
                    "correlationId": ("RB%s%s" % (dt.date.today().strftime(
                        "%y%m%d"), sym))[:30],
                    "transactionType": "BUY", "exchangeSegment": "NSE_EQ",
                    "productType": "MTF" if is_mtf else "CNC",
                    "orderType": order_type, "validity": "DAY",
                    "securityId": str(x["id"]), "quantity": qty,
                    "disclosedQuantity": 0, "price": lim, "triggerPrice": 0.0,
                    "afterMarketOrder": True, "amoTime": "OPEN"}
            d = _call(sess, "POST", "/orders", body=body)
            status = str(d.get("orderStatus", "")).upper()
            oid = str(d.get("orderId", ""))
            if status == "REJECTED" or not oid:
                return False, "order rejected (%s)" % (
                    d.get("omsErrorDescription") or _err(d)), \
                    status or "REJECTED"
            return True, oid, status
        if sess.broker == "ANGEL":
            body = {"variety": "AMO", "tradingsymbol": x["tsym"],
                    "symboltoken": str(x["id"]), "transactiontype": "BUY",
                    "exchange": "NSE", "ordertype": order_type,
                    "producttype": "MARGIN" if is_mtf else "DELIVERY",
                    "duration": "DAY", "price": "%.2f" % lim, "squareoff": "0",
                    "stoploss": "0", "quantity": str(qty)}
            d = _call(sess, "POST",
                      "/rest/secure/angelbroking/order/v1/placeOrder", body=body)
            oid = str((d or {}).get("orderid") or "")
            return (True, oid, "AMO") if oid else \
                (False, "no order id in reply", "ERROR")
        form = {"tradingsymbol": x["tsym"], "exchange": "NSE",
                "transaction_type": "BUY", "order_type": order_type,
                "quantity": qty, "product": "MTF" if is_mtf else "CNC",
                "validity": "DAY"}
        if order_type == "LIMIT":
            form["price"] = lim
        d = _call(sess, "POST", "/orders/amo", form=form)
        oid = str((d or {}).get("order_id") or "")
        return (True, oid, "AMO") if oid else \
            (False, "no order id in reply", "ERROR")
    except BrokerError as e:
        return False, str(e), "ERROR"


_STATUS = {"TRADED": "TRADED", "COMPLETE": "TRADED", "REJECTED": "REJECTED",
           "CANCELLED": "CANCELLED", "EXPIRED": "EXPIRED"}


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
            t = _call(sess, "GET", "/trades/%s" % oid)
            rows = t if isinstance(t, list) else [t]
            q = sum(int(r.get("tradedQuantity") or 0) for r in rows)
            v = sum(int(r.get("tradedQuantity") or 0) *
                    float(r.get("tradedPrice") or 0) for r in rows)
            avg = v / q if q else None
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
