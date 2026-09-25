#!/usr/bin/env python3
"""
FUNDAMENTAL HISTORY FOR BACKTESTS  (used by backtest.py --fundamentals)
======================================================================

Source: Tickertape's public web API (the one their website uses).
  ~40 quarters (from ~Sep 2016) and ~10 fiscal years per company:
  quarterly P&L, annual P&L, balance sheet, cash flow.
  Unofficial -- it can change or block without notice. Fetched slowly,
  cached in data/tickertape/ for 30 days.

POINT-IN-TIME RULE (no look-ahead)
  Tickertape has no result announcement dates, so each period is only
  used from SEBI's LAST allowed date (LODR Reg 33) + 2 days buffer:
    quarter ending Jun / Sep / Dec : quarter end + 45 days
    quarter / year ending Mar      : + 60 days
  Real results usually come earlier, so this is conservative.

KNOWN LIMITS
  * Numbers may be restated (latest version), not exactly what was
    known at the time.
  * Revenue = total revenue (Tickertape does not split out other
    income), profit = profit before tax. The live fundamentals.py uses
    PBT minus other income -- close, not identical.
  * Pledge %, auditor, SEBI action: no history -> not tested.
"""

import os
import json
import time
import datetime as dt

import numpy as np
import pandas as pd
import requests

TT = "https://api.tickertape.in"
HDRS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0 Safari/537.36",
        "Accept": "application/json"}
PAUSE = 0.5
CACHE_DAYS = 30
BUFFER_DAYS = 2


def _get(path):
    for attempt in range(4):
        try:
            r = requests.get(TT + path, headers=HDRS, timeout=30)
        except requests.RequestException:
            time.sleep(3)
            continue
        finally:
            time.sleep(PAUSE)
        if r.status_code == 429:
            time.sleep(30 * (attempt + 1))
            continue
        if r.status_code != 200:
            return None
        try:
            return r.json()
        except ValueError:
            return None
    return None


def _sid(sym):
    j = _get("/search?text=%s&types=stock" % requests.utils.quote(sym))
    for s in ((j or {}).get("data") or {}).get("stocks") or []:
        if str(s.get("ticker", "")).upper() == sym.upper():
            return s.get("sid"), s.get("sector") or ""
    return None, ""


def fetch(sym, cache_dir):
    """Raw Tickertape data for one NSE symbol, cached. None if unknown."""
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, sym.upper().replace("&", "_") + ".json")
    if os.path.exists(path) and \
            time.time() - os.path.getmtime(path) < CACHE_DAYS * 86400:
        with open(path) as f:
            d = json.load(f)
        return d if d.get("sid") else None
    sid, sector = _sid(sym)
    d = {"symbol": sym.upper(), "sid": sid, "sector": sector}
    if sid:
        for key, p in (("q", "income/%s/interim/normal?count=40"),
                       ("a", "income/%s/annual/normal?count=20"),
                       ("bs", "balancesheet/%s/annual/normal?count=20"),
                       ("cf", "cashflow/%s/annual/normal?count=20")):
            j = _get("/stocks/financials/" + p % sid)
            d[key] = (j or {}).get("data") or []
    tmp = path + ".tmp%d" % os.getpid()
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, path)            # atomic: readers never see half a file
    return d if sid else None


# ================================================================== tables
def _avail(end):
    days = 60 if end.month == 3 else 45
    return end + pd.Timedelta(days=days + BUFFER_DAYS)


def tables(d):
    """-> (quarterly DataFrame, annual DataFrame), indexed by period end,
    with an 'avail' column = first date the numbers may be used."""
    q = pd.DataFrame(d.get("q") or [])
    if not q.empty and "endDate" in q:
        q = q[q.endDate.astype(str).str.len() > 0].copy()
        q["end"] = pd.to_datetime(q.endDate).dt.tz_localize(None).dt.normalize()
        q = q.rename(columns={"qIncTrev": "rev", "qIncPbt": "pbt",
                              "qIncNinc": "np", "qIncEps": "eps"})
        q = q.set_index("end").sort_index()
        q = q[~q.index.duplicated(keep="last")]
        q["avail"] = [_avail(e) for e in q.index]
    a = pd.DataFrame(d.get("a") or [])
    bs = pd.DataFrame(d.get("bs") or [])
    cf = pd.DataFrame(d.get("cf") or [])
    frames = []
    for df, ren in ((a, {"incTrev": "rev", "incPbt": "pbt", "incNinc": "np",
                         "incPbi": "pbit", "incIoi": "interest"}),
                    (bs, {"balTeq": "equity", "balTdeb": "debt",
                          "balTota": "assets"}),
                    (cf, {"cafCfoa": "cfo"})):
        if df.empty or "endDate" not in df:
            continue
        df = df[df.endDate.astype(str).str.len() > 0].copy()   # drops TTM
        df["end"] = pd.to_datetime(df.endDate).dt.tz_localize(None) \
            .dt.normalize()
        df = df.rename(columns=ren).set_index("end")
        df = df[~df.index.duplicated(keep="last")]
        frames.append(df[[c for c in ren.values() if c in df]])
    ann = pd.concat(frames, axis=1).sort_index() if frames else pd.DataFrame()
    if not ann.empty:
        ann["avail"] = [_avail(e) for e in ann.index]
    return q, ann


# ================================================================== as-of
def _yoy(s, i):
    """YoY % of row i vs the row one year earlier (same month)."""
    end = s.index[i]
    prev = end - pd.DateOffset(years=1)
    m = s.index[(s.index.year == prev.year) & (s.index.month == prev.month)]
    if not len(m):
        return None
    a, b = s.iloc[i], s[m[0]]
    if not (b > 0) or a != a:
        return None
    return (a / b - 1) * 100


def asof(q, ann, date, financial=False):
    """Everything fundamentals.py checks, using only numbers public by
    `date`. Missing -> None."""
    m = {}
    date = pd.Timestamp(date)
    qq = q[q.avail <= date] if not q.empty else q
    if len(qq) >= 5:
        n = len(qq)
        m["q_profit_yoy"] = _yoy(qq["pbt"], n - 1)
        m["q_sales_yoy"] = _yoy(qq["rev"], n - 1)
        ser = [_yoy(qq["pbt"], i) for i in range(max(n - 3, 4), n)]
        ser_s = [_yoy(qq["rev"], i) for i in range(max(n - 2, 4), n)]
        m["decel2"] = len(ser) == 3 and None not in ser and \
            ser[2] < ser[1] < ser[0]
        m["q_last2_pos"] = (min(ser[-2:]) > 0 and min(ser_s) > 0) \
            if len(ser) >= 2 and None not in ser[-2:] and \
            len(ser_s) == 2 and None not in ser_s else None
        e = qq["eps"]
        m["eps_yoy_abs"] = None
        prev = qq.index[-1] - pd.DateOffset(years=1)
        k = qq.index[(qq.index.year == prev.year) &
                     (qq.index.month == prev.month)]
        if len(k) and e.iloc[-1] == e.iloc[-1] and e[k[0]] == e[k[0]]:
            m["eps_yoy_abs"] = e.iloc[-1] - e[k[0]]
    aa = ann[ann.avail <= date] if not ann.empty else ann
    if len(aa):
        eq = aa.get("equity")
        npa = aa.get("np")
        if eq is not None and npa is not None:
            roes = []
            for i in range(max(1, len(aa) - 3), len(aa)):
                base = (eq.iloc[i] + eq.iloc[i - 1]) / 2
                if base > 0 and npa.iloc[i] == npa.iloc[i]:
                    roes.append(npa.iloc[i] / base * 100)
            m["roe3"] = float(np.mean(roes)) if len(roes) == 3 else None
            if eq.iloc[-1] > 0 and "debt" in aa and not financial:
                dbt = aa["debt"].iloc[-1]
                m["de"] = (dbt if dbt == dbt else 0) / eq.iloc[-1]
        if "pbit" in aa and "interest" in aa and not financial:
            it, pb = aa["interest"].iloc[-1], aa["pbit"].iloc[-1]
            if pb == pb:
                m["icr"] = 99.0 if not it or it != it or it <= 0.5 else pb / it
        if "cfo" in aa and npa is not None and not financial:
            last = aa.iloc[-5:]
            ok = last[["cfo", "np"]].dropna()
            if len(ok) >= 3 and ok["np"].sum() > 0:
                m["cfo_pat"] = ok["cfo"].sum() / ok["np"].sum()
        if npa is not None:
            last6 = npa.dropna().iloc[-6:]
            m["loss_years"] = int((last6 < 0).sum()) if len(last6) >= 5 \
                else (int((last6 < 0).sum()) if (last6 < 0).any() else None)
            s = npa.dropna()
            if len(s) >= 4 and s.iloc[-1] > 0 and s.iloc[-4] > 0:
                m["profit_cagr3"] = ((s.iloc[-1] / s.iloc[-4]) ** (1 / 3) - 1) * 100
        if "rev" in aa:
            s = aa["rev"].dropna()
            if len(s) >= 4 and s.iloc[-1] > 0 and s.iloc[-4] > 0:
                m["sales_cagr3"] = ((s.iloc[-1] / s.iloc[-4]) ** (1 / 3) - 1) * 100
    return m
