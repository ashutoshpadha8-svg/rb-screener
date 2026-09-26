#!/usr/bin/env python3
"""
HOLDINGS REVIEW  (rbreview)  --  what you HOLD vs what the system would hold
===========================================================================

Reads your real demat holdings from the ACTIVE account's broker (token.txt),
whatever you bought them for, and answers two questions:

  1. KEEP / WEAK / SELL for every holding -- and WHY
  2. ADD -- today's momentum top 20 you do not hold -- and WHY

The checks are the rules that survived the backtests (CLAUDE.md), applied to
"today" instead of to a position opened by the system:

  Momentum rank  (RAMOM, >= Rs 10k Cr universe)   keep while rank <= 40
  40-week MA     (close vs 200-DMA)               swing exit rule
  Stage 4        (10 closes under a FALLING 30w MA) investing exit rule
  Sector count   (NSE industry)                   momentum cap = 4 per sector

  SELL   Stage 4 now, OR below the 40w MA AND rank > 40 / not ranked
  WEAK   exactly one warning (below the 40w MA, or rank > 40 / not ranked)
  KEEP   above the 40w MA and rank <= 40        (STRONG: rank <= 20)

HONEST LIMITS
  * Each rule was backtested; this combined verdict on holdings you bought
    for other reasons was NOT tested as its own strategy.
  * Stocks outside the >= Rs 10,000 Cr universe (small caps, ETFs, gold,
    SGBs) have no momentum rank -> judged on the trend rules only.
  * Momentum sells/buys are meant for the 1st trading day of the month.
  * Nothing is sold or bought here. Sells: in your broker app.

RUN   rbscan first (it refreshes the momentum ranking), then:
        rbreview            real demat holdings
        rbreview --paper    your PAPER portfolio (split.csv, mode PAPER)
        rbreview --no-excel terminal only
OUTPUT terminal + sheet "Holdings_Review" in today's RB_Screener report
"""

import warnings
warnings.filterwarnings("ignore")

import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daily_screener as ds
import momentum_screener as ms
import position_tracker as pt

KEEP_RANK = ms.BUFFER * ms.SLOTS          # 40
STRONG_RANK = ms.SLOTS                    # 20


def paper_holdings():
    """PAPER rows of split.csv as holdings (qty = all legs, entry price)."""
    if not os.path.exists(ms.SPLIT_FILE):
        return []
    sp = pd.read_csv(ms.SPLIT_FILE)
    if "mode" not in sp:
        return []
    sp = sp[sp["mode"].astype(str).str.upper() == "PAPER"]
    out = {}
    for _, r in sp.iterrows():
        q = sum(float(pd.to_numeric(r.get(c), errors="coerce") or 0)
                for c in ("swing_qty", "investing_qty", "momentum_qty"))
        if q > 0:
            s = str(r["symbol"]).upper().strip()
            o = out.setdefault(s, {"symbol": s, "qty": 0.0, "cost": 0.0})
            o["qty"] += q
            o["cost"] += q * float(r.get("entry_price") or 0)
    return [{"symbol": s, "qty": o["qty"],
             "avg_price": o["cost"] / o["qty"] if o["qty"] else 0}
            for s, o in out.items()]


def load_ranks(warns):
    if not os.path.exists(pt.RANKS_FILE):
        print("! No momentum ranking yet -- run rbscan first.")
        sys.exit(1)
    d = pd.read_csv(pt.RANKS_FILE)
    day = str(d["date"].iloc[0]) if len(d) else "?"
    age = (pd.Timestamp(ds.now_ist().date()) - pd.Timestamp(day)).days \
        if day != "?" else 99
    if age > 5:
        warns.append("momentum ranking is from %s -- run rbscan first" % day)
    d["symbol"] = d["symbol"].astype(str).str.upper()
    return d.set_index("symbol"), day


def trend(c):
    """(above 40w MA?, ma200, stage4 now?, run under falling 30w, ret6m)"""
    ma200 = c.rolling(200).mean()
    ma150 = c.rolling(150).mean()
    below = (c < ma150).astype(int)
    run = below.groupby((below == 0).cumsum()).cumsum()
    falling = ma150 < ma150.shift(10)
    st4 = bool(run.iloc[-1] >= 10 and falling.iloc[-1])
    ret6 = (c.iloc[-1] / c.iloc[-127] - 1) * 100 if len(c) > 127 else np.nan
    return (bool(c.iloc[-1] > ma200.iloc[-1]), float(ma200.iloc[-1]), st4,
            int(run.iloc[-1]) if falling.iloc[-1] else 0, ret6)


def judge(sym, h, c, ranks, fund):
    px = float(c.iloc[-1])
    up, ma200, st4, run, ret6 = trend(c)
    rk = int(ranks.loc[sym, "rank"]) if sym in ranks.index else None
    sector = ranks.loc[sym, "sector"] if sym in ranks.index else "?"
    why, bad = [], 0
    if st4:
        why.append("Stage 4: 10+ closes under a FALLING 30w MA")
    if up:
        why.append("above 40w MA (%.0f, %+.0f%%)" % (ma200, (px / ma200 - 1) * 100))
    else:
        bad += 1
        why.append("BELOW 40w MA %.0f (%.0f%%)" % (ma200, (px / ma200 - 1) * 100))
    if rk is None:
        why.append("no momentum rank (outside the >= Rs 10k Cr / liquid "
                   "universe) -> trend rules only")
    elif rk > KEEP_RANK:
        bad += 1
        why.append("momentum rank %d > %d" % (rk, KEEP_RANK))
    else:
        why.append("momentum rank %d (keep <= %d)" % (rk, KEEP_RANK))
    weak_rank = rk is None or rk > KEEP_RANK
    if st4 or (not up and weak_rank and rk is not None) or \
            (not up and rk is None and run >= 5):
        verdict = "SELL"
    elif bad or (rk is None and not up):
        verdict = "WEAK"
    elif rk is not None and rk <= STRONG_RANK:
        verdict = "KEEP (strong)"
    else:
        verdict = "KEEP"
    val = h["qty"] * px
    pnl = (px / h["avg_price"] - 1) * 100 if h["avg_price"] else np.nan
    return {"Verdict": verdict, "Symbol": sym, "Qty": h["qty"],
            "Avg Cost": round(h["avg_price"], 2), "LTP": round(px, 2),
            "Value (Rs)": round(val), "P&L %": round(pnl, 1),
            "Mom Rank": rk if rk is not None else "",
            "6m Ret %": round(ret6, 1) if ret6 == ret6 else "",
            "40w MA": round(ma200, 1), "Sector": sector,
            "Fund Check (info)": fund.get(sym, ""),
            "Why": "; ".join(why)}


def add_list(held, report, ranks):
    """Momentum top 20 (sector-capped, from today's report) not held."""
    top = pd.DataFrame()
    if report:
        top = ms._read_sheet(report, "Momentum_Top20")
        top = top[pd.to_numeric(top.get("Mom Rank"), errors="coerce").notna()] \
            if not top.empty else top
    sw = ms._read_sheet(report, "Swing") if report else pd.DataFrame()
    swing = set(sw["Symbol"].astype(str).str.upper()) if "Symbol" in sw else set()
    rows = []
    if top.empty:                       # fall back: raw ranking, no sector cap
        for s, r in ranks[ranks["rank"] <= STRONG_RANK].iterrows():
            if s not in held:
                rows.append({"Symbol": s, "Mom Rank": int(r["rank"]),
                             "Sector": r["sector"], "Why": "momentum rank %d"
                             % r["rank"]})
        return rows
    for _, r in top.iterrows():
        s = str(r["Symbol"]).upper()
        if s in held:
            continue
        why = ["momentum rank %d of the >= Rs 10k Cr universe" % r["Mom Rank"],
               "6m %+.0f%%, 12m %+.0f%%, 1y vol %.0f%%"
               % (r.get("6m Ret %", np.nan), r.get("12m Ret %", np.nan),
                  r.get("1y Vol %", np.nan))]
        if s in swing:
            why.append("ALSO on the W+TT Swing list (Super-Buy)")
        rows.append({"Symbol": s, "Mom Rank": int(r["Mom Rank"]),
                     "Sector": r.get("Sector / Industry", "?"),
                     "LTP": r.get("LTP"), "Shares (Rs slot)":
                     r.get("Shares to Buy"), "Amount (Rs)": r.get("Amount (Rs)"),
                     "Why": "; ".join(why)})
    return rows


def write_sheet(report, rev, adds, banner):
    from openpyxl import load_workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = load_workbook(report)
    if "Holdings_Review" in wb.sheetnames:
        del wb["Holdings_Review"]
    ws = wb.create_sheet("Holdings_Review", 0)
    bold = Font(bold=True)
    fills = {"SELL": "F8CBAD", "WEAK": "FFE699", "KEEP": "C6EFCE",
             "KEEP (strong)": "A9D08E"}
    ws.cell(row=1, column=1, value=banner).font = bold
    r = 3
    ws.cell(row=r, column=1, value="YOUR HOLDINGS").font = bold
    r += 1
    cols = list(rev.columns) if len(rev) else []
    for i, c in enumerate(cols, 1):
        ws.cell(row=r, column=i, value=c).font = bold
    for _, x in rev.iterrows():
        r += 1
        for i, c in enumerate(cols, 1):
            v = x[c]
            ws.cell(row=r, column=i, value=None if v != v else v)
        ws.cell(row=r, column=1).fill = PatternFill(
            "solid", fgColor=fills.get(x["Verdict"], "FFFFFF"))
    r += 3
    ws.cell(row=r, column=1, value="ADD (momentum top 20 you do not hold)").font = bold
    r += 1
    acols = ["Symbol", "Mom Rank", "Sector", "LTP", "Shares (Rs slot)",
             "Amount (Rs)", "Why"]
    for i, c in enumerate(acols, 1):
        ws.cell(row=r, column=i, value=c).font = bold
    for x in adds:
        r += 1
        for i, c in enumerate(acols, 1):
            v = x.get(c)
            ws.cell(row=r, column=i, value=None if v is None or v != v else v)
    r += 2
    for line in [
            "SELL = Stage 4 now, or below the 40w MA AND momentum rank > 40.  "
            "WEAK = one warning.  KEEP = above 40w MA and rank <= 40.",
            "Each rule is from the backtests (CLAUDE.md); this combined verdict "
            "on holdings bought for other reasons was NOT tested on its own.",
            "Momentum changes are meant for the 1st trading day of the month. "
            "Sell in your broker app -- nothing here places orders."]:
        ws.cell(row=r, column=1, value=line).alignment = Alignment(wrap_text=False)
        r += 1
    widths = {"A": 14, "B": 13, "C": 8, "D": 10, "E": 10, "F": 11, "G": 8,
              "H": 9, "I": 9, "J": 10, "K": 22, "L": 12, "M": 90}
    for k, w in widths.items():
        ws.column_dimensions[k].width = w
    try:
        wb.save(report)
        return report
    except PermissionError:
        alt = report.replace(".xlsx", "_review.xlsx")
        wb.save(alt)
        return alt


def main():
    import account
    acc = account.activate()
    a = sys.argv[1:]
    paper = "--paper" in a
    sess = acc.session if acc.token_ok else None
    warns = []
    if paper:
        holdings, src = paper_holdings(), "PAPER portfolio (split.csv)"
    else:
        if not sess:
            print("! Token expired / missing -- paste a fresh one (rbtoken).")
            sys.exit(1)
        print("Fetching holdings from %s ..." % sess.label)
        holdings, src = pt.get_holdings(sess), "%s demat" % sess.label
    if not holdings:
        print("No holdings found in the %s." % src)
        sys.exit(0)
    held = {h["symbol"]: h for h in holdings}
    ranks, rank_day = load_ranks(warns)
    report = ms.todays_report()
    fund = {}
    if report:
        f = ms._read_sheet(report, "Fundamentals")
        col = next((c for c in f.columns if str(c).startswith("Swing Check")),
                   None) if not f.empty else None
        if col:
            fund = dict(zip(f["Symbol"].astype(str).str.upper(),
                            f[col].astype(str)))
    print("Loading prices for %d holdings ..." % len(held))
    if sess:
        closes, lows, highs, prov, note = pt.load_prices(sess, list(held), warns)
    else:                                   # --paper without a token
        closes = {s: ds.fetch_eod(s.lower())["Close"] for s in held
                  if ds.fetch_eod(s.lower()) is not None}
        note = "free source only (no token)"
    rows, nodata = [], []
    for s, h in held.items():
        c = closes.get(s)
        if c is None or len(c) < 210:
            nodata.append(s)
            continue
        rows.append(judge(s, h, c, ranks, fund))
    order = {"SELL": 0, "WEAK": 1, "KEEP": 2, "KEEP (strong)": 3}
    rev = pd.DataFrame(rows)
    if len(rev):
        rev = rev.sort_values(["Verdict", "Mom Rank"], key=lambda x: x.map(
            order) if x.name == "Verdict" else pd.to_numeric(x, errors="coerce")
            .fillna(9999))

    # regime from today's report banner (momentum_screener wrote it)
    regime_red = False
    if report:
        m = ms._read_sheet(report, "Momentum_Top20")
        regime_red = "Regime" in m and m["Regime"].astype(str).str.contains(
            "Red").any()
    adds = add_list(set(held), report, ranks)

    # ------------------------------------------------------------ terminal
    tot = rev["Value (Rs)"].sum() if len(rev) else 0
    print("\n" + "=" * 78)
    print(" HOLDINGS REVIEW -- %s | %d holdings | value ~Rs %s | ranking %s"
          % (src, len(held), format(int(tot), ","), rank_day))
    print(" prices: %s" % note)
    print("=" * 78)
    for v in ("SELL", "WEAK", "KEEP", "KEEP (strong)"):
        part = rev[rev["Verdict"] == v] if len(rev) else rev
        if len(part):
            print("\n---- %s (%d) ----" % (v, len(part)))
            for _, x in part.iterrows():
                print("  %-12s %6s sh  P&L %+6.1f%%  ~Rs %9s  | %s"
                      % (x["Symbol"], format(x["Qty"], "g"), x["P&L %"],
                         format(int(x["Value (Rs)"]), ","), x["Why"]))
    if nodata:
        print("\n---- NO DATA (%d): %s -- not enough price history (new "
              "listing, ETF/SGB or renamed symbol)" % (len(nodata),
                                                       ", ".join(nodata)))
    if len(rev):
        sec = rev[rev["Sector"] != "?"].groupby("Sector")["Symbol"].count()
        over = sec[sec > ms.SECTOR_CAP]
        if len(over):
            print("\n! Sector concentration (momentum cap is %d): %s"
                  % (ms.SECTOR_CAP, ", ".join("%s %d" % (k, v)
                                              for k, v in over.items())))
    print("\n---- ADD: momentum top %d you do not hold (%d) ----"
          % (ms.SLOTS, len(adds)))
    for x in adds:
        print("  %-12s rank %-3s %-24s | %s" % (x["Symbol"], x["Mom Rank"],
                                                str(x["Sector"])[:24],
                                                x["Why"]))
    if regime_red:
        print("\n!!! MARKET RED (Nifty < 200-DMA): the backtest says new buys "
              "now do worse. Paper first.")
    for w in warns:
        print("  ! " + w)
    print("\nRules: SELL = Stage 4, or below 40w MA AND rank > %d. WEAK = one "
          "warning. KEEP = above 40w MA and rank <= %d." % (KEEP_RANK, KEEP_RANK))
    print("Each rule is backtested; this combined verdict on outside holdings "
          "is NOT. Momentum changes: 1st trading day of the month.")
    print("Nothing is sold or bought here -- sell in your broker app.")

    if "--no-excel" not in a and report:
        path = write_sheet(report, rev, adds,
                           "Holdings Review %s | %s | ranking %s"
                           % (ds.now_ist().date(), src, rank_day))
        print("\nExcel: %s (sheet Holdings_Review, first tab)" % path)
    elif not report:
        print("\n(no RB_Screener report today -- run rbscan for the Excel sheet)")
    account.banner(acc)


if __name__ == "__main__":
    main()
