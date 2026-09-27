#!/usr/bin/env python3
"""
PORTFOLIO  (rbport)  --  everything about YOUR holdings, per account
===================================================================

The market scan (rbscan) is one shared file a day. This script does the
account part, for the account in token.txt:

  Holdings   every stock you hold (demat + PAPER portfolio from split.csv):
             trend      40w MA, 30w MA + Weinstein stage, 50-DMA
             technical  RSI(14), % from 52w high, ATR %, 6m / 12m return
             strategies W+TT signal today?  swing rule (20% stop / 40w MA),
                        investing rule (Stage 4), momentum rank (keep <= 40)
             fundamentals (Screener.in, info only)  +  latest news
             RECOMMENDATION + WHY
  Rebalance  momentum: SELL / BUY / HOLD per LIVE and PAPER (1st trading day)
  Actions    the master Strategy_Comparison list + an Action dropdown
             (BUY / BUY MTF / WATCH) -> rbtrack;  SIP  regular buying plans

RECOMMENDATION
  A stock tagged in split.csv is judged by ITS strategy's exit rule (the
  backtested rules; worst leg wins):
     EXIT        rule fired (stop / 40w MA / Stage 4)
     SELL@REBAL  momentum rank > 40 -> sell at the monthly rebalance
     WATCH       close to an exit level
     HOLD        rule says stay
  An untagged holding (bought outside the system) gets the combined check:
     SELL   Stage 4, or below the 40w MA AND momentum rank > 40
     WEAK   one warning       KEEP  above 40w MA and rank <= 40
  -> the single rules are backtested; the combined check on outside holdings
     is NOT. Fundamentals and news never change the verdict (the fundamental
     gate did not help in the 2018-26 backtest) -- they are for your eyes.

OUTPUT accounts/<BROKER>_<ID>/reports/Portfolio_<BROKER>_<Name>.xlsx (one file)
       = the ONE file to open: Dashboard (summary + links), Holdings, Actions,
       Rebalance, Watchlist, then today's master scan sheets copied in
       (Swing, Investing, Momentum_Top20, Fundamentals)
RUN    rbport               (rbscan first, once a day)
       rbport --no-news     faster
       rbport --no-fund     skip Screener.in for holdings not in the scan
"""

import warnings
warnings.filterwarnings("ignore")

import os
import sys
import glob
import math
import re

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daily_screener as ds
import momentum_screener as ms
import position_tracker as pt

REPORTS = os.path.join(ds.HERE, "reports")     # routed to the account folder
TAG = ""                                       # e.g. DHAN_Ashutosh (routed)
WATCH_FILE = os.path.join(ds.DATA, "watchlist.csv")   # routed per account
KEEP_RANK = ms.BUFFER * ms.SLOTS
SLOT_RS = int(ms.CAPITAL / ms.SLOTS)   # default own money per stock (Rs 10,000)
MTF_X = 4                              # = auto_tracker_update.MTF_LEVERAGE
LEG_ORDER = {"EXIT": 0, "SELL@REBAL": 1, "SELL": 1, "WATCH": 2, "WEAK": 2,
             "HOLD": 3, "KEEP": 3, "AVOID": 4, "STRONG": 4, "SIP": 5}
WATCH_WORD = {"KEEP": "STRONG", "WEAK": "WEAK", "SELL": "AVOID"}


def path_for(day=None):
    """ONE portfolio file per account, updated by every rb (RB, 27 Sep);
    the report date sits on the Dashboard (see report_date)."""
    return os.path.join(REPORTS, "Portfolio_%s.xlsx" % (TAG or "account"))


def latest():
    """The portfolio file (for rbtrack)."""
    p = path_for()
    if os.path.exists(p):
        return p
    files = [f for f in glob.glob(os.path.join(REPORTS, "Portfolio_*.xlsx"))
             if not os.path.basename(f).startswith("~$")]
    return max(files, key=os.path.getmtime) if files else None


def report_date(path):
    """'YYYY-MM-DD' the file was made for (Dashboard A1), or None."""
    try:
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True)
        v = str(wb["Dashboard"]["A1"].value or "")
        m = re.search(r"(\d{4}-\d{2}-\d{2})\s*$", v)
        return m.group(1) if m else None
    except Exception:
        return None


def tidy_old_files():
    """Old one-file-per-day Portfolio_*_YYYY-MM-DD*.xlsx -> data/old_reports/
    (moved, never deleted)."""
    import shutil
    old = [f for f in glob.glob(os.path.join(REPORTS, "Portfolio_*.xlsx"))
           if re.search(r"_\d{4}-\d{2}-\d{2}", os.path.basename(f))]
    if not old:
        return 0
    dst = os.path.join(os.path.dirname(ms.SPLIT_FILE), "old_reports")
    os.makedirs(dst, exist_ok=True)
    for f in old:
        shutil.move(f, os.path.join(dst, os.path.basename(f)))
    return len(old)


# ================================================================== inputs
def read_split():
    if not os.path.exists(ms.SPLIT_FILE):
        return pd.DataFrame()
    sp = pd.read_csv(ms.SPLIT_FILE, dtype={"order_id": str})
    sp["symbol"] = sp["symbol"].astype(str).str.upper().str.strip()
    for c in ("swing_qty", "investing_qty", "momentum_qty", "entry_price"):
        sp[c] = pd.to_numeric(sp.get(c, 0), errors="coerce").fillna(0)
    sp["mode"] = sp.get("mode", "LIVE")
    sp["mode"] = sp["mode"].fillna("").astype(str).str.upper().replace("", "LIVE")
    sp["strategy"] = sp.get("strategy", "").fillna("") if "strategy" in sp \
        else ""
    return sp[sp["symbol"].isin(["", "EXAMPLE", "NAN"]) == False]  # noqa: E712


def positions(broker_holdings, sp):
    """One row per (mode, symbol): qty, entry, entry_date, legs."""
    out = []
    live = sp[sp["mode"] == "LIVE"] if len(sp) else sp
    for h in broker_holdings:
        s = h["symbol"]
        rows = live[live["symbol"] == s] if len(live) else live
        legs = {}
        for _, r in rows.iterrows():
            for leg in ("swing", "investing", "momentum"):
                if r["%s_qty" % leg] > 0:
                    k = "sip" if str(r.get("strategy")) == "SIP" else leg
                    legs[k] = legs.get(k, 0) + r["%s_qty" % leg]
        tagged_qty = sum(legs.values())
        edate = rows["entry_date"].dropna().astype(str).min() if len(rows) \
            and "entry_date" in rows else None
        rq = rows["swing_qty"] + rows["investing_qty"] + rows["momentum_qty"] \
            if len(rows) else None
        ok = (rows["entry_price"] > 0) & (rq > 0) if len(rows) else None
        entry = float((rows["entry_price"][ok] * rq[ok]).sum() / rq[ok].sum()) \
            if len(rows) and ok.any() else h["avg_price"]      # qty-weighted
        note = ""
        if legs and abs(tagged_qty - h["qty"]) > 0.5:
            note = "split.csv legs total %g, demat %g" % (tagged_qty, h["qty"])
        out.append({"mode": "LIVE", "symbol": s, "qty": h["qty"],
                    "entry": entry or h["avg_price"], "entry_date": edate,
                    "legs": legs, "note": note})
    held = {h["symbol"] for h in broker_holdings}
    for _, r in (live[~live["symbol"].isin(held)].iterrows() if len(live)
                 else []):
        q = r["swing_qty"] + r["investing_qty"] + r["momentum_qty"]
        legs = {("sip" if str(r.get("strategy")) == "SIP" else leg):
                r["%s_qty" % leg] for leg in ("swing", "investing", "momentum")
                if r["%s_qty" % leg] > 0}
        if q > 0:
            out.append({"mode": "LIVE", "symbol": r["symbol"], "qty": q,
                        "entry": r["entry_price"], "entry_date":
                        r.get("entry_date"), "legs": legs, "note":
                        "in split.csv but NOT in demat (AMO pending? rbsync)"})
    if os.path.exists(WATCH_FILE):          # WATCH picks from rbtrack
        w = pd.read_csv(WATCH_FILE)
        for _, r in w.iterrows():
            out.append({"mode": "WATCH", "symbol": str(r["symbol"]).upper(),
                        "qty": 0, "entry": float(r["price_added"])
                        if r.get("price_added") == r.get("price_added") and
                        r.get("price_added") else 0,
                        "entry_date": None, "legs": {},
                        "note": "on watchlist since %s" % r.get("added")})
    paper = sp[sp["mode"] == "PAPER"] if len(sp) else sp
    for s, g in (paper.groupby("symbol") if len(paper) else []):
        legs = {leg: g["%s_qty" % leg].sum() for leg in
                ("swing", "investing", "momentum") if g["%s_qty" % leg].sum()}
        q = sum(legs.values())
        if q > 0:
            out.append({"mode": "PAPER", "symbol": s, "qty": q,
                        "entry": float((g["entry_price"] * (
                            g["swing_qty"] + g["investing_qty"] +
                            g["momentum_qty"])).sum() / q),
                        "entry_date": g["entry_date"].astype(str).min()
                        if "entry_date" in g else None,
                        "legs": legs, "note": ""})
    return out


def add_watch(items):
    """[(symbol, price, source)] -> watchlist.csv (skips ones already on it)."""
    if not items:
        return []
    cols = ["symbol", "added", "price_added", "source"]
    w = pd.read_csv(WATCH_FILE) if os.path.exists(WATCH_FILE) else \
        pd.DataFrame(columns=cols)
    have = set(w["symbol"].astype(str).str.upper())
    new = [{"symbol": s, "added": ds.now_ist().date().isoformat(),
            "price_added": px, "source": src}
           for s, px, src in items if s not in have]
    if new:
        pd.concat([w, pd.DataFrame(new)], ignore_index=True).to_csv(
            WATCH_FILE, index=False)
    return [x["symbol"] for x in new]


# ================================================================== analysis
def technicals(c, lo, hi):
    px = float(c.iloc[-1])
    ma50, ma150, ma200 = (c.rolling(n).mean() for n in (50, 150, 200))
    rising = bool(ma150.iloc[-1] > ma150.iloc[-11])
    above = px > ma150.iloc[-1]
    stage = ("Stage 2 (uptrend)" if above and rising else
             "Stage 4 (downtrend)" if not above and not rising else
             "Stage 3 (topping?)" if above else "Stage 1 / pullback")
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = float(100 - 100 / (1 + up.iloc[-1] / dn.iloc[-1])) if dn.iloc[-1] \
        else 100.0
    tr = np.maximum(np.maximum(hi - lo, (hi - c.shift(1)).abs()),
                    (lo - c.shift(1)).abs())
    atr = float(tr.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])
    hi52 = float(c.iloc[-252:].max())
    ret = lambda n: (px / float(c.iloc[-n - 1]) - 1) * 100 if len(c) > n \
        else np.nan
    return {"px": px, "ma50": float(ma50.iloc[-1]),
            "ma150": float(ma150.iloc[-1]), "ma200": float(ma200.iloc[-1]),
            "stage": stage, "rsi": rsi, "atr_pct": atr / px * 100,
            "dist52": (px / hi52 - 1) * 100, "ret6": ret(126), "ret12": ret(252)}


def combined(t, st4_now, rk):
    """Untagged holding: SELL / WEAK / KEEP (see docstring)."""
    below = t["px"] < t["ma200"]
    weak_rank = rk is None or rk > KEEP_RANK
    if st4_now or (below and rk is not None and rk > KEEP_RANK):
        return "SELL"
    if below or (weak_rank and rk is not None):
        return "WEAK"
    return "KEEP"


def stage4_now(c):
    ma150 = c.rolling(150).mean()
    below = (c < ma150).astype(int)
    run = below.groupby((below == 0).cumsum()).cumsum()
    return bool(run.iloc[-1] >= 10 and ma150.iloc[-1] < ma150.iloc[-11])


def fundamentals_for(syms, fund_sheet, fetch):
    """{sym: dict} from the master Fundamentals sheet, else Screener.in."""
    out = {}
    if not fund_sheet.empty and "Symbol" in fund_sheet:
        for _, r in fund_sheet.iterrows():
            out[str(r["Symbol"]).upper()] = {
                "P/E": r.get("P/E"), "ROCE %": r.get("ROCE %"),
                "ROE %": r.get("ROE %"), "D/E": r.get("D/E"),
                "Qtr Profit YoY %": r.get("Qtr Profit YoY %"),
                "Qtr Sales YoY %": r.get("Qtr Sales YoY %"),
                "Fund Swing": r.get("Swing Check (info)"),
                "Fund Invest": r.get("Investing Check (info)"),
                "Promoter Δ": r.get("Promoter Δ (pp)"),
                "FII Δ": r.get("FII Δ (pp)"), "DII Δ": r.get("DII Δ (pp)")}
    todo = [s for s in syms if s not in out]
    if not (fetch and todo):
        return out
    import fundamentals as fu
    print("Fundamentals for %d holding(s) not in today's scan (Screener.in, "
          "~%d s) ..." % (len(todo), int(len(todo) * fu.PAUSE * 1.3)))
    for s in todo:
        try:
            p = fu.load_company(s)
            if p is None or p["pl"].empty:
                continue
            m = fu.metrics(p)
            r1 = lambda k: round(m[k], 1) if isinstance(m.get(k), (int, float)) \
                and m[k] == m[k] else None
            out[s] = {"P/E": r1("pe"), "ROCE %": r1("roce_now"),
                      "ROE %": r1("roe_now"), "D/E": r1("de"),
                      "Qtr Profit YoY %": r1("q_profit_yoy"),
                      "Qtr Sales YoY %": r1("q_sales_yoy"),
                      "Fund Swing": fu.verdict(fu.swing_rules(m)),
                      "Fund Invest": fu.verdict(fu.invest_rules(m)),
                      "Promoter Δ": m.get("d_prom"), "FII Δ": m.get("d_fii"),
                      "DII Δ": m.get("d_dii")}
        except Exception:
            continue
    return out


def fmt_filings(fl):
    if fl is None:
        return "(NSE did not answer -- try again later)"
    return " || ".join("%s%s %s: %s" % ("!! " if red else "", d, c, t)
                       for d, c, t, red in fl)


def analyse(pos, closes, lows, highs, prov, ranks, wtt, fund, news,
            filings=None):
    s = pos["symbol"]
    c = closes.get(s)
    base = {"Mode": pos["mode"], "Symbol": s, "Qty": pos["qty"],
            "Entry": round(pos["entry"], 2) if pos["entry"] else None}
    if c is None or len(c) < 210:
        base.update({"Recommendation": "NO DATA", "Why":
                     "not enough price history (ETF/SGB, new listing or "
                     "renamed symbol) " + pos["note"]})
        return base
    lo, hi = lows[s], highs[s]
    t = technicals(c, lo, hi)
    rk = ranks.get(s)
    legs, why, verdicts = pos["legs"], [], []
    legv = {}                                 # leg -> its rule's verdict
    exits = []          # (verdict, short why, exit level text, door text, door %)
    px_now = float(c.iloc[-1])

    def pct_door(level):
        d = (px_now / level - 1) * 100 if level else None
        return ("%.1f" % level if level else "-",
                "%+.1f%%" % d if d is not None else "-", d)
    if "swing" in legs:
        r = pt.judge_swing(c, lo, pos["entry"], pos["entry_date"])
        v, w = r[:2]
        verdicts.append(v)
        legv["swing"] = v
        why.append("Swing rule: %s (%s)" % (v, w))
        lvl = max(x for x in (r[3], r[4]) if x == x) if len(r) > 4 else None
        exits.append((v, "swing: " + w) + pct_door(lvl))
    if "investing" in legs:
        r = pt.judge_investing(c, pos["entry_date"])
        v, w = r[:2]
        verdicts.append(v)
        legv["investing"] = v
        why.append("Investing rule: %s (%s)" % (v, w))
        exits.append((v, "investing: " + w) +
                     pct_door(r[3] if len(r) > 3 else None))
    if "momentum" in legs:
        r = pt.judge_momentum(s, c, lo, hi, pos["entry"],
                              pos["entry_date"], ranks)
        v, w = r[:2]
        verdicts.append(v)
        legv["momentum"] = v
        why.append("Momentum rule: %s (%s)" % (v, w))
        rk0 = ranks.get(s)
        exits.append((v, "momentum: " + w, "rank %d" % KEEP_RANK,
                      "%d rank" % (KEEP_RANK - rk0) if rk0 is not None
                      else "rank ?", (KEEP_RANK - rk0) / 2.0
                      if rk0 is not None else None))
    if "sip" in legs:
        verdicts.append("SIP")
        why.append("SIP: regular buying, no sell rule (%g sh)" % legs["sip"])
        exits.append(("SIP", "SIP: koi sell rule nahi", "-", "-", None))
    if verdicts:
        rec = min(verdicts, key=lambda v: LEG_ORDER.get(v, 9))
        basis = "+".join(legs)
    else:
        rec = combined(t, stage4_now(c), rk)
        basis = "untagged (combined check)"
        if pos["mode"] == "WATCH":
            rec, basis = WATCH_WORD[rec], "watchlist (combined check)"
        why.append("%s: %s 40w MA %.0f; momentum rank %s"
                   % (rec, "above" if t["px"] > t["ma200"] else "BELOW",
                      t["ma200"], rk if rk is not None else "none (outside "
                      "the >= Rs 10k Cr universe)"))
        exits.append((rec, "%s 40w MA, rank %s" % (
            "above" if t["px"] > t["ma200"] else "BELOW",
            rk if rk is not None else "-")) + pct_door(t["ma200"]))
    if prov.get(s) and rec not in ("HOLD", "KEEP"):
        why.append("live price during market hours -- counts only if it "
                   "CLOSES here")
    if pos["note"]:
        why.append(pos["note"])
    f = fund.get(s, {})
    n = news.get(s, [])
    ex = sorted(exits, key=lambda e: (LEG_ORDER.get(e[0], 9),
                                      e[4] if e[4] is not None else 1e9))
    ex = ex[0] if ex else (rec, "", "-", "-", None)
    fl = (filings or {}).get(s) or []
    base.update({
        "Kyun": ex[1], "Exit level": ex[2], "Exit se door": ex[3],
        "_door": ex[4], "_legv": legv,
        "Headline": ("!! " + fl[0][2]) if fl and fl[0][3] else
        ("%s: %s" % (n[0][0], n[0][1]) if n else
         ("%s %s" % (fl[0][0], fl[0][2]) if fl else "")),
        "Recommendation": rec, "Basis": basis, "Why": " | ".join(why),
        "LTP": round(t["px"], 2),
        "P&L %": round((t["px"] / pos["entry"] - 1) * 100, 1)
        if pos["entry"] else None,
        "Value (Rs)": round(t["px"] * pos["qty"]),
        "Stage": t["stage"], "40w MA": round(t["ma200"], 1),
        "vs 40w %": round((t["px"] / t["ma200"] - 1) * 100, 1),
        "30w MA": round(t["ma150"], 1), "50 DMA": round(t["ma50"], 1),
        "RSI 14": round(t["rsi"], 0), "From 52w High %": round(t["dist52"], 1),
        "ATR %": round(t["atr_pct"], 1),
        "6m Ret %": round(t["ret6"], 1) if t["ret6"] == t["ret6"] else None,
        "12m Ret %": round(t["ret12"], 1) if t["ret12"] == t["ret12"] else None,
        "Mom Rank": rk, "W+TT today": wtt.get(s, "-"),
        "P/E": f.get("P/E"), "ROCE %": f.get("ROCE %"), "ROE %": f.get("ROE %"),
        "D/E": f.get("D/E"), "Qtr Profit YoY %": f.get("Qtr Profit YoY %"),
        "Qtr Sales YoY %": f.get("Qtr Sales YoY %"),
        "Fund (swing)": f.get("Fund Swing"), "Fund (invest)": f.get("Fund Invest"),
        "Promoter Δ": f.get("Promoter Δ"), "FII Δ": f.get("FII Δ"),
        "DII Δ": f.get("DII Δ"),
        "News (7 days)": " || ".join("%s: %s (%s)" % x for x in n),
        "NSE filings (30d)": fmt_filings((filings or {}).get(s, []))
        if filings is not None else "",
        "Red flag": "YES" if any(x[3] for x in ((filings or {}).get(s) or []))
        else ""})
    return base


# ================================================================== excel
HCOLS = ["Recommendation", "Mode", "Symbol", "Qty", "Entry", "LTP", "P&L %",
         "Value (Rs)", "Basis", "Why", "Stage", "40w MA", "vs 40w %", "30w MA",
         "50 DMA", "RSI 14", "From 52w High %", "ATR %", "6m Ret %",
         "12m Ret %", "Mom Rank", "W+TT today", "P/E", "ROCE %", "ROE %", "D/E",
         "Qtr Profit YoY %", "Qtr Sales YoY %", "Fund (swing)", "Fund (invest)",
         "Promoter Δ", "FII Δ", "DII Δ", "Red flag", "NSE filings (30d)", "News (7 days)"]
WIDTH = {"Why": 70, "News (7 days)": 90, "NSE filings (30d)": 90, "Red flag": 8, "Basis": 16, "Stage": 16,
         "Recommendation": 13, "Symbol": 13, "Fund (swing)": 9,
         "Fund (invest)": 9}
REC_FILL = {"EXIT": "F8CBAD", "SELL": "F8CBAD", "SELL@REBAL": "FCE4D6",
            "WATCH": "FFE699", "WEAK": "FFE699", "HOLD": "C6EFCE",
            "KEEP": "C6EFCE", "NO DATA": "D9D9D9", "STRONG": "C6EFCE",
            "AVOID": "F8CBAD", "SIP": "DDEBF7"}


SCAN_SHEETS = ["Swing", "Investing", "Momentum_Top20", "Fundamentals"]
SHEET_INFO = [
    ("Dashboard", "this page: summary + what to do today"),
    ("Holdings", "your stocks as cards: ACTION, why, P&L, how far the exit is"),
    ("Sell", "stocks the rules say to SELL today: Sell? YES/NO -> rbtrack "
             "(only if TRADING is ON)"),
    ("Journal", "every trade: P&L after fees, dividends and tax, month by "
                "month, vs Nifty"),
    ("Actions", "all buy candidates: pick BUY / BUY MTF / WATCH + Amount (Rs)"),
    ("SIP", "regular buying plans: Monthly / Weekly / Daily, amount, capital, "
            "BUY / BUY MTF -> rbtrack buys when due"),
    ("Super-Buy", "common stocks: in BOTH the W+TT swing list and momentum "
                  "top 20, best momentum rank first"),
    ("Rebalance", "momentum SELL / BUY / HOLD (1st trading day of the month)"),
    ("Watchlist", "your WATCH stocks, best momentum rank first"),
    ("Holdings_Table", "the same holdings as one sortable table, all columns"),
    ("Swing", "master scan: W+TT signals (BUY / FIT / LATE) + fundamentals"),
    ("Investing", "master scan: same signals, Stage-4 exit"),
    ("Momentum_Top20", "master scan: RAMOM top 20 (sector cap 4)"),
    ("Fundamentals", "master scan: Screener.in detail per stock (info only)")]
TAB = {"Dashboard": "1F4E78", "Holdings": "548235", "Journal": "7030A0",
       "Sell": "C00000",
       "Actions": "FFC000", "SIP": "FFC000", "Super-Buy": "00B050", "Rebalance": "2E75B6",
       "Watchlist": "2E75B6"}
NAVY, GREY_TXT, LINE = "1F4E78", "7F7F7F", "D9D9D9"
ACT_COL = {"EXIT": ("C00000", "FFFFFF"), "SELL": ("C00000", "FFFFFF"),
           "AVOID": ("C00000", "FFFFFF"), "SELL@REBAL": ("E46C0A", "FFFFFF"),
           "WATCH": ("FFC000", "1F1F1F"), "WEAK": ("FFC000", "1F1F1F"),
           "HOLD": ("1E7B34", "FFFFFF"), "KEEP": ("1E7B34", "FFFFFF"),
           "STRONG": ("1E7B34", "FFFFFF"), "NO DATA": ("7F7F7F", "FFFFFF"),
           "SIP": ("2E75B6", "FFFFFF")}
MONEY = ("Value (Rs)", "Amount (Rs)", "Gross", "Gross P&L", "Dividend", "Fees",
         "Fees (buy)", "NET", "NET (tax se pehle)", "Ab tak kul NET",
         "Tax (andaaza)", "Unrealised", "Agar aaj becho: NET")
PRICE = ("Entry", "LTP", "Buy", "Sell", "40w MA", "30w MA", "50 DMA",
         "Added @")
SIGNED = ("P&L %", "Net %", "vs 40w %", "Promoter Δ", "FII Δ", "DII Δ",
          "Nifty same period %", "Nifty same mahina %") + MONEY
# Watchlist: fewer, clearer columns (header shown -> data key)
WCOLS = [("Mom Rank", "Mom Rank"), ("Symbol", "Symbol"),
         ("Verdict", "Recommendation"), ("Kyun", "Why"),
         ("Since added %", "P&L %"), ("Added @", "Entry"), ("LTP", "LTP"),
         ("Stage", "Stage"), ("RSI 14", "RSI 14"), ("vs 40w %", "vs 40w %"),
         ("From 52w High %", "From 52w High %"), ("W+TT today", "W+TT today"),
         ("Fund (swing)", "Fund (swing)"), ("Red flag", "Red flag"),
         ("NSE filings (30d)", "NSE filings (30d)"),
         ("News (7 days)", "News (7 days)")]
ACOLS = ["Ticker", "Action", "Amount (Rs)", "Qty (auto)", "Strategy Overlap",
         "Held here", "Mom Rank", "RS Rank", "W+TT Status", "LTP",
         "Sector / Industry", "Fundamental Status", "Momentum Score", "ATR %",
         "Dist 52W High %"]


def nfmt(h):
    if h in MONEY:
        return '#,##0;-#,##0;0'
    if h in PRICE:
        return '#,##0.00'
    if h in ("RSI 14",) or "Rank" in h or h in ("Qty", "Din", "Trades band",
                                                "Jeete", "Qty Held",
                                                "Shares to Buy", "Qty (auto)"):
        return '#,##0'
    if h in ("Promoter Δ", "FII Δ", "DII Δ"):
        return '+0.00;-0.00;0'
    if "%" in h or h in ("P/E", "D/E", "Momentum Score"):
        return '+0.0;-0.0;0' if h in SIGNED else '0.0'
    return None


def dashboard(ws, d, have):
    """First sheet: short, sorted summary + clickable sheet list."""
    from openpyxl.styles import Font, PatternFill, Alignment
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 110
    ws.sheet_view.showGridLines = False
    r = [1]

    def line(a, b="", bold=False, color=None, fill=None, link=None):
        ca = ws.cell(row=r[0], column=1, value=a)
        cb = ws.cell(row=r[0], column=2, value=b)
        ca.font = Font(bold=True)
        cb.font = Font(bold=bold, color=color)
        cb.alignment = Alignment(wrap_text=True, vertical="top")
        ca.alignment = Alignment(vertical="top")
        if fill:
            for c in (ca, cb):
                c.fill = PatternFill("solid", fgColor=fill)
        if link:
            from openpyxl.worksheet.hyperlink import Hyperlink
            ca.hyperlink = Hyperlink(ref=ca.coordinate,
                                     location="'%s'!A1" % link)
            ca.font = Font(bold=True, color="0563C1", underline="single")
        r[0] += 1

    def section(t):
        r[0] += 1
        c = ws.cell(row=r[0], column=1, value=t)
        c.font = Font(bold=True, color="FFFFFF", size=12)
        for col in (1, 2):
            ws.cell(row=r[0], column=col).fill = PatternFill("solid",
                                                             fgColor="1F4E78")
        r[0] += 1

    t = ws.cell(row=1, column=1, value=d["title"])
    t.font = Font(bold=True, size=16)
    r[0] = 2
    import settings
    from openpyxl.worksheet.datavalidation import DataValidation
    on = d.get("trading", "OFF") == "ON"
    line(settings.LABEL, "ON" if on else "OFF", bold=True,
         color="1E7B34" if on else "C00000", fill="FFF2CC")
    dv = DataValidation(type="list", formula1='"ON,OFF"', allow_blank=False)
    dv.add("B2")
    ws.add_data_validation(dv)
    ws.cell(row=2, column=2).font = Font(bold=True, size=14,
                                         color="1E7B34" if on else "C00000")
    line("", "OFF = rbtrack koi order nahi bhejta (na BUY, na SIP, na SELL). "
         "ON = bhejta hai, phir bhi pehle YES / YES SELL type karna hota hai. "
         "Badalna: B2 mein ON/OFF chuno, save.", color="7F7F7F")
    line("Prices", d["prices"])
    line("Master scan", d["master"])
    line("Market", d["regime"], bold=True,
         color="C00000" if d["regime_red"] else "006100")
    section("YOUR MONEY")
    for a, b in d["money"]:
        line(a, b)
    section("DO / CHECK TODAY")
    for a, b, red in d["todo"]:
        line(a, b, bold=red, color="C00000" if red else None,
             fill="FCE4D6" if red else None)
    section("WATCHLIST")
    for a, b in d["watch"]:
        line(a, b)
    section("SHEETS (click a name)")
    for name, info in SHEET_INFO:
        if name in have:
            line(name, info, link=name)
    for w in d["warns"]:
        line("! warning", w, color="C00000")
    ws.freeze_panes = "A2"


def rebal_window(today):
    """Momentum sells go at the open of the 1st trading day of a month: an AMO
    placed on the last weekday of the month (or catch-up on the 1st)."""
    d = pd.Timestamp(today)
    nxt = d + pd.Timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += pd.Timedelta(days=1)
    first = pd.Timestamp(d.year, d.month, 1)
    while first.weekday() >= 5:
        first += pd.Timedelta(days=1)
    return nxt.month != d.month or d.normalize() == first


SELL_COLS = ["Symbol", "Product", "Qty", "Sell?", "Rule", "Backtested?",
             "Kyun", "Note"]


def sell_rows(hold, sp, demat, trading, picks, today):
    """Rows for the Sell sheet: LIVE stocks whose rule says sell today.
    Qty = only the legs whose rule fired (split.csv), per product; untagged
    holdings = whole demat qty. Default Sell? = YES only for backtested rules
    (EXIT, SELL@REBAL in the rebalance window) and only if TRADING is ON."""
    import broker_api as ba
    dq = {h["symbol"]: float(h["qty"]) for h in demat or []}
    win = rebal_window(today)
    live = sp[sp["mode"] == "LIVE"] if len(sp) else sp
    out = []
    for h in hold:
        if h.get("Mode") != "LIVE" or h.get("Recommendation") not in (
                "EXIT", "SELL@REBAL", "SELL"):
            continue
        s = h["Symbol"]
        if s not in dq:
            continue                           # not (or no longer) in demat
        legv = h.get("_legv") or {}
        rows = live[live["symbol"] == s] if len(live) else live
        byprod = {}
        if legv:                               # tagged: firing legs only
            for _, r in rows.iterrows():
                for leg in ("swing", "investing", "momentum"):
                    v = legv.get(leg)
                    if str(r.get("strategy")) == "SIP" or r["%s_qty" % leg] <= 0:
                        continue
                    if v == "EXIT" or (v == "SELL@REBAL"):
                        prod = "MTF" if str(r.get("product", "")).upper() \
                            == "MTF" else "CNC"
                        byprod.setdefault(prod, [0.0, v])
                        byprod[prod][0] += r["%s_qty" % leg]
                        if v == "EXIT":
                            byprod[prod][1] = "EXIT"
        else:                                  # bought outside the system
            byprod["CNC"] = [dq[s], "SELL"]
        left = dq[s]
        for prod, (q, rule) in byprod.items():
            q = min(q, left)
            left -= q
            if q < 1:
                continue
            tested = rule in ("EXIT", "SELL@REBAL")
            note, blocked = "", False
            if not tested:
                note = "bahar se khareeda: combined check backtested NAHI " \
                    "(bechna ho to khud YES chuno)"
            if rule == "SELL@REBAL" and not win:
                blocked, note = True, "momentum: sirf mahine ke 1st trading " \
                    "day (uske pehle wali shaam rbtrack)"
            if ba.sold_recently(s):
                blocked, note = True, "SELL order pehle hi ja chuka (4 din)"
            default = "YES" if (tested and trading == "ON") else "NO"
            pick = picks.get((s, prod))
            out.append({"Symbol": s, "Product": prod, "Qty": int(q),
                        "Sell?": "NO" if blocked else (
                            pick if pick in ("YES", "NO") else default),
                        "Rule": {"EXIT": "EXIT (strategy rule)",
                                 "SELL@REBAL": "SELL@REBAL (momentum)",
                                 "SELL": "SELL (combined check)"}[rule],
                        "Backtested?": "Haan" if tested else "Nahi",
                        "Kyun": short_why(h.get("Kyun") or h.get("Why", "")),
                        "Note": note})
    return out


def cut(t, n):
    t = " ".join(str(t).split())
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def short_why(t):
    """The exit-rule text, short enough for a card."""
    t = str(t)
    for a, b in ((" -- rule already fired, you should be out",
                  " (rule fired, bahar niklo)"),
                 ("10 straight closes under a falling 30-week MA -- Stage 4 "
                  "breakdown", "Stage 4: 10 closes falling 30w MA ke neeche"),
                 ("Stage 4 breakdown on", "Stage 4 on"),
                 ("under a falling 30-week MA for", "falling 30w MA ke neeche"),
                 ("under the 30-week MA but the MA is still rising",
                  "30w MA ke neeche (MA abhi bhi upar ja raha)"),
                 ("low touched the 20% stop", "20% stop hit"),
                 ("closed below the 40-week MA", "40w MA ke neeche close"),
                 ("clear of the nearer exit", "exit se door"),
                 ("above the nearer exit level", "exit se upar"),
                 ("30-week MA", "30w MA"), ("40-week MA", "40w MA"),
                 ("keep while <=", "rakho jab tak <="), ("session(s)", "din")):
        t = t.replace(a, b)
    return cut(t, 110)


def write_book(path, hold, rebal, comp, held_modes, old_actions, banner,
               old_amount=None, master=None, dash=None, jrep=None,
               sip_rows=None, sells=None, trading="OFF", symbols=None):
    old_amount = old_amount or {}
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter as L
    from openpyxl.worksheet.datavalidation import DataValidation
    head = Font(bold=True, color="FFFFFF")
    hfill = PatternFill("solid", fgColor=NAVY)
    thin = Side(style="thin", color=LINE)
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    fill = lambda c: PatternFill("solid", fgColor=c)                # noqa
    wb = None
    if master and os.path.exists(master):   # one file: scan sheets inside
        try:
            wb = load_workbook(master)
            for n in list(wb.sheetnames):
                if n not in SCAN_SHEETS:
                    del wb[n]
        except Exception as e:
            print("! could not copy the master scan sheets (%s)"
                  % type(e).__name__)
            wb = None
    if wb is None:
        wb = Workbook()
        del wb[wb.active.title]

    def clean(v):
        if isinstance(v, (np.floating, np.integer)):
            v = float(v)
        if isinstance(v, float) and v != v:
            v = None
        return v

    def table(ws, cols, rows, fills=None, widths=None, start=1, keys=None,
              freeze="C2", filt=True):
        """Header row + rows; number formats + green/red for signed cols."""
        keys = keys or cols
        for i, h in enumerate(cols, 1):
            c = ws.cell(row=start, column=i, value=h)
            c.font, c.fill, c.border = head, hfill, box
            c.alignment = Alignment(wrap_text=True, vertical="center",
                                    horizontal="center")
            if widths is not None:
                ws.column_dimensions[L(i)].width = widths.get(h, 11)
        ws.row_dimensions[start].height = 30
        for r, x in enumerate(rows, start + 1):
            for i, (h, k) in enumerate(zip(cols, keys), 1):
                v = clean(x.get(k))
                c = ws.cell(row=r, column=i, value=v)
                c.border = box
                f = nfmt(h)
                if f and isinstance(v, (int, float)):
                    c.number_format = f
                if h in SIGNED and isinstance(v, (int, float)) and v:
                    c.font = Font(bold=h in ("P&L %", "Net %", "NET",
                                             "NET (tax se pehle)"),
                                  color="1E7B34" if v > 0 else "C00000")
                if h in ("Symbol", "Ticker"):
                    c.font = Font(bold=True)
            if fills:
                k, fmap = fills
                col = fmap.get(x.get(k))
                if col:
                    ws.cell(row=r, column=keys.index(k) + 1).fill = fill(col)
        if freeze:
            ws.freeze_panes = freeze
        if filt and rows:
            ws.auto_filter.ref = "A%d:%s%d" % (start, L(len(cols)),
                                               start + len(rows))
        return start + len(rows)

    def note(ws, row, text, col=1):
        c = ws.cell(row=row, column=col, value=text)
        c.font = Font(italic=True, color=GREY_TXT, size=10)

    def band(ws, row, text, ncol, color=NAVY, size=12):
        for i in range(1, ncol + 1):
            ws.cell(row=row, column=i).fill = fill(color)
        ws.merge_cells(start_row=row, start_column=1, end_row=row,
                       end_column=ncol)
        c = ws.cell(row=row, column=1, value=text)
        c.font = Font(bold=True, color="FFFFFF", size=size)
        ws.row_dimensions[row].height = 22

    def boxes(ws, row, items, width=3):
        """Summary boxes: [(label, value, color[, small text under it])],
        each `width` columns; everything wraps inside its own box."""
        subs = any(len(x) > 3 and x[3] for x in items)
        for n, x in enumerate(items):
            lab, val, col = x[:3]
            sub = x[3] if len(x) > 3 else ""
            c0 = 1 + n * width
            cells = [(row, lab, Font(size=9, color=GREY_TXT, bold=True)),
                     (row + 1, val, Font(size=15, bold=True,
                                         color=col or "1F1F1F"))]
            if subs:
                cells.append((row + 2, sub, Font(size=9, color="404040")))
            for rr, v, f in cells:
                c = ws.cell(row=rr, column=c0, value=v)
                c.font = f
                c.alignment = Alignment(wrap_text=True, vertical="center")
                ws.merge_cells(start_row=rr, start_column=c0, end_row=rr,
                               end_column=c0 + width - 2)
                for cc in range(c0, c0 + width - 1):
                    ws.cell(row=rr, column=cc).fill = fill("F3F6FA")
        ws.row_dimensions[row].height = 26
        ws.row_dimensions[row + 1].height = 26
        if subs:
            ws.row_dimensions[row + 2].height = 32

    own = [h for h in hold if h["Mode"] != "WATCH"]
    watch = sorted([h for h in hold if h["Mode"] == "WATCH"],
                   key=lambda h: h.get("Mom Rank") if h.get("Mom Rank")
                   is not None else 10 ** 6)

    # ------------------------------------------------------------ Holdings
    ws = wb.create_sheet("Holdings")
    ws.sheet_view.showGridLines = False
    PER, W = 4, 3                                  # cards per row, cols/card
    CW = 32                                        # value column width
    for k in range(PER):
        ws.column_dimensions[L(k * W + 1)].width = 18   # fits HINDCOPPER
        ws.column_dimensions[L(k * W + 2)].width = CW
        ws.column_dimensions[L(k * W + 3)].width = 2
    ncol = PER * W
    who = banner.split(" | master")[0].replace("Portfolio ", "")
    band(ws, 1, "HOLDINGS  |  " + who, ncol, size=14)
    sell = [h["Symbol"] for h in own if h.get("Recommendation") in
            ("EXIT", "SELL", "SELL@REBAL")]
    near = [h["Symbol"] for h in own if h.get("Recommendation") not in
            ("EXIT", "SELL", "SELL@REBAL") and h.get("_door") is not None
            and h["_door"] < 5]
    flags = [h["Symbol"] for h in own if h.get("Red flag")]

    def pnl(mode):
        rows = [h for h in own if h["Mode"] == mode and h.get("Value (Rs)")]
        val = sum(h["Value (Rs)"] for h in rows)
        cost = sum((h.get("Entry") or 0) * h["Qty"] for h in rows)
        return (val - cost, (val / cost - 1) * 100 if cost else 0) \
            if rows else None
    lp, pp = pnl("LIVE"), pnl("PAPER")
    txt = lambda p: "-" if p is None else "%s%s (%+.1f%%)" % (      # noqa
        "+" if p[0] >= 0 else "-", format(int(abs(p[0])), ","), p[1])
    names = lambda xs: ", ".join(xs[:8]) + (" +%d" % (len(xs) - 8)   # noqa
                                            if len(xs) > 8 else "")
    boxes(ws, 3, [
        ("AAJ BECHNA", len(sell), "C00000" if sell else "1E7B34",
         names(sell)),
        ("EXIT KE PAAS (<5%)", len(near), "9C6500" if near else "1E7B34",
         names(near)),
        ("RED FLAG (NSE filing)", len(flags), "C00000" if flags else "1E7B34",
         names(flags)),
        ("P&L (LIVE)", txt(lp), "1E7B34" if lp and lp[0] > 0 else
         "C00000" if lp and lp[0] < 0 else "1F1F1F",
         "paper %s" % txt(pp) if pp else "")], width=W)

    def card(r0, c0, h):
        rec = h.get("Recommendation", "")
        bg, fg = ACT_COL.get(rec, ("7F7F7F", "FFFFFF"))
        a = ws.cell(row=r0, column=c0, value=h["Symbol"])
        b = ws.cell(row=r0, column=c0 + 1, value=rec)
        for c in (a, b):
            c.fill, c.font = fill(bg), Font(bold=True, size=13, color=fg)
        b.alignment = Alignment(horizontal="right")
        p = clean(h.get("P&L %"))
        a = ws.cell(row=r0 + 1, column=c0, value=p / 100 if isinstance(
            p, (int, float)) else "-")
        a.number_format = '+0.0%;-0.0%;0.0%'
        a.font = Font(bold=True, size=18, color="1E7B34" if (p or 0) > 0
                      else "C00000" if (p or 0) < 0 else "1F1F1F")
        v = clean(h.get("Value (Rs)"))
        b = ws.cell(row=r0 + 1, column=c0 + 1, value="Rs %s  |  %s" % (
            format(int(v), ",") if v else "-", h["Mode"]))
        b.font = Font(color=GREY_TXT)
        b.alignment = Alignment(horizontal="right", vertical="center")
        lines = [
            ("Kyun", short_why(h.get("Kyun") or h.get("Why", ""))),
            ("Exit se door", h.get("Exit se door", "-")),
            ("Exit level", h.get("Exit level", "-")),
            ("Qty @ Entry", "%g @ %s" % (h.get("Qty") or 0, "%.2f" %
                                         h["Entry"] if h.get("Entry") else "-")),
            ("Stage / RSI", "%s / %s" % (str(h.get("Stage", "-")).split(" (")[0],
                                         "%.0f" % h["RSI 14"] if h.get(
                                             "RSI 14") is not None else "-")),
            ("Rank / W+TT", "%s / %s" % (h.get("Mom Rank") if h.get(
                "Mom Rank") is not None else "-", h.get("W+TT today", "-"))),
            ("News / filing", cut(h.get("Headline") or "-", 115))]
        for n, (lab, val) in enumerate(lines, 2):
            a = ws.cell(row=r0 + n, column=c0, value=lab)
            b = ws.cell(row=r0 + n, column=c0 + 1, value=val)
            a.font = Font(size=9, color=GREY_TXT)
            wrap = lab in ("Kyun", "News / filing")
            a.alignment = Alignment(vertical="top")
            b.alignment = Alignment(horizontal="left" if wrap else "right",
                                    vertical="top", wrap_text=wrap)
            if lab == "Exit se door" and h.get("_door") is not None and \
                    h["_door"] < 5:
                b.fill, b.font = fill("FFE0E0"), Font(bold=True,
                                                     color="C00000")
            if lab == "News / filing" and str(val).startswith("!!"):
                b.font = Font(bold=True, color="C00000")
        for rr in range(r0, r0 + 9):
            for cc in (c0, c0 + 1):
                ws.cell(row=rr, column=cc).border = box
        return 9

    row = 7
    for mode, label in (("LIVE", "LIVE (demat, asli paisa)"),
                        ("PAPER", "PAPER (practice)")):
        rows = sorted([h for h in own if h["Mode"] == mode],
                      key=lambda x: (LEG_ORDER.get(x.get("Recommendation"), 8),
                                     x["_door"] if x.get("_door") is not None
                                     else 1e9))
        if not rows:
            continue
        p = pnl(mode)
        band(ws, row, "%s  --  %d stock(s)%s" % (
            label, len(rows), "  |  P&L " + txt(p) if p else ""), ncol,
            color="548235" if mode == "LIVE" else "8EA9C1")
        row += 2
        for n in range(0, len(rows), PER):
            for k, h in enumerate(rows[n:n + PER]):
                card(row, 1 + k * W, h)
            chunk = rows[n:n + PER]                   # Kyun / News: fit text
            for rr, key in ((row + 2, "Kyun"), (row + 8, "News / filing")):
                txts = [short_why(h.get("Kyun") or h.get("Why", ""))
                        if key == "Kyun" else cut(h.get("Headline") or "-",
                                                  115) for h in chunk]
                nl = max(math.ceil(len(t) / (CW + 2)) for t in txts)
                ws.row_dimensions[rr].height = max(18, 15 * min(nl, 4) + 4)
            row += 10
    if not own:
        ws.cell(row=6, column=1, value="Koi holding nahi (demat khaali, koi "
                "SIP / trade abhi).").font = Font(size=12, italic=True)
        row = 8
    note(ws, row, "Card ka rang = ACTION. Laal 'Exit se door' = exit 5% se kam "
         "door. Sort/filter: Holdings_Table tab. Sell hamesha broker app mein.")
    note(ws, row + 1, "Tagged (split.csv) -> strategy ka backtested rule; "
         "untagged -> combined check (backtested nahi). Fundamentals / news "
         "sirf info.")

    # ------------------------------------------------------------ Sell
    wsl = wb.create_sheet("Sell")
    wsl.sheet_view.showGridLines = False
    on = trading == "ON"
    band(wsl, 1, "SELL  |  TRADING %s  --  %s" % (
        "ON" if on else "OFF", "Sell? = YES wale rbtrack se bikenge (YES SELL "
        "type karke)" if on else "koi order nahi jaayega (Dashboard B2 = ON "
        "karo)"), len(SELL_COLS), color="1E7B34" if on else "C00000")
    last = table(wsl, SELL_COLS, list(sells or []), None,
                 {"Symbol": 13, "Product": 9, "Qty": 8, "Sell?": 8,
                  "Rule": 24, "Backtested?": 12, "Kyun": 48, "Note": 48},
                 start=3, freeze="B4", filt=False)
    sc = SELL_COLS.index("Sell?") + 1
    for rr, x in enumerate(sells or [], 4):
        c = wsl.cell(row=rr, column=sc)
        c.fill = fill("FFF2CC")
        c.font = Font(bold=True, color="C00000" if x["Sell?"] == "YES"
                      else "7F7F7F")
        for cc in (SELL_COLS.index("Kyun") + 1, SELL_COLS.index("Note") + 1):
            wsl.cell(row=rr, column=cc).alignment = Alignment(wrap_text=True,
                                                              vertical="top")
    if sells:
        v = DataValidation(type="list", formula1='"YES,NO"', allow_blank=False)
        v.add("%s4:%s%d" % (L(sc), L(sc), last))
        wsl.add_data_validation(v)
    else:
        note(wsl, 4, "Aaj kisi stock pe bechne ka rule nahi aaya.")
        last = 4
    note(wsl, last + 2, "YES = rbtrack (15:30 ke baad) is qty ka SELL AMO "
         "lagayega (agle din open pe). Qty = sirf us strategy ka hissa jiska "
         "rule fire hua (SIP kabhi nahi). Momentum SELL@REBAL sirf mahine ke 1st "
         "trading day.")
    note(wsl, last + 3, "Demat se bechne ke liye broker pe DDPI / POA chahiye. "
         "Bika hua trade agle rb pe journal mein khud aata hai.")

    # ------------------------------------------------------------ Journal
    wj = wb.create_sheet("Journal")
    wj.sheet_view.showGridLines = False
    widths = [13, 12, 22, 12, 12, 8, 8, 10, 10, 11, 10, 10, 13, 9, 11, 22]
    for i, w in enumerate(widths, 1):
        wj.column_dimensions[L(i)].width = w
    band(wj, 1, "TRADE JOURNAL  |  " + banner.split(" | master")[0].replace(
        "Portfolio ", ""), 16, size=14)
    row = 3
    if not jrep:
        wj.cell(row=3, column=1, value="Abhi koi trade nahi. rbtrack se BUY / "
                "BUY MTF / SIP karoge to yahan aayega.").font = Font(size=12,
                                                             italic=True)
        row = 5
    for mode in ("LIVE", "PAPER"):
        r = (jrep or {}).get(mode)
        if not r:
            continue
        band(wj, row, "LIVE  --  asli paisa" if mode == "LIVE" else
             "PAPER  --  practice (nakli paisa, asli rates se fees/tax)", 16,
             color="548235" if mode == "LIVE" else "8EA9C1")
        row += 1
        items = []
        for lab, val, sub in r["cards"]:
            if isinstance(val, (int, float)):
                col = "1E7B34" if val > 0 else "C00000" if val < 0 else None
                val = ("+" if val > 0 else "-" if val < 0 else "") + \
                    "Rs " + format(int(round(abs(val))), ",")
            else:
                col = "1E7B34" if str(val).startswith("+") else \
                    "C00000" if str(val).startswith("-") else None
            items.append((lab.upper(), val, col))
        boxes(wj, row + 1, [it + (c[2],) for it, c in zip(items, r["cards"])],
              width=3)
        row += 5
        wj.cell(row=row, column=1, value="MAHINE-WISE").font = Font(
            bold=True, color=NAVY)
        mcols = ["Mahina", "Trades band", "Jeete", "Gross", "Dividend", "Fees",
                 "Tax (andaaza)", "NET", "Graph", "Ab tak kul NET",
                 "Nifty same mahina %"]
        big = max([abs(m["NET"]) for m in r["months"]] or [1]) or 1
        for m in r["months"]:
            m["Graph"] = "█" * max(1, int(round(abs(m["NET"]) / big * 14))) \
                if m["NET"] else ""
        last = table(wj, mcols, r["months"], start=row + 1, freeze=None,
                     filt=False)
        for rr, m in enumerate(r["months"], row + 2):
            g = wj.cell(row=rr, column=mcols.index("Graph") + 1)
            g.font = Font(color="70AD47" if m["NET"] >= 0 else "E06666")
        if not r["months"]:
            note(wj, last + 1, "abhi koi trade band nahi hua / dividend nahi")
            last += 1
        row = last + 2
        wj.cell(row=row, column=1, value="BAND HUE TRADES").font = Font(
            bold=True, color=NAVY)
        ccols = ["Symbol", "Strategy", "Kyun becha", "Buy date", "Sell date",
                 "Din", "Qty", "Buy", "Sell", "Gross P&L", "Dividend", "Fees",
                 "NET (tax se pehle)", "Net %", "Nifty same period %",
                 "Rule follow?"]
        last = table(wj, ccols, r["closed"], start=row + 1, freeze=None,
                     filt=False)
        for rr, x in enumerate(r["closed"], row + 2):
            c = wj.cell(row=rr, column=len(ccols))
            c.font = Font(bold=True, color="1E7B34" if x["Rule follow?"] ==
                          "Haan" else "C00000")
        if not r["closed"]:
            note(wj, last + 1, "koi nahi")
            last += 1
        row = last + 2
        wj.cell(row=row, column=1, value="ABHI KHULE TRADES").font = Font(
            bold=True, color=NAVY)
        ocols = ["Symbol", "Strategy", "Status", "Buy date", "Din", "Qty",
                 "Buy", "LTP", "Unrealised", "Dividend", "Fees (buy)",
                 "Agar aaj becho: NET", "Note"]
        last = table(wj, ocols, r["open"], start=row + 1, freeze=None,
                     filt=False)
        if not r["open"]:
            note(wj, last + 1, "koi nahi")
            last += 1
        row = last + 3
    note(wj, row, "Fees = broker ke official rates (STT 0.1% dono taraf, "
         "stamp, exchange, SEBI, GST, DP har sell). Tax = ANDAAZA: STCG 20.8%, "
         "LTCG 13% (Rs 1.25 lakh chhoot), loss set-off ke baad, STT deductible "
         "nahi. Dividend pe tax slab se (alag). ITR ke liye broker ka P&L "
         "statement final.")
    note(wj, row + 1, "Sell apne aap pakda jaata hai (demat + broker trade "
         "history). Na pakde to: rbtrack --sold SYMBOL PRICE --date "
         "YYYY-MM-DD")

    # ------------------------------------------------------------ Actions
    wa = wb.create_sheet("Actions")
    extra = [c for c in comp.columns if c not in ACOLS and c not in
             ("Regime", "Shares (Rs slot)")] if len(comp) else []
    acols = ACOLS + extra
    rows = []
    for _, x in comp.iterrows():
        d = dict(x)
        t = str(d.get("Ticker", "")).upper()
        d["Held here"] = ", ".join(sorted(held_modes.get(t, [])))
        d["Action"] = old_actions.get(t, "")
        d["Amount (Rs)"] = old_amount.get(t)
        rows.append(d)
    widths = {"Ticker": 13, "Strategy Overlap": 14, "Sector / Industry": 24,
              "Action": 12, "Held here": 10, "Amount (Rs)": 12,
              "Qty (auto)": 9, "Fundamental Status": 12, "W+TT Status": 9}
    last = table(wa, acols, rows, ("Strategy Overlap",
                                   {"Super-Buy": "C6EFCE"}), widths,
                 freeze="E2")
    col = L(acols.index("Action") + 1)
    amt = L(acols.index("Amount (Rs)") + 1)
    qty = acols.index("Qty (auto)") + 1
    ltp = L(acols.index("LTP") + 1)
    for r in range(2, last + 1):
        for c in (col, amt):
            wa["%s%d" % (c, r)].fill = fill("FFF2CC")
        wa["%s%d" % (amt, r)].number_format = "#,##0"
        wa.cell(row=r, column=qty, value=(
            '=IF(OR({a}{r}="",{a}{r}="WATCH"),"",IFERROR(INT(IF({m}{r}="",'
            '{d},{m}{r})*IF(ISNUMBER(SEARCH("MTF",{a}{r})),{x},1)/{p}{r}),'
            '""))').format(a=col, m=amt, p=ltp, r=r, d=SLOT_RS, x=MTF_X))
    dv = DataValidation(type="list", formula1='"%s"' % ",".join(ms.ACTIONS),
                        allow_blank=True, showErrorMessage=True,
                        errorTitle="Action", error="Pick from the list",
                        promptTitle="Action", showInputMessage=True,
                        prompt="BUY / BUY MTF = real AMO (next open), "
                               "WATCH = no order, only the watchlist")
    dv.add("%s2:%s%d" % (col, col, max(last, 2)))
    wa.add_data_validation(dv)
    note(wa, last + 2, "Peele columns bharo: Action + Amount (Rs) (khaali = Rs "
         "%s). Qty apne aap. Save karo, phir rbtrack (15:30 ke baad). Hara = "
         "Super-Buy. Momentum buy sirf mahine ke 1st trading day."
         % format(SLOT_RS, ","))
    note(wa, last + 3, "MTF: Qty (auto) %dx maan ke dikhata hai; rbtrack broker "
         "ka asli leverage leta hai." % MTF_X)

    # ------------------------------------------------------------ SIP
    import sip as sipm
    wp = wb.create_sheet("SIP")
    pcols = [h for h, _ in sipm.SHEET] + sipm.STATUS
    cmap = {c.split(" | ")[0]: c for c in symbols or []}
    prow = [dict(x, Symbol=cmap.get(x["Symbol"], x["Symbol"]))
            for x in sip_rows or []]
    blank = 5
    last = table(wp, pcols, prow + [{} for _ in range(blank)], None,
                 {"Symbol": 13, "Frequency": 11, "Day": 7,
                  "Amount per buy (Rs)": 12, "Total capital (Rs)": 12,
                  "Product": 10, "Active": 8, "Start date": 11,
                  "Invested (Rs)": 11, "Buys": 6, "Last buy": 11,
                  "Next due": 16, "Capital left (Rs)": 12, "id": 15},
                 freeze="B2", filt=False)
    ned = len(sipm.SHEET)
    sc = pcols.index("Start date") + 1           # real date + calendar picker
    for r in range(2, last + 1):
        c = wp.cell(row=r, column=sc)
        ds_ = sipm.parse_date(c.value)
        if ds_:
            c.value = pd.Timestamp(ds_).to_pydatetime()
        c.number_format = "DD-MMM-YYYY"
    v = DataValidation(type="date", operator="greaterThan",
                       formula1="DATE(2020,1,1)", allow_blank=True,
                       showErrorMessage=True, errorTitle="Start date",
                       error="Date chahiye: double-click -> calendar, ya "
                             "DD-MM-YYYY (01-10-2026)")
    v.add("%s2:%s%d" % (L(sc), L(sc), last))
    wp.add_data_validation(v)
    dl = pcols.index("Day") + 1                   # Day dropdown
    v = DataValidation(type="list", allow_blank=True, showErrorMessage=False,
                       formula1='"%s"' % ",".join(
                           list(sipm.DAYS) + [str(i) for i in range(1, 29)]))
    v.add("%s2:%s%d" % (L(dl), L(dl), last))
    wp.add_data_validation(v)
    for r in range(2, last + 1):
        for c in range(1, ned + 1):
            wp.cell(row=r, column=c).fill = fill("FFF2CC")
        for c in range(ned + 1, len(pcols) + 1):
            wp.cell(row=r, column=c).font = Font(color=GREY_TXT)
    if symbols:                   # searchable Symbol dropdown (hidden list)
        wl = wb.create_sheet("Symbols")
        wl.cell(row=1, column=1, value="Symbol | Company (SIP dropdown)")
        for i, x in enumerate(symbols, 2):
            wl.cell(row=i, column=1, value=x)
        wl.column_dimensions["A"].width = 60
        wl.sheet_state = "hidden"
        v = DataValidation(type="list", allow_blank=True,
                           formula1="Symbols!$A$2:$A$%d" % (len(symbols) + 1),
                           showErrorMessage=False)
        v.add("A2:A%d" % last)
        wp.add_data_validation(v)
        wp.column_dimensions["A"].width = 30
    for colname, opts in (("Frequency", sipm.FREQS),
                          ("Product", sipm.PRODUCTS), ("Active", ("YES", "NO"))):
        L_ = L(pcols.index(colname) + 1)
        v = DataValidation(type="list", formula1='"%s"' % ",".join(opts),
                           allow_blank=True)
        v.add("%s2:%s%d" % (L_, L_, last))
        wp.add_data_validation(v)
    note(wp, last + 2, "Symbol: cell pe click -> dropdown mein naam ke kuch "
         "akshar likho (jaise 'tata' / 'nifty') -> list se chuno. "
         "Peele columns bharo, save karo. rbtrack (15:30 ke baad) "
         "jo SIP due hai uska order lagata hai. Day: Monthly = tarikh 1-28, "
         "Weekly = Mon..Fri, Daily = khaali. Start date: double-click -> "
         "calendar (khaali = aaj se). Amount = TUMHARA paisa har buy; "
         "BUY MTF = broker ka leverage x amount.")
    note(wp, last + 3, "Total capital khaali = koi limit nahi. Rokna: Active = "
         "NO. Hatana: row ki Symbol cell khaali karo. Grey columns khud bante "
         "hain. Har buy journal mein 'SIP' ke naam se.")
    note(wp, last + 4, "Backtest: seedhi monthly SIP ~ Nifty; weekly/daily se "
         "kuch extra nahi; single stock SIP: sabse bure 10% stocks ~ -4%/saal.")

    # ------------------------------------------------------------ Super-Buy
    wsb = wb.create_sheet("Super-Buy")
    sb = [dict(x, **{"Held here": ", ".join(sorted(held_modes.get(
        str(x.get("Ticker", "")).upper(), [])))})
          for _, x in comp.iterrows()
          if x.get("Strategy Overlap") == "Super-Buy"] if len(comp) and \
        "Strategy Overlap" in comp else []
    sb.sort(key=lambda x: x.get("Mom Rank") if x.get("Mom Rank") ==
            x.get("Mom Rank") and x.get("Mom Rank") is not None else 10 ** 6)
    scols = ["Mom Rank", "Ticker", "W+TT Status", "RS Rank", "LTP",
             "Sector / Industry", "Fundamental Status", "Momentum Score",
             "ATR %", "Dist 52W High %", "Held here"]
    scols = [c for c in scols if not len(comp) or c in comp.columns or
             c == "Held here"]
    last = table(wsb, scols, sb, None, {"Ticker": 13, "Sector / Industry": 24,
                                        "Held here": 10, "Mom Rank": 8,
                                        "Fundamental Status": 12})
    note(wsb, last + 2, "%d stock(s) W+TT swing list AUR momentum top %d dono "
         "mein. Khareedna: Actions sheet (wahi stocks, hare). Sirf overlap "
         "khareedna alag se backtest NAHI hua." % (len(sb), ms.SLOTS)
         if sb else "Aaj koi stock dono list mein nahi.")

    # ------------------------------------------------------------ Rebalance
    wr = wb.create_sheet("Rebalance")
    rcols = ["Section", "Mode", "Symbol", "Mom Rank", "Momentum Score",
             "Sector", "Qty Held", "Entry", "LTP", "P&L %", "Shares to Buy",
             "Amount (Rs)", "Note"]
    last = table(wr, rcols, rebal, ("Section", {"SELL": "FFC7CE",
                                                "BUY": "C6EFCE",
                                                "HOLD": "DDEBF7"}),
                 {"Note": 45, "Sector": 22, "Symbol": 13})
    note(wr, last + 2, "Sirf momentum. Mahine ke 1st trading day: SELL rows "
         "open pe becho, BUY rows khaali slot bharo. Rakho jab tak rank <= %d."
         % KEEP_RANK)

    # ------------------------------------------------------------ Watchlist
    ww = wb.create_sheet("Watchlist")
    last = table(ww, [h for h, _ in WCOLS], watch,
                 ("Recommendation", REC_FILL),
                 {"Mom Rank": 8, "Symbol": 13, "Verdict": 10, "Kyun": 45,
                  "Stage": 16, "NSE filings (30d)": 60, "News (7 days)": 60,
                  "Red flag": 8}, keys=[k for _, k in WCOLS])
    note(ww, last + 2, "Tumhare WATCH stocks, best momentum rank pehle. STRONG = "
         "40w MA ke upar + rank <= 40; WEAK = ek warning; AVOID = Stage 4 ya "
         "40w MA ke neeche + rank > 40. Hatana: rbtrack --unwatch SYMBOL")

    # ------------------------------------------------------------ table copy
    wt = wb.create_sheet("Holdings_Table")
    last = table(wt, HCOLS, own, ("Recommendation", REC_FILL), WIDTH)
    note(wt, last + 2, banner)

    dashboard(wb.create_sheet("Dashboard"), dash or {
        "title": banner, "prices": "", "master": "", "regime": "",
        "regime_red": False, "money": [], "todo": [], "watch": [],
        "warns": []}, set(wb.sheetnames))
    order = [n for n, _ in SHEET_INFO if n in wb.sheetnames]
    wb._sheets = [wb[n] for n in order] + \
        [x for x in wb._sheets if x.title not in order]
    for x in wb.worksheets:
        x.sheet_properties.tabColor = TAB.get(x.title, "A6A6A6")
        x.sheet_view.tabSelected = False
    wb.active = 0
    wb.worksheets[0].sheet_view.tabSelected = True
    try:
        wb.save(path)
        return path
    except PermissionError:
        alt = path.replace(".xlsx", "_%s.xlsx" % ds.now_ist().strftime("%H%M"))
        wb.save(alt)
        print("! %s is open in Excel -- saved as %s (your Action picks there "
              "are NOT read by rbtrack until you close + re-run)"
              % (os.path.basename(path), os.path.basename(alt)))
        return alt


def dashboard_data(acc, today, master, note, regime_red, hold, rebal, comp,
                   sw, warns, jrep=None):
    names = lambda xs: ", ".join(xs) if xs else "-"
    money = []
    for m, r in (jrep or {}).items():
        c = dict((k, v) for k, v, _ in r["cards"])
        v = c.get("Net profit (fees + tax ke baad)", 0)
        money.append(("Journal %s" % m, "net (fees + tax ke baad) %sRs %s | "
                      "jeete/band %s | khule %d" % (
                          "+" if v >= 0 else "-", format(int(abs(v)), ","),
                          c.get("Win rate", "-"), len(r["open"]))))
    for m in ("LIVE", "PAPER"):
        rows = [h for h in hold if h["Mode"] == m]
        if not rows:
            money.append(("%s holdings" % m, "none"))
            continue
        val = sum(h.get("Value (Rs)") or 0 for h in rows)
        cost = sum((h.get("Entry") or 0) * h["Qty"] for h in rows
                   if h.get("Value (Rs)"))
        money.append(("%s holdings" % m, "%d stock(s) | value ~Rs %s | cost "
                      "~Rs %s | P&L %s" % (
                          len(rows), format(int(val), ","),
                          format(int(cost), ","),
                          "%+.1f%%" % ((val / cost - 1) * 100) if cost
                          else "n/a")))
    own = [h for h in hold if h["Mode"] != "WATCH"]
    sell = [h["Symbol"] + " (%s %s)" % (h["Mode"], h["Recommendation"])
            for h in own if h["Recommendation"] in
            ("EXIT", "SELL", "SELL@REBAL")]
    near = [h["Symbol"] for h in own if h["Recommendation"] in ("WATCH",
                                                                "WEAK")]
    flags = [h["Symbol"] for h in hold if h.get("Red flag")]
    buys = []
    if "Action" in sw and "Symbol" in sw:
        buys = [str(s) for s, a in zip(sw["Symbol"], sw["Action"])
                if str(a).upper() == "BUY"]
    sup = []
    if len(comp) and "Strategy Overlap" in comp:
        sup = list(comp.loc[comp["Strategy Overlap"] == "Super-Buy", "Ticker"])
    todo = [("Sell (Sell sheet)", names(sell), bool(sell)),
            ("Near an exit / weak", names(near), False),
            ("NSE red flags", names(flags), bool(flags)),
            ("New W+TT BUY signals", names(buys), False),
            ("Super-Buy (W+TT + momentum)", names(sup), False)]
    for m in ("LIVE", "PAPER"):
        rr = [x for x in rebal if x["Mode"] == m]
        if rr:
            todo.append(("Momentum rebalance %s" % m,
                         "only on the 1st trading day: SELL %s | BUY %s" % (
                             names([x["Symbol"] for x in rr
                                    if x["Section"] == "SELL"]),
                             names([x["Symbol"] for x in rr
                                    if x["Section"] == "BUY"
                                    and "fills" in str(x.get("Note"))])),
                         False))
    wl = [h for h in hold if h["Mode"] == "WATCH"]
    watch = [(k, names([h["Symbol"] for h in wl
                        if h["Recommendation"] == k]))
             for k in ("STRONG", "WEAK", "AVOID")] if wl else \
        [("Watchlist", "empty -- pick WATCH in the Actions sheet")]
    return {"title": "RB_Screener | %s | %s" % (acc.label, today),
            "prices": note, "master": os.path.basename(master),
            "regime": "RED: Nifty below 200-DMA -- new buys did worse in the "
                      "backtest, paper first" if regime_red else
                      "OK: Nifty above 200-DMA",
            "regime_red": bool(regime_red), "money": money, "todo": todo,
            "watch": watch, "warns": list(warns)}


# ================================================================== main
def main():
    import account
    acc = account.activate()
    a = sys.argv[1:]
    sess = acc.session if acc.token_ok else None
    warns = []
    master = ms.todays_report()
    today = ds.now_ist().date().isoformat()
    if not master:
        print("! No master scan yet -- run rbscan first.")
        sys.exit(1)
    if today not in os.path.basename(master):
        warns.append("master scan is %s, not today -- run rbscan"
                     % os.path.basename(master))
    if not os.path.exists(pt.RANKS_FILE):
        print("! No momentum ranking -- run rbscan first.")
        sys.exit(1)
    rk = pd.read_csv(pt.RANKS_FILE)
    rk["symbol"] = rk["symbol"].astype(str).str.upper()
    ranks = dict(zip(rk["symbol"], rk["rank"].astype(int)))
    regime_red = bool(rk["regime_red"].iloc[0]) if "regime_red" in rk and \
        len(rk) else False

    # ---- holdings
    broker = []
    if sess:
        print("Fetching holdings from %s ..." % sess.label)
        broker = pt.get_holdings(sess)
    else:
        warns.append("token missing/expired -> demat holdings NOT read, only "
                     "the PAPER portfolio")
    # Action picks already made in today's file (kept on re-run); WATCH picks
    # need no order and no money, so they go straight onto the watchlist
    old_actions, prev_ltp, old_amount = {}, {}, {}
    moved = tidy_old_files()
    if moved:
        print("  %d old dated Portfolio file(s) moved to data/old_reports/"
              % moved)
    prev = path_for()
    try:                            # copy in Google Drive (Sheets edits)
        import drive_copy
    except ImportError:
        drive_copy = None
    if drive_copy:
        drive_copy.pull(prev)       # picks you made in Google Sheets
    import sip
    import settings
    sell_picks = {}
    if os.path.exists(prev):
        settings.read_dashboard(prev)       # switch: always kept
    same_day = os.path.exists(prev) and report_date(prev) == today
    if same_day:                    # Sell + Action picks: only today's
        try:
            so = pd.read_excel(prev, sheet_name="Sell", header=2, dtype=str)
            for _, x in so.fillna("").iterrows():
                if x.get("Symbol") and x.get("Product"):
                    sell_picks[(x["Symbol"].upper(), x["Product"].upper())] = \
                        str(x.get("Sell?", "")).upper().strip()
        except Exception:
            pass
    trading = settings.load()["trading"]
    if os.path.exists(prev):        # SIP sheet edits -> sip.csv
        for pr in sip.read_sheet(prev):
            warns.append("SIP: " + pr)
    if same_day:
        o = ms._read_sheet(prev, "Actions")
        if "Ticker" in o and "Action" in o:
            for _, r in o.iterrows():
                v = r["Action"]
                if isinstance(v, str) and v.strip():
                    t = str(r["Ticker"]).upper()
                    old_actions[t] = " ".join(v.upper().split())
                    prev_ltp[t] = (r.get("LTP"), r.get("Strategy Overlap", ""))
                amt = pd.to_numeric(str(r.get("Amount (Rs)", "")).replace(",", ""),
                                  errors="coerce")
                if amt == amt and amt > 0:
                    old_amount[str(r["Ticker"]).upper()] = float(amt)
    added = add_watch([(t,) + prev_ltp[t] for t, v in old_actions.items()
                       if v == "WATCH"])
    if added:
        print("  WATCH picks added to the watchlist: %s" % ", ".join(added))
    sp = read_split()
    import journal
    try:                            # buys, confirmed sells, dividends
        _, jmsg = journal.sync(sp, broker, {}, {}, sess, acc.broker)
        if any(" SOLD " in m for m in jmsg):
            sp = read_split()       # closed trades left split.csv
    except Exception as e:
        journal = None
        warns.append("journal not updated (%s: %s)" % (type(e).__name__, e))
    pos = positions(broker, sp)
    syms = sorted({p["symbol"] for p in pos})
    print("  %d demat holding(s), %d position row(s)" % (len(broker), len(pos)))

    # ---- prices
    closes, lows, highs, prov = {}, {}, {}, {}
    note = "no holdings"
    if syms:
        print("Loading prices ...")
        if sess:
            closes, lows, highs, prov, note = pt.load_prices(sess, syms, warns)
        else:
            for s in syms:
                df = ds.fetch_eod(s.lower())
                if df is not None:
                    closes[s], lows[s], highs[s] = df["Close"], df["Low"], df["High"]
            note = "free source only (no token)"

    # ---- master scan inputs
    sw = ms._read_sheet(master, "Swing")
    wtt = dict(zip(sw["Symbol"].astype(str).str.upper(), sw["Action"])) \
        if "Symbol" in sw and "Action" in sw else {}
    fund = fundamentals_for(syms, ms._read_sheet(master, "Fundamentals"),
                            "--no-fund" not in a)
    news, filings = {}, None
    if syms and "--no-news" not in a:
        import news_feed as nf
        print("News for %d stock(s) ..." % len(syms))
        news = {s: nf.latest(s, n=2) for s in syms}
        print("NSE filings (last 30 days) ...")
        filings = {s: nf.nse_announcements(s) for s in syms}
    else:
        filings = None

    hold = [analyse(p, closes, lows, highs, prov, ranks, wtt, fund, news,
                    filings) for p in pos]
    hold.sort(key=lambda x: ({"LIVE": 0, "PAPER": 1}.get(x["Mode"], 2),
                             LEG_ORDER.get(x["Recommendation"], 8),
                             -(x.get("Value (Rs)") or 0)))

    # ---- rebalance (momentum) + actions
    full = rk.rename(columns={})
    top = rk[rk.get("in_top", False) == True] if "in_top" in rk else \
        rk[rk["rank"] <= ms.SLOTS]                                  # noqa
    rebal = ms.rebalance_plan(top, full) if len(top) else []
    demat = {h["symbol"] for h in broker}
    for x in rebal:        # already owned, just not tagged Momentum in split.csv
        if x["Section"] == "BUY" and x["Mode"] == "LIVE" and x["Symbol"] in demat:
            x["Note"] = ("ALREADY IN DEMAT (not tagged Momentum) -- don't buy "
                         "again; set momentum_qty/strategy in split.csv")
    comp = ms._read_sheet(master, "Strategy_Comparison")
    if len(comp) and "Ticker" in comp:
        comp = comp[comp["Ticker"].notna() & comp["Strategy Overlap"].isin(
            ["Super-Buy", "Momentum only", "W+TT only"])]
    held_modes = {}
    for p in pos:
        held_modes.setdefault(p["symbol"], set()).add(p["mode"])
    # ---- terminal
    live_rows = [h for h in hold if h["Mode"] == "LIVE"]
    val = sum(h.get("Value (Rs)") or 0 for h in live_rows)
    cost = sum((h.get("Entry") or 0) * h["Qty"] for h in live_rows
               if h.get("Value (Rs)"))
    print("\n" + "=" * 78)
    print(" PORTFOLIO %s | master scan %s" % (acc.label,
                                              os.path.basename(master)))
    print(" prices: %s" % note)
    if val:
        print(" LIVE value ~Rs %s | cost ~Rs %s | P&L %+.1f%%"
              % (format(int(val), ","), format(int(cost), ","),
                 (val / cost - 1) * 100 if cost else 0))
    print("=" * 78)
    watch_rows = sorted([h for h in hold if h["Mode"] == "WATCH"],
                        key=lambda h: h.get("Mom Rank") if h.get("Mom Rank")
                        is not None else 10 ** 6)
    for h in [h for h in hold if h["Mode"] != "WATCH"]:
        print("\n %-10s %-5s %-12s qty %-6g P&L %s  %s | RSI %s | rank %s | "
              "W+TT %s" % (h["Recommendation"], h["Mode"], h["Symbol"],
                           h["Qty"], "%+.1f%%" % h["P&L %"]
                           if h.get("P&L %") is not None else "  n/a",
                           h.get("Stage", ""), h.get("RSI 14", "-"),
                           h.get("Mom Rank") if h.get("Mom Rank") is not None
                           else "-", h.get("W+TT today", "-")))
        print("    why: %s" % h["Why"])
        if h.get("Fund (swing)") or h.get("P/E"):
            f = lambda v: "n/a" if v is None or v != v else (
                "%.0f" % v if isinstance(v, float) else str(v))
            print("    fundamentals (info): P/E %s, ROCE %s%%, qtr profit YoY "
                  "%s%%, check swing %s / invest %s"
                  % (f(h.get("P/E")), f(h.get("ROCE %")),
                     f(h.get("Qtr Profit YoY %")), h.get("Fund (swing)"),
                     h.get("Fund (invest)")))
        if h.get("NSE filings (30d)"):
            print("    %sNSE filings: %s" % ("!! RED FLAG -- " if h.get("Red flag")
                                           else "", h["NSE filings (30d)"][:260]))
        if h.get("News (7 days)"):
            print("    news: %s" % h["News (7 days)"][:220])
    if not [h for h in hold if h["Mode"] != "WATCH"]:
        print("\n (no holdings -- demat empty and no PAPER rows)")
    if watch_rows:
        print("\n---- WATCHLIST (%d), best momentum rank first -- details in the "
              "Watchlist sheet ----" % len(watch_rows))
        print("  %-7s %-12s %5s  %-19s %4s  %-5s %7s  %s" % (
            "", "symbol", "rank", "stage", "RSI", "W+TT", "since", "flag"))
        for h in watch_rows:
            print("  %-7s %-12s %5s  %-19s %4s  %-5s %7s  %s" % (
                h["Recommendation"], h["Symbol"],
                h.get("Mom Rank") if h.get("Mom Rank") is not None else "-",
                h.get("Stage", "")[:19], "%.0f" % h["RSI 14"]
                if h.get("RSI 14") is not None else "-",
                h.get("W+TT today", "-"), "%+.1f%%" % h["P&L %"]
                if h.get("P&L %") is not None else "",
                "!! RED FLAG" if h.get("Red flag") else ""))
    for m in ("LIVE", "PAPER"):
        rr = [x for x in rebal if x["Mode"] == m]
        if rr:
            print("\n REBALANCE %s (1st trading day): SELL %s | BUY %s | HOLD %d"
                  % (m, ", ".join(x["Symbol"] for x in rr
                                  if x["Section"] == "SELL") or "-",
                     ", ".join(x["Symbol"] for x in rr if x["Section"] == "BUY"
                               and "fills" in x["Note"]) or "-",
                     sum(1 for x in rr if x["Section"] == "HOLD")))
    if regime_red:
        print("\n!!! MARKET RED (Nifty < 200-DMA): new buys did worse in the "
              "backtest. Paper first.")
    for w in warns:
        print("  ! " + w)
    jrep = None
    sells = sell_rows(hold, read_split(), broker, trading, sell_picks, today)
    sip_rows = sip.status(today)
    sdue = [r["Symbol"] for r in sip_rows if str(r["Next due"]).startswith(
        "aaj")]
    if journal:
        try:                        # exit signals ("rule followed?") + sheet
            last_px = {s_: float(c_.iloc[-1]) for s_, c_ in closes.items()
                       if c_ is not None and len(c_)}
            jr, _ = journal.sync(read_split(), broker, {
                (h["Mode"], h["Symbol"]): h.get("Recommendation")
                for h in hold}, last_px, sess, acc.broker, quiet=True)
            jrep = journal.report(jr, last_px)
        except Exception as e:
            warns.append("journal sheet skipped (%s: %s)"
                         % (type(e).__name__, e))
    dash = dashboard_data(acc, today, master, note, regime_red, hold, rebal,
                          comp, sw, warns, jrep)
    dash["trading"] = trading
    if sip_rows:
        dash["todo"].append(("SIP", "%d plan(s) active | aaj due: %s" % (
            sum(r["Active"] == "YES" for r in sip_rows),
            ", ".join(sdue) or "-"), False))
    path = write_book(path_for(), hold, rebal, comp, held_modes, old_actions,
                      "Portfolio %s | %s | master %s | prices: %s"
                      % (acc.label, today, os.path.basename(master), note),
                      old_amount, master, dash, jrep, sip_rows, sells,
                      trading, sip.symbol_choices(sess))
    if sells:
        print("\nSELL sheet (TRADING %s): %s" % (trading, ", ".join(
            "%s %s x%d = %s" % (x["Symbol"], x["Product"], x["Qty"],
                                x["Sell?"]) for x in sells)))
    print("\nExcel (the ONE file to open): %s" % path)
    print("  Dashboard | Holdings | Sell | Journal | Actions | SIP | Super-Buy | Rebalance | "
          "Watchlist | Holdings_Table | Swing | Investing | Momentum_Top20 | "
          "Fundamentals")
    if drive_copy:
        drive_copy.push(path)
    if watch_rows:              # for TradingView "Import list" (one click)
        wl = os.path.join(REPORTS, "Watchlist_%s.txt" % (TAG or "account"))
        with open(wl, "w") as f:
            f.write(",".join("NSE:" + h["Symbol"] for h in watch_rows) + "\n")
        print("Watchlist for TradingView import: %s" % wl)
        if drive_copy:
            drive_copy.push(wl, quiet=True)
    if old_actions:
        print("  kept your Action picks: %s" % ", ".join(
            "%s=%s" % kv for kv in old_actions.items()))
    print("Next: pick Actions in the Actions sheet -> save + close -> rbtrack "
          "(after 15:30)")
    account.banner(acc)


if __name__ == "__main__":
    main()
