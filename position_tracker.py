
#!/usr/bin/env python3
"""
DAILY POSITION TRACKER  --  swing + investing legs
==================================================

WHAT IT DOES
------------
1. Pulls your live holdings from Dhan (symbol + total quantity + avg price).
2. Reads split.csv -- YOUR decision of how much of each holding is a
   SWING position and how much is a LONG-TERM INVESTING position.
3. Applies the exit rules that won the backtests, separately per leg.
4. Prints, and saves, a HOLD / WATCH / EXIT verdict per leg.

EXIT RULES  (do not "improve" these -- every tightening lost money in testing)
-----------------------------------------------------------------------------
SWING leg
    * Fixed stop at 20% below YOUR entry price. Not trailing.
    * Exit on a daily CLOSE below the 40-week moving average.
    * No profit target. No breakeven shift.
    -> tested: 47.5% win rate, avg trade +20.8%, profit factor 3.99

INVESTING leg
    * Only exits on a Stage-4 breakdown: close below the 30-week MA,
      with the 30-week MA itself declining, held for 10 sessions.
    * A 20% drawdown is NOT an exit here. Selling early is what
      turned multibaggers into small winners in every test.

SETUP  (one time)
-----------------
    pip install pandas numpy requests

    Put these three files in one folder:
        position_tracker.py     <- this file
        dhan_token.txt          <- see below
        split.csv               <- auto-created on first run

    dhan_token.txt : paste your Dhan access token as a single line.
    It expires every 24 hours, so paste a fresh one each morning.
    Nothing else in the file. Never share this file.

    Your Dhan client ID goes in the CLIENT_ID constant below (that one
    does not change).

DAILY USE
---------
    1. paste today's token into dhan_token.txt
    2. python3 position_tracker.py
"""

import os
import io
import sys
import json
import datetime as dt

import numpy as np
import pandas as pd
import requests

# ------------------------------------------------------------------ config
CLIENT_ID = "1100120973"   # does not expire, set once

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(HERE, "dhan_token.txt")
SPLIT_FILE = os.path.join(HERE, "split.csv")
DATA = os.path.join(HERE, "data")            # shared with daily_screener.py
os.makedirs(DATA, exist_ok=True)

DHAN_HOLDINGS = "https://api.dhan.co/v2/holdings"
EOD_BASE = "https://raw.githubusercontent.com/BennyThadikaran/eod2_data/main/daily/"


# ------------------------------------------------------------------ token
def read_token():
    if not os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "w") as f:
            f.write("")
        print("Created %s -- paste today's Dhan access token into it, "
              "then run again." % TOKEN_FILE)
        sys.exit(1)
    tok = open(TOKEN_FILE).read().strip()
    if not tok:
        print("dhan_token.txt is empty. Paste today's token and run again.")
        sys.exit(1)
    return tok


def get_holdings(token):
    """Returns list of dicts: symbol, qty, avg_price. Exits loudly on a
    stale token rather than silently returning nothing."""
    r = requests.get(
        DHAN_HOLDINGS,
        headers={"access-token": token, "client-id": CLIENT_ID,
                 "Accept": "application/json"},
        timeout=30,
    )
    if r.status_code in (401, 403):
        print("\n*** Dhan rejected the token (HTTP %d). It has most likely "
              "expired -- tokens last 24 hours.\n    Paste a fresh one into "
              "dhan_token.txt and run again. ***\n" % r.status_code)
        sys.exit(1)
    try:
        data = r.json()
    except Exception:
        print("Unexpected reply from Dhan:", r.text[:300])
        sys.exit(1)

    if isinstance(data, dict):
        code = str(data.get("errorCode", ""))
        if "1111" in code or "No holdings" in json.dumps(data):
            print("Dhan reports no holdings in the demat account.")
            return []
        if data.get("errorType") or data.get("errorCode"):
            print("Dhan error:", json.dumps(data)[:300])
            sys.exit(1)
        data = data.get("data", [])

    out = []
    for h in data:
        qty = float(h.get("totalQty") or h.get("availableQty") or 0)
        if qty <= 0:
            continue
        out.append({
            "symbol": (h.get("tradingSymbol") or h.get("symbol") or "").upper(),
            "qty": qty,
            "avg_price": float(h.get("avgCostPrice") or 0),
        })
    return out


# ------------------------------------------------------------------ split
def load_split(holdings):
    """split.csv is the one file you maintain by hand."""
    if not os.path.exists(SPLIT_FILE):
        rows = [{"symbol": h["symbol"], "swing_qty": 0,
                 "investing_qty": int(h["qty"]),
                 "entry_price": h["avg_price"],
                 "entry_date": dt.date.today().isoformat(),
                 "note": "EDIT ME -- move qty into swing_qty as needed"}
                for h in holdings]
        if not rows:
            rows = [{"symbol": "EXAMPLE", "swing_qty": 0, "investing_qty": 0,
                     "entry_price": 0, "entry_date": "2026-09-24",
                     "note": "delete this row"}]
        pd.DataFrame(rows).to_csv(SPLIT_FILE, index=False)
        print("Created %s from your holdings.\n"
              "Open it, set how many shares of each name are SWING and how "
              "many are INVESTING, then run again." % SPLIT_FILE)
        sys.exit(0)

    sp = pd.read_csv(SPLIT_FILE)
    sp["symbol"] = sp["symbol"].str.upper().str.strip()
    return sp


# ------------------------------------------------------------------ prices
def fetch_eod(sym):
    """Daily adjusted OHLC from the same free source the screener uses."""
    fn = sym.lower().replace("&", "").replace(" ", "")
    path = os.path.join(DATA, fn + ".csv")
    if os.path.exists(path):
        age = dt.datetime.now() - dt.datetime.fromtimestamp(os.path.getmtime(path))
        if age.total_seconds() < 20 * 3600:
            return pd.read_csv(path, parse_dates=["Date"], index_col="Date")
    try:
        r = requests.get(EOD_BASE + fn + ".csv", timeout=30)
        if r.status_code != 200:
            return None
        open(path, "wb").write(r.content)
        return pd.read_csv(io.BytesIO(r.content), parse_dates=["Date"],
                           index_col="Date")
    except Exception:
        return None


# ------------------------------------------------------------------ rules
def judge_swing(df, entry_price):
    c = df["Close"]
    px = float(c.iloc[-1])
    ma40w = float(c.rolling(200).mean().iloc[-1])
    stop = entry_price * 0.80

    if px <= stop:
        return "EXIT", "closed at/below the 20%% stop (%.1f)" % stop, px, stop, ma40w
    if px < ma40w:
        return "EXIT", "closed below the 40-week MA (%.1f)" % ma40w, px, stop, ma40w

    to_stop = (px / stop - 1) * 100
    to_ma = (px / ma40w - 1) * 100
    nearest = min(to_stop, to_ma)
    if nearest < 4:
        return ("WATCH", "only %.1f%% above the nearer exit level" % nearest,
                px, stop, ma40w)
    return "HOLD", "%.1f%% clear of the nearer exit" % nearest, px, stop, ma40w


def judge_investing(df):
    c = df["Close"]
    px = float(c.iloc[-1])
    ma30w = c.rolling(150).mean()
    cur = float(ma30w.iloc[-1])
    declining = float(ma30w.iloc[-1]) < float(ma30w.iloc[-11])
    below_10 = bool((c.iloc[-10:] < ma30w.iloc[-10:]).all())

    if below_10 and declining:
        return ("EXIT", "10 straight closes under a falling 30-week MA "
                "-- Stage 4 breakdown", px, cur)
    if px < cur and declining:
        return ("WATCH", "under a falling 30-week MA, not yet 10 sessions",
                px, cur)
    if px < cur:
        return "WATCH", "under the 30-week MA but the MA is still rising", px, cur
    return "HOLD", "%.1f%% above the 30-week MA" % ((px / cur - 1) * 100), px, cur


# ------------------------------------------------------------------ main
def main():
    token = read_token()
    print("Fetching holdings from Dhan ...")
    holdings = get_holdings(token)
    hq = {h["symbol"]: h for h in holdings}
    print("  %d holdings" % len(holdings))

    split = load_split(holdings)

    swing_rows, inv_rows, warnings = [], [], []

    for _, r in split.iterrows():
        sym = str(r["symbol"]).strip().upper()
        if sym in ("", "EXAMPLE", "NAN"):
            continue
        sw = float(r.get("swing_qty") or 0)
        iv = float(r.get("investing_qty") or 0)
        if sw + iv == 0:
            continue

        held = hq.get(sym)
        if held is None:
            warnings.append("%s is in split.csv but not in your Dhan holdings"
                            % sym)
        elif abs(held["qty"] - (sw + iv)) > 0.5:
            warnings.append("%s: split.csv totals %g but Dhan shows %g"
                            % (sym, sw + iv, held["qty"]))

        entry = float(r.get("entry_price") or 0)
        if entry <= 0 and held:
            entry = held["avg_price"]

        df = fetch_eod(sym)
        if df is None or len(df) < 210:
            warnings.append("%s: not enough price history to judge" % sym)
            continue
        df = df[~df.index.duplicated(keep="last")].sort_index()

        if sw > 0:
            verdict, why, px, stop, ma40w = judge_swing(df, entry)
            swing_rows.append({
                "symbol": sym, "qty": int(sw), "entry": round(entry, 1),
                "price": round(px, 1),
                "pnl_pct": round((px / entry - 1) * 100, 1) if entry else 0,
                "stop_20pct": round(stop, 1), "ma40w": round(ma40w, 1),
                "verdict": verdict, "reason": why,
            })

        if iv > 0:
            verdict, why, px, ma30w = judge_investing(df)
            inv_rows.append({
                "symbol": sym, "qty": int(iv), "entry": round(entry, 1),
                "price": round(px, 1),
                "pnl_pct": round((px / entry - 1) * 100, 1) if entry else 0,
                "ma30w": round(ma30w, 1),
                "verdict": verdict, "reason": why,
            })

    stamp = dt.date.today().isoformat()

    def show(title, rows, fname):
        print("\n==== %s ====" % title)
        if not rows:
            print("  (none)")
            return
        d = pd.DataFrame(rows)
        order = {"EXIT": 0, "WATCH": 1, "HOLD": 2}
        d = d.sort_values("verdict", key=lambda s: s.map(order))
        print(d.drop(columns=["reason"]).to_string(index=False))
        for _, x in d.iterrows():
            if x["verdict"] != "HOLD":
                print("   %-12s %-5s  %s" % (x["symbol"], x["verdict"], x["reason"]))
        p = os.path.join(HERE, "%s_%s.csv" % (fname, stamp))
        d.to_csv(p, index=False)
        print("  saved: %s" % p)

    show("SWING LEG", swing_rows, "tracker_swing")
    show("INVESTING LEG", inv_rows, "tracker_investing")

    if warnings:
        print("\n---- check these ----")
        for w in warnings:
            print("  !", w)

    print("""
REMEMBER
  The swing stop is fixed at 20% below your entry. Do not trail it,
  do not tighten it, do not set a profit target -- each of those cut
  returns in every backtest we ran.
  The investing leg is meant to survive scary drawdowns. Its only
  exit is a Stage 4 breakdown.
""")


if __name__ == "__main__":
    main()
