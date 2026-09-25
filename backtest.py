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
                    sx, sp, why = t + 1, O[t + 1, j], "40w MA"
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
                    ix, ip = t + 1, O[t + 1, j]
                    break
            iopen = ix is None or not ip > 0
            if iopen:
                ix, ip = n - 1, C[n - 1, j]
            if not overlap:
                busy_until = sx      # one swing trade per stock at a time
            rows.append({
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
