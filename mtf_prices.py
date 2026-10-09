"""Public official NSE quotes for MTF reports; no broker account mutation.
Endpoint observed in NSE's own quote-page JS on 9 Oct 2026:
/_next/static/chunks/c1e5e22f1c971efe.js (getMetaData/getSymbolData).
Fail closed on mismatched symbols/series, missing times, stale/future data.
Website endpoints are not a contractual public API and may change.
"""
import datetime as dt
import math
import re
import time
import requests

IST = dt.timezone(dt.timedelta(hours=5,minutes=30))
URL = 'https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi'


def stamp(value):
    for fmt in ('%d-%b-%Y %H:%M:%S','%d-%b-%Y %H:%M','%Y-%m-%d %H:%M:%S'):
        try:return dt.datetime.strptime(str(value),fmt).replace(tzinfo=IST)
        except ValueError:pass
    return None


def parse_quote(payload,symbol,now,expected,market_open):
    rows=payload.get('equityResponse') if isinstance(payload,dict) else None
    if not isinstance(rows,list):raise ValueError('NSE quote schema changed')
    rows=[r for r in rows if isinstance(r,dict) and isinstance(r.get('metaData'),dict) and
          r.get('metaData',{}).get('symbol')==symbol and
          r.get('metaData',{}).get('series')=='EQ']
    if len(rows)!=1:raise ValueError('NSE symbol/series missing or ambiguous')
    r=rows[0];book=r.get('orderBook');p=book.get('lastPrice') if isinstance(book,dict) else None;t=stamp(r.get('lastUpdateTime'))
    try:p=float(p)
    except (TypeError,ValueError):raise ValueError('NSE price missing')
    if not math.isfinite(p) or p<=0:raise ValueError('NSE price invalid')
    if t is None:raise ValueError('NSE timestamp missing')
    if now.tzinfo is None:now=now.replace(tzinfo=IST)
    now=now.astimezone(IST)
    if t>now+dt.timedelta(minutes=2):raise ValueError('NSE timestamp in future')
    if market_open:
        if t.date()!=now.date() or now-t>dt.timedelta(minutes=15):
            raise ValueError('NSE quote stale during trading')
        label='NSE official LTP'
    else:
        if t.date() not in {expected,now.date()} or t.date()<expected:
            raise ValueError('NSE quote older than last completed session')
        if t.date()==expected and t.time()<dt.time(15,30):
            raise ValueError('NSE completed-session quote is intraday only')
        label='NSE official session-end LTP' if t.time()>=dt.time(15,30) else 'NSE official timestamped LTP'
    return p,'VERIFIED',label+' '+t.strftime('%Y-%m-%d %H:%M:%S IST')


def nse_quotes(symbols,now,expected,market_open,http=None):
    out={};http=http or requests.Session()
    http.headers.update({'User-Agent':'Mozilla/5.0','Accept':'application/json',
                         'Referer':'https://www.nseindia.com/'})
    for i,s in enumerate(sorted(set(str(s).upper() for s in symbols))):
        if not re.fullmatch(r'[A-Z0-9&_.-]+',s):continue
        try:
            r=http.get(URL,params={'functionName':'getMetaData','symbol':s},timeout=10)
            r.raise_for_status();meta=r.json()
            if not isinstance(meta,dict) or meta.get('symbol')!=s or 'EQ' not in meta.get('activeSeries',[]):
                raise ValueError('NSE stock identity/EQ series not confirmed')
            if str(meta.get('isDelisted')).lower()=='true' or str(meta.get('isSuspended')).lower()=='true':
                raise ValueError('NSE stock delisted/suspended')
            market_type=meta.get('marketType')
            if not isinstance(market_type,str) or not market_type:
                raise ValueError('NSE market type missing')
            r=http.get(URL,params={'functionName':'getSymbolData','marketType':market_type,
                                  'series':'EQ','symbol':s},timeout=10)
            r.raise_for_status()
            out[s]=parse_quote(r.json(),s,now,expected,market_open)
        except (requests.RequestException,ValueError,TypeError,KeyError) as e:
            # Do not bypass 401/403, retry across proxies, or use search caches.
            print('! NSE quote %s unavailable: %s'%(s,type(e).__name__))
        if i+1<len(set(symbols)):time.sleep(.2)
    return out


def safe_error(error,sess):
    text=str(error)
    for value in (getattr(sess,'token',''),getattr(sess,'_jwt','')):
        if value:text=text.replace(str(value),'[REDACTED]')
    text=re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+','[REDACTED JWT]',text)
    return re.sub(r'[\r\n]+',' ',text)[:240]


def data_plan_note(ba,sess):
    if getattr(sess,'broker',None)!='DHAN':return ''
    try:
        p=ba._call(sess,'GET','/profile')
        if not isinstance(p,dict):return ''
        if str(p.get('dataPlan','')).lower()=='deactive':
            return 'Dhan Data API Deactive; token validity alone does not enable quotes. NSE remains primary; no paid activation performed.'
        return 'Dhan dataPlan='+str(p.get('dataPlan','UNKNOWN'))
    except Exception:return 'Dhan profile unavailable; data-plan status UNKNOWN'
