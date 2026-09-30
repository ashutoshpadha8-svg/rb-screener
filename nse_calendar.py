"""
nse_calendar.py -- NSE trading days (30 Sep 2026, Codex review: the momentum
rebalance window counted weekdays only, so a holiday on the 1st weekday of a
month shifted the plan to the wrong day).

Holidays come from NSE's own list (nseindia.com/api/holiday-master?type=trading,
equity segment 'CM'), cached weekly in data/_nse_holidays.json. If NSE cannot
be reached and there is no cache, it falls back to weekdays and says so once.

  is_trading_day(d)      next_trading_day(d)      first_trading_day(y, m)
  python3 nse_calendar.py      -> this year's holidays + next rebalance day
"""

import datetime as dt
import json
import os
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "_nse_holidays.json")
URL = "https://www.nseindia.com/api/holiday-master?type=trading"
_mem = None
_warned = False


def _fetch():
    try:
        import daily_screener as ds
        hdrs = [ds.NSE_HDRS, {"User-Agent": "Mozilla/5.0"}, ds.NSE_HDRS]
    except Exception:
        hdrs = [{"User-Agent": "Mozilla/5.0"}]
    for i, h in enumerate(hdrs):
        try:
            s = requests.Session()
            s.get("https://www.nseindia.com/", headers=h, timeout=15)
            j = s.get(URL, headers=h, timeout=15).json()
            rows = j.get("CM") or [x for v in j.values() for x in v]
            days = sorted({dt.datetime.strptime(x["tradingDate"], "%d-%b-%Y")
                           .date().isoformat() for x in rows
                           if x.get("tradingDate")})
            if days:
                return days
        except Exception:
            time.sleep(2 * (i + 1))
    return None


def holidays():
    """Set of ISO dates (NSE equity holidays). Empty set = weekdays only."""
    global _mem, _warned
    if _mem is not None:
        return _mem
    cache = {}
    try:
        with open(CACHE) as f:
            cache = json.load(f)
    except (IOError, OSError, ValueError):
        pass
    fresh = cache.get("fetched", "") >= (dt.date.today() -
                                         dt.timedelta(days=7)).isoformat()
    year_ok = any(d.startswith(str(dt.date.today().year))
                  for d in cache.get("days", []))
    if not (fresh and year_ok):
        days = _fetch()
        if days:
            cache = {"fetched": dt.date.today().isoformat(), "days": days}
            try:
                os.makedirs(os.path.dirname(CACHE), exist_ok=True)
                with open(CACHE, "w") as f:
                    json.dump(cache, f)
            except (IOError, OSError):
                pass
    _mem = set(cache.get("days", []))
    if not _mem and not _warned:
        _warned = True
        print("! NSE holiday list not available -- using weekdays only "
              "(a holiday on the rebalance day would be missed).")
    return _mem


def is_trading_day(d):
    d = d.date() if isinstance(d, dt.datetime) else d
    return d.weekday() < 5 and d.isoformat() not in holidays()


def next_trading_day(d):
    d = (d.date() if isinstance(d, dt.datetime) else d) + dt.timedelta(days=1)
    while not is_trading_day(d):
        d += dt.timedelta(days=1)
    return d


def first_trading_day(year, month):
    d = dt.date(year, month, 1)
    while not is_trading_day(d):
        d += dt.timedelta(days=1)
    return d


if __name__ == "__main__":
    h = sorted(x for x in holidays() if x.startswith(str(dt.date.today().year)))
    print("NSE holidays %s: %s" % (dt.date.today().year, ", ".join(h) or "-"))
    t = dt.date.today()
    nm = dt.date(t.year + (t.month == 12), t.month % 12 + 1, 1)
    print("Next month's 1st trading day: %s" % first_trading_day(nm.year,
                                                                   nm.month))
