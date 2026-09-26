#!/usr/bin/env python3
"""
NEWS HEADLINES  --  free Google News RSS, no API key, no extra packages.

latest(symbol) -> up to 3 (date, headline, source) from the last 7 days,
searched by the company name from NSE's industry list when available.
Headlines are information only -- none of the backtested rules use news.
"""

import os
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
