
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
    -> backtest.py (>= Rs 10,000 Cr, 2013-2026): win 39%, avg trade
       +11.8%, profit factor 2.43
    Both rules are checked on EVERY day since entry_date in split.csv,
    so an exit you missed on an earlier day is still reported.

INVESTING leg
    * Only exits on a Stage-4 breakdown: close below the 30-week MA,
      with the 30-week MA itself declining, held for 10 sessions.
    * A 20% drawdown is NOT an exit here. Selling early is what
      turned multibaggers into small winners in every test.

SETUP  (one time)
-----------------
    pip3 install pandas numpy requests

    Keep this file next to daily_screener.py in ~/Desktop/RB_Screener
    (it re-uses the screener's Dhan price code). dhan_token.txt is the
    same file the screener reads. split.csv is auto-created on the
    first run. The Dhan client ID is read from the token itself.

PRICES  (v2)
------------
    Free history (lags a few days) + missing days filled from Dhan +
    today's live price from Dhan. During market hours today's price is
    PROVISIONAL: a verdict marked "*" only counts if the stock closes
    there. Without a valid token it says loudly that data is old.

DAILY USE
---------
    1. paste today's token into dhan_token.txt
    2. python3 ~/Desktop/RB_Screener/position_tracker.py
"""

import os
import sys
import json
import datetime as dt

import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daily_screener as ds     # shared price / Dhan code -- rules untouched

# ------------------------------------------------------------------ config
CLIENT_ID = ""                  # read from the token at start-up
TOKEN_FILE = ds.TOKEN_FILE
SPLIT_FILE = os.path.join(ds.HERE, "split.csv")
RANKS_FILE = os.path.join(ds.DATA, "momentum_ranks_latest.csv")
MOMENTUM_KEEP_RANK = 40         # momentum_screener: keep while rank <= 2 x 20
# Smart trailing stop for the MOMENTUM leg. OFF because it destroyed the
# backtest (RAMOM 18.3%/yr -> 2.4%/yr with a 3xATR trail; breakeven at +20%
# alone 18.3% -> 16.6%). Set True only if you accept that.
MOMENTUM_SMART_SL = False
SMART_SL_ATR = 3.0
SMART_SL_BREAKEVEN = 0.20

DHAN_HOLDINGS = "https://api.dhan.co/v2/holdings"


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
    cid, exp = ds.token_info(tok)
    if not cid:
        print("Could not read the client id from the token -- is "
              "dhan_token.txt holding the full token?")
        sys.exit(1)
    if exp and exp < ds.now_ist():
        print("Token in dhan_token.txt expired at %s. Paste a fresh one."
              % exp.strftime("%d %b %H:%M"))
        sys.exit(1)
    global CLIENT_ID
    CLIENT_ID = ds.CLIENT_ID = cid      # ds.dhan_headers() uses it
    if exp:
        print("  Dhan token OK, valid till %s" % exp.strftime("%d %b %H:%M"))
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
                 "investing_qty": int(h["qty"]), "momentum_qty": 0,
                 "entry_price": h["avg_price"],
                 "entry_date": dt.date.today().isoformat(), "strategy": "",
                 "note": "EDIT ME -- move qty into swing_qty as needed"}
                for h in holdings]
        if not rows:
            rows = [{"symbol": "EXAMPLE", "swing_qty": 0, "investing_qty": 0,
                     "momentum_qty": 0, "entry_price": 0,
                     "entry_date": "2026-09-24", "strategy": "",
                     "note": "delete this row"}]
        pd.DataFrame(rows).to_csv(SPLIT_FILE, index=False)
        print("Created %s from your holdings.\n"
              "Open it, set how many shares of each name are SWING and how "
              "many are INVESTING, then run again." % SPLIT_FILE)
        sys.exit(0)

    sp = pd.read_csv(SPLIT_FILE)
    sp["symbol"] = sp["symbol"].astype(str).str.upper().str.strip()
    # v3 columns (auto_tracker_update.py): momentum leg + strategy label
    if "momentum_qty" not in sp:
        sp["momentum_qty"] = 0
    if "strategy" not in sp:
        sp["strategy"] = ""
    return sp


# ------------------------------------------------------------------ prices
def load_prices(token, symbols, warns):
    """Free history + Dhan gap-fill + today's live price.
    Returns ({sym: close Series}, {sym: True if last bar is provisional},
    data_note)."""
    want = ds.last_expected_session()
    frames = {}
    for s in symbols:
        df = ds.fetch_eod(s.lower())
        if df is None or len(df) < 210:
            warns.append("%s: not enough price history to judge" % s)
            continue
        frames[s] = df
    if not frames:
        return {}, {}, "no price data"
    scrip, live = {}, {}
    try:
        scrip = ds.load_scrip_map()
        for s in list(frames):
            sid = scrip.get(s)
            if not sid:
                warns.append("%s: not in Dhan scrip master -- no gap-fill / "
                             "live price" % s)
                continue
            frames[s] = ds.gap_fill(frames[s], token, sid, "NSE_EQ", "EQUITY",
                                    want, warns, s)
        ids = {s: scrip[s] for s in frames if s in scrip}
        ltp = ds.dhan_ltp(token, list(ids.values()))
        live = {s: ltp[i] for s, i in ids.items() if i in ltp}
    except PermissionError as e:
        print("\n*** Dhan refused the request (%s)." % e)
        print("*** Token not expired by its own clock -> check that Data API "
              "access is active on your Dhan account.")
        print("*** Continuing WITHOUT Dhan -- prices below may be OLD. ***\n")
    except Exception as e:
        print("\n  ! Dhan price step failed (%s). Continuing without it." % e)

    now = ds.now_ist()
    today = now.date()
    # before 09:15 (or on a weekend) the live price is just an old close
    session_started = today.weekday() < 5 and (now.hour, now.minute) >= (9, 15)
    closes, lows, highs, prov = {}, {}, {}, {}
    for s, df in frames.items():
        c = df["Close"].copy()
        lo = df["Low"].copy()
        hi = df["High"].copy()
        p = False
        if s in live and session_started:
            if c.index[-1].date() < today and not (
                    not ds.market_open() and live[s] == c.iloc[-1]):
                # (same price after hours = holiday -> no new bar)
                # today's bar not in history yet -> use the live price
                c.loc[pd.Timestamp(today)] = live[s]
                lo.loc[pd.Timestamp(today)] = live[s]   # intraday low unknown
                hi.loc[pd.Timestamp(today)] = live[s]
                p = ds.market_open()
            elif c.index[-1].date() == today and ds.market_open():
                c.iloc[-1] = live[s]
                lo.iloc[-1] = min(lo.iloc[-1], live[s])
                hi.iloc[-1] = max(hi.iloc[-1], live[s])
                p = True
        closes[s], lows[s], prov[s] = c, lo, p
        highs[s] = hi
    last = max(c.index[-1] for c in closes.values()).date()
    note = "data to %s | %s" % (last, "Dhan live price" if live
                                else "NO live price")
    if last < want:
        note += "  !!! DATA IS BEHIND (expected %s) -- do not act on it" % want
    return closes, lows, highs, prov, note


# ------------------------------------------------------------------ rules
def _since(c, entry_date):
    """Bars from the entry day on. Unknown entry date -> last bar only."""
    try:
        d = pd.Timestamp(entry_date)
    except (ValueError, TypeError):
        d = None
    if d is None or d != d or d > c.index[-1]:
        return c.index[-1:]
    return c.index[c.index >= d]
def judge_swing(c, lo, entry_price, entry_date):
    """Backtest rules, checked on EVERY bar since entry (not just today):
    the day's low touching the 20% stop, or a close below the 40-week MA.
    A rule that fired on an earlier day is reported as a missed exit."""
    px = float(c.iloc[-1])
    ma = c.rolling(200).mean()
    ma40w = float(ma.iloc[-1])
    stop = entry_price * 0.80
    idx = _since(c, entry_date)
    hit_stop = idx[(lo.reindex(idx) <= stop).values]
    hit_ma = idx[(c.reindex(idx) < ma.reindex(idx)).values]
    first = min([x for x in (hit_stop[:1].tolist() + hit_ma[:1].tolist())],
                default=None)
    if first is not None:
        which = ("low touched the 20%% stop (%.1f)" % stop
                 if len(hit_stop) and hit_stop[0] == first else
                 "closed below the 40-week MA (%.1f)" % float(ma[first]))
        if first == c.index[-1]:
            return "EXIT", which, px, stop, ma40w
        return ("EXIT", "%s on %s -- rule already fired, you should be out"
                % (which, first.date()), px, stop, ma40w)

    to_stop = (px / stop - 1) * 100
    to_ma = (px / ma40w - 1) * 100
    nearest = min(to_stop, to_ma)
    if nearest < 4:
        return ("WATCH", "only %.1f%% above the nearer exit level" % nearest,
                px, stop, ma40w)
    return "HOLD", "%.1f%% clear of the nearer exit" % nearest, px, stop, ma40w


def judge_investing(c, entry_date):
    """Stage 4: 10 straight closes under a falling 30-week MA, checked on
    every bar since entry."""
    px = float(c.iloc[-1])
    ma30w = c.rolling(150).mean()
    cur = float(ma30w.iloc[-1])
    below = (c < ma30w).astype(int)
    run = below.groupby((below == 0).cumsum()).cumsum()     # streak length
    falling = ma30w < ma30w.shift(10)
    trig = (run >= 10) & falling
    idx = _since(c, entry_date)
    fired = idx[trig.reindex(idx).fillna(False).values]
    declining = bool(falling.iloc[-1])

    if len(fired):
        if fired[0] == c.index[-1]:
            return ("EXIT", "10 straight closes under a falling 30-week MA "
                    "-- Stage 4 breakdown", px, cur)
        return ("EXIT", "Stage 4 breakdown on %s -- rule already fired, you "
                "should be out" % fired[0].date(), px, cur)
    if px < cur and declining:
        return ("WATCH", "under a falling 30-week MA for %d session(s), exit "
                "at 10" % int(run.iloc[-1]), px, cur)
    if px < cur:
        return "WATCH", "under the 30-week MA but the MA is still rising", px, cur
    return "HOLD", "%.1f%% above the 30-week MA" % ((px / cur - 1) * 100), px, cur


def load_ranks(warns):
    """Latest full momentum ranking written by momentum_screener.py."""
    if not os.path.exists(RANKS_FILE):
        warns.append("no momentum ranking yet -- run rbscan "
                     "(momentum_screener.py) first")
        return {}, None
    d = pd.read_csv(RANKS_FILE)
    day = str(d["date"].iloc[0]) if "date" in d and len(d) else None
    if day and (pd.Timestamp(ds.now_ist().date()) - pd.Timestamp(day)).days > 5:
        warns.append("momentum ranking is from %s -- run rbscan for fresh "
                     "ranks" % day)
    return dict(zip(d["symbol"].astype(str).str.upper(), d["rank"])), day


def judge_momentum(sym, c, lo, hi, entry, entry_date, ranks):
    """Backtest rule: hold while rank <= 40, sell at the next monthly
    rebalance (1st trading day) once it drops below. Optional smart stop."""
    px = float(c.iloc[-1])
    rk = ranks.get(sym)
    stop = None
    if MOMENTUM_SMART_SL and entry > 0:
        tr = np.maximum(np.maximum(hi - lo, (hi - c.shift(1)).abs()),
                        (lo - c.shift(1)).abs())
        atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        idx = _since(c, entry_date)
        a0 = float(atr.reindex(idx).iloc[0]) if len(idx) else float(atr.iloc[-1])
        stop, top = entry - SMART_SL_ATR * a0, entry
        for d in idx:
            if lo[d] <= stop:
                return ("EXIT", "smart stop %.1f hit on %s (3xATR trail)"
                        % (stop, d.date()), px, rk, stop)
            top = max(top, c[d])
            stop = max(stop, top - SMART_SL_ATR * float(atr[d]))
            if c[d] >= entry * (1 + SMART_SL_BREAKEVEN):
                stop = max(stop, entry)
    if rk is None:
        return ("SELL@REBAL", "not in the eligible ranking (below Rs 10k Cr, "
                "illiquid or no data) -> sell at the next rebalance", px, rk,
                stop)
    if rk > MOMENTUM_KEEP_RANK:
        return ("SELL@REBAL", "rank %d > %d -> sell at the next monthly "
                "rebalance (1st trading day)" % (rk, MOMENTUM_KEEP_RANK), px,
                rk, stop)
    if rk > MOMENTUM_KEEP_RANK - 5:
        return "WATCH", "rank %d, close to the %d cut" % (rk, MOMENTUM_KEEP_RANK), \
            px, rk, stop
    return "HOLD", "rank %d (keep while <= %d)" % (rk, MOMENTUM_KEEP_RANK), \
        px, rk, stop


# ------------------------------------------------------------------ main
def main():
    token = read_token()
    print("Fetching holdings from Dhan ...")
    holdings = get_holdings(token)
    hq = {h["symbol"]: h for h in holdings}
    print("  %d holdings" % len(holdings))

    split = load_split(holdings)

    swing_rows, inv_rows, warnings = [], [], []

    syms = [str(x).strip().upper() for x in split["symbol"]
            if str(x).strip().upper() not in ("", "EXAMPLE", "NAN")]
    print("Loading prices (free history + Dhan fill + live) ...")
    closes, lows, highs, prov, data_note = load_prices(token, syms, warnings)
    ranks, ranks_date = load_ranks(warnings)
    mom_rows = []

    for _, r in split.iterrows():
        sym = str(r["symbol"]).strip().upper()
        if sym in ("", "EXAMPLE", "NAN"):
            continue
        sw = float(pd.to_numeric(r.get("swing_qty"), errors="coerce") or 0)
        iv = float(pd.to_numeric(r.get("investing_qty"), errors="coerce") or 0)
        mo = float(pd.to_numeric(r.get("momentum_qty"), errors="coerce") or 0)
        sw, iv, mo = [0.0 if x != x else x for x in (sw, iv, mo)]
        if sw + iv + mo == 0:
            continue

        held = hq.get(sym)
        if held is None:
            warnings.append("%s is in split.csv but not in your Dhan holdings"
                            " (fine if you are paper trading)" % sym)
        elif abs(held["qty"] - (sw + iv + mo)) > 0.5:
            warnings.append("%s: split.csv totals %g but Dhan shows %g"
                            % (sym, sw + iv + mo, held["qty"]))

        entry = float(r.get("entry_price") or 0)
        if entry <= 0 and held:
            entry = held["avg_price"]

        c = closes.get(sym)
        if c is None:
            continue
        star = "*" if prov.get(sym) else ""
        edate = r.get("entry_date")
        if sw > 0 and entry <= 0:
            warnings.append("%s: no entry price in split.csv and not in Dhan "
                            "holdings -- swing leg not judged" % sym)
            sw = 0

        if sw > 0:
            verdict, why, px, stop, ma40w = judge_swing(c, lows[sym], entry,
                                                        edate)
            if star and verdict != "HOLD" and "already fired" not in why:
                verdict, why = verdict + star, why + " (live price -- only " \
                    "counts if it CLOSES here)"
            swing_rows.append({
                "symbol": sym, "qty": int(sw), "entry": round(entry, 1),
                "price": round(px, 1),
                "pnl_pct": round((px / entry - 1) * 100, 1) if entry else 0,
                "stop_20pct": round(stop, 1), "ma40w": round(ma40w, 1),
                "verdict": verdict, "reason": why,
            })

        if mo > 0:
            verdict, why, px, rk, stop = judge_momentum(
                sym, c, lows[sym], highs[sym], entry, edate, ranks)
            mom_rows.append({
                "symbol": sym, "qty": int(mo), "entry": round(entry, 1),
                "price": round(px, 1),
                "pnl_pct": round((px / entry - 1) * 100, 1) if entry else 0,
                "rank": rk if rk is not None else "-",
                "smart_stop": round(stop, 1) if stop is not None else "off",
                "verdict": verdict, "reason": why,
            })

        if iv > 0:
            verdict, why, px, ma30w = judge_investing(c, edate)
            if star and verdict != "HOLD" and "already fired" not in why:
                verdict, why = verdict + star, why + " (live price -- only " \
                    "counts if it CLOSES here)"
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
        order = {"EXIT": 0, "EXIT*": 0, "SELL@REBAL": 0, "WATCH": 1,
                 "WATCH*": 1, "HOLD": 2}
        d = d.sort_values("verdict", key=lambda s: s.map(order))
        print(d.drop(columns=["reason"]).to_string(index=False))
        for _, x in d.iterrows():
            if x["verdict"] != "HOLD":
                print("   %-12s %-5s  %s" % (x["symbol"], x["verdict"], x["reason"]))
        p = os.path.join(ds.REPORTS, "%s_%s.csv" % (fname, stamp))
        d.to_csv(p, index=False)
        print("  saved: %s" % p)

    print("\n" + data_note)
    show("SWING LEG", swing_rows, "tracker_swing")
    show("INVESTING LEG", inv_rows, "tracker_investing")
    show("MOMENTUM LEG (ranking of %s)" % (ranks_date or "n/a"), mom_rows,
         "tracker_momentum")

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
  Momentum leg: trade only on the 1st trading day of the month. Sell a
  holding when its rank is > 40 then; no stop (a trailing stop cut the
  backtest from ~18%/yr to ~2%/yr).
""")


if __name__ == "__main__":
    main()
