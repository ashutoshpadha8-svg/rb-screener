#!/usr/bin/env python3
"""
SIGNAL TRACKER  --  how did every stock the screener found actually do? (30 Sep 2026)
===================================================================================

Reads EVERY master scan (reports/RB_Screener_YYYY-MM-DD.xlsx) -- so the days
before this file existed are included too -- and keeps a permanent log
(data/signals_log.csv; rows are only ever added / updated, never dropped,
so a deleted xlsx loses nothing).

What counts as a "find" (one row each):
  W+TT      a Swing-sheet row BUY / FIT / LATE, one row per signal date
            (a stock that signals again later = a new row)
  MOMENTUM  a Momentum Top 20 stock, one row per stretch in the list
            (out of the list for > 20 days and back = a new row)
  both      marked in the 'Both lists' column (= Super-Buy that day)

Per find: price the day it was first found (the scan's own price), today's
price, return, Nifty over the same days, best / worst point since (daily
high / low), whether the 20% stop would have hit, and a rule status
(W+TT: close below the 40-week MA = exit; momentum: today's rank > 40 = sell
at the next rebalance). Finds younger than 30 days are marked TOO EARLY --
a week of prices says nothing.

Writes sheet "Signal_Tracker" into today's master scan (portfolio.py copies it
into every Portfolio file) + data/signal_tracker_latest.csv. No orders.

python3 signal_tracker.py            (rb_scan.py runs it after every scan)
"""

import os
import re
import sys
import glob
import datetime as dt

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daily_screener as ds                                    # noqa: E402

LOG = os.path.join(ds.DATA, "signals_log.csv")
OUT = os.path.join(ds.DATA, "signal_tracker_latest.csv")
REPORTS = os.path.join(ds.HERE, "reports")
SHEET = "Signal_Tracker"
MOM_GAP_DAYS = 20          # out of the top 20 longer than this = new find
TOO_EARLY = 30             # calendar days
STOP = 0.20
LOG_COLS = ["source", "symbol", "key", "first_found", "first_status",
            "price_found", "signal_date", "signal_price", "rank_found",
            "last_seen", "days_listed", "both_lists"]
SYM_OK = re.compile(r"^[A-Z0-9][A-Z0-9&\-_.]{0,19}$")


# ================================================================== scans
def scan_files():
    """{date: path} for every master scan; the plain file wins over a
    *_fund.xlsx copy of the same day."""
    out = {}
    for p in glob.glob(os.path.join(REPORTS, "RB_Screener_*.xlsx")):
        b = os.path.basename(p)
        m = re.match(r"RB_Screener_(\d{4}-\d{2}-\d{2})(_fund)?\.xlsx$", b)
        if not m:
            continue
        d = m.group(1)
        if d not in out or not m.group(2):
            out[d] = p
    return dict(sorted(out.items()))


def _num(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def read_scan(day, path):
    """Rows (source, symbol, status, price, rank, signal_date, signal_price)."""
    rows = []
    try:
        sw = pd.read_excel(path, sheet_name="Swing")
        for _, r in sw.iterrows():
            s = str(r.get("Symbol", "")).strip().upper()
            act = str(r.get("Action", "")).strip().upper()
            if not SYM_OK.match(s) or act not in ("BUY", "FIT", "LATE"):
                continue
            sd = str(r.get("Signal Date", ""))[:10]
            rows.append(dict(day=day, source="W+TT", symbol=s, status=act,
                             price=_num(r.get("Price")),
                             rank=_num(r.get("RS Rank")), signal_date=sd,
                             signal_price=_num(r.get("Signal Price"))))
    except Exception as e:
        print("  ! %s: Swing sheet not read (%s)" % (day, type(e).__name__))
    try:
        mo = pd.read_excel(path, sheet_name="Momentum_Top20")
        for _, r in mo.iterrows():
            s = str(r.get("Symbol", "")).strip().upper()
            rk = _num(r.get("Mom Rank"))
            if not SYM_OK.match(s) or rk is None:
                continue
            px = _num(r.get("LTP")) or _num(r.get("Last Close"))
            rows.append(dict(day=day, source="MOMENTUM", symbol=s,
                             status="TOP20", price=px, rank=rk,
                             signal_date="", signal_price=None))
    except Exception as e:
        print("  ! %s: Momentum sheet not read (%s)" % (day, type(e).__name__))
    return rows


def load_log():
    try:
        d = pd.read_csv(LOG, dtype=str).fillna("")
        for c in LOG_COLS:
            if c not in d:
                d[c] = ""
        return d[LOG_COLS]
    except (IOError, OSError, ValueError):
        return pd.DataFrame(columns=LOG_COLS)


def build_log(files):
    """All scans -> one row per find. Existing log rows are kept (a scan file
    that was deleted later still counts)."""
    raw = []
    for day, path in files.items():
        raw += read_scan(day, path)
    finds = {}
    if raw:
        R = pd.DataFrame(raw).sort_values(["day"])
        wtt_days = {(r.symbol, r.day) for r in R[(R.source == "W+TT") & (
            R.status != "LATE")].itertuples()}
        mom_days = {(r.symbol, r.day) for r in R[R.source == "MOMENTUM"]
                    .itertuples()}
        for r in R[R.source == "W+TT"].itertuples():
            key = r.signal_date or r.day
            k = ("W+TT", r.symbol, key)
            f = finds.get(k)
            if f is None:
                finds[k] = dict(source="W+TT", symbol=r.symbol, key=key,
                                first_found=r.day, first_status=r.status,
                                price_found=r.price, signal_date=r.signal_date,
                                signal_price=r.signal_price, rank_found=r.rank,
                                last_seen=r.day, days_listed=1,
                                both_lists="YES" if (r.symbol, r.day)
                                in mom_days else "")
            else:
                f["last_seen"] = r.day
                f["days_listed"] += 1
        for sym, g in R[R.source == "MOMENTUM"].groupby("symbol"):
            start = prev = None
            for r in g.itertuples():
                d = pd.Timestamp(r.day)
                if prev is None or (d - prev).days > MOM_GAP_DAYS:
                    start = r.day
                    finds[("MOMENTUM", sym, start)] = dict(
                        source="MOMENTUM", symbol=sym, key=start,
                        first_found=r.day, first_status="TOP20",
                        price_found=r.price, signal_date="",
                        signal_price=None, rank_found=r.rank,
                        last_seen=r.day, days_listed=1,
                        both_lists="YES" if (sym, r.day) in wtt_days else "")
                else:
                    f = finds[("MOMENTUM", sym, start)]
                    f["last_seen"] = r.day
                    f["days_listed"] += 1
                prev = d
    new = pd.DataFrame(list(finds.values()), columns=LOG_COLS).astype(str) \
        .replace({"None": "", "nan": ""})
    old = load_log()
    om = old[old.source == "MOMENTUM"]
    for i in new.index[new.source == "MOMENTUM"]:   # same stretch, earlier
        o = om[(om.symbol == new.at[i, "symbol"]) &      # start in the log
               (om.first_found <= new.at[i, "first_found"])]
        if len(o):
            o = o.sort_values("first_found").iloc[-1]
            gap = (pd.Timestamp(new.at[i, "first_found"]) -
                   pd.Timestamp(o.last_seen)).days
            if gap <= MOM_GAP_DAYS:
                new.at[i, "key"] = o.key
    ok_ = old.source + "|" + old.symbol + "|" + old.key
    nk = new.source + "|" + new.symbol + "|" + new.key
    keep = old[~ok_.isin(nk)]
    prev = old.set_index(ok_)
    for i, k in enumerate(nk):            # an older scan file was deleted:
        if k in prev.index:               # the log remembers the first find
            o = prev.loc[k]
            o = o.iloc[0] if isinstance(o, pd.DataFrame) else o
            if o.first_found and o.first_found < new.at[i, "first_found"]:
                for c in ("first_found", "first_status", "price_found",
                          "rank_found", "both_lists"):
                    new.at[i, c] = o[c]
            new.at[i, "last_seen"] = max(o.last_seen, new.at[i, "last_seen"])
            new.at[i, "days_listed"] = str(max(
                int(_num(o.days_listed) or 0),
                int(_num(new.at[i, "days_listed"]) or 0)))
    log = pd.concat([keep, new], ignore_index=True)
    log = log.sort_values(["first_found", "source", "symbol"])
    tmp = LOG + ".tmp"
    log.to_csv(tmp, index=False)
    os.replace(tmp, LOG)
    return log


# ================================================================== prices
def prices(symbols):
    """Daily history per symbol (free source + broker gap fill) and live
    prices when a broker token is active."""
    frames = {}
    for s in symbols:
        df = ds.fetch_eod(s.lower())
        if df is not None and len(df):
            frames[s.lower()] = df
    bm = ds.fetch_eod(ds.BENCH)
    live, note = {}, "free source only (no broker token)"
    try:
        import momentum_screener as ms
        import broker_api as ba
        sess = ms.get_session()
        if sess and frames:
            frames, bm, live = ba.refresh(sess, frames, bm,
                                          ds.last_expected_session(), [])
            note = "%s fill + live price" % sess.label
    except SystemExit:
        pass
    except Exception as e:
        note = "broker step skipped (%s)" % type(e).__name__
    return frames, bm, live, note


def _ranks_now():
    try:
        r = pd.read_csv(os.path.join(ds.DATA, "momentum_ranks_latest.csv"))
        return dict(zip(r["symbol"].astype(str).str.upper(), r["rank"]))
    except Exception:
        return {}


def evaluate(log, frames, bm, live, today):
    ranks = _ranks_now()
    bmc = bm["Close"] if bm is not None else None
    rows = []
    for f in log.itertuples():
        s = f.symbol.lower()
        df = frames.get(s)
        found = pd.Timestamp(f.first_found)
        p0 = _num(f.price_found)
        base = dict(Symbol=f.symbol, Source=f.source,
                    **{"First status": f.first_status,
                       "Found on": f.first_found, "Price then": p0,
                       "Both lists": f.both_lists,
                       "Days listed": _num(f.days_listed),
                       "Last in list": f.last_seen})
        if df is None or not p0:
            rows.append(dict(base, Status="NO DATA"))
            continue
        after = df[df.index > found]
        now = live.get(s) or float(df["Close"].iloc[-1])
        hi = max([now] + list(after["High"].dropna()))
        lo = min([now] + list(after["Low"].dropna()))
        n0 = n1 = None
        if bmc is not None and len(bmc):
            b_then = bmc[bmc.index <= found]
            n0 = float(b_then.iloc[-1]) if len(b_then) else None
            n1 = float(bmc.iloc[-1])
        ret = now / p0 - 1
        nret = n1 / n0 - 1 if n0 and n1 else None
        age = (pd.Timestamp(today) - found).days
        # rule status
        c = df["Close"]
        if f.source == "W+TT":
            ma200 = c.rolling(200).mean()
            below = after.index[(c.reindex(after.index) <
                                 ma200.reindex(after.index))]
            stop_hit = lo <= p0 * (1 - STOP)
            if stop_hit:
                status = "STOP HIT (-20%)"
            elif len(below):
                status = "SWING EXIT (close < 40w MA %s)" % below[0].date()
            else:
                status = "rule: hold"
        else:
            rk = ranks.get(f.symbol)
            if not ranks:
                status = "rank unknown (no ranks file)"
            elif rk is None:
                status = "not ranked now -> SELL at rebalance"
            else:
                status = "rank %d" % rk + (" -> SELL at rebalance" if rk > 40
                                           else " (keep, <= 40)")
        if age < TOO_EARLY:
            status += " | TOO EARLY"
        rows.append(dict(base, **{
            "Price now": round(now, 2), "Return %": 100 * ret,
            "Nifty same days %": 100 * nret if nret is not None else None,
            "vs Nifty %": 100 * (ret - nret) if nret is not None else None,
            "Best since %": 100 * (hi / p0 - 1),
            "Worst since %": 100 * (lo / p0 - 1),
            "Days since found": age, "Status": status}))
    return pd.DataFrame(rows)


def summary(t):
    if t.empty or "Return %" not in t:
        return pd.DataFrame()
    t = t.dropna(subset=["Return %"])
    groups = [("W+TT BUY (found on signal day)",
               (t.Source == "W+TT") & (t["First status"] == "BUY")),
              ("W+TT FIT (found later)",
               (t.Source == "W+TT") & (t["First status"] == "FIT")),
              ("W+TT LATE (not tested)",
               (t.Source == "W+TT") & (t["First status"] == "LATE")),
              ("Momentum Top 20", t.Source == "MOMENTUM"),
              ("In BOTH lists (Super-Buy)",
               (t["Both lists"] == "YES") & (t.Source == "W+TT")),
              ("ALL finds", t.Source.notna())]
    out = []
    for name, m in groups:
        g = t[m]
        if not len(g):
            continue
        vs = g["vs Nifty %"].dropna()
        out.append({"Group": name, "Finds": len(g),
                    "Up now": int((g["Return %"] > 0).sum()),
                    "Down now": int((g["Return %"] <= 0).sum()),
                    "Avg return %": g["Return %"].mean(),
                    "Median %": g["Return %"].median(),
                    "Avg vs Nifty %": vs.mean() if len(vs) else None,
                    "Beat Nifty": "%d of %d" % ((vs > 0).sum(), len(vs)),
                    "Best %": g["Return %"].max(),
                    "Worst %": g["Return %"].min(),
                    "Avg worst dip %": g["Worst since %"].mean(),
                    "20% stop hit": int(g["Status"].str.startswith(
                        "STOP").sum()),
                    "Older than 30 days": int((g["Days since found"] >=
                                               TOO_EARLY).sum())})
    return pd.DataFrame(out)


# ================================================================== output
def write_sheet(path, summ, t, note, today):
    from openpyxl import load_workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = load_workbook(path)
    if SHEET in wb.sheetnames:
        del wb[SHEET]
    ws = wb.create_sheet(SHEET)
    head = Font(bold=True, color="FFFFFF")
    navy = PatternFill("solid", fgColor="1F4E78")
    grey = PatternFill("solid", fgColor="EDEDED")
    ws.cell(row=1, column=1, value="SIGNAL TRACKER | %s | prices: %s"
            % (today, note)).font = Font(bold=True, size=13)
    ws.cell(row=2, column=1, value=(
        "Every stock the screener ever found, from the day it was found. "
        "Grey = younger than 30 days: TOO EARLY, a few days of prices say "
        "nothing. Backtest (2013-26) expects W+TT ~39% winners, avg +11.8% "
        "per trade over months; momentum picks beat the universe by ~6% in "
        "6 months. Info only -- no orders.")).font = Font(italic=True,
                                                          size=10)

    def table(df, r0):
        for j, h in enumerate(df.columns, 1):
            c = ws.cell(row=r0, column=j, value=h)
            c.font, c.fill = head, navy
            c.alignment = Alignment(wrap_text=True, vertical="center")
        for i, row in enumerate(df.itertuples(index=False), r0 + 1):
            young = False
            for j, v in enumerate(row, 1):
                if isinstance(v, float):
                    v = None if v != v else round(v, 1)
                c = ws.cell(row=i, column=j, value=v)
                h = df.columns[j - 1]
                if isinstance(v, float) and ("%" in h):
                    c.number_format = "+0.0;-0.0;0.0"
                    c.font = Font(color="1E7B34" if v > 0 else "C00000"
                                  if v < 0 else "000000")
                if h == "Status" and "TOO EARLY" in str(v):
                    young = True
            if young:
                for j in range(1, len(df.columns) + 1):
                    ws.cell(row=i, column=j).fill = grey
        return r0 + len(df) + 2

    r = 4
    if len(summ):
        ws.cell(row=r, column=1, value="SUMMARY").font = Font(bold=True)
        r = table(summ, r + 1)
    ws.cell(row=r, column=1, value="EVERY FIND (newest first)").font = \
        Font(bold=True)
    table(t, r + 1)
    for j in range(1, 20):
        ws.column_dimensions[chr(64 + j)].width = 13
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["P"].width = 34
    ws.freeze_panes = "B6"
    wb.save(path)


def main():
    today = ds.now_ist().date().isoformat()
    files = scan_files()
    if not files:
        print("No master scans in %s yet -- run rb first." % REPORTS)
        return
    print("Signal tracker: %d master scan(s) %s .. %s"
          % (len(files), list(files)[0], list(files)[-1]))
    log = build_log(files)
    syms = sorted(set(log.symbol))
    frames, bm, live, note = prices(syms)
    t = evaluate(log, frames, bm, live, today)
    cols = ["Symbol", "Source", "First status", "Found on", "Days since found",
            "Price then", "Price now", "Return %", "Nifty same days %",
            "vs Nifty %", "Best since %", "Worst since %", "Both lists",
            "Days listed", "Last in list", "Status"]
    t = t.reindex(columns=cols).sort_values(["Found on", "Return %"],
                                            ascending=[False, False])
    summ = summary(t)
    t.to_csv(OUT, index=False)
    latest = list(files.values())[-1]
    try:
        write_sheet(latest, summ, t, note, today)
        print("  sheet '%s' written into %s" % (SHEET, os.path.basename(latest)))
    except Exception as e:
        print("  ! could not write the sheet (%s) -- CSV: %s"
              % (type(e).__name__, OUT))
    print("\n==== SIGNAL TRACKER (%d finds, prices: %s) ====" % (len(t), note))
    if len(summ):
        pd.set_option("display.width", 200)
        print(summ[["Group", "Finds", "Up now", "Down now", "Avg return %",
                    "Avg vs Nifty %", "Beat Nifty", "Worst %",
                    "Older than 30 days"]]
              .to_string(index=False, float_format=lambda x: "%+.1f" % x))
    young = int(t["Status"].astype(str).str.contains("TOO EARLY").sum())
    if young:
        print("  %d of %d finds are younger than %d days -> TOO EARLY to judge."
              % (young, len(t), TOO_EARLY))


if __name__ == "__main__":
    main()
