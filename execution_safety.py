"""Fail-closed validation for manual delivery/MTF order workflows."""
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

import pandas as pd
from order_inputs import quantity

_LOCKS = {}


def workflow_lock(directory):
    """Shared by rbtrack, rbport and rbpos; kept until process exit."""
    import fcntl
    key = (os.getpid(), str(Path(directory).resolve()))
    if key in _LOCKS:
        return True
    Path(directory).mkdir(parents=True, exist_ok=True)
    handle = open(Path(directory)/'rbtrack.lock', 'a')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        handle.close()
        return False
    _LOCKS[key] = handle
    return True


def atomic_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.'+path.name+'.', dir=str(path.parent))
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(content);stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def finite_positive(value, label):
    try:number=float(value)
    except (TypeError,ValueError):raise ValueError('%s is missing/invalid' % label)
    if not math.isfinite(number) or number <= 0:
        raise ValueError('%s must be finite and positive' % label)
    return number


def validate_report(path, broker, client_id, today):
    from openpyxl import load_workbook
    try:
        wb=load_workbook(path,read_only=True,data_only=False)
        title=str(wb['Dashboard']['A1'].value or '')
        parts=[p.strip() for p in title.split('|')]
        wb.close()
    except Exception as error:
        raise ValueError('Cannot read report identity/date: %s' % type(error).__name__)
    if len(parts)<4 or parts[0]!='RB_Screener' or parts[1].upper()!=broker.upper() or parts[2].upper()!=client_id.upper():
        raise ValueError('Report does not belong to the active broker/client; regenerate with rb')
    if parts[-1] != str(today):
        raise ValueError('Report is from %s, not today (%s); run rb' % (parts[-1],today))


def validate_batch(buys, sells=()):
    seen=set();selling={str(r['symbol']).strip().upper() for r in sells}
    for row in buys:
        symbol=str(row['symbol']).strip().upper()
        if not re.fullmatch(r'[A-Z0-9&_.-]{1,30}',symbol):
            raise ValueError('Invalid symbol: %s' % symbol)
        if symbol in seen:raise ValueError('%s has duplicate BUY selections/SIPs; select one' % symbol)
        if symbol in selling:raise ValueError('%s is selected for both BUY and SELL; choose one' % symbol)
        seen.add(symbol)
        if 'shares' in row:
            if not quantity(row['shares'],symbol+' Qty'):raise ValueError(symbol+' quantity must be positive')
            finite_positive(row['entry_price'],symbol+' price')
            leverage = finite_positive(row.get('lev',1),symbol+' leverage')
            if row.get('product') == 'MTF' and not 1 < leverage <= 10:
                raise ValueError(symbol+' MTF leverage is unverified/invalid')
            if row.get('product') not in ('CNC','MTF'):raise ValueError('Unknown product for '+symbol)
    return seen


def validate_caps(symbols, cache, today, floor=10000, max_age_days=5):
    if not symbols:return
    try:frame=pd.read_csv(cache)
    except Exception as error:raise ValueError('Market-cap cache unavailable; run rbscan (%s)' % type(error).__name__)
    if not {'symbol','mcap_cr','asof'} <= set(frame):raise ValueError('Market-cap cache fields missing')
    frame['symbol']=frame['symbol'].astype(str).str.upper().str.strip()
    for symbol in symbols:
        rows=frame[frame.symbol==symbol]
        if len(rows)!=1:raise ValueError('%s has missing/duplicate market-cap data' % symbol)
        row=rows.iloc[0]
        try:asof=dt.date.fromisoformat(str(row['asof'])[:10])
        except ValueError:raise ValueError(symbol+' market-cap date is invalid')
        age=(today-asof).days
        if not 0<=age<=max_age_days:raise ValueError(symbol+' market-cap data is stale/future; run rbscan')
        cap=finite_positive(row['mcap_cr'],symbol+' market cap')
        if cap<floor:raise ValueError('%s market cap %.0f Cr is below %.0f Cr' % (symbol,cap,floor))


def publish_ranks(path, frame):
    content=frame.to_csv(index=False).encode()
    meta=dict(rows=len(frame),sha256=hashlib.sha256(content).hexdigest())
    atomic_bytes(path,content)
    atomic_bytes(str(path)+'.meta.json',json.dumps(meta).encode())


def ranking_days(now=None):
    """Ranking dates accepted today: the last completed session, plus TODAY
    once today's session has started (09:15 IST) -- an rb run in market hours
    ranks on the live price, so its date is today (RB runs rb intraday)."""
    import datetime as dt
    import daily_screener as ds
    import nse_calendar as nc
    now = now or ds.now_ist()
    days = {ds.last_expected_session()}
    if nc.is_trading_day(now.date()) and (now.hour, now.minute) >= (9, 15):
        days.add(now.date())
    return days


def read_ranks(path, expected_day):
    """A truncated, stale or pre-update ranking cannot imply an exit.
    expected_day: one date or a set of accepted dates (ranking_days())."""
    try:
        content=Path(path).read_bytes();meta=json.loads(Path(str(path)+'.meta.json').read_text())
        from io import BytesIO
        frame=pd.read_csv(BytesIO(content))
        if meta['sha256']!=hashlib.sha256(content).hexdigest() or meta['rows']!=len(frame):
            raise ValueError('ranking integrity/count mismatch')
        if not {'symbol','rank','date','regime_red'}<=set(frame) or frame.empty:
            raise ValueError('ranking fields/rows missing')
        symbols=frame.symbol.astype(str).str.upper().str.strip()
        rank=pd.to_numeric(frame['rank'],errors='coerce')
        if symbols.duplicated().any() or not all(symbols) or rank.isna().any() or set(rank)!=set(range(1,len(frame)+1)):
            raise ValueError('ranking symbols/ranks incomplete or invalid')
        ok_days={str(d) for d in expected_day} if isinstance(expected_day,(set,frozenset,list,tuple)) else {str(expected_day)}
        if len(set(frame.date.astype(str)))!=1 or set(frame.date.astype(str))-ok_days:
            raise ValueError('ranking is not from the expected completed trading session')
        regimes=frame.regime_red.astype(str).str.lower()
        if len(set(regimes))!=1 or regimes.iloc[0] not in ('true','false'):
            raise ValueError('ranking regime invalid')
        frame['symbol']=symbols
        return frame
    except Exception as error:
        raise ValueError('Ranking unverified (%s); run rbscan' % error)


def limit_price(price, tick, buffer=0):
    """Round upward using this instrument's actual tick, never a global guess."""
    from decimal import Decimal, ROUND_CEILING
    price=finite_positive(price,'price');tick=finite_positive(tick,'broker instrument tick')
    step=Decimal(str(tick))
    return float((Decimal(str(price))*(Decimal(1)+Decimal(str(buffer)))/step).to_integral_value(rounding=ROUND_CEILING)*step)
