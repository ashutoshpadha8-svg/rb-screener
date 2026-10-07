#!/usr/bin/env python3
"""
mtf_check.py -- MTF hisaab with honest status (v29, 7 Oct 2026).
READ-ONLY: no order, nothing changed in split.csv / journal.

v29 = rewrite after Codex's v27 review (8 findings, 17 synthetic cases):
every number carries a STATUS:
  VERIFIED   from the broker (trade history, ledger) or typed by you
  ESTIMATED  a model (last close instead of live price, interest by lot
             days, sell fees from the rate card, product guessed ...)
  UNKNOWN    a required input is missing -> the number is NOT shown as a
             value and every total that needs it is UNKNOWN too
             (a 'partial' subtotal of the known parts is shown separately)
Nothing missing is ever counted as 0.

Scopes are kept apart:
  MTF_Open           open MTF lots: cost, value, gross price P&L, interest
                     estimate by LOT (each lot its own days)
  MTF_Exit_Estimate  if sold now: gross - current loan - unpaid interest -
                     sell fees  (needs --loan; a hypothetical sale, never
                     'actual')
  MTF_Period         since --from: matched realised P&L (UNKNOWN when a
                     sell has no buy in the history) + open P&L - ALL MTF
                     interest debited - MTF trade charges
  Reconciliation     FIFO MTF qty vs demat qty, uncovered sells, demat
                     stocks with no MTF trade, unallocated account items
                     (DP / pledge / dividends / money in-out: account-wide,
                     NOT put into the MTF result)

Current loan: the Dhan API used here does not give the MTF funded amount.
Type it from the Dhan app (MTF / pledge section, 'funded amount'):
      python3 mtf_check.py --loan 272000
Without it loan, own money, exit cash and open-position interest are
UNKNOWN. 'Last interest debit / days x 365 / rate' is shown only as the
AVERAGE interest-bearing balance of that past period (a diagnostic).

Run:  python3 mtf_check.py                 (history from 1 Apr 2024)
      python3 mtf_check.py --loan 272000 --own-cash 140000
      python3 mtf_check.py --ledger ~/Downloads/ledger.xlsx   (API fails)
Output: terminal + accounts/<..>/reports/MTF_Check_<date>.xlsx
Exit code 2 = an essential source failed (report marked INCOMPLETE).
"""

import argparse
import datetime as dt
import math
import os
import re
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

MTF_RATE = 0.1249          # Dhan's published base slab; ESTIMATE only
VERIFIED, ESTIMATED, UNKNOWN = "VERIFIED", "ESTIMATED", "UNKNOWN"
PAGE_LIMIT = 50


# ================================================================== values
class Num(object):
    """A money value with a status. value None <=> UNKNOWN."""

    def __init__(self, value=None, status=None, note="", partial=None):
        ok = value is not None and _finite(value)
        self.value = float(value) if ok else None
        self.status = (status or VERIFIED) if ok else UNKNOWN
        self.note = note
        self.partial = partial          # known subtotal when UNKNOWN

    @property
    def known(self):
        return self.value is not None

    def __neg__(self):
        return Num(-self.value if self.known else None, self.status,
                   self.note, -self.partial if self.partial is not None
                   else None)

    def __repr__(self):
        return "Num(%r, %s)" % (self.value, self.status)


def _finite(v):
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def total(parts, note=""):
    """Sum of Num parts. Any UNKNOWN -> UNKNOWN (partial = known sum);
    any ESTIMATED -> ESTIMATED."""
    known = [p for p in parts if p.known]
    s = sum(p.value for p in known)
    if len(known) < len(parts):
        return Num(None, UNKNOWN, note, partial=s)
    st = ESTIMATED if any(p.status == ESTIMATED for p in parts) else VERIFIED
    return Num(s, st, note)


def rs(x):
    """'Rs 1,234' / '-Rs 1,234' / 'UNKNOWN'. Takes a number or a Num."""
    if isinstance(x, Num):
        if not x.known:
            return "UNKNOWN" + (" (known part %s)" % rs(x.partial)
                                if x.partial is not None else "")
        x = x.value
    if x is None or not _finite(x):
        return "-"
    return ("-Rs " if x < 0 else "Rs ") + format(abs(int(round(x))), ",")


def _num(v):
    """float, or nan for anything that is not a finite number."""
    try:
        f = float(str(v).replace(",", "").strip() or 0)
        return f if math.isfinite(f) else float("nan")
    except ValueError:
        return float("nan")


# ================================================================== ledger
def classify(narration):
    """Bucket of one ledger row by its narration. '_' buckets are not
    charges: _balance (opening/closing), _trade (buy/sell bills),
    _money (money you added / took out)."""
    n = str(narration or "").lower()
    if "opening balance" in n or "closing balance" in n:
        return "_balance"
    if "mtf" in n and ("int" in n or "interest" in n):
        return "MTF interest"
    if "dividend" in n:
        return "Dividend (income)"
    if "interest" in n or "dpc" in n or "delayed payment" in n:
        return "Other interest"
    if "pledge" in n:
        return "Pledge charges"
    if re.search(r"\bdp\b|depository|cdsl|nsdl", n):
        return "DP charges"
    if re.search(r"bill|settlement|trade|stt", n):
        return "_trade"
    if re.search(r"payin|pay-in|payout|pay-out|fund|transfer|upi|neft|imps|"
                 r"rtgs|bank|withdraw|deposit", n):
        return "_money"
    return "Other charges"


DATE_FMTS = ("%b %d, %Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y",
             "%d-%m-%Y", "%d-%b-%Y", "%d %b %Y")


def parse_date(v):
    """date or None. Explicit formats; slashes/dashes are DAY first (Indian
    statements), never month first (Codex F8: 05/10/2026 = 5 Oct)."""
    if isinstance(v, (dt.datetime, pd.Timestamp)):
        return v.date() if not pd.isna(v) else None
    if isinstance(v, dt.date):
        return v
    s = str(v or "").strip()
    if not s or s.lower() in ("nan", "nat", "none"):
        return None
    for f in DATE_FMTS:
        try:
            return dt.datetime.strptime(s, f).date()
        except ValueError:
            pass
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return parse_date(m.group(1)) if m else None


def ledger_rows(raw):
    """Rows (dicts) from the Dhan API or a downloaded file ->
    DataFrame date, narration, debit, credit, bucket, voucher, bad.
    Duplicate vouchers (same number/date/narration/amounts) are dropped."""
    cols_out = ["date", "narration", "debit", "credit", "bucket", "voucher",
                "bad"]
    d = pd.DataFrame(raw)
    if d.empty:
        return pd.DataFrame(columns=cols_out)
    cols = {c: str(c).lower().replace(" ", "") for c in d.columns}

    def pick(*keys):
        for c, lc in cols.items():
            if any(k == lc or (len(k) > 4 and k in lc) for k in keys):
                return d[c]
        return pd.Series([""] * len(d))
    def exact(*keys):
        for c, lc in cols.items():
            if lc in keys:
                return d[c]
        return pd.Series([""] * len(d))
    nar = pick("narration", "description", "particular", "particulars",
               "remark", "remarks")
    vd = pick("voucherdesc", "vouchertype")
    out = pd.DataFrame({
        "date": [parse_date(x) for x in pick("voucherdate", "date",
                                             "txndate", "transactiondate")],
        "narration": [("%s %s" % (a, b)).strip() if str(b).lower() not in
                      str(a).lower() else str(a)
                      for a, b in zip(nar.fillna(""), vd.fillna(""))],
        "debit": [_num(x) for x in pick("debit")],
        "credit": [_num(x) for x in pick("credit")],
        "voucher": [str(x) for x in exact("vouchernumber", "voucherno",
                                          "voucher_no", "voucherid")]})
    out["bucket"] = [classify(x) for x in out["narration"]]
    out["bad"] = out["debit"].isna() | out["credit"].isna()
    key = out[["voucher", "date", "narration", "debit", "credit"]].astype(str)
    has_v = out["voucher"].str.strip().ne("") & out["voucher"].ne("nan")
    dup = key.duplicated() & has_v
    return out[~dup][cols_out].reset_index(drop=True)


def read_ledger_file(path):
    if path.lower().endswith((".xlsx", ".xls")):
        raw = pd.read_excel(path)
        for i in range(min(15, len(raw))):     # title rows above the header
            row = [str(x).lower() for x in raw.iloc[i].values]
            if any("debit" in x for x in row) and any("credit" in x
                                                      for x in row):
                raw.columns = raw.iloc[i].values
                raw = raw.iloc[i + 1:]
                break
    else:
        raw = pd.read_csv(path)
    return ledger_rows(raw.to_dict("records"))


def dhan_ledger(sess, frm, to):
    import broker_api as ba
    d = ba._call(sess, "GET", "/ledger", params={
        "from-date": frm.isoformat(), "to-date": to.isoformat()})
    d = d.get("data", d) if isinstance(d, dict) else d
    if not isinstance(d, list):
        raise ValueError("ledger reply is not a list")
    return ledger_rows(d)


def charges(led):
    """{bucket: Num(debit - credit, VERIFIED, 'n rows')} for the charge
    buckets; a bucket with an unreadable amount is UNKNOWN."""
    x = led[~led["bucket"].astype(str).str.startswith("_")]
    out = {}
    for b, g in x.groupby("bucket"):
        if g["bad"].any():
            ok = g[~g["bad"]]
            out[b] = Num(None, UNKNOWN, "%d unreadable rows" % g["bad"].sum(),
                         partial=round(ok["debit"].sum() - ok["credit"].sum(),
                                       2))
        else:
            out[b] = Num(round(g["debit"].sum() - g["credit"].sum(), 2),
                         VERIFIED, "%d rows" % len(g))
    return out


def closing_balance(led):
    """Ledger closing balance (+ = cash with Dhan), or None."""
    x = led[[("closing balance" in str(n).lower()) for n in led["narration"]]]
    if not len(x):
        return None
    r = x.iloc[-1]
    return round(r["credit"] - r["debit"], 2)


def money_in_out(led):
    """(added, withdrawn) from the _money rows (credit = added)."""
    x = led[led["bucket"] == "_money"]
    return round(x["credit"].sum(), 2), round(x["debit"].sum(), 2)


def interest_periods(led):
    """MTF interest rows with their period: [(start, end, debit, credit)]."""
    out = []
    for _, r in led[led["bucket"] == "MTF interest"].iterrows():
        m = re.findall(r"(\d{2})/(\d{2})/(\d{4})", str(r["narration"]))
        a = b = None
        if len(m) >= 2:
            try:
                a, b = (dt.date(int(y), int(mo), int(d)) for d, mo, y in m[:2])
            except ValueError:
                a = b = None
        out.append((a, b, r["debit"], r["credit"]))
    return out


def avg_interest_balance(led, rate=MTF_RATE):
    """DIAGNOSTIC ONLY (Codex F1): last MTF interest debit / its days x 365
    / rate = the AVERAGE interest-bearing balance of that past period at
    that assumed rate -- not today's loan. (avg Rs, per day Rs, period text,
    period end) or (None, None, '', None)."""
    if not rate or rate <= 0:
        return None, None, "", None
    per = [p for p in interest_periods(led) if p[0] and p[1] and p[2] > 0]
    if not per:
        return None, None, "", None
    a, b, deb, _ = max(per, key=lambda p: p[1])
    days = (b - a).days + 1
    if days <= 0:
        return None, None, "", None
    day = deb / days
    return round(day * 365 / rate, 2), round(day, 2), "%s -> %s" % (a, b), b


# ================================================================== trades
def _ts(v):
    """datetime of an execution, or None (never invented)."""
    s = str(v or "").strip()
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
              "%d-%m-%Y %H:%M:%S", "%d-%b-%Y %H:%M:%S"):
        for c in (s, s[:19]):
            try:
                return dt.datetime.strptime(c, f)
            except ValueError:
                pass
    return None


def parse_trade(x, ids=None):
    """Dhan trade-history row -> dict, keeping identity + exact time."""
    ids = ids or {}
    sid = str(x.get("securityId") or "")
    sym = ids.get(sid) or re.sub(r"-(EQ|BE)$", "", str(
        x.get("tradingSymbol") or x.get("customSymbol") or "").upper())
    ts = _ts(x.get("exchangeTime") or x.get("createTime") or
             x.get("updateTime"))
    chg = [_num(x.get(k)) for k in ("sebiTax", "stt", "brokerageCharges",
                                    "serviceTax", "exchangeTransactionCharges",
                                    "stampDuty") if x.get(k) not in (None, "")]
    return {
        "symbol": sym, "side": str(x.get("transactionType") or "").upper(),
        "qty": _num(x.get("tradedQuantity")),
        "price": _num(x.get("tradedPrice")),
        "ts": ts, "date": ts.date().isoformat() if ts else None,
        "product": str(x.get("productType") or "").upper(),
        "exch": str(x.get("exchangeSegment") or ""),
        "isin": str(x.get("isin") or ""),
        "tid": str(x.get("exchangeTradeId") or x.get("tradeId") or ""),
        "oid": str(x.get("orderId") or x.get("exchangeOrderId") or ""),
        "charges": sum(c for c in chg if c == c),
        "charges_ok": all(c == c for c in chg)}


def dedupe(trades):
    """Drop replayed executions: same exchange + execution id (or, without
    an id, same order id + time + qty + price). Returns (kept, dropped)."""
    seen, out, drop = set(), [], 0
    for t in trades:
        k = (t.get("exch"), t["tid"]) if t.get("tid") else \
            ("noid", t.get("oid"), t.get("ts"), t["qty"], t["price"],
             t["side"], t["symbol"])
        if k in seen:
            drop += 1
            continue
        seen.add(k)
        out.append(t)
    return out, drop


def dhan_trades(sess, frm, to, chunk=90):
    """Every executed trade (Dhan GET /v2/trades/{from}/{to}/{page}, asked
    90 days at a time). Returns (trades, meta); meta['complete'] is False
    when a chunk still had data at the page limit."""
    import broker_api as ba
    ids = {}
    try:
        ids = {str(v["id"]): k for k, v in ba.symbol_map(sess).items()}
    except Exception:
        pass
    out, notes, complete = [], [], True
    a = frm
    while a <= to:
        b = min(to, a + dt.timedelta(days=chunk - 1))
        for page in range(PAGE_LIMIT):
            d = ba._call(sess, "GET", "/trades/%s/%s/%d" % (a, b, page))
            d = d.get("data", d) if isinstance(d, dict) else d
            if not d:
                break
            out += [parse_trade(x, ids) for x in d
                    if "EQ" in str(x.get("exchangeSegment", "EQ"))]
            if page == PAGE_LIMIT - 1:
                complete = False
                notes.append("%s..%s: still data at page %d" % (a, b, page))
        a = b + dt.timedelta(days=1)
    out, drop = dedupe(out)
    if drop:
        notes.append("%d duplicate executions dropped" % drop)
    return out, {"complete": complete, "notes": notes}


def valid_trade(t, today=None):
    today = today or dt.date.today()
    return (t["side"] in ("BUY", "SELL") and _finite(t["qty"]) and
            t["qty"] > 0 and _finite(t["price"]) and t["price"] > 0 and
            t["ts"] is not None and t["ts"].date() <= today and
            bool(t["symbol"]))


def fifo(trades, today=None):
    """MTF trades -> FIFO by EXACT execution time (Codex F5: never re-sort a
    same-day SELL after a BUY). A SELL without enough earlier BUYs in the
    history = 'uncovered' -> realised P&L is UNKNOWN (the matched part is
    kept as 'matched').
    Returns dict: bought, sold, matched (Rs), realised (Num), charges (Num),
    lots {sym: [[date, qty, price, charge_left]]}, uncovered {sym: qty},
    invalid (count of rows without a valid time/qty/price)."""
    good = [t for t in trades if valid_trade(t, today)]
    invalid = len(trades) - len(good)
    order = sorted(range(len(good)), key=lambda i: (good[i]["ts"], i))
    lots, bought, sold, matched, chg, unc = {}, 0.0, 0.0, 0.0, 0.0, {}
    chg_ok = True
    for i in order:
        t = good[i]
        L = lots.setdefault(t["symbol"], [])
        chg += t.get("charges", 0)
        chg_ok = chg_ok and t.get("charges_ok", True)
        if t["side"] == "BUY":
            L.append([t["date"], t["qty"], t["price"], t.get("charges", 0)])
            bought += t["qty"] * t["price"]
        else:
            sold += t["qty"] * t["price"]
            left = t["qty"]
            while left > 1e-9 and L:
                take = min(left, L[0][1])
                matched += take * (t["price"] - L[0][2])
                L[0][3] -= L[0][3] * take / L[0][1]
                L[0][1] -= take
                left -= take
                if L[0][1] <= 1e-9:
                    L.pop(0)
            if left > 1e-9:
                unc[t["symbol"]] = unc.get(t["symbol"], 0) + left
    lots = {s: L for s, L in lots.items() if sum(x[1] for x in L) > 1e-9}
    realised = Num(round(matched, 2), VERIFIED, "") if not unc and \
        not invalid else Num(None, UNKNOWN, "sells without a buy in the "
                             "history / invalid rows", partial=round(matched,
                                                                     2))
    return {"bought": round(bought, 2), "sold": round(sold, 2),
            "matched": round(matched, 2), "realised": realised,
            "charges": Num(round(chg, 2), VERIFIED if chg_ok else UNKNOWN,
                           "per-trade fees in the history"),
            "lots": lots, "uncovered": unc, "invalid": invalid}


def lot_interest(lots, share, rate, today):
    """Interest ESTIMATE, each lot its own calendar days (Codex F6):
    sum(qty x price x share x rate x days/365). Broker billing (settlement
    days, slabs, daily balance) differs -> always ESTIMATED."""
    if share is None or not rate or rate <= 0:
        return Num(None, UNKNOWN, "needs --loan (funded share) and a rate")
    s = 0.0
    for d, q, p, _ in lots:
        days = (today - dt.date.fromisoformat(d)).days
        if days < 0:
            return Num(None, UNKNOWN, "lot dated in the future")
        s += q * p * share * rate * days / 365
    return Num(round(s, 2), ESTIMATED, "lot days x %.0f%% funded x %.2f%%"
               % (100 * share, 100 * rate))


# ================================================================== prices
def last_closes(symbols):
    """{SYM: (close, date)} from the free history + NSE bhavcopy fill."""
    import broker_api as ba
    import daily_screener as ds
    fr = {}
    for x in symbols:
        try:
            f = ds.fetch_eod(x.lower())
        except Exception:
            f = None
        if f is not None and len(f):
            fr[x.lower()] = f
    try:
        ba.bhav_fill(fr, ds.last_expected_session())
    except Exception:
        pass
    return {x.upper(): (float(f["Close"].iloc[-1]), f.index[-1].date())
            for x, f in fr.items()}


def quotes(sess, symbols):
    """{SYM: (price, status, source)}: live = VERIFIED, last close =
    ESTIMATED (with its date), none = missing."""
    import broker_api as ba
    out, live = {}, {}
    try:
        live = ba.live_prices(sess, symbols) if symbols else {}
    except Exception as e:
        print("! live price nahi mila (%s) -- last close use hoga (Dhan Data "
              "API active nahi?)" % type(e).__name__)
    for s in symbols:
        if _finite(live.get(s)) and live[s] > 0:
            out[s] = (float(live[s]), VERIFIED, "live LTP")
    miss = [s for s in symbols if s not in out]
    if miss:
        for s, (c, d) in last_closes(miss).items():
            if s in miss and _finite(c) and c > 0:
                out[s] = (c, ESTIMATED, "last close %s" % d)
    return out


# ================================================================== build
def mtf_positions(sess):
    """{SYM: qty} of MTF rows in Dhan's positions API (product-tagged)."""
    import broker_api as ba
    pos = ba._call(sess, "GET", "/positions")
    pos = pos.get("data", pos) if isinstance(pos, dict) else pos
    out = {}
    for p in pos or []:
        prod = str(p.get("productType") or "").upper()
        q = _num(p.get("netQty"))
        if prod in ("MTF", "MARGIN") and q == q and q > 0:
            sym = re.sub(r"-(EQ|BE)$", "", str(p.get("tradingSymbol") or
                                              "").upper())
            out[sym] = out.get(sym, 0) + q
    return out


def reconcile(f, demat, demat_ok, current=None):
    """Open MTF lots vs demat qty. Dhan's demat qty is ALL products, so it
    can confirm 'not more than', never 'this much is MTF' (Codex F4).
    Returns (rows, use {sym: lots}) -- a stock is valued only when its MTF
    qty is consistent with the demat."""
    rows, use = [], {}
    for s in sorted(set(f["lots"]) | set(f["uncovered"])):
        lots = f["lots"].get(s, [])
        q = sum(x[1] for x in lots)
        dq = demat.get(s, {}).get("qty") if demat_ok else None
        if s in f["uncovered"]:
            st, note = UNKNOWN, ("sold %g more than bought since --from: "
                                 "older buys missing" % f["uncovered"][s])
        elif not demat_ok:
            st, note = UNKNOWN, "demat holdings / history could not be read"
        elif not dq:
            st, note = UNKNOWN, ("history says %g open but NOT in demat "
                                 "(sold / converted / transferred?)" % q)
        elif dq + 1e-9 < q:
            st, note = UNKNOWN, ("demat %g < MTF lots %g (partial sale / "
                                 "conversion not in history)" % (dq, q))
        elif dq > q + 1e-9:
            st, note = ESTIMATED, ("demat %g > MTF lots %g: rest = CNC or "
                                   "bought before --from" % (dq, q))
        else:
            st, note = VERIFIED, "MTF lots = demat qty"
        rows.append({"Symbol": s, "MTF qty (history)": q, "Demat qty": dq,
                     "Status": st, "Note": note})
        if q > 0 and st != UNKNOWN:
            use[s] = lots
    for s, q in sorted((current or {}).items()):
        if s not in f["lots"] and s not in f["uncovered"]:
            rows.append({"Symbol": s, "MTF qty (history)": 0,
                         "Demat qty": demat.get(s, {}).get("qty"),
                         "Status": UNKNOWN,
                         "Note": "broker shows %g MTF now but no MTF buy in "
                                 "the history (bought before --from?)" % q})
    if demat_ok:
        for s in sorted(demat):
            if s not in f["lots"] and s not in f["uncovered"] and \
                    s not in (current or {}):
                rows.append({"Symbol": s, "MTF qty (history)": 0,
                             "Demat qty": demat[s].get("qty"),
                             "Status": "NOT MTF",
                             "Note": "in demat, no MTF trade in the history "
                                     "-> not counted as MTF"})
    return rows, use


def open_table(use, px, today, share, rate, broker="DHAN"):
    """One row per open MTF stock, every money column with its status."""
    import journal
    rows = []
    for s, lots in sorted(use.items()):
        q = sum(x[1] for x in lots)
        cost = sum(x[1] * x[2] for x in lots)
        p = px.get(s)
        val = Num(q * p[0], p[1], p[2]) if p else Num(None, UNKNOWN,
                                                       "no price")
        pnl = total([val, Num(-cost)])
        intr = lot_interest(lots, share, rate, today)
        fee = Num(journal.fees(broker, "SELL", val.value)[0], ESTIMATED,
                  "rate card") if val.known else Num(None, UNKNOWN)
        rows.append({
            "Symbol": s, "Qty": q, "Avg cost": round(cost / q, 2),
            "Lots": len(lots), "First buy": lots[0][0],
            "Last buy": lots[-1][0], "Open cost (Rs)": round(cost, 2),
            "Price": p[0] if p else None, "Price source": p[2] if p else
            "UNKNOWN", "Value (Rs)": val, "Gross P&L (Rs)": pnl,
            "Gross P&L %": round(100 * pnl.value / cost, 2) if pnl.known
            and cost else None,
            "Interest est. (Rs)": intr, "Sell fees est. (Rs)": fee,
            "Buy charges (Rs)": round(sum(x[3] for x in lots), 2)})
    return rows


def money_cell(n):
    return n.value if isinstance(n, Num) and n.known else None


def flatten(rows):
    """Num cells -> value column + '<col> status' column for Excel."""
    out = []
    for r in rows:
        o = {}
        for k, v in r.items():
            if isinstance(v, Num):
                o[k] = money_cell(v)
                o[k + " status"] = v.status
            else:
                o[k] = v
        out.append(o)
    return pd.DataFrame(out)


def build(args, sess, today, frm):
    """All the numbers (no printing). Returns a dict of sections."""
    import broker_api as ba
    src = {}
    # 1. trade history (MTF product; blank product guessed only if no MTF)
    try:
        allt, meta = dhan_trades(sess, frm, today)
        src["trades"] = (VERIFIED if meta["complete"] else UNKNOWN,
                         "; ".join(meta["notes"]) or "%d trades" % len(allt))
    except Exception as e:
        allt = []
        src["trades"] = (UNKNOWN, "%s: %s" % (type(e).__name__, str(e)[:80]))
    prods = {}
    for t in allt:
        prods[t["product"] or "?"] = prods.get(t["product"] or "?", 0) + 1
    mtf = [t for t in allt if t["product"] in ("MTF", "MARGIN")]
    guessed = False
    if not mtf and any(not t["product"] for t in allt):
        mtf, guessed = [t for t in allt if not t["product"]], True
    f = fifo(mtf, today)
    if f["invalid"]:
        src["trades"] = (UNKNOWN, src["trades"][1] + "; %d MTF rows without "
                         "a valid time/qty/price" % f["invalid"])
    # 2. demat (all products) for reconciliation
    try:
        demat = {h["symbol"]: h for h in ba.holdings(sess)}
        demat_ok = True
    except Exception as e:
        demat, demat_ok = {}, False
        src["demat"] = (UNKNOWN, type(e).__name__)
    try:
        current = mtf_positions(sess)
    except Exception:
        current = {}
    rec, use = reconcile(f, demat, demat_ok and src["trades"][0] != UNKNOWN,
                         current)
    # an unreconciled MTF stock makes every open total UNKNOWN (no silent
    # omission, Codex F4)
    gap = [r["Symbol"] for r in rec if r["Status"] == UNKNOWN]
    if guessed:
        for r in rec:
            if r["Status"] == VERIFIED:
                r["Status"] = ESTIMATED
                r["Note"] += "; product blank in Dhan history, taken as MTF"
    # 3. ledger
    led = ledger_rows([])
    try:
        if args.ledger:
            led = read_ledger_file(os.path.expanduser(args.ledger))
            src["ledger"] = (VERIFIED, "file " + os.path.basename(args.ledger))
        else:
            led = dhan_ledger(sess, frm, today)
            src["ledger"] = (VERIFIED, "Dhan ledger API %s -> %s" % (frm,
                                                                     today))
    except Exception as e:
        src["ledger"] = (UNKNOWN, "%s: %s" % (type(e).__name__, str(e)[:80]))
    led_ok = src["ledger"][0] != UNKNOWN
    # ledger still charging MTF interest lately but no open MTF lot found
    # -> the inventory is incomplete, never 'no MTF position'
    if led_ok and not use and not gap:
        ends = [p[1] for p in interest_periods(led) if p[1]]
        if ends and (today - max(ends)).days <= 10:
            gap.append("(ledger)")
            rec.append({"Symbol": "?", "MTF qty (history)": 0,
                        "Demat qty": None, "Status": UNKNOWN,
                        "Note": "MTF interest charged till %s but no open "
                                "MTF lot found in the trade history"
                                % max(ends)})
    ch = charges(led) if led_ok else {}
    paid = ch.get("MTF interest", Num(0.0, VERIFIED, "no MTF interest rows")) \
        if led_ok else Num(None, UNKNOWN, "ledger not read")
    avg_bal, per_day, per_txt, per_end = avg_interest_balance(led, args.rate) \
        if led_ok else (None, None, "", None)
    # 4. prices + open table
    px = quotes(sess, sorted(use))
    open_cost = sum(x[1] * x[2] for L in use.values() for x in L)
    loan = Num(args.loan, VERIFIED, "typed (--loan)") if args.loan is not None \
        else Num(None, UNKNOWN, "current MTF loan not given (--loan)")
    share = (loan.value / open_cost) if loan.known and open_cost > 0 and \
        not gap else None
    if share is not None and share > 1:
        share = None
        loan = Num(None, UNKNOWN, "--loan is more than the open MTF cost")
    rows = open_table(use, px, today, share, args.rate)
    # 5. totals per scope
    hole = [Num(None, UNKNOWN, "unreconciled: " + ", ".join(gap))] if gap \
        else []
    val = total([r["Value (Rs)"] for r in rows] + hole)
    gross = total([r["Gross P&L (Rs)"] for r in rows] + hole)
    fees = total([r["Sell fees est. (Rs)"] for r in rows] + hole)
    intr_open = total([r["Interest est. (Rs)"] for r in rows] + hole)
    buy_chg = Num(sum(r["Buy charges (Rs)"] for r in rows), f["charges"].status)
    if args.unpaid_interest is not None:
        unpaid = Num(args.unpaid_interest, VERIFIED, "typed")
    elif not rows and not gap:
        unpaid = Num(0.0, VERIFIED, "no open MTF position")
    elif per_day is not None and per_end is not None:
        days = max(0, (today - per_end).days) + 1   # + ~T+1 settlement day
        unpaid = Num(round(per_day * days, 2), ESTIMATED,
                     "%d days x last Rs %.2f/day since %s" % (days, per_day,
                                                              per_end))
    else:
        unpaid = Num(None, UNKNOWN, "no interest rate history")
    own = Num(open_cost - loan.value, VERIFIED, "open cost - loan") \
        if loan.known and not gap else Num(None, UNKNOWN,
                                           "needs --loan + full inventory")
    exit_cash = total([val, -loan, -unpaid, -fees],
                      "value - loan - unpaid interest - sell fees")
    open_pnl = total([gross, -intr_open, -fees, -buy_chg],
                     "open lots: price - lot interest est. - sell fees - "
                     "buy charges")
    period = total([f["realised"], gross, -paid, -unpaid, -f["charges"],
                    -fees], "realised + open price - ALL MTF interest - "
                   "unpaid est. - MTF trade fees - sell fees")
    init_cash = Num(args.own_cash, VERIFIED, "typed (--own-cash)") \
        if args.own_cash is not None else Num(None, UNKNOWN,
                                              "needs --own-cash")
    roi = Num(round(100 * open_pnl.value / init_cash.value, 2),
              open_pnl.status, "% of initial own cash") \
        if open_pnl.known and init_cash.known and init_cash.value > 0 \
        else Num(None, UNKNOWN, "needs open P&L + --own-cash")
    unalloc = {k: v for k, v in ch.items() if k != "MTF interest"}
    add, wd = money_in_out(led) if led_ok else (None, None)
    essential_ok = all(src.get(k, (VERIFIED,))[0] != UNKNOWN
                       for k in ("trades", "ledger", "demat"))
    return {"src": src, "prods": prods, "guessed": guessed, "mtf": mtf,
            "fifo": f, "rec": rec, "rows": rows, "led": led, "ch": ch,
            "paid": paid, "avg": (avg_bal, per_day, per_txt), "loan": loan,
            "own": own, "val": val, "gross": gross, "fees": fees,
            "intr_open": intr_open, "unpaid": unpaid, "exit": exit_cash,
            "open_pnl": open_pnl, "period": period, "init_cash": init_cash,
            "roi": roi, "unalloc": unalloc, "money": (add, wd),
            "closing": closing_balance(led) if led_ok else None,
            "open_cost": open_cost, "ok": essential_ok}


# ================================================================== main
def line(label, n, note=""):
    st = n.status if isinstance(n, Num) else ""
    nt = note or (n.note if isinstance(n, Num) else "")
    shown = ("%.2f%%" % n.value if n.known else rs(n)) if \
        label.endswith("%") and isinstance(n, Num) else rs(n)
    print("%-44s %26s  %-9s %s" % (label, shown, st, nt))
    return {"Item": label.strip(), "Rs": money_cell(n) if isinstance(n, Num)
            else n, "Status": st, "Note": nt}


def main():
    ap = argparse.ArgumentParser(description="MTF hisaab with status")
    ap.add_argument("--from", dest="frm", default="2024-04-01",
                    help="start: before your FIRST MTF buy (YYYY-MM-DD)")
    ap.add_argument("--ledger", help="downloaded Dhan ledger (xlsx/csv)")
    ap.add_argument("--rate", type=float, default=MTF_RATE,
                    help="MTF interest per year as a fraction (0.1249)")
    ap.add_argument("--loan", type=float, help="current MTF funded amount "
                    "from the Dhan app (Rs)")
    ap.add_argument("--unpaid-interest", type=float,
                    help="interest accrued but not yet debited (Rs)")
    ap.add_argument("--own-cash", type=float,
                    help="your own cash put into the open MTF lots (Rs)")
    a = ap.parse_args()
    if 1 < a.rate <= 100:
        print("  --rate %.2f read as %.2f%% -> %.4f" % (a.rate, a.rate,
                                                       a.rate / 100))
        a.rate = a.rate / 100
    if not (_finite(a.rate) and 0 <= a.rate < 1):
        print("--rate must be a fraction like 0.1249")
        return 1
    for k in ("loan", "unpaid_interest", "own_cash"):
        v = getattr(a, k)
        if v is not None and (not _finite(v) or v < 0):
            print("--%s must be a number >= 0" % k.replace("_", "-"))
            return 1
    today = dt.date.today()
    frm = parse_date(a.frm)
    if not frm or frm > today:
        print("--from must be a past date YYYY-MM-DD")
        return 1
    import account
    acc = account.activate()
    if not acc.token_ok:
        print("Token expire hai -- token.txt mein naya token daalo.")
        return 1
    sess = acc.session
    if sess.broker != "DHAN":
        print("Ye check abhi sirf Dhan ke liye hai (account: %s)." % sess.broker)
        return 1
    R = build(a, sess, today, frm)
    f = R["fifo"]

    print("\n==== MTF HISAAB  %s  %s  %s ====" % (
        acc.label, today, "" if R["ok"] else "** INCOMPLETE **"))
    for k, (st, note) in sorted(R["src"].items()):
        print("  source %-7s %-9s %s" % (k, st, note))
    print("  trades by product: %s%s" % (", ".join(
        "%s %d" % kv for kv in sorted(R["prods"].items())) or "none",
        "  -> blank product taken as MTF (ESTIMATED)" if R["guessed"] else ""))
    if R["rows"]:
        t = flatten(R["rows"])
        print(t[["Symbol", "Qty", "Avg cost", "First buy", "Last buy",
                 "Price", "Price source", "Open cost (Rs)", "Value (Rs)",
                 "Gross P&L (Rs)", "Gross P&L %", "Interest est. (Rs)"]]
              .to_string(index=False))
    else:
        print("  (koi open MTF stock reconcile nahi hua -- Reconciliation "
              "dekho)")
    for r in R["rec"]:
        if r["Status"] != VERIFIED:
            print("  %-12s %-9s %s" % (r["Symbol"], r["Status"], r["Note"]))

    out_open, out_exit, out_period, out_acc = [], [], [], []
    print("\n-- OPEN MTF POSITIONS --")
    out_open.append(line("Open cost (lots)", Num(R["open_cost"])))
    out_open.append(line("Value now", R["val"]))
    out_open.append(line("Gross price P&L", R["gross"]))
    out_open.append(line("Interest est. on these lots", -R["intr_open"]))
    out_open.append(line("Net P&L of open lots", R["open_pnl"]))
    out_open.append(line("Own cash put in", R["init_cash"]))
    out_open.append(line("Return on initial own cash %", R["roi"],
                         "not annual; top-ups change it"))
    print("\n-- AGAR AAJ SAB BECHO (hypothetical, settlement nahi) --")
    out_exit.append(line("Value now", R["val"]))
    out_exit.append(line("Current MTF loan (Dhan ka paisa)", -R["loan"]))
    out_exit.append(line("Unpaid accrued interest", -R["unpaid"]))
    out_exit.append(line("Sell fees", -R["fees"]))
    out_exit.append(line("= Cash released", R["exit"]))
    out_exit.append(line("Own money in open lots", R["own"]))
    avg_bal, per_day, per_txt = R["avg"]
    print("\n-- MTF PERIOD (%s se aaj tak) --" % a.frm)
    out_period.append(line("MTF bought (history)", Num(f["bought"])))
    out_period.append(line("MTF sold (history)", Num(f["sold"])))
    out_period.append(line("Realised price P&L", f["realised"],
                           "matched part %s" % rs(f["matched"])))
    out_period.append(line("Open price P&L", R["gross"]))
    out_period.append(line("MTF interest debited (ALL, incl. closed)",
                           -R["paid"]))
    out_period.append(line("Unpaid accrued interest", -R["unpaid"]))
    out_period.append(line("MTF trade fees (history)", -f["charges"]))
    out_period.append(line("Sell fees (open lots)", -R["fees"]))
    out_period.append(line("= MTF period economic P&L", R["period"]))
    if per_day is not None:
        print("  diagnostic: last interest %s = Rs %.2f/day -> AVERAGE "
              "interest-bearing balance ~%s at %.2f%% (NOT today's loan)"
              % (per_txt, per_day, rs(avg_bal), 100 * a.rate))
    print("\n-- ACCOUNT-WIDE / UNALLOCATED (MTF result mein NAHI jode) --")
    for k, v in sorted(R["unalloc"].items()):
        out_acc.append(line(k, -v))
    add, wd = R["money"]
    if add is not None:
        out_acc.append(line("Money added (ledger rows)", Num(add)))
        out_acc.append(line("Money withdrawn (ledger rows)", Num(-wd)))
    if R["closing"] is not None:
        out_acc.append(line("Ledger closing balance", Num(R["closing"])))
    need = []
    if not R["loan"].known:
        need.append("--loan <Dhan app ka MTF funded amount>")
    if not R["init_cash"].known:
        need.append("--own-cash <apna paisa jo in stocks mein laga>")
    if f["uncovered"]:
        need.append("--from <pehle MTF buy se pehle ki date>")
    if need:
        print("\nUNKNOWN pakka karne ke liye: python3 mtf_check.py "
              + " ".join(need))

    os.makedirs(acc.reports, exist_ok=True)
    out = os.path.join(acc.reports, "MTF_Check_%s.xlsx" % today)
    with pd.ExcelWriter(out) as w:
        pd.DataFrame(out_open).to_excel(w, sheet_name="MTF_Open_Summary",
                                        index=False)
        flatten(R["rows"]).to_excel(w, sheet_name="MTF_Open", index=False)
        pd.DataFrame(out_exit).to_excel(w, sheet_name="MTF_Exit_Estimate",
                                        index=False)
        pd.DataFrame(out_period).to_excel(w, sheet_name="MTF_Period",
                                          index=False)
        src = pd.DataFrame([{"Symbol": "source " + k, "Status": v[0],
                             "Note": v[1]} for k, v in sorted(R["src"].items())])
        pd.concat([src, pd.DataFrame(R["rec"]), pd.DataFrame(out_acc)],
                  ignore_index=True).to_excel(w, sheet_name="Reconciliation",
                                              index=False)
        pd.DataFrame([{k: v for k, v in t.items() if k != "ts"}
                      for t in R["mtf"]]).to_excel(w, sheet_name="MTF_Trades",
                                                   index=False)
        if len(R["led"]):
            R["led"].to_excel(w, sheet_name="Ledger", index=False)
    print("\nExcel: %s" % out)
    print("READ-ONLY: koi order nahi gaya. Exact settlement sirf asli sell + "
          "contract note + ledger se.")
    return 0 if R["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
