#!/usr/bin/env python3
"""
SIP  --  buy a stock / ETF regularly: Monthly / Weekly / Daily
==============================================================

You fill the SIP sheet of the Portfolio file (yellow columns):
  Symbol | Frequency (Monthly / Weekly / Daily) | Day (Monthly: 1-28,
  Weekly: Mon-Fri, Daily: -) | Amount per buy (Rs, YOUR money) |
  Total capital (Rs, stop when this much is in; blank = no limit) |
  Product (BUY = normal / BUY MTF) | Active (YES / NO) | Start date

rbtrack (after 15:30) then places an AMO for every SIP that is due:
  Monthly  once a month, on/after that day of the month
  Weekly   once a week, on/after that weekday
  Daily    every weekday
A missed day is caught up later in the SAME month / week (not later).
Qty = floor(amount x leverage / price); leverage 1 for BUY, the broker's real
MTF leverage for BUY MTF. Last buy is cut to the capital left.

Every SIP buy goes to split.csv (strategy SIP, no sell rule) -> the journal
tracks it like any trade (fees, dividends, P&L, tax estimate).
Files: accounts/<..>/data/sip.csv (your plans), sip_log.csv (every buy).

Backtest (sip_backtest.py): plain SIP ~ Nifty; weekly/daily add nothing over
monthly; single stocks: worst 10% of stocks ~ -4%/yr in each half.
"""

import os
import math
import datetime as dt

import pandas as pd

import momentum_screener as ms

FREQS = ("Monthly", "Weekly", "Daily")
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")
PRODUCTS = ("BUY", "BUY MTF")
PLAN_COLS = ["id", "symbol", "frequency", "day", "amount", "capital",
             "product", "active", "start"]
LOG_COLS = ["date", "sip_id", "symbol", "period", "qty", "price", "own",
            "product", "order_id", "status"]
# sheet header -> plan column
SHEET = [("Symbol", "symbol"), ("Frequency", "frequency"), ("Day", "day"),
         ("Amount per buy (Rs)", "amount"), ("Total capital (Rs)", "capital"),
         ("Product", "product"), ("Active", "active"),
         ("Start date", "start")]
STATUS = ["Invested (Rs)", "Buys", "Last buy", "Next due", "Capital left (Rs)",
          "id"]


def _dir():
    return os.path.dirname(ms.SPLIT_FILE)


def plans_path():
    return os.path.join(_dir(), "sip.csv")


def log_path():
    return os.path.join(_dir(), "sip_log.csv")


def _read(p, cols):
    if not os.path.exists(p):
        return pd.DataFrame(columns=cols)
    d = pd.read_csv(p, dtype=str).fillna("")
    for c in cols:
        if c not in d:
            d[c] = ""
    return d[cols]


def load_plans():
    return _read(plans_path(), PLAN_COLS)


def load_log():
    return _read(log_path(), LOG_COLS)


def _num(v):
    try:
        x = float(str(v).replace(",", "").strip())
        return None if x != x else x
    except (TypeError, ValueError):
        return None


NSE_LISTS = ("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
             "https://nsearchives.nseindia.com/content/equities/"
             "eq_etfseclist.csv")


def symbol_choices(sess=None):
    """['TATAMOTORS | Tata Motors Limited', 'NIFTYBEES | ...', ...] for the SIP
    dropdown: NSE equity (+ ETF) list with names, cached a week in data/,
    plus every symbol the broker trades (ETFs without a name get '-')."""
    import time
    import requests
    import daily_screener as ds
    p = os.path.join(ds.DATA, "_nse_symbols.csv")
    names = {}
    if not os.path.exists(p) or time.time() - os.path.getmtime(p) > 7 * 86400:
        rows = []
        for u in NSE_LISTS:
            try:
                r = requests.get(u, headers={"User-Agent": "Mozilla/5.0"},
                                 timeout=30)
                if r.status_code == 200 and r.text.startswith(("SYMBOL",
                                                               "Symbol")):
                    from io import StringIO
                    d = pd.read_csv(StringIO(r.text), index_col=False)
                    d.columns = [c.strip().upper() for c in d.columns]
                    nm = next((c for c in d.columns if "NAME" in c or
                               "UNDERLYING" in c), None)
                    for _, x in d.iterrows():
                        rows.append((str(x["SYMBOL"]).strip().upper(),
                                     str(x[nm]).strip() if nm else ""))
            except Exception:
                pass
        if rows:
            pd.DataFrame(rows, columns=["symbol", "name"]).drop_duplicates(
                "symbol").to_csv(p, index=False)
    if os.path.exists(p):
        d = pd.read_csv(p, dtype=str).fillna("")
        names = dict(zip(d["symbol"], d["name"]))
    syms = set(names)
    if sess is not None:
        try:
            import broker_api as ba
            syms |= {k for k in ba.symbol_map(sess) if k and k != ba.INDEX
                     and k in names or (k and "TEST" not in k and
                                        not k[0].isdigit() and k != ba.INDEX)}
        except Exception:
            pass
    return ["%s | %s" % (k, names.get(k) or "-") for k in sorted(syms)]


def _clean(r):
    """Normalise one plan row; returns (row, problem or '')."""
    sym = str(r.get("symbol", "")).split("|")[0].upper().strip()
    fr = str(r.get("frequency", "")).strip().capitalize() or "Monthly"
    if fr not in FREQS:
        return None, "%s: Frequency must be Monthly / Weekly / Daily" % sym
    day = str(r.get("day", "")).strip()
    if fr == "Monthly":
        d = _num(day)
        day = str(int(d)) if d and 1 <= d <= 28 else "1"
    elif fr == "Weekly":
        day = day[:3].capitalize() if day[:3].capitalize() in DAYS else "Mon"
    else:
        day = ""
    amt = _num(r.get("amount"))
    if not amt or amt <= 0:
        return None, "%s: Amount per buy missing" % sym
    cap = _num(r.get("capital"))
    prod = " ".join(str(r.get("product", "")).upper().split()) or "BUY"
    if prod not in PRODUCTS:
        return None, "%s: Product must be BUY or BUY MTF" % sym
    act = str(r.get("active", "")).upper().strip() or "YES"
    start = str(r.get("start", "")).strip()[:10]
    try:
        start = pd.Timestamp(start).date().isoformat() if start else ""
    except ValueError:
        start = ""
    return {"id": str(r.get("id", "")).strip(), "symbol": sym,
            "frequency": fr, "day": day, "amount": "%g" % amt,
            "capital": "%g" % cap if cap else "", "product": prod,
            "active": "NO" if act.startswith("N") else "YES",
            "start": start}, ""


def read_sheet(xlsx):
    """SIP sheet of a Portfolio file -> sip.csv (your edits win).
    Returns list of problems (rows ignored)."""
    try:
        d = pd.read_excel(xlsx, sheet_name="SIP", dtype=str)
    except Exception:
        return []                       # older file without a SIP sheet
    d = d.fillna("")
    if "Symbol" not in d:
        return []
    old = load_plans()
    rows, probs, used = [], [], set(old["id"])
    for _, x in d.iterrows():
        sym = str(x.get("Symbol", "")).split("|")[0].strip()
        if not sym or " " in sym or len(sym) > 20:      # blank / note lines
            continue
        r = {k: x.get(h, "") for h, k in SHEET}
        r["id"] = x.get("id", "")
        c, p = _clean(r)
        if p:
            probs.append(p)
            continue
        if not c["id"]:                 # same plan read again -> same id
            m = old[(old["symbol"] == c["symbol"]) &
                    (old["frequency"] == c["frequency"]) &
                    (~old["id"].isin([x["id"] for x in rows]))]
            if len(m):
                c["id"] = m["id"].iloc[0]
        if not c["id"]:
            n = 1
            while "%s-%d" % (c["symbol"], n) in used:
                n += 1
            c["id"] = "%s-%d" % (c["symbol"], n)
            used.add(c["id"])
        rows.append(c)
    new = pd.DataFrame(rows, columns=PLAN_COLS)
    tmp = plans_path() + ".tmp"
    new.to_csv(tmp, index=False)
    os.replace(tmp, plans_path())
    return probs


def period(freq, d):
    d = pd.Timestamp(d)
    if freq == "Monthly":
        return d.strftime("%Y-%m")
    if freq == "Weekly":
        y, w, _ = d.isocalendar()
        return "%d-W%02d" % (y, w)
    return d.strftime("%Y-%m-%d")


def _invested(log, pid):
    g = log[(log["sip_id"] == pid) & (log["status"] != "REJECTED")]
    return sum(_num(x) or 0 for x in g["own"]), g


def status(today=None):
    """Plan rows + Invested / Buys / Last buy / Next due / Capital left."""
    today = pd.Timestamp(str(today or dt.date.today())[:10])
    plans, log = load_plans(), load_log()
    out = []
    for _, p in plans.iterrows():
        inv, g = _invested(log, p["id"])
        cap = _num(p["capital"])
        left = cap - inv if cap else None
        out.append({"Symbol": p["symbol"], "Frequency": p["frequency"],
                    "Day": p["day"] or "-",
                    "Amount per buy (Rs)": _num(p["amount"]),
                    "Total capital (Rs)": cap, "Product": p["product"],
                    "Active": p["active"], "Start date": p["start"],
                    "Invested (Rs)": round(inv), "Buys": len(g),
                    "Last buy": max(g["date"]) if len(g) else "-",
                    "Next due": next_due(p, log, today),
                    "Capital left (Rs)": round(left) if left is not None
                    else None, "id": p["id"]})
    return out


def _is_due(p, log, d):
    if p["active"] != "YES" or d.weekday() >= 5 and p["frequency"] == "Daily":
        return False
    if p["start"] and d.date().isoformat() < p["start"]:
        return False
    inv, g = _invested(log, p["id"])
    cap = _num(p["capital"])
    if cap and cap - inv < 1:
        return False
    if (g["period"] == period(p["frequency"], d)).any():
        return False
    if p["frequency"] == "Monthly":
        return d.day >= int(p["day"] or 1)
    if p["frequency"] == "Weekly":
        return d.weekday() >= DAYS.index(p["day"] or "Mon")
    return True


def next_due(p, log, today):
    if p["active"] != "YES":
        return "paused"
    cap = _num(p["capital"])
    if cap and cap - _invested(log, p["id"])[0] < 1:
        return "DONE (capital used)"
    for k in range(0, 40):
        d = today + pd.Timedelta(days=k)
        if _is_due(p, log, d):
            return "aaj (rbtrack)" if k == 0 else d.strftime("%d %b")
    return "-"


def due(today=None):
    today = pd.Timestamp(str(today or dt.date.today())[:10])
    plans, log = load_plans(), load_log()
    out = []
    for _, p in plans.iterrows():
        if _is_due(p, log, today):
            inv, _ = _invested(log, p["id"])
            cap = _num(p["capital"])
            amt = _num(p["amount"])
            if cap:
                amt = min(amt, cap - inv)
            out.append(dict(p, amount_now=amt,
                            period=period(p["frequency"], today)))
    return out


def plan_orders(items, px, lev_of, today):
    """Due SIPs -> split.csv-style rows for rbtrack (LIVE only)."""
    new, skip = [], []
    for p in items:
        s = p["symbol"]
        if s not in px:
            skip.append("SIP %s (no price)" % s)
            continue
        price, src = px[s]
        mtf = p["product"] == "BUY MTF"
        lev, lev_note = lev_of(s, price) if mtf else (1.0, "")
        shares = int(math.floor(p["amount_now"] * lev / price))
        if shares < 1:
            skip.append("SIP %s (Rs %g buys 0 shares at %.0f)"
                        % (s, p["amount_now"], price))
            continue
        own = shares * price / lev
        new.append({"symbol": s, "swing_qty": 0, "investing_qty": shares,
                    "momentum_qty": 0, "entry_price": round(price, 2),
                    "entry_date": today, "strategy": "SIP", "mode": "LIVE",
                    "product": "MTF" if mtf else "CNC", "order_id": "",
                    "shares": shares, "lev": lev, "sip_id": p["id"],
                    "sip_period": p["period"], "own": round(own, 2),
                    "note": "SIP %s %s | own Rs %s | %s%s" % (
                        p["id"], p["frequency"], format(int(own), ","), src,
                        " | " + lev_note if mtf else "")})
    return new, skip


def log_buys(rows, today):
    log = load_log()
    add = [{"date": today, "sip_id": x["sip_id"], "symbol": x["symbol"],
            "period": x["sip_period"], "qty": x["shares"],
            "price": x["entry_price"], "own": x["own"],
            "product": x["product"], "order_id": x.get("order_id", ""),
            "status": "SENT" if x.get("order_id") else "MANUAL"}
           for x in rows if x.get("sip_id")]
    if add:
        log = pd.concat([log, pd.DataFrame(add)], ignore_index=True)
        log.to_csv(log_path(), index=False)


def mark_rejected(order_id):
    log = load_log()
    m = log["order_id"] == str(order_id)
    if m.any():
        log.loc[m, "status"] = "REJECTED"
        log.to_csv(log_path(), index=False)
