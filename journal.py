#!/usr/bin/env python3
"""
TRADE JOURNAL  --  every trade the system made, with fees, dividends and tax
===========================================================================

File: accounts/<BROKER>_<ID>/data/journal.csv  (one row per buy; never
deleted, only closed). rb / rbport keeps it up to date:

  BUY    PAPER rows are logged when rbtrack adds them to split.csv; LIVE rows
         once the stock shows up in the demat (so rejected AMOs never count).
  SELL   LIVE: the stock left the demat AND the broker's trade history shows
         the sell (Dhan: any date; Angel / Zerodha: only on the day of the
         sale -> run rb that evening). No confirmation -> it waits and asks:
             rbtrack --sold SYMBOL PRICE [--date YYYY-MM-DD]
         PAPER: rbtrack --sold SYMBOL [PRICE] --paper   (no price = last price)
         A closed trade is removed from split.csv (backup kept).
  DIVIDEND  NSE corporate actions: ex-date while you held it x your qty.
  FEES   the account's broker rate card (equity delivery, official pages
         27 Sep 2026): STT 0.1% buy+sell, NSE 0.00307%, SEBI Rs 10/cr,
         GST 18%, stamp 0.015% buy, DP per sell (Dhan 12.5+GST, Zerodha
         15.34, Angel 20+GST), Angel brokerage min(Rs 20, 0.1%, >= Rs 5).
         MTF: + interest 12.49%/yr on the funded part (Dhan's rate).
  TAX    ESTIMATE per financial year: STCG 20.8% (<= 12 months), LTCG 13%
         above Rs 1.25 lakh; short-term losses set off against gains, long-
         term losses only against long-term; STT not deductible. Dividends
         are taxed at your slab -> not included. Your broker's P&L statement
         is what counts for the ITR.
  RULE   first day rb saw EXIT / SELL@REBAL for the trade vs the sell date.

PAPER_AUTO_EXIT (off): close PAPER trades by themselves on the day the rule
says EXIT (at that day's price) -- switch on only if you want it.
"""

import os
import re
import json
import datetime as dt

import numpy as np
import pandas as pd

import daily_screener as ds
import momentum_screener as ms

PAPER_AUTO_EXIT = False
SELLISH = ("EXIT", "SELL", "SELL@REBAL")
COLS = ["id", "symbol", "mode", "broker", "strategy", "product", "lev", "qty",
        "buy_date", "buy_price", "buy_fees", "buy_stt", "sell_date",
        "sell_price", "sell_fees", "sell_stt", "sell_reason", "dividends",
        "div_note", "exit_signal", "exit_signal_date", "seen_demat", "status",
        "note"]
EXCH, SEBI, GST, STAMP, STT = 0.0000307, 0.000001, 0.18, 0.00015, 0.001
DP = {"DHAN": 12.5 * 1.18, "ZERODHA": 15.34, "ANGEL": 20 * 1.18}
MTF_RATE = 0.1249
STCG, LTCG, LTCG_FREE = 0.208, 0.13, 125000.0


# ================================================================== files
def path():
    return os.path.join(os.path.dirname(ms.SPLIT_FILE), "journal.csv")


def load():
    p = path()
    if not os.path.exists(p):
        return pd.DataFrame(columns=COLS)
    j = pd.read_csv(p, dtype=str).fillna("")
    for c in COLS:
        if c not in j:
            j[c] = ""
    return j[COLS]


def save(j):
    p = path()
    tmp = p + ".tmp"
    j[COLS].to_csv(tmp, index=False)
    os.replace(tmp, p)


def _f(v, d=0.0):
    try:
        x = float(v)
        return d if x != x else x
    except (TypeError, ValueError):
        return d


# ================================================================== fees/tax
def fees(broker, side, value, product="CNC"):
    """(total fees, of which STT) for one side of an equity delivery trade."""
    b = str(broker or "DHAN").upper()
    brok = min(20.0, max(5.0, value * 0.001)) if b == "ANGEL" else 0.0
    exch, sebi = value * EXCH, value * SEBI
    other = brok + exch + sebi + GST * (brok + exch + sebi)
    stt = value * STT
    if side == "BUY":
        other += value * STAMP
    else:
        other += DP.get(b, DP["DHAN"])
    return round(other + stt, 2), round(stt, 2)


def mtf_interest(row, upto):
    if str(row["product"]).upper() != "MTF":
        return 0.0
    lev = max(1.0, _f(row["lev"], 4.0))
    days = max(0, (pd.Timestamp(upto) - pd.Timestamp(row["buy_date"])).days)
    val = _f(row["qty"]) * _f(row["buy_price"])
    return round(val * (1 - 1 / lev) * MTF_RATE * days / 365, 2)


def fy_of(d):
    d = pd.Timestamp(d)
    y = d.year if d.month >= 4 else d.year - 1
    return "FY %d-%02d" % (y, (y + 1) % 100)


def fy_tax(closed):
    """closed: rows with 'tax_gain' and 'long' -> estimated tax (set-off)."""
    st = sum(r["tax_gain"] for r in closed if not r["long"])
    lt = sum(r["tax_gain"] for r in closed if r["long"])
    if st < 0:                        # short-term loss also cuts long-term
        lt, st = lt + st, 0.0
    lt = max(0.0, lt)
    return round(max(st, 0.0) * STCG + max(lt - LTCG_FREE, 0.0) * LTCG, 2)


# ================================================================== dividends
def _ca_cache(sym):
    d = os.path.join(ds.DATA, "_nse_ca")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "%s.json" % re.sub(r"[^A-Z0-9&_-]", "_", sym))


def dividends_of(sym):
    """[(ex_date, Rs per share)] from NSE corporate actions (cached a day)."""
    p = _ca_cache(sym)
    today = dt.date.today().isoformat()
    try:
        with open(p) as f:
            c = json.load(f)
        if c.get("day") == today:
            return [tuple(x) for x in c["divs"]]
    except (IOError, OSError, ValueError, KeyError):
        c = None
    try:
        import news_feed as nf
        r = nf._nse_session().get(
            "https://www.nseindia.com/api/corporates-corporateActions",
            params={"index": "equities", "symbol": sym}, headers=nf.NSE_HDR,
            timeout=20)
        data = r.json() if r.status_code == 200 else None
    except Exception:
        data = None
    if not isinstance(data, list):
        return [tuple(x) for x in (c or {}).get("divs", [])]
    divs = []
    for x in data:
        subj = str(x.get("subject") or "").lower()
        if "dividend" not in subj:
            continue
        try:
            ex = dt.datetime.strptime(str(x.get("exDate")), "%d-%b-%Y").date()
        except ValueError:
            continue
        amt = sum(float(a) for a in re.findall(
            r"(?:rs|re|inr)\.?\s*([0-9]+(?:\.[0-9]+)?)", subj))
        if amt > 0:
            divs.append((ex.isoformat(), amt))
    with open(p, "w") as f:
        json.dump({"day": today, "divs": divs}, f)
    return divs


# ================================================================== sync
def _new_row(r, broker, qty, seen):
    price = _f(r["entry_price"])
    fee, stt = fees(broker, "BUY", qty * price)
    lev = ""
    m = re.search(r"MTF ([0-9.]+)x", str(r.get("note", "")))
    if m:
        lev = m.group(1)
    return {"id": "%s|%s|%s" % (r["symbol"], r["mode"],
                                str(r.get("entry_date", ""))[:10]),
            "symbol": r["symbol"], "mode": r["mode"], "broker": broker,
            "strategy": r.get("strategy", "") or "W+TT",
            "product": r.get("product", "") or "CNC", "lev": lev,
            "qty": "%g" % qty, "buy_date": str(r.get("entry_date", ""))[:10],
            "buy_price": "%.2f" % price, "buy_fees": "%.2f" % fee,
            "buy_stt": "%.2f" % stt, "sell_date": "", "sell_price": "",
            "sell_fees": "", "sell_stt": "", "sell_reason": "",
            "dividends": "0", "div_note": "", "exit_signal": "",
            "exit_signal_date": "", "seen_demat": "1" if seen else "",
            "status": "OPEN", "note": ""}


def _qty(r):
    q = sum(_f(r.get(c)) for c in ("swing_qty", "investing_qty", "momentum_qty"))
    if r.get("order_id") and "filled_qty_confirmed" in r and str(r.get("filled_qty_confirmed")) not in ("", "nan", "None"):
        q = min(q, max(0, _f(r.get("filled_qty_confirmed"))))
    return q


def close_row(j, i, price, date, reason, broker):
    q = _f(j.at[i, "qty"])
    fee, stt = fees(broker or j.at[i, "broker"], "SELL", q * price)
    j.at[i, "sell_price"] = "%.2f" % price
    j.at[i, "sell_date"] = str(date)[:10]
    j.at[i, "sell_fees"] = "%.2f" % fee
    j.at[i, "sell_stt"] = "%.2f" % stt
    j.at[i, "sell_reason"] = reason
    j.at[i, "status"] = "CLOSED"


def _split_after_close(symbol, mode, qty):
    """Take a sold qty out of split.csv (oldest row first), backup kept."""
    import shutil
    sf = ms.SPLIT_FILE
    if not os.path.exists(sf):
        return
    sp = pd.read_csv(sf, dtype={"order_id": str})
    m = sp.get("mode", pd.Series(["LIVE"] * len(sp))).fillna("LIVE") \
        .astype(str).str.upper().replace("", "LIVE")
    left = qty
    for i in sp.index[(sp["symbol"].astype(str).str.upper() == symbol) &
                      (m == mode)]:
        for c in ("swing_qty", "investing_qty", "momentum_qty"):
            if left <= 0:
                break
            have = _f(sp.at[i, c])
            take = min(have, left)
            sp.at[i, c] = have - take
            left -= take
    q = sum(pd.to_numeric(sp[c], errors="coerce").fillna(0)
            for c in ("swing_qty", "investing_qty", "momentum_qty"))
    sp = sp[q > 0]
    shutil.copyfile(sf, os.path.join(os.path.dirname(sf), "split_backup.csv"))
    sp.to_csv(sf + ".tmp", index=False)
    os.replace(sf + ".tmp", sf)


def sync(sp, demat, recs, last_px, sess=None, broker="DHAN", today=None,
         quiet=False):
    """Bring journal.csv up to date. sp = split.csv frame, demat = broker
    holdings [{symbol, qty}], recs = {(mode, symbol): recommendation},
    last_px = {symbol: last price}. Returns (journal frame, messages)."""
    today = str(today or ds.now_ist().date())[:10]
    j = load()
    msgs = []
    have = set(j["id"])
    dq = {h["symbol"]: float(h["qty"]) for h in demat or []}
    # ---- buys
    for _, r in (sp.iterrows() if len(sp) else []):
        r = r.to_dict()
        r["mode"] = str(r.get("mode") or "LIVE").upper()
        q = _qty(r)
        rid = "%s|%s|%s" % (r["symbol"], r["mode"],
                            str(r.get("entry_date", ""))[:10])
        if q <= 0:
            continue
        if rid in have:
            i = j.index[j["id"] == rid][0]
            # Shrinking a BUY lot here erases the difference needed by SELL reconciliation.
            if j.at[i, "status"] == "OPEN" and q > _f(j.at[i, "qty"]) + 1e-9:
                j.at[i, "qty"] = "%g" % q             # more fills (3 -> 6)
                fee, stt = fees(j.at[i, "broker"], "BUY",
                                q * _f(j.at[i, "buy_price"]))
                j.at[i, "buy_fees"], j.at[i, "buy_stt"] = \
                    "%.2f" % fee, "%.2f" % stt
                msgs.append("journal: %s %s qty now %g" % (r["mode"],
                                                           r["symbol"], q))
            if j.at[i, "status"] == "OPEN" and _f(r["entry_price"]) > 0 and \
                    abs(_f(j.at[i, "buy_price"]) - _f(r["entry_price"])) > 0.001:
                fee, stt = fees(j.at[i, "broker"], "BUY",
                                _f(j.at[i, "qty"]) * _f(r["entry_price"]))
                j.at[i, "buy_price"] = "%.2f" % _f(r["entry_price"])
                j.at[i, "buy_fees"], j.at[i, "buy_stt"] = \
                    "%.2f" % fee, "%.2f" % stt       # real fill from rbsync
            continue
        if r["mode"] == "LIVE" and r["symbol"] not in dq:
            continue                           # not delivered yet
        j = pd.concat([j, pd.DataFrame([_new_row(r, broker, q, r["mode"] ==
                                                 "LIVE")])],
                      ignore_index=True)
        have.add(rid)
        msgs.append("journal: bought %s %s x%g" % (r["mode"], r["symbol"], q))
    # ---- LIVE sells (confirmed by the broker's trade history only)
    for i in j.index[(j["status"] == "OPEN") & (j["mode"] == "LIVE")]:
        if j.at[i, "symbol"] in dq:
            j.at[i, "seen_demat"] = "1"
    op = j[(j["status"] == "OPEN") & (j["mode"] == "LIVE")]
    tr = None
    for sym, g in op.groupby("symbol"):
        g = g[g["seen_demat"] == "1"].sort_values("buy_date")
        open_q = sum(_f(x) for x in g["qty"])
        gone = open_q - dq.get(sym, 0.0)
        if gone < 0.5 or not len(g):
            continue
        if tr is None:                         # one call for all symbols
            seen = op[op["seen_demat"] == "1"]
            tr = ba_trades(sess, min(seen["buy_date"]), today)
        sells = [t for t in tr if t["symbol"] == sym and t["side"] == "SELL"
                 and t["date"] >= min(g["buy_date"])]
        sq = sum(t["qty"] for t in sells)
        if sq < 0.5:
            j.loc[g.index, "note"] = "SOLD? not in demat -- run: rbtrack " \
                "--sold %s PRICE --date YYYY-MM-DD" % sym
            msgs.append("! %s left the demat but no sell found in %s's trade "
                        "history -> rbtrack --sold %s PRICE --date YYYY-MM-DD"
                        % (sym, broker, sym))
            continue
        booked = j[(j["symbol"] == sym) & (j["mode"] == "LIVE") &
                   (j["status"] == "CLOSED") & (j["sell_date"] >= min(g["buy_date"]))]
        used = sum(_f(q) for q in booked["qty"])
        remaining = []
        for trade in sorted(sells, key=lambda t: (t["date"], str(t.get("time", "")))):
            taken = min(used, trade["qty"]); used -= taken
            if trade["qty"] > taken:
                remaining.append(dict(trade, qty=trade["qty"]-taken))
        sells = remaining
        sq = sum(t["qty"] for t in sells)
        if sq < 0.5:
            msgs.append("! %s quantity decreased but no unbooked SELL evidence; review in broker" % sym)
            continue
        avg = sum(t["qty"] * t["price"] for t in sells) / sq
        last = max(t["date"] for t in sells)
        left = min(gone, sq)
        for i in g.index:                      # FIFO, split a partial lot
            if left <= 0:
                break
            q = _f(j.at[i, "qty"])
            if q > left + 1e-9:
                rest = j.loc[i].to_dict()
                rest["qty"] = "%g" % (q - left)
                rest["id"] = rest["id"] + "|rest%s" % today
                f, s_ = fees(rest["broker"], "BUY", (q - left) *
                             _f(rest["buy_price"]))
                rest["buy_fees"], rest["buy_stt"] = "%.2f" % f, "%.2f" % s_
                j.at[i, "qty"] = "%g" % left
                f, s_ = fees(j.at[i, "broker"], "BUY", left *
                             _f(j.at[i, "buy_price"]))
                j.at[i, "buy_fees"], j.at[i, "buy_stt"] = "%.2f" % f, \
                    "%.2f" % s_
                j = pd.concat([j, pd.DataFrame([rest])], ignore_index=True)
                q = left
            close_row(j, i, avg, last, j.at[i, "exit_signal"] or
                      "sold in broker app", broker)
            j.at[i, "note"] = ""
            _split_after_close(sym, "LIVE", q)
            left -= q
            msgs.append("journal: SOLD LIVE %s x%g @ %.2f (%s)"
                        % (sym, q, avg, last))
    # ---- exit signals (for the "rule followed?" column)
    for i in j.index[j["status"] == "OPEN"]:
        rec = recs.get((j.at[i, "mode"], j.at[i, "symbol"]))
        if rec in SELLISH:
            if not j.at[i, "exit_signal_date"]:
                j.at[i, "exit_signal"], j.at[i, "exit_signal_date"] = \
                    rec, today
        elif rec is not None and j.at[i, "exit_signal_date"]:
            j.at[i, "exit_signal"], j.at[i, "exit_signal_date"] = "", ""
        if PAPER_AUTO_EXIT and j.at[i, "mode"] == "PAPER" and rec == "EXIT" \
                and j.at[i, "symbol"] in last_px:
            close_row(j, i, last_px[j.at[i, "symbol"]], today,
                      "EXIT rule (paper auto)", j.at[i, "broker"])
            _split_after_close(j.at[i, "symbol"], "PAPER", _f(j.at[i, "qty"]))
            msgs.append("journal: PAPER %s closed by the rule"
                        % j.at[i, "symbol"])
    # ---- dividends
    for sym in sorted(set(j["symbol"])):
        divs = dividends_of(sym)
        for i in j.index[j["symbol"] == sym]:
            end = j.at[i, "sell_date"] or today
            got = [(ex, a) for ex, a in divs
                   if j.at[i, "buy_date"] < ex <= end]
            q = _f(j.at[i, "qty"])
            j.at[i, "dividends"] = "%.2f" % sum(a * q for _, a in got)
            j.at[i, "div_note"] = ", ".join("%s Rs %g" % (
                pd.Timestamp(ex).strftime("%d %b %y"), a) for ex, a in got)
    save(j)
    if not quiet:
        for m in msgs:
            print("  " + m)
    return j, msgs


def ba_trades(sess, frm, to):
    if sess is None:
        return []
    try:
        import broker_api as ba
        return ba.trades(sess, pd.Timestamp(frm).date(), pd.Timestamp(to).date())
    except Exception:
        return []


def close_manual(symbol, price, date, mode, broker, last_px=None):
    """rbtrack --sold: close every OPEN row of symbol+mode."""
    j = load()
    idx = j.index[(j["symbol"] == symbol) & (j["mode"] == mode) &
                  (j["status"] == "OPEN")]
    if not len(idx):
        return "no OPEN %s trade for %s in the journal" % (mode, symbol)
    if price is None:
        price = (last_px or {}).get(symbol)
        if not price:
            return "no price for %s -- give it: rbtrack --sold %s PRICE" \
                % (symbol, symbol)
    q = 0.0
    for i in idx:
        close_row(j, i, float(price), date, j.at[i, "exit_signal"] or
                  "sold (entered by hand)", broker or j.at[i, "broker"])
        j.at[i, "note"] = ""
        q += _f(j.at[i, "qty"])
    save(j)
    _split_after_close(symbol, mode, q)
    return "closed %s %s x%g @ %.2f on %s" % (mode, symbol, q, float(price),
                                             str(date)[:10])


# ================================================================== numbers
def _nifty():
    try:
        df = ds.fetch_eod(ds.BENCH)
        return df["Close"] if df is not None else None
    except Exception:
        return None


def _ret(series, a, b):
    if series is None or not len(series):
        return None
    s = series[series.index <= pd.Timestamp(b)]
    s0 = series[series.index <= pd.Timestamp(a)]
    if not len(s) or not len(s0):
        return None
    return (float(s.iloc[-1]) / float(s0.iloc[-1]) - 1) * 100


def _bdays(a, b):
    return int(np.busday_count(pd.Timestamp(a).date(), pd.Timestamp(b).date()))


def rule_follow(r):
    if not r["exit_signal_date"]:
        return "Rule ke bina becha"
    sig, sell = pd.Timestamp(r["exit_signal_date"]), pd.Timestamp(r["sell_date"])
    due = sig
    if r["exit_signal"] == "SELL@REBAL":
        first = pd.Timestamp(sig.year, sig.month, 1)
        while first.weekday() >= 5:
            first += pd.Timedelta(days=1)
        if sig.date() != first.date():
            nxt = (sig + pd.offsets.MonthBegin(1)).normalize()
            while nxt.weekday() >= 5:
                nxt += pd.Timedelta(days=1)
            due = nxt
    late = _bdays(due, sell)
    if sell < sig:
        return "Rule se pehle becha"
    return "Haan" if late <= 1 else "Nahi (%d din late)" % late


def report(j, last_px, today=None):
    """Numbers for the Journal sheet: {mode: {cards, months, closed, open}}."""
    today = pd.Timestamp(str(today or ds.now_ist().date())[:10])
    nifty = _nifty()
    out = {}
    for mode in ("LIVE", "PAPER"):
        g = j[j["mode"] == mode]
        if not len(g):
            continue
        closed, opened = [], []
        for _, r in g.iterrows():
            q, bp = _f(r["qty"]), _f(r["buy_price"])
            div = _f(r["dividends"])
            if r["status"] == "CLOSED":
                sp_ = _f(r["sell_price"])
                gross = q * (sp_ - bp)
                fee = _f(r["buy_fees"]) + _f(r["sell_fees"]) + \
                    mtf_interest(r, r["sell_date"])
                net = gross + div - fee
                days = (pd.Timestamp(r["sell_date"]) -
                        pd.Timestamp(r["buy_date"])).days
                tax_gain = gross - (_f(r["buy_fees"]) - _f(r["buy_stt"])) - \
                    (_f(r["sell_fees"]) - _f(r["sell_stt"]))
                nf_ = _ret(nifty, r["buy_date"], r["sell_date"])
                closed.append({
                    "Symbol": r["symbol"], "Strategy": r["strategy"],
                    "Kyun becha": r["sell_reason"], "Buy date": r["buy_date"],
                    "Sell date": r["sell_date"], "Din": days, "Qty": q,
                    "Buy": bp, "Sell": sp_, "Gross P&L": round(gross, 2),
                    "Dividend": round(div, 2), "Fees": -round(fee, 2),
                    "NET (tax se pehle)": round(net, 2),
                    "Net %": round(net / (q * bp) * 100, 1) if q * bp else None,
                    "Nifty same period %": round(nf_, 1)
                    if nf_ is not None else None,
                    "Rule follow?": rule_follow(r),
                    "_month": r["sell_date"][:7], "_fy": fy_of(r["sell_date"]),
                    "tax_gain": tax_gain, "long": days > 365})
            else:
                ltp = last_px.get(r["symbol"]) or bp
                gross = q * (ltp - bp)
                sfee, sstt = fees(r["broker"], "SELL", q * ltp)
                fee = _f(r["buy_fees"]) + sfee + mtf_interest(r, today)
                days = (today - pd.Timestamp(r["buy_date"])).days
                tg = gross - (_f(r["buy_fees"]) - _f(r["buy_stt"])) - \
                    (sfee - sstt)
                tax = max(tg, 0) * (LTCG if days > 365 else STCG)
                opened.append({
                    "Symbol": r["symbol"], "Strategy": r["strategy"],
                    "Status": r["exit_signal"] or "HOLD",
                    "Buy date": r["buy_date"], "Din": days, "Qty": q,
                    "Buy": bp, "LTP": round(ltp, 2),
                    "Unrealised": round(gross, 2), "Dividend": round(div, 2),
                    "Fees (buy)": -_f(r["buy_fees"]),
                    "Agar aaj becho: NET": round(gross + div - fee - tax, 2),
                    "Note": r["note"]})
        # months: closed trades by sell month, dividends by ex-date month
        months = {}
        for c in closed:
            m = months.setdefault(c["_month"], {"n": 0, "win": 0, "gross": 0.0,
                                                "div": 0.0, "fee": 0.0})
            m["n"] += 1
            m["win"] += c["NET (tax se pehle)"] > 0
            m["gross"] += c["Gross P&L"]
            m["fee"] += c["Fees"]
        for _, r in g.iterrows():
            q = _f(r["qty"])
            for part in [x for x in str(r["div_note"]).split(", ") if x]:
                try:
                    d, amt = part.split(" Rs ")
                    mk = pd.Timestamp(dt.datetime.strptime(d, "%d %b %y")) \
                        .strftime("%Y-%m")
                except ValueError:
                    continue
                m = months.setdefault(mk, {"n": 0, "win": 0, "gross": 0.0,
                                           "div": 0.0, "fee": 0.0})
                m["div"] += float(amt) * q
        rows, cum, tax_total = [], 0.0, 0.0
        for mk in sorted(months):
            m = months[mk]
            fy = fy_of(mk + "-15")
            upto = [c for c in closed if c["_fy"] == fy and c["_month"] <= mk]
            prev = [c for c in closed if c["_fy"] == fy and c["_month"] < mk]
            tax = fy_tax(upto) - fy_tax(prev)
            net = m["gross"] + m["div"] + m["fee"] - tax
            cum += net
            tax_total += tax
            end = pd.Timestamp(mk + "-01") + pd.offsets.MonthEnd(0)
            start = pd.Timestamp(mk + "-01") - pd.Timedelta(days=1)
            nret = _ret(nifty, start, end)
            rows.append({"Mahina": pd.Timestamp(mk + "-01").strftime("%b %Y"),
                         "Trades band": m["n"], "Jeete": m["win"],
                         "Gross": round(m["gross"], 2),
                         "Dividend": round(m["div"], 2),
                         "Fees": round(m["fee"], 2),
                         "Tax (andaaza)": -round(tax, 2),
                         "NET": round(net, 2), "Ab tak kul NET": round(cum, 2),
                         "Nifty same mahina %": round(nret, 1)
                         if nret is not None else None})
        wins = [c for c in closed if c["NET (tax se pehle)"] > 0]
        loss = [c for c in closed if c["NET (tax se pehle)"] <= 0]
        vs = [c["Net %"] - c["Nifty same period %"] for c in closed
              if c["Net %"] is not None and c["Nifty same period %"] is not None]
        cards = [
            ("Net profit (fees + tax ke baad)", sum(r["NET"] for r in rows),
             "gross %s" % _rs(sum(c["Gross P&L"] for c in closed))),
            ("Fees + charges", sum(c["Fees"] for c in closed),
             "STT, stamp, exchange, GST, DP" + (", MTF interest" if any(
                 str(x).upper() == "MTF" for x in g["product"]) else "")),
            ("Dividend mila", sum(_f(x) for x in g["dividends"]),
             "%d stock(s), slab tax alag" % sum(_f(x) > 0 for x in
                                                g["dividends"])),
            ("Tax (andaaza)", -tax_total, "STCG 20.8% / LTCG 13%, set-off ke baad"),
            ("Win rate", "%d / %d" % (len(wins), len(closed)) if closed else "-",
             "avg win %s | avg loss %s" % (
                 _pct(np.mean([c["Net %"] for c in wins])) if wins else "-",
                 _pct(np.mean([c["Net %"] for c in loss])) if loss else "-")),
            ("Avg trade vs Nifty", _pct(np.mean(vs)) if vs else "-",
             "same dates, har trade")]
        for c in closed:
            for k in ("_month", "_fy", "tax_gain", "long"):
                c.pop(k, None)
        closed.sort(key=lambda c: c["Sell date"], reverse=True)
        opened.sort(key=lambda c: c["Buy date"])
        out[mode] = {"cards": cards, "months": rows, "closed": closed,
                     "open": opened}
    return out


def _rs(v):
    return ("+" if v >= 0 else "-") + "Rs " + format(int(round(abs(v))), ",")


def _pct(v):
    return "%+.1f%%" % v
