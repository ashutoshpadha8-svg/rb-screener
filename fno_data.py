#!/usr/bin/env python3
"""
NSE F&O FUTURES HISTORY  (for backtest.py --fno)
================================================

Downloads NSE's daily F&O bhavcopy for every trading day since 2013 and
keeps only futures rows (stock futures + NIFTY index futures):
  date, symbol, kind (STK/IDX), expiry, open, high, low, close, settle,
  contracts, oi, lot
Point-in-time by construction: a stock is "in F&O" on a day only if it
has futures rows in that day's file.

Sources (nsearchives.nseindia.com):
  up to 05-Jul-2024 : content/historical/DERIVATIVES/YYYY/MON/foDDMONYYYYbhav.csv.zip
  from 08-Jul-2024  : content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip (UDiFF)
Old files have no lot size -> lot = turnover / (contracts x price), rounded.
NSE's CDN often answers 403 once and 200 on retry, so every file is tried
up to 6 times. Resumable: days already done are skipped.

Output: data/fno/futures_YYYY.csv.gz  (+ data/fno/_done.txt)
First run: ~3,300 files, ~2.5 GB download, 30-60 min.

RUN
    python3 ~/Desktop/RB_Screener/fno_data.py
"""

import os
import io
import sys
import time
import zipfile
import threading
import datetime as dt
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import daily_screener as ds

FNO = os.path.join(ds.DATA, "fno")
os.makedirs(FNO, exist_ok=True)
DONE = os.path.join(FNO, "_done.txt")
START = "2013-01-01"
UDIFF_FROM = pd.Timestamp("2024-07-08")
OLD = ("https://nsearchives.nseindia.com/content/historical/DERIVATIVES/"
       "%Y/%b/fo%d%b%Ybhav.csv.zip")
NEW = ("https://nsearchives.nseindia.com/content/fo/"
       "BhavCopy_NSE_FO_0_0_0_%Y%m%d_F_0000.csv.zip")
THREADS = 4
_lock = threading.Lock()


def _url(day, new):
    u = (NEW if new else OLD)
    s = day.strftime(u)
    if not new:
        s = s.replace(day.strftime("%b"), day.strftime("%b").upper())
    return s


def _get(url):
    for i in range(6):
        try:
            r = requests.get(url, headers=ds.NSE_HDRS, timeout=60)
            if r.status_code == 200 and r.content[:2] == b"PK":
                return r.content
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(1.5 * (i + 1))
    return None


def _parse_old(raw, day):
    z = zipfile.ZipFile(io.BytesIO(raw))
    d = pd.read_csv(z.open(z.namelist()[0]))
    d.columns = [c.strip() for c in d.columns]
    d = d[(d.INSTRUMENT == "FUTSTK") |
          ((d.INSTRUMENT == "FUTIDX") & (d.SYMBOL == "NIFTY"))]
    price = d.CLOSE.where(d.CLOSE > 0, d.SETTLE_PR)
    lot = (d.VAL_INLAKH * 1e5 / (d.CONTRACTS * price)).where(d.CONTRACTS > 0)
    return pd.DataFrame({
        "date": day.date(), "symbol": d.SYMBOL.str.strip(),
        "kind": np.where(d.INSTRUMENT == "FUTSTK", "STK", "IDX"),
        "expiry": pd.to_datetime(d.EXPIRY_DT, format="%d-%b-%Y").dt.date,
        "open": d.OPEN, "high": d.HIGH, "low": d.LOW, "close": d.CLOSE,
        "settle": d.SETTLE_PR, "contracts": d.CONTRACTS, "oi": d.OPEN_INT,
        "lot": lot.round()})


def _parse_new(raw, day):
    z = zipfile.ZipFile(io.BytesIO(raw))
    d = pd.read_csv(z.open(z.namelist()[0]))
    d = d[(d.FinInstrmTp == "STF") |
          ((d.FinInstrmTp == "IDF") & (d.TckrSymb == "NIFTY"))]
    lot = d.NewBrdLotQty
    return pd.DataFrame({
        "date": day.date(), "symbol": d.TckrSymb.str.strip(),
        "kind": np.where(d.FinInstrmTp == "STF", "STK", "IDX"),
        "expiry": pd.to_datetime(d.XpryDt).dt.date,
        "open": d.OpnPric, "high": d.HghPric, "low": d.LwPric,
        "close": d.ClsPric, "settle": d.SttlmPric,
        "contracts": d.TtlTradgVol, "oi": d.OpnIntrst,
        "lot": lot})


def fetch_day(day):
    new = day >= UDIFF_FROM
    raw = _get(_url(day, new))
    if raw is None:                       # format switch date is fuzzy
        raw = _get(_url(day, not new))
        new = not new
    if raw is None:
        return day, None
    try:
        return day, (_parse_new if new else _parse_old)(raw, day)
    except Exception as e:
        print("\n  ! parse failed %s: %s" % (day.date(), e))
        return day, None


def trading_days():
    """Trading calendar = dates in the Nifty history file (+ weekdays after
    its last date, since the free source lags a few days)."""
    path = os.path.join(ds.DATA, ds.BENCH + ".csv")
    if not os.path.exists(path):
        ds.fetch_eod(ds.BENCH)
    cal = pd.to_datetime(pd.read_csv(path).Date)
    cal = cal[cal >= START]
    extra = pd.bdate_range(cal.max() + pd.Timedelta(days=1),
                           ds.now_ist().date() - dt.timedelta(days=1))
    return list(cal) + list(extra)


def main():
    done = set()
    if os.path.exists(DONE):
        done = set(open(DONE).read().split())
    days = [d for d in trading_days() if d.strftime("%Y-%m-%d") not in done]
    print("F&O bhavcopy: %d days to fetch (%d already done)"
          % (len(days), len(done)))
    buf, missing, n = {}, [], 0

    def flush():
        for y, frames in buf.items():
            path = os.path.join(FNO, "futures_%d.csv.gz" % y)
            df = pd.concat(frames)
            df.to_csv(path, mode="a", index=False, compression="gzip",
                      header=not os.path.exists(path))
        buf.clear()

    with ThreadPoolExecutor(THREADS) as ex:
        for day, df in ex.map(fetch_day, days):
            n += 1
            with _lock:
                if df is None:
                    missing.append(day.date())
                else:
                    buf.setdefault(day.year, []).append(df)
                    with open(DONE, "a") as f:
                        f.write(day.strftime("%Y-%m-%d") + "\n")
                if n % 50 == 0 or n == len(days):
                    flush()
                    sys.stdout.write("\r  %4d/%d  (missing %d)"
                                     % (n, len(days), len(missing)))
                    sys.stdout.flush()
    flush()
    print()
    if missing:
        print("  no file for %d days (holidays or NSE refused): %s%s"
              % (len(missing), ", ".join(str(d) for d in missing[:10]),
                 " ..." if len(missing) > 10 else ""))


SYMCHG_URL = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"


def symbol_map():
    """old NSE symbol -> today's symbol (follows chains A->B->C)."""
    path = os.path.join(ds.DATA, "_nse_symbolchange.csv")
    if not os.path.exists(path) or \
            time.time() - os.path.getmtime(path) > 7 * 86400:
        raw = _get_plain(SYMCHG_URL)
        if raw:
            open(path, "wb").write(raw)
    if not os.path.exists(path):
        return {}
    d = pd.read_csv(path, header=None, encoding="latin-1",
                    names=["name", "old", "new", "date"])
    d["old"] = d["old"].astype(str).str.strip().str.upper()
    d["new"] = d["new"].astype(str).str.strip().str.upper()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    m = dict(zip(d.sort_values("date")["old"], d.sort_values("date")["new"]))
    out = {}
    for o in m:
        n, seen = m[o], {o}
        while n in m and n not in seen:
            seen.add(n)
            n = m[n]
        out[o] = n
    return out


def _get_plain(url):
    for i in range(6):
        try:
            r = requests.get(url, headers=ds.NSE_HDRS, timeout=60)
            if r.status_code == 200:
                return r.content
        except requests.RequestException:
            pass
        time.sleep(1.5 * (i + 1))
    return None


def load_futures(years=None):
    """All downloaded futures rows as one DataFrame."""
    frames = []
    for f in sorted(os.listdir(FNO)):
        if f.startswith("futures_") and f.endswith(".csv.gz"):
            y = int(f[8:12])
            if years and y not in years:
                continue
            frames.append(pd.read_csv(os.path.join(FNO, f),
                                      parse_dates=["date", "expiry"]))
    if not frames:
        return pd.DataFrame()
    d = pd.concat(frames)
    mp = symbol_map()                    # old names -> today's names
    d["symbol"] = d["symbol"].map(lambda x: mp.get(x, x))
    d = d.drop_duplicates(["date", "symbol", "expiry"])
    return d.sort_values(["symbol", "date", "expiry"]).reset_index(drop=True)


if __name__ == "__main__":
    main()
