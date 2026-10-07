#!/usr/bin/env python3
"""
mtf_check.py -- MTF holdings: kitna loss, interest milake (7 Oct 2026, RB).
READ-ONLY: no order, nothing changed in split.csv / journal.

For the ACTIVE account (token.txt), per MTF position:
  avg cost, qty, LTP, unrealised P&L,
  first buy date (trade history, FIFO over the qty still held = estimate),
  interest ESTIMATE = cost x funded share x 12.49%/yr x days held.
Account level (Dhan only): the REAL money Dhan debited, from the ledger
(GET /v2/ledger): MTF interest, pledge / DP / other charges, by narration.
  NET = unrealised P&L - interest paid - charges - selling cost today.

Interest in the ledger also covers MTF positions already SOLD in the period,
so 'interest paid' can be more than the open positions caused.

If the Dhan ledger API fails: download the ledger in Dhan (web -> Reports ->
Ledger, Excel/CSV) and pass it:  python3 mtf_check.py --ledger ~/Downloads/x.xlsx

Run:  python3 mtf_check.py                (ledger + trades from 1 Apr 2024)
      python3 mtf_check.py --from 2023-04-01
v26 (RB's first real run: ledger OK, positions EMPTY): open MTF stocks now
come from the Dhan TRADE HISTORY (productType MTF, FIFO, charges per trade),
capped at the demat qty; Dhan's money = last weekly MTF interest / days x
365 / 12.49%; answers: bought / sold / realised, cost, Dhan's money, own
money, value, interest paid, charges, 'haath mein' if sold today, ACTUAL.
Output: terminal + accounts/<..>/reports/MTF_Check_<date>.xlsx
"""

import argparse
import datetime as dt
import os
import re
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

MTF_RATE = 0.1249          # Dhan MTF interest p.a. (estimate only)
FUNDED = 0.75              # Dhan pays ~75% at 4x; your margin = 25%


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


def funded_from_interest(led, rate=None):
    """Dhan's money in your MTF now ~ last MTF interest entry per day x 365
    / rate ('MTF Interest for Period 24/09/2026 To 30/09/2026' = 7 days).
    (funded Rs, per-day Rs, period text) or (None, None, '')."""
    rate = rate or MTF_RATE
    x = led[led["bucket"] == "MTF interest"].copy()
    if not len(x):
        return None, None, ""
    x = x.sort_values("date")
    for _, r in x[::-1].iterrows():
        m = re.findall(r"(\d{2})/(\d{2})/(\d{4})", str(r["narration"]))
        if len(m) >= 2 and r["debit"] > 0:
            a, b = (dt.date(int(y), int(mo), int(d)) for d, mo, y in m[:2])
            days = (b - a).days + 1
            if days > 0:
                per = r["debit"] / days
                return round(per * 365 / rate, 2), round(per, 2), \
                    "%s -> %s" % (a, b)
    return None, None, ""


def _num(v):
    try:
        return float(str(v).replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def ledger_rows(raw):
    """Rows (dicts) from the Dhan API or a downloaded file ->
    DataFrame date, narration, debit, credit, bucket."""
    d = pd.DataFrame(raw)
    if d.empty:
        return pd.DataFrame(columns=["date", "narration", "debit", "credit",
                                     "bucket"])
    cols = {c: str(c).lower().replace(" ", "") for c in d.columns}

    def pick(*keys):
        for c, lc in cols.items():
            if any(k in lc for k in keys):
                return d[c]
        return pd.Series([""] * len(d))
    nar = pick("narration", "description", "particular", "remark")
    vd = pick("voucherdesc", "vouchertype")
    out = pd.DataFrame({
        "date": pd.to_datetime(pick("voucherdate", "date"), errors="coerce",
                               dayfirst=False).dt.date,
        "narration": [("%s %s" % (a, b)).strip() if str(b).lower() not in
                      str(a).lower() else str(a)
                      for a, b in zip(nar.fillna(""), vd.fillna(""))],
        "debit": [_num(x) for x in pick("debit")],
        "credit": [_num(x) for x in pick("credit")]})
    out["bucket"] = [classify(x) for x in out["narration"]]
    return out


def read_ledger_file(path):
    if path.lower().endswith((".xlsx", ".xls")):
        raw = pd.read_excel(path)
        # downloaded statements often have a few title rows above the header
        for i in range(min(15, len(raw))):
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
    return ledger_rows(d or [])


def charges(led):
    """{bucket: (Rs debited - Rs reversed, count)}, trade/money rows out."""
    x = led[~led["bucket"].astype(str).str.startswith("_")]
    out = {}
    for b, g in x.groupby("bucket"):
        out[b] = (round(g["debit"].sum() - g["credit"].sum(), 2), len(g))
    return out


# ================================================================== positions
def mtf_positions(sess):
    """[{symbol, qty, avg}] of open MTF positions (Dhan positions API)."""
    import broker_api as ba
    pos = ba._call(sess, "GET", "/positions")
    pos = pos.get("data", pos) if isinstance(pos, dict) else pos
    out = []
    for p in pos or []:
        prod = str(p.get("productType") or p.get("producttype") or "").upper()
        q = _num(p.get("netQty") or p.get("netqty"))
        if prod not in ("MTF", "MARGIN") or q <= 0:
            continue
        sym = re.sub(r"-(EQ|BE)$", "", str(p.get("tradingSymbol") or
                                          p.get("tradingsymbol") or "").upper())
        avg = _num(p.get("costPrice") or p.get("buyAvg") or
                   p.get("buyavgprice"))
        out.append({"symbol": sym, "qty": q, "avg": avg})
    return out


def dhan_trades(sess, frm, to, chunk=90):
    """Every executed trade with its product + charges (Dhan trade history,
    GET /v2/trades/{from}/{to}/{page}, asked 90 days at a time).
    [{symbol, side, qty, price, date, product, charges}]."""
    import broker_api as ba
    ids = {}
    try:
        ids = {str(v["id"]): k for k, v in ba.symbol_map(sess).items()}
    except Exception:
        pass
    out, a = [], frm
    while a <= to:
        b = min(to, a + dt.timedelta(days=chunk - 1))
        for page in range(50):
            d = ba._call(sess, "GET", "/trades/%s/%s/%d" % (a, b, page))
            d = d.get("data", d) if isinstance(d, dict) else d
            if not d:
                break
            for x in d:
                if "EQ" not in str(x.get("exchangeSegment", "EQ")):
                    continue
                sid = str(x.get("securityId") or "")
                sym = ids.get(sid) or re.sub(r"-(EQ|BE)$", "", str(
                    x.get("tradingSymbol") or x.get("customSymbol") or
                    "").upper())
                tm = str(x.get("exchangeTime") or x.get("createTime") or "")
                m = re.search(r"(\d{4}-\d{2}-\d{2})", tm)
                out.append({
                    "symbol": sym, "side": str(x.get("transactionType"))
                    .upper(), "qty": _num(x.get("tradedQuantity")),
                    "price": _num(x.get("tradedPrice")),
                    "date": m.group(1) if m else b.isoformat(),
                    "product": str(x.get("productType") or "").upper(),
                    "charges": sum(_num(x.get(k)) for k in (
                        "sebiTax", "stt", "brokerageCharges", "serviceTax",
                        "exchangeTransactionCharges", "stampDuty"))})
        a = b + dt.timedelta(days=1)
    return [x for x in out if x["qty"] > 0 and x["price"] > 0]


def fifo(trades):
    """MTF trades -> totals + open lots, FIFO per stock.
    Returns dict: bought, sold (Rs), realised (Rs, price only), charges,
    open {sym: {qty, avg, first}}, short {sym: qty sold without a buy in
    the history = bought before --from}."""
    by, bought, sold, real, chg, short = {}, 0.0, 0.0, 0.0, 0.0, {}
    for x in sorted(trades, key=lambda t: (t["date"], t["side"] != "BUY")):
        lots = by.setdefault(x["symbol"], [])
        chg += x.get("charges", 0)
        if x["side"] == "BUY":
            lots.append([x["date"], x["qty"], x["price"]])
            bought += x["qty"] * x["price"]
        elif x["side"] == "SELL":
            sold += x["qty"] * x["price"]
            left = x["qty"]
            while left > 1e-9 and lots:
                take = min(left, lots[0][1])
                real += take * (x["price"] - lots[0][2])
                lots[0][1] -= take
                left -= take
                if lots[0][1] <= 1e-9:
                    lots.pop(0)
            if left > 1e-9:
                short[x["symbol"]] = short.get(x["symbol"], 0) + left
    opn = {}
    for sym, lots in by.items():
        q = sum(l[1] for l in lots)
        if q > 1e-9:
            opn[sym] = {"qty": q, "avg": sum(l[1] * l[2] for l in lots) / q,
                        "first": lots[0][0]}
    return {"bought": round(bought, 2), "sold": round(sold, 2),
            "realised": round(real, 2), "charges": round(chg, 2),
            "open": opn, "short": short}


def held_since(trades, symbol, qty):
    """Oldest buy date still held, FIFO: sells eat the oldest buys first.
    None when the trade history does not cover the qty (bought earlier)."""
    t = sorted([x for x in trades if x["symbol"] == symbol],
               key=lambda x: x["date"])
    lots = []
    for x in t:
        if x["side"] == "BUY":
            lots.append([x["date"], x["qty"]])
        elif x["side"] == "SELL":
            left = x["qty"]
            while left > 0 and lots:
                take = min(left, lots[0][1])
                lots[0][1] -= take
                left -= take
                if lots[0][1] <= 0:
                    lots.pop(0)
    have = sum(q for _, q in lots)
    if not lots or have + 1e-9 < qty:
        return None
    # the qty still held = the LAST `qty` shares bought
    need, first = qty, None
    for d, q in reversed(lots):
        first = d
        need -= q
        if need <= 0:
            break
    return first


def analyse(pos, ltp, trades, today, funded=FUNDED, broker="DHAN"):
    import journal
    rows = []
    for p in pos:
        px = ltp.get(p["symbol"])
        cost = p["qty"] * p["avg"]
        val = p["qty"] * px if px else None
        since = held_since(trades, p["symbol"], p["qty"])
        days = (today - dt.date.fromisoformat(since)).days if since else None
        intr = cost * funded * MTF_RATE * days / 365 if days else None
        sell = journal.fees(broker, "SELL", val)[0] if val else None
        pnl = val - cost if val is not None else None
        rows.append({
            "Symbol": p["symbol"], "Qty": p["qty"], "Avg cost": p["avg"],
            "LTP": px, "Invested (Rs)": round(cost, 2),
            "Current (Rs)": round(val, 2) if val is not None else None,
            "P&L (Rs)": round(pnl, 2) if pnl is not None else None,
            "P&L %": round(100 * pnl / cost, 2) if pnl is not None and cost
            else None,
            "Held since (est.)": since or "?", "Days": days,
            "Your margin ~ (Rs)": round(cost * (1 - funded), 2),
            "Dhan funded ~ (Rs)": round(cost * funded, 2),
            "Interest est. (Rs)": round(intr, 2) if intr is not None else None,
            "Interest/day now (Rs)": round(cost * funded * MTF_RATE / 365, 2),
            "Sell cost today (Rs)": sell,
            "Net after int+sell (Rs)": round(pnl - (intr or 0) - (sell or 0),
                                             2) if pnl is not None else None})
    return pd.DataFrame(rows)


def rs(x):
    return "-" if x is None or x != x else ("-Rs " if x < 0 else "Rs ") + \
        format(abs(int(round(x))), ",")


# ================================================================== main
def main():
    ap = argparse.ArgumentParser(description="MTF loss incl. interest")
    ap.add_argument("--from", dest="frm", default="2024-04-01",
                    help="start: before your FIRST MTF buy")
    ap.add_argument("--ledger", help="downloaded Dhan ledger (xlsx/csv)")
    ap.add_argument("--rate", type=float, default=MTF_RATE,
                    help="Dhan MTF interest per year (0.1249)")
    a = ap.parse_args()
    frm = dt.date.fromisoformat(a.frm)
    today = dt.date.today()
    import account
    import broker_api as ba
    acc = account.activate()
    if not acc.token_ok:
        print("Token expire hai -- token.txt mein naya token daalo, phir dobara.")
        return 1
    sess = acc.session
    if sess.broker != "DHAN":
        print("Ye check abhi sirf Dhan ke liye hai (account: %s)." % sess.broker)
        return 1

    # 1. every MTF trade since --from (product + charges per trade)
    try:
        allt = dhan_trades(sess, frm, today)
    except Exception as e:
        allt = []
        print("! trade history nahi mili (%s: %s)" % (type(e).__name__,
                                                    str(e)[:120]))
    prods = {}
    for x in allt:
        prods[x["product"] or "?"] = prods.get(x["product"] or "?", 0) + 1
    mtf = [x for x in allt if x["product"] in ("MTF", "MARGIN")]
    print("Trades %s -> %s: %d  (by product: %s)" % (frm, today, len(allt),
          ", ".join("%s %d" % kv for kv in sorted(prods.items())) or "none"))
    f = fifo(mtf)

    # 2. what the demat holds now (any product) -> cap the open MTF lots
    try:
        demat = {h["symbol"]: h for h in ba.holdings(sess)}
    except Exception as e:
        demat = {}
        print("! demat holdings nahi mile (%s)" % type(e).__name__)
    pos, gone = [], []
    for sym, o in sorted(f["open"].items()):
        held = demat.get(sym, {}).get("qty")
        if demat and not held:
            gone.append(sym)
            continue
        q = min(o["qty"], held) if held else o["qty"]
        pos.append({"symbol": sym, "qty": q, "avg": o["avg"]})
    if not pos:                       # no MTF trades: fall back to positions
        try:
            pos = mtf_positions(sess)
        except Exception:
            pass

    # 3. ledger: interest + charges actually debited
    led, src = pd.DataFrame(), ""
    try:
        if a.ledger:
            led, src = read_ledger_file(os.path.expanduser(a.ledger)), \
                "file " + os.path.basename(a.ledger)
        else:
            led, src = dhan_ledger(sess, frm, today), "Dhan ledger API"
    except Exception as e:
        print("! ledger nahi mila (%s: %s) -- Dhan web se ledger download "
              "karke --ledger FILE do." % (type(e).__name__, str(e)[:120]))
    ch = charges(led) if len(led) else {}
    paid = ch.get("MTF interest", (0.0, 0))[0]
    funded, per_day, per_txt = funded_from_interest(led, a.rate) \
        if len(led) else (None, None, "")

    # 4. per stock
    ltp = ba.live_prices(sess, [p["symbol"] for p in pos]) if pos else {}
    cost = sum(p["qty"] * p["avg"] for p in pos)
    share = min(1.0, funded / cost) if funded and cost else 0.75
    tab = analyse(pos, ltp, mtf, today, share, "DHAN")
    val = tab["Current (Rs)"].sum() if len(tab) else 0.0
    miss = [p["symbol"] for p in pos if not ltp.get(p["symbol"])]
    unreal = tab["P&L (Rs)"].sum() if len(tab) else 0.0
    sellc = tab["Sell cost today (Rs)"].sum() if len(tab) else 0.0
    loan = funded if funded is not None else cost * 0.75
    margin = cost - loan
    other = sum(v for k, (v, n) in ch.items()
                if k not in ("MTF interest", "Dividend (income)"))
    divi = -ch.get("Dividend (income)", (0.0, 0))[0]
    keep = val - sellc - loan
    actual = f["realised"] + unreal - paid - other - f["charges"] - sellc \
        + divi

    L = []
    def say(k, v, note=""):
        L.append((k, v, note))
        print("%-40s %14s  %s" % (k, rs(v) if isinstance(v, (int, float))
                                  else v, note))
    print("\n==== MTF HISAAB  %s  %s ====" % (acc.label, today))
    if len(tab):
        print(tab[["Symbol", "Qty", "Avg cost", "LTP", "Invested (Rs)",
                   "Current (Rs)", "P&L (Rs)", "P&L %", "Held since (est.)",
                   "Days"]].to_string(index=False))
    print()
    say("1. MTF mein kul kharida (shuru se)", f["bought"],
        "%d buy+sell trades since %s" % (len(mtf), frm))
    say("   MTF mein kul becha", f["sold"])
    say("   Bech chuke stocks ka P&L (price)", f["realised"])
    say("2. Abhi ke stocks ki cost (capital)", cost, "%d stocks" % len(pos))
    say("   Dhan ka paisa (margin mila) ~", loan,
        ("from last interest %s: Rs %.2f/din @ %.2f%%" %
         (per_txt, per_day, 100 * a.rate)) if funded is not None
        else "ESTIMATE 75% (no interest entry)")
    say("   Tumhara apna paisa laga ~", margin,
        "! Dhan's money > cost: that interest week also had stocks sold "
        "later, or history before --from is missing" if margin < 0 else "")
    say("3. Current value (aaj)", val, ("LTP missing: " + ", ".join(miss))
        if miss else "")
    say("   Abhi ke stocks ka P&L (price)", unreal)
    say("4. MTF interest PAY kiya (aaj tak)", -paid,
        "%s, %d entries" % (src or "no ledger",
                            ch.get("MTF interest", (0, 0))[1]))
    say("   Baaki charges (DP/pledge/margin int/...)", -other)
    say("   Trade charges (brokerage/STT/GST/stamp)", -f["charges"],
        "from the trade history")
    if divi:
        say("   Dividend mila", divi)
    say("5. Aaj sab becho -> bechne ka kharcha ~", -sellc)
    say("   Dhan ka paisa wapas", -loan)
    say("   TUMHARE HAATH MEIN AAYEGA ~", keep,
        "= current value - sell cost - Dhan ka paisa")
    print("-" * 70)
    say("6. ACTUAL LOSS / PROFIT (sab milake)", actual,
        "= realised + unrealised - interest - charges - sell cost + dividend")
    if per_day:
        print("Interest abhi bhi chal raha hai: ~%s/din, ~%s/mahina" % (
            rs(per_day), rs(per_day * 30)))
    cb = closing_balance(led) if len(led) else None
    add, wd = money_in_out(led) if len(led) else (0, 0)
    if add or wd:
        say("Cross-check: paise daale (ledger)", add)
        say("             paise nikaale (ledger)", -wd)
        if cb is not None:
            say("             ledger cash abhi", cb)
            say("  -> poore account ka net (all products)",
                keep + cb - (add - wd), "= haath mein + cash - (daale - "
                "nikaale); CNC trades bhi isme")
    if gone:
        print("! FIFO says still open but NOT in demat (converted/sold "
              "elsewhere?): %s" % ", ".join(gone))
    if f["short"]:
        print("! Sold more than bought since %s (bought earlier -> use an "
              "earlier --from): %s" % (frm, ", ".join(f["short"])))
    if len(led):
        x = led[~led["bucket"].astype(str).str.startswith("_")]
        mon = led[led["bucket"] == "_money"]
        print("\nLedger buckets (check):")
        for b, g in pd.concat([x, mon]).groupby("bucket"):
            print("  %-18s %4d rows  %s" % (b, len(g), rs(g["debit"].sum() -
                                                           g["credit"].sum())))

    os.makedirs(acc.reports, exist_ok=True)
    out = os.path.join(acc.reports, "MTF_Check_%s.xlsx" % today)
    with pd.ExcelWriter(out) as w:
        pd.DataFrame(L, columns=["Item", "Rs", "Note"]).to_excel(
            w, sheet_name="Hisaab", index=False)
        tab.to_excel(w, sheet_name="Positions", index=False)
        pd.DataFrame(mtf).to_excel(w, sheet_name="MTF_Trades", index=False)
        if len(led):
            led.to_excel(w, sheet_name="Ledger", index=False)
    print("\nExcel: %s" % out)
    print("READ-ONLY: koi order nahi gaya.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
