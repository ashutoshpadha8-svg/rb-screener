#!/usr/bin/env python3
"""
NEWS HEADLINES  --  free Google News RSS, no API key, no extra packages.

latest(symbol) -> up to 3 (date, headline, source) from the last 7 days,
searched by the company name from NSE's industry list when available.
Headlines are information only -- none of the backtested rules use news.
"""

import os
import re
import time
import datetime as dt
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import pandas as pd
import requests

import daily_screener as ds

RSS = "https://news.google.com/rss/search?q=%s&hl=en-IN&gl=IN&ceid=IN:en"
INDUSTRY_FILE = os.path.join(ds.DATA, "_nse_industry.csv")
_names = None


def _company(symbol):
    global _names
    if _names is None:
        _names = {}
        if os.path.exists(INDUSTRY_FILE):
            d = pd.read_csv(INDUSTRY_FILE)
            _names = dict(zip(d["Symbol"].astype(str).str.upper(),
                              d["Company Name"].astype(str)))
    n = _names.get(symbol.upper())
    if not n:
        return None
    for tail in (" Ltd.", " Limited", " Ltd"):
        n = n.replace(tail, "")
    return n.strip()


def latest(symbol, n=3, days=7):
    name = _company(symbol)
    q = '"%s" share OR stock' % name if name else "%s NSE share" % symbol
    try:
        r = requests.get(RSS % quote(q), timeout=15,
                         headers={"User-Agent": "Mozilla/5.0"})
        time.sleep(0.3)
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
    except (requests.RequestException, ET.ParseError):
        return []
    cut = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    out = []
    for it in root.iter("item"):
        try:
            when = parsedate_to_datetime(it.findtext("pubDate"))
        except (TypeError, ValueError):
            continue
        if when < cut:
            continue
        title = (it.findtext("title") or "").strip()
        src = ""
        if " - " in title:
            title, src = title.rsplit(" - ", 1)
        out.append((when, title, src))
    out.sort(key=lambda x: x[0], reverse=True)
    return [(w.strftime("%d %b"), t, s) for w, t, s in out[:n]]


def print_news(symbols, label=""):
    if not symbols:
        return
    print("\n==== NEWS (last 7 days, Google News)%s ====" % label)
    for s in symbols:
        items = latest(s)
        print("  %s" % s)
        if not items:
            print("     (no headlines found)")
        for d, t, src in items:
            print("     %s  %s%s" % (d, t[:100], ("  [%s]" % src) if src else ""))


# ================================================================== NSE filings
# Official corporate announcements (what the company itself files with NSE).
# Free, no key. NSE's bot filter sometimes answers 403 -> fresh session +
# retry; on failure the list is just empty (information only, never a rule).
NSE_API = "https://www.nseindia.com/api/corporate-announcements"
NSE_HDR = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 "
                         "Safari/537.36",
           "Accept": "application/json, text/plain, */*",
           "Accept-Language": "en-US,en;q=0.9",
           "Referer": "https://www.nseindia.com/"}
# routine filings nobody needs to read
NSE_SKIP = ("trading window", "analysts/institutional investor meet",
            "newspaper publication", "copy of newspaper", "loss of share",
            "duplicate share", "certificate under sebi (depositories",
            "esop", "esos", "esps", "record date", "general updates",
            "shareholders meeting", "change in rta", "investor presentation")
# worth a red flag (checked in the category AND the text)
NSE_RED = re.compile(
    r"\bpledg|\bencumb|\bresign|\bsebi (order|adjudicat)|\bpenalt|\bfraud|"
    r"\bdefault|\binsolvency|\bcirp\b|search and seizure|income tax search|"
    r"\braid|\bdowngrad|\bstrikes?\b|\blockout|\bsuspension|\bforensic|"
    r"qualified opinion|\blitigation|\bdisturbance|\bdelay in|\bcessation")
_nse = None


def _nse_session(fresh=False):
    global _nse
    if _nse is None or fresh:
        _nse = requests.Session()
        try:
            _nse.get("https://www.nseindia.com/", headers=NSE_HDR, timeout=15)
        except requests.RequestException:
            pass
    return _nse


def nse_announcements(symbol, days=30, n=4):
    """Up to n recent, non-routine NSE filings, red flags first.
    [(date 'dd Mon', category, short text, is_red_flag)]"""
    to = dt.date.today()
    fr = to - dt.timedelta(days=days)
    params = {"index": "equities", "symbol": symbol,
              "from_date": fr.strftime("%d-%m-%Y"),
              "to_date": to.strftime("%d-%m-%Y")}
    data = None
    for attempt in range(3):
        try:
            r = _nse_session(fresh=attempt > 0).get(
                NSE_API, headers=NSE_HDR, params=params, timeout=20)
            if r.status_code == 200 and r.content[:1] in (b"[", b"{"):
                data = r.json()
                break
        except (requests.RequestException, ValueError):
            pass
        time.sleep(1.5 * (attempt + 1))
    time.sleep(0.4)
    if not isinstance(data, list):
        return None                                  # unknown (blocked)
    out = []
    for x in data:
        cat = str(x.get("desc") or "")
        txt = " ".join(str(x.get("attchmntText") or "").split())
        low = (cat + " " + txt).lower()
        if any(k in cat.lower() for k in NSE_SKIP) or "pursuant to esop" in low:
            continue
        red = bool(NSE_RED.search(low)) or (
            "auditor" in low and any(k in low for k in ("cessation", "removal",
                                                        "resign", "qualif")))
        try:
            d = dt.datetime.strptime(str(x.get("an_dt")), "%d-%b-%Y %H:%M:%S")
        except ValueError:
            continue
        short = re.sub(r"^%s\s*:\s*" % re.escape(symbol), "", txt)
        short = re.sub(r"^.{0,80}?has informed the Exchange (about|regarding) ",
                       "", short, flags=re.I)
        out.append((d, cat, short[:140], red))
    out.sort(key=lambda t: (not t[3], -t[0].timestamp()))
    return [(d.strftime("%d %b"), c, s, red) for d, c, s, red in out[:n]]
