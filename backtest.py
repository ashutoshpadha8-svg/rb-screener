#!/usr/bin/env python3
"""
BACKTEST  --  Weinstein + Minervini entry, swing and investing exits
====================================================================

Same entry rules as daily_screener.py (imported, not copied, where
possible) run over history, on the ">= Rs 10,000 Cr" universe.

UNIVERSES (--universe)
  pit10k    (default) point-in-time-ish: on each day, stocks whose
            ESTIMATED market cap that day was >= Rs 10,000 Cr.
            Estimate = today's NSE market cap x (adj. close that day /
            adj. close today). Wrong when share count changed (QIPs,
            mergers, buybacks) -- see --check-mcap for the error size.
  today10k  today's >= Rs 10,000 Cr list used for the WHOLE period.
            Look-ahead biased (picks today's winners) -- reference only.
  b173      the old 173-stock backtest list -- to compare with the
            earlier result (3633 trades, PF 3.99).

KNOWN BIAS (cannot be fixed with free data)
  Price history exists only for stocks listed TODAY. Delisted / bankrupt
  companies are missing, so every result here is somewhat too good.

TRADE RULES
  Entry  : Weinstein AND Trend Template on day t, buy at open t+1.
           One open trade per stock at a time.
  Swing  : fixed stop 20% below entry (hit if the day's LOW touches it;
           filled at the stop, or at the open if it gapped below),
           or a CLOSE below the 40-week (200-day) MA -> sell next open.
  Invest : 10 straight closes below a falling 30-week (150-day) MA
           -> sell next open.
  Cost   : 0.25% per side.
  Still-open trades are valued at the last close and flagged.

RUN
  python3 ~/Desktop/RB_Screener/backtest.py                 (pit10k)
  python3 ~/Desktop/RB_Screener/backtest.py --universe b173
  python3 ~/Desktop/RB_Screener/backtest.py --check-mcap
  python3 ~/Desktop/RB_Screener/backtest.py --portfolio   (slots, CAGR,
            drawdown vs Nifty; improvement ideas in- and out-of-sample)
  python3 ~/Desktop/RB_Screener/backtest.py --fundamentals   (does the
            fundamentals.py gate help? point-in-time, 2018 onwards;
            first run downloads Tickertape history, ~30-40 min)
  options: --start 2012-01-01  --rs-min 70  --min-load 1000
           --overlap  (count every signal day as a trade, even while the
                       stock is already held -- inflates trade count)
First run downloads ~1,500 price files (~500 MB) into data/.
Output: reports/backtest_<universe>_trades.csv + summary on screen.
"""

import warnings
warnings.filterwarnings("ignore")

import os
import io
import sys
import time
import zipfile
import datetime as dt
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daily_screener as ds     # universe file, price source, paths

# ------------------------------------------------------------------ config
START = "2012-01-01"     # first signal date
MCAP_MIN = 10000         # Rs crore
MIN_LOAD = 1000          # load stocks >= this today (catches fallen names)
COST = 0.0025            # per side
STOP = 0.20
RS_MIN = 70              # Trend Template RS floor (Weinstein uses > 50)
INV_BARS = 10            # investing exit: closes below falling 30w MA
THREADS = 8
CASH_RATE = 0.06         # idle cash in a liquid fund, per year (--cash 0 to drop)
PORT_START = "2013-01-01"  # first full year with signals (data starts 2012)


# ================================================================== data
def _download(sym):
    path = os.path.join(ds.DATA, sym + ".csv")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 20 * 3600:
        return sym, True
    for _ in range(3):
        try:
            r = requests.get(ds.EOD_BASE + requests.utils.quote(sym + ".csv"),
                             timeout=60)
            if r.status_code == 200:
                with open(path, "wb") as f:
                    f.write(r.content)
                return sym, True
            if r.status_code == 404:
                break
        except requests.RequestException:
            time.sleep(2)
    return sym, os.path.exists(path)


def _read(sym):
    path = os.path.join(ds.DATA, sym + ".csv")
    try:
        df = pd.read_csv(path, parse_dates=["Date"], index_col="Date",
                         usecols=["Date", "Open", "High", "Low", "Close",
                                  "Volume"])
    except Exception:
        return None
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.dropna(subset=["Close"])


def load_panels(symbols, first_day):
    print("Loading price files for %d stocks (downloads only if older "
          "than 20h) ..." % len(symbols))
    ok = []
    with ThreadPoolExecutor(THREADS) as ex:
        for i, (s, good) in enumerate(ex.map(_download, symbols), 1):
            if good:
                ok.append(s)
            if i % 50 == 0 or i == len(symbols):
                sys.stdout.write("\r  %4d/%d" % (i, len(symbols)))
                sys.stdout.flush()
    print()
    frames = {}
    for s in ok:
        df = _read(s)
        if df is not None and len(df) > 300:
            frames[s] = df[df.index >= first_day]
    bm = _read(ds.BENCH)
    if bm is None:
        _download(ds.BENCH)
        bm = _read(ds.BENCH)
    if bm is None:
        print("Could not load Nifty 50 history.")
        sys.exit(1)
    bm = bm[bm.index >= first_day]
    cal = bm.index
    P = {}
    for col in ("Open", "High", "Low", "Close", "Volume"):
        P[col] = pd.DataFrame({s: f[col] for s, f in frames.items()}) \
            .reindex(cal)
    P["BM"] = bm["Close"]
    print("  usable: %d of %d (missing/short: %d)"
          % (len(frames), len(symbols), len(symbols) - len(frames)))
    return P


# ================================================================== signals
def signals(P, universe, rs_min=RS_MIN):
    """Exactly the daily_screener.py rules, with RS ranked among the
    universe members of that day."""
    CL = P["Close"].ffill(limit=5)
    VO = P["Volume"]
    BM = P["BM"].ffill(limit=5)
    liq = (CL * VO).rolling(60).median() > 5e7
    ma50 = CL.rolling(50).mean()
    ma150 = CL.rolling(150).mean()
    ma200 = CL.rolling(200).mean()
    hi52 = CL.rolling(252).max()
    lo52 = CL.rolling(252).min()
    rs6 = (CL / CL.shift(126)).div(BM / BM.shift(126), axis=0)
    rs = rs6.where(universe).rank(axis=1, pct=True) * 100

    wein = ((CL > ma150) & (ma150 > ma150.shift(10)) & (rs > 50) &
            (CL >= CL.rolling(30).max()) &
            (VO > 2 * VO.rolling(50).mean()) & liq)
    tt = ((CL > ma50) & (ma50 > ma150) & (ma150 > ma200) &
          (ma200 > ma200.shift(22)) & (CL > 1.3 * lo52) &
          (CL > 0.75 * hi52) & (rs >= rs_min))
    sig = (wein & tt & universe).fillna(False).astype(bool)
    return sig, rs, ma150, ma200


# ================================================================== trades
def _next_open(O, t, j, n):
    """First bar >= t with a real open price (skips untraded days)."""
    while t < n and not O[t, j] > 0:
        t += 1
    return (t, O[t, j]) if t < n else (None, None)


def simulate(P, sig, rs, ma150, ma200, start, overlap=False):
    O, H, L, C = (P[k].values for k in ("Open", "High", "Low", "Close"))
    m150, m200, rsv = ma150.values, ma200.values, rs.values
    cal = P["Close"].index
    first = cal.searchsorted(pd.Timestamp(start))
    n = len(cal)
    rows = []
    for j, sym in enumerate(P["Close"].columns):
        hits = np.flatnonzero(sig.values[:, j])
        hits = hits[hits >= first]
        busy_until = -1
        for k in hits:
            if k <= busy_until or k + 1 >= n:
                continue
            e = O[k + 1, j]
            if not e > 0:
                continue
            stop = e * (1 - STOP)
            # ---- swing leg
            sx, sp, why = None, None, "open"
            for t in range(k + 1, n):
                if L[t, j] <= stop:
                    sx, sp, why = t, min(O[t, j], stop) if O[t, j] > 0 \
                        else stop, "stop"
                    break
                if C[t, j] < m200[t, j] and t + 1 < n:
                    sx, sp = _next_open(O, t + 1, j, n)
                    why = "40w MA"
                    break
            if sx is None or not sp > 0:
                sx, sp = n - 1, C[n - 1, j]
                why = "open"
            # ---- investing leg (same entry)
            ix, ip, below = None, None, 0
            for t in range(k + 1, n):
                c, m = C[t, j], m150[t, j]
                falling = t >= 10 and m < m150[t - 10, j]
                below = below + 1 if c < m else 0
                if below >= INV_BARS and falling and t + 1 < n:
                    ix, ip = _next_open(O, t + 1, j, n)
                    break
            iopen = ix is None or not ip > 0
            if iopen:
                ix, ip = n - 1, C[n - 1, j]
            if not overlap:
                busy_until = sx      # one swing trade per stock at a time
            rows.append({
                "col": j, "k_sig": k, "k_in": k + 1, "k_out": sx,
                "k_iout": ix,
                "symbol": sym.upper(), "signal": cal[k].date(),
                "rs": round(float(rsv[k, j]), 1),
                "entry_date": cal[k + 1].date(), "entry": round(e, 2),
                "exit_date": cal[sx].date(), "exit": round(sp, 2),
                "exit_why": why, "bars": sx - (k + 1),
                "ret": (sp * (1 - COST)) / (e * (1 + COST)) - 1,
                "inv_exit_date": cal[ix].date(), "inv_exit": round(ip, 2),
                "inv_open": iopen, "inv_bars": ix - (k + 1),
                "inv_ret": (ip * (1 - COST)) / (e * (1 + COST)) - 1,
            })
    return pd.DataFrame(rows)


# ================================================================== report
def stats(r):
    r = r.dropna()
    if not len(r):
        return {}
    w, l = r[r > 0], r[r <= 0]
    pf = w.sum() / -l.sum() if len(l) and l.sum() < 0 else np.inf
    return {"trades": len(r), "win%": 100 * len(w) / len(r),
            "avg%": 100 * r.mean(), "median%": 100 * r.median(),
            "PF": pf, "avg_win%": 100 * w.mean() if len(w) else 0,
            "avg_loss%": 100 * l.mean() if len(l) else 0,
            "2x+ %": 100 * (r >= 1).mean()}


def report(t, label):
    print("\n" + "=" * 72)
    print(" %s" % label)
    print("=" * 72)
    if t.empty:
        print("  no trades")
        return
    closed = t[t.exit_why != "open"]
    rows = {"SWING  (all)": stats(t.ret),
            "SWING  (closed only)": stats(closed.ret),
            "INVEST (all)": stats(t.inv_ret),
            "INVEST (closed only)": stats(t[~t.inv_open].inv_ret)}
    d = pd.DataFrame(rows).T
    print(d.to_string(float_format=lambda x: "%.2f" % x))
    print("\n  swing exits: " + ", ".join(
        "%s %d" % (k, v) for k, v in t.exit_why.value_counts().items()))
    print("  median hold: swing %d bars, investing %d bars"
          % (t.bars.median(), t.inv_bars.median()))
    t = t.copy()
    t["year"] = pd.to_datetime(t.entry_date).dt.year
    y = t.groupby("year").agg(trades=("ret", "size"),
                              win=("ret", lambda x: 100 * (x > 0).mean()),
                              avg=("ret", lambda x: 100 * x.mean()),
                              inv_avg=("inv_ret", lambda x: 100 * x.mean()))
    print("\n  by entry year (swing avg %, investing avg %):")
    print(y.to_string(float_format=lambda x: "%.1f" % x))


# ================================================================== portfolio
def run_portfolio(P, cand, slots=20, exit_kind="swing", start_k=0, end_k=None,
                  cash_rate=CASH_RATE, expo=None):
    """Daily portfolio: equal slots (equity / slots at entry, capped by
    cash), new signals ranked by RS, one position per stock. Cash earns 0.
    cand = trades from simulate(..., overlap=True): every signal day with
    its own swing and investing exit. Returns the daily equity Series."""
    C = P["Close"].ffill().values
    cal = P["Close"].index
    n = len(cal) if end_k is None else end_k
    ko = "k_out" if exit_kind == "swing" else "k_iout"
    po = "exit" if exit_kind == "swing" else "inv_exit"
    c = cand[(cand.k_in >= start_k) & (cand.k_in < n)]
    by_day = {k: g.sort_values("rs", ascending=False)
              for k, g in c.groupby("k_in")}
    cash, pos = 1.0, {}          # col -> [shares, k_out, exit_px]
    eq = np.full(n, np.nan)
    inv = np.full(n, np.nan)
    day_rate = (1 + cash_rate) ** (1 / 252) - 1
    for t in range(start_k, n):
        cash *= 1 + day_rate
        # exits first (scheduled at this bar's open / stop)
        for col in [cc for cc, p_ in pos.items() if p_[1] <= t]:
            sh, _, px = pos.pop(col)
            if px is None:               # cut off by the window end
                px = C[t, col]
            cash += sh * px * (1 - COST)
        # entries at today's open
        if t in by_day and len(pos) < slots:
            mark = cash + sum(p_[0] * C[t - 1, cc] for cc, p_ in pos.items()
                              if C[t - 1, cc] == C[t - 1, cc])
            for r in by_day[t].itertuples():
                if len(pos) >= slots:
                    break
                if r.col in pos:
                    continue
                exit_k = getattr(r, ko)
                if exit_k >= n:          # would exit after the window end
                    exit_k = n - 1
                amt = min(mark / slots, cash)
                if amt <= 0:
                    break
                sh = amt / (r.entry * (1 + COST))
                cash -= amt
                px = getattr(r, po) if exit_k == getattr(r, ko) else None
                pos[r.col] = [sh, exit_k, px]
        eq[t] = cash + sum(p_[0] * C[t, cc] for cc, p_ in pos.items()
                           if C[t, cc] == C[t, cc])
        inv[t] = 1 - cash / eq[t]
    if expo is not None:
        expo.append(np.nanmean(inv[start_k:n]))
    return pd.Series(eq[start_k:n], index=cal[start_k:n])


def perf(e):
    e = e.dropna()
    if len(e) < 2:
        return {}
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    cagr = (e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1
    dd = (e / e.cummax() - 1).min()
    r = e.pct_change().dropna()
    return {"CAGR%": 100 * cagr, "maxDD%": 100 * dd,
            "vol%": 100 * r.std() * np.sqrt(252),
            "CAGR/DD": cagr / -dd if dd < 0 else np.nan}


def portfolio_study(P, sig_fn, universe, start, split="2020-01-01",
                    cash_rate=CASH_RATE):
    """Pre-registered variants, judged in-sample AND out-of-sample."""
    cal = P["Close"].index
    k0 = cal.searchsorted(max(pd.Timestamp(start), pd.Timestamp(PORT_START)))
    ks = cal.searchsorted(pd.Timestamp(split))
    bm = P["BM"].ffill()
    regime = (bm > bm.rolling(200).mean()).values      # Nifty > 200DMA
    cands = {}
    for rsm in (70, 85):
        sig, rs, m150, m200 = sig_fn(P, universe, rsm)
        cands[rsm] = simulate(P, sig, rs, m150, m200, start, overlap=True)
    variants = [
        ("BASE  20 slots, swing exit", 70, False, 20, "swing"),
        ("+ Nifty > 200DMA filter", 70, True, 20, "swing"),
        ("RS >= 85", 85, False, 20, "swing"),
        ("RS >= 85 + Nifty filter", 85, True, 20, "swing"),
        ("10 slots", 70, False, 10, "swing"),
        ("investing (Stage 4) exit", 70, False, 20, "invest"),
        ("investing exit + Nifty filter", 70, True, 20, "invest"),
    ]
    out, curves = [], {}
    for name, rsm, reg, sl, ex in variants:
        c = cands[rsm]
        if reg:
            c = c[regime[c.k_sig.values]]
        row = {"variant": name}
        for tag, a_, b_ in (("IS 13-19", k0, ks), ("OOS 20-26", ks, None),
                            ("FULL", k0, None)):
            ex_ = [] if tag == "FULL" else None
            e = run_portfolio(P, c, sl, ex, a_, b_, cash_rate, ex_)
            p_ = perf(e)
            if ex_:
                row["invested%"] = 100 * ex_[0]
            row[tag + " CAGR"] = p_.get("CAGR%")
            row[tag + " DD"] = p_.get("maxDD%")
            if tag == "FULL":
                curves[name] = e
                row["trades"] = int(((c.k_in >= k0)).sum())
        out.append(row)
    for tag, a_, b_ in (("IS 13-19", k0, ks), ("OOS 20-26", ks, None),
                        ("FULL", k0, None)):
        e = bm.iloc[a_:b_]
        p_ = perf(e / e.iloc[0])
        out_row = next((o for o in out if o["variant"] == "NIFTY 50 buy & hold"),
                       None)
        if out_row is None:
            out_row = {"variant": "NIFTY 50 buy & hold"}
            out.append(out_row)
        out_row[tag + " CAGR"] = p_["CAGR%"]
        out_row[tag + " DD"] = p_["maxDD%"]
    curves["NIFTY 50 buy & hold"] = bm.iloc[k0:] / bm.iloc[k0]
    d = pd.DataFrame(out).set_index("variant").drop(columns="trades",
                                                    errors="ignore")
    print("\nPORTFOLIO from %s | idle cash earns %.1f%%/yr | Nifty = price "
          "index, no dividends (~1.3%%/yr)" % (cal[k0].date(), cash_rate * 100))
    print(d.to_string(float_format=lambda x: "%.1f" % x))
    yearly = pd.DataFrame({k: v.resample("YE").last().pct_change() * 100
                           for k, v in curves.items()})
    yearly.iloc[0] = [v.resample("YE").last().iloc[0] / v.iloc[0] * 100 - 100
                      for v in curves.values()]
    yearly.index = yearly.index.year
    print("\nCalendar-year returns %:")
    print(yearly.T.to_string(float_format=lambda x: "%.0f" % x))
    return d, curves


# ================================================================== fundamentals
FUND_START = "2018-01-01"   # Tickertape quarters start ~Sep 2016 -> YoY usable ~Nov 2017
FUND_SPLIT = "2022-01-01"


def fund_verdicts(t, cal_close, cache_dir):
    """Add point-in-time swing / investing fundamental verdicts to each
    trade row, using the SAME rules as fundamentals.py."""
    import fundamentals as fu
    import fund_history as fh
    syms = sorted(t.symbol.unique())
    print("Fundamental history for %d symbols (Tickertape, cached 30 days; "
          "first run ~%d min) ..." % (len(syms), len(syms) * 5 * 0.9 // 60 + 1))
    data, miss = {}, []
    for i, s in enumerate(syms, 1):
        sys.stdout.write("\r  %4d/%d  %-12s" % (i, len(syms), s))
        sys.stdout.flush()
        d = fh.fetch(s, cache_dir)
        if d is None or not d.get("q"):
            miss.append(s)
            continue
        q, ann = fh.tables(d)
        data[s] = (q, ann, d.get("sector") == "Financials")
    print("\n  with data: %d | not found on Tickertape: %d%s"
          % (len(data), len(miss), (" (" + ", ".join(miss[:12]) +
                                    (" ..." if len(miss) > 12 else "") + ")")
             if miss else ""))
    keys = ("q_profit_yoy", "q_sales_yoy", "roe3", "de", "decel2", "icr",
            "cfo_pat", "loss_years", "profit_cagr3", "sales_cagr3",
            "q_last2_pos", "eps_yoy_abs")
    out = []
    for r in t.itertuples():
        row = {"sw_verdict": "NODATA", "in_verdict": "NODATA"}
        if r.symbol in data:
            q, ann, fin = data[r.symbol]
            m = {k: None for k in keys}
            m.update(fh.asof(q, ann, r.signal, fin))
            m.update({"pledge": None, "oi_share": None, "roce3": None,
                      "nnpa": None, "gnpa": None, "roa": None,
                      "fin": "fin_other" if fin else ""})
            so, io = fu.swing_rules(m), fu.invest_rules(m)
            # backtest: rules with no data are ignored (not CHECK)
            row["sw_verdict"] = "FAIL" if so["fail"] else "PASS"
            row["in_verdict"] = "FAIL" if io["fail"] else "PASS"
            row["sw_fail"] = "; ".join(so["fail"])
            row["in_fail"] = "; ".join(io["fail"])
            row["sw_checked"] = 4 - sum(
                m[k] is None for k in ("q_profit_yoy", "q_sales_yoy", "roe3")) \
                - (0 if fin else (m["de"] is None))
            for k in ("q_profit_yoy", "q_sales_yoy", "roe3", "de"):
                row["f_" + k] = m[k]
        out.append(row)
    return pd.concat([t.reset_index(drop=True), pd.DataFrame(out)], axis=1)


def _grp(t, col, ret="ret"):
    rows = {}
    for v, g in t.groupby(col):
        rows[v] = stats(g[ret])
    return pd.DataFrame(rows).T


def fundamentals_study(P, universe, start):
    cal = P["Close"].index
    sig, rs, m150, m200 = signals(P, universe, RS_MIN)
    fs = max(pd.Timestamp(start), pd.Timestamp(FUND_START))
    cand = simulate(P, sig, rs, m150, m200, fs, overlap=True)
    one = simulate(P, sig, rs, m150, m200, fs, overlap=False)
    cache = os.path.join(ds.DATA, "tickertape")
    cand = fund_verdicts(cand, cal, cache)
    key = ["col", "k_sig"]
    one = one.merge(cand[key + [c for c in cand.columns
                                if c.startswith(("sw_", "in_", "f_"))]],
                    on=key, how="left")
    path = os.path.join(ds.REPORTS, "backtest_fund_trades.csv")
    one.to_csv(path, index=False)
    fmt = lambda x: "%.2f" % x
    for label, a_, b_ in (("ALL %s .." % fs.year, None, None),
                          ("FIRST HALF %s-%d" % (fs.year,
                                                 int(FUND_SPLIT[:4]) - 1),
                           None, FUND_SPLIT),
                          ("SECOND HALF %s-" % FUND_SPLIT[:4], FUND_SPLIT,
                           None)):
        d = one.copy()
        sd = pd.to_datetime(d.signal)
        if a_:
            d = d[sd >= a_]
        if b_:
            d = d[sd < b_]
        print("\n" + "=" * 72)
        print(" TRADES (one per stock at a time) -- %s" % label)
        print("=" * 72)
        print(" Swing leg by SWING fundamental verdict:")
        print(_grp(d, "sw_verdict").to_string(float_format=fmt))
        print(" Investing leg by INVESTING fundamental verdict:")
        print(_grp(d, "in_verdict", "inv_ret").to_string(float_format=fmt))
    d = one[one.sw_verdict != "NODATA"].copy()
    print("\n Swing leg, one rule at a time (ALL years):")
    rules = {"qtr profit YoY >= %g" % 20: d.f_q_profit_yoy >= 20,
             "qtr sales YoY >= %g" % 15: d.f_q_sales_yoy >= 15,
             "3y ROE >= %g" % 10: d.f_roe3 >= 10,
             "D/E <= %g" % 1.5: d.f_de <= 1.5}
    rows = []
    for name, ok in rules.items():
        col = d[{"qtr profit YoY >= 20": "f_q_profit_yoy",
                 "qtr sales YoY >= 15": "f_q_sales_yoy",
                 "3y ROE >= 10": "f_roe3", "D/E <= 1.5": "f_de"}[name]]
        for tag, mask in (("pass", ok & col.notna()),
                          ("fail", ~ok & col.notna())):
            st = stats(d[mask].ret)
            st["rule"] = "%s: %s" % (name, tag)
            rows.append(st)
    print(pd.DataFrame(rows).set_index("rule").to_string(float_format=fmt))

    # ---------------------------------------------------------- portfolio
    k0 = cal.searchsorted(fs)
    ks = cal.searchsorted(pd.Timestamp(FUND_SPLIT))
    # compare ONLY stocks that have fundamental data; NODATA (mostly
    # renamed / newer symbols Tickertape does not know) is shown apart --
    # it holds big 2020-24 winners and would fake a "gate" benefit.
    cd = cand[cand.sw_verdict != "NODATA"]
    variants = [
        ("swing exit, all with data", cd, "swing"),
        ("swing exit, swing PASS only", cd[cd.sw_verdict == "PASS"], "swing"),
        ("investing exit, all with data", cd, "invest"),
        ("investing exit, inv PASS only", cd[cd.in_verdict == "PASS"],
         "invest"),
        ("investing exit, swing PASS only", cd[cd.sw_verdict == "PASS"],
         "invest"),
        ("(artifact check) NODATA only, inv exit",
         cand[cand.sw_verdict == "NODATA"], "invest"),
    ]
    out = []
    for name, c, ex in variants:
        row = {"variant": name}
        for tag, a_, b_ in (("H1", k0, ks), ("H2", ks, None),
                            ("ALL", k0, None)):
            p_ = perf(run_portfolio(P, c, 20, ex, a_, b_))
            row[tag + " CAGR"] = p_.get("CAGR%")
            row[tag + " DD"] = p_.get("maxDD%")
        out.append(row)
    bm = P["BM"].ffill()
    row = {"variant": "NIFTY 50 buy & hold"}
    for tag, a_, b_ in (("H1", k0, ks), ("H2", ks, None), ("ALL", k0, None)):
        e = bm.iloc[a_:b_]
        p_ = perf(e / e.iloc[0])
        row[tag + " CAGR"], row[tag + " DD"] = p_["CAGR%"], p_["maxDD%"]
    out.append(row)
    print("\nPORTFOLIO 20 slots from %s (H1 = to %s, H2 = after), idle cash "
          "%.0f%%" % (cal[k0].date(), FUND_SPLIT, CASH_RATE * 100))
    print(pd.DataFrame(out).set_index("variant")
          .to_string(float_format=lambda x: "%.1f" % x))
    print("\nTrades with verdicts saved: %s" % path)


# ================================================================== mcap check
def check_mcap(P, mcap_now):
    """Compare the estimated past market cap with NSE's real MCAP files
    (NSE publishes them inside the PR zip only from ~mid-2024)."""
    last = P["Close"].ffill().iloc[-1]
    est_scale = mcap_now.reindex(P["Close"].columns) / last
    out = []
    today = ds.now_ist().date()
    for months_back in range(1, 28, 3):
        d0 = (pd.Timestamp(today) - pd.DateOffset(months=months_back)).date()
        got = None
        for add in range(0, 8):
            d = d0 + dt.timedelta(days=add)
            if d.weekday() >= 5:
                continue
            try:
                r = requests.get(ds.NSE_PR % d.strftime("%d%m%y"),
                                 headers=ds.NSE_HDRS, timeout=30)
            except requests.RequestException:
                continue
            if r.status_code != 200 or r.content[:2] != b"PK":
                continue
            zf = zipfile.ZipFile(io.BytesIO(r.content))
            name = next((x for x in zf.namelist() if "mcap" in x.lower()), None)
            if name:
                got = (d, ds.parse_mcap(pd.read_csv(zf.open(name))))
                break
        if not got:
            continue
        d, real = got
        real = real.set_index(real.symbol.str.lower())["mcap_cr"]
        ts = P["Close"].index[P["Close"].index <= pd.Timestamp(d)][-1]
        est = (P["Close"].loc[ts] * est_scale).dropna()
        both = est.index.intersection(real.index)
        e, a = est[both], real[both]
        err = (e / a - 1).abs()
        in_real, in_est = a >= MCAP_MIN, e >= MCAP_MIN
        out.append({"date": d, "stocks": len(both),
                    "median_err%": 100 * err.median(),
                    "err>20%": 100 * (err > 0.2).mean(),
                    "real>=10k": int(in_real.sum()),
                    "est>=10k": int(in_est.sum()),
                    "both": int((in_real & in_est).sum()),
                    "missed": int((in_real & ~in_est).sum()),
                    "extra": int((~in_real & in_est).sum())})
    print("\nEstimated vs real NSE market cap (only where NSE files exist):")
    print(pd.DataFrame(out).to_string(index=False,
                                      float_format=lambda x: "%.1f" % x)
          if out else "  no NSE MCAP files found")


# ================================================================== main
def main():
    a = sys.argv[1:]

    def opt(name, default):
        return a[a.index(name) + 1] if name in a else default

    uni = opt("--universe", "pit10k")
    start = opt("--start", START)
    rs_min = float(opt("--rs-min", RS_MIN))
    min_load = float(opt("--min-load", MIN_LOAD))
    # rules need 252 bars + 126-bar RS + 22-bar slope -> ~2 years warm-up
    first_day = (pd.Timestamp(start) - pd.DateOffset(days=800)).strftime(
        "%Y-%m-%d")

    if uni == "b173":
        syms, mcap_now = list(ds.FALLBACK), None
    else:
        m, asof, src = ds.fetch_mcap()
        if m is None:
            print("Could not get NSE market-cap file.")
            sys.exit(1)
        print("NSE market cap %s (%s)" % (asof, src))
        m = m.set_index(m.symbol.str.lower())["mcap_cr"]
        mcap_now = m
        lo = MCAP_MIN if uni == "today10k" else min_load
        syms = list(m[m >= lo].index)

    P = load_panels(syms, first_day)
    cols = P["Close"].columns

    if "--check-mcap" in a:
        check_mcap(P, mcap_now)
        return

    if uni == "pit10k":
        last = P["Close"].ffill().iloc[-1]
        scale = mcap_now.reindex(cols) / last
        est = P["Close"].ffill(limit=5) * scale
        universe = est >= MCAP_MIN
        size = universe.sum(axis=1)
        yr = size.groupby(size.index.year).mean().round(0)
        print("  avg universe size by year: " + ", ".join(
            "%d:%d" % (k, v) for k, v in yr.items() if k >= int(start[:4])))
    else:
        universe = pd.DataFrame(True, index=P["Close"].index, columns=cols)
        universe = universe & P["Close"].notna()

    if "--fundamentals" in a:
        fundamentals_study(P, universe, start)
        return

    if "--portfolio" in a:
        print("Portfolio study (7 variants x 3 periods, takes a few minutes)")
        d, curves = portfolio_study(P, signals, universe, start,
                                    cash_rate=float(opt("--cash", CASH_RATE)))
        path = os.path.join(ds.REPORTS, "backtest_%s_portfolio.csv" % uni)
        pd.DataFrame(curves).to_csv(path)
        print("\nEquity curves saved: %s" % path)
        return

    print("Computing signals ...")
    sig, rs, ma150, ma200 = signals(P, universe, rs_min)
    print("Simulating trades ...")
    overlap = "--overlap" in a     # every signal = a trade (old style?)
    t = simulate(P, sig, rs, ma150, ma200, start, overlap)
    path = os.path.join(ds.REPORTS, "backtest_%s%s_trades.csv"
                        % (uni, "_overlap" if overlap else ""))
    t.to_csv(path, index=False)
    report(t, "Universe %s | %s to %s | RS >= %g | cost %.2f%%/side"
           % (uni, start, P["Close"].index[-1].date(), rs_min, COST * 100))
    print("\nTrades saved: %s" % path)
    print("Reminder: stocks delisted before today are missing -> results "
          "are somewhat too good.")


if __name__ == "__main__":
    main()
