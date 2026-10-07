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

Run:  python3 mtf_check.py                (ledger + trades from 1 Apr 2025)
      python3 mtf_check.py --from 2024-04-01
      python3 mtf_check.py --funded 0.75  (funded share for the estimate)
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
    """Bucket of one ledger debit by its narration."""
    n = str(narration or "").lower()
    if "mtf" in n and ("int" in n or "interest" in n):
        return "MTF interest"
    if "interest" in n or "dpc" in n or "delayed payment" in n:
        return "Other interest"
    if "pledge" in n:
        return "Pledge charges"
    if re.search(r"\bdp\b|depository|cdsl|nsdl", n):
        return "DP charges"
    if re.search(r"bill|settlement|trade|stt|payin|pay-in|payout|pay-out|"
                 r"fund|transfer|upi|neft|imps|rtgs|bank|withdraw", n):
        return "_trade_or_money"          # buy/sell bills, money in/out
    return "Other charges"


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
    x = led[led["bucket"] != "_trade_or_money"]
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
    ap.add_argument("--from", dest="frm", default="2025-04-01")
    ap.add_argument("--ledger", help="downloaded Dhan ledger (xlsx/csv)")
    ap.add_argument("--funded", type=float, default=FUNDED)
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
        print("Abhi sirf Dhan ka ledger padh sakta hoon (account: %s). "
              "Positions + estimate phir bhi dikhaunga." % sess.broker)
    pos = []
    if sess.broker == "DHAN":
        try:
            pos = mtf_positions(sess)
        except Exception as e:
            print("! Dhan positions nahi mile (%s)" % type(e).__name__)
    try:
        demat = ba.holdings(sess)
    except Exception as e:
        demat = []
        print("! demat holdings nahi mile (%s)" % type(e).__name__)
    have = {p["symbol"] for p in pos}
    for h in demat:                    # MTF shown under holdings instead
        q = h.get("sellable_by_product", {}).get("MTF") or 0
        if q and h["symbol"] not in have:
            pos.append({"symbol": h["symbol"], "qty": q,
                        "avg": h["avg_price"]})
    cnc = [h["symbol"] for h in demat if h["symbol"] not in
           {p["symbol"] for p in pos}]
    if not pos:
        print("Is account mein koi open MTF position nahi mili (%s)."
              % acc.label)
    if cnc:
        print("Demat mein %d aur stocks MTF tag ke bina (CNC?): %s%s\n"
              "  -> agar inme MTF wale hain to mujhe batao." % (
                  len(cnc), ", ".join(cnc[:15]), " ..." if len(cnc) > 15
                  else ""))
    ltp = ba.live_prices(sess, [p["symbol"] for p in pos]) if pos else {}
    trades = ba.trades(sess, frm, today) if pos else []
    tab = analyse(pos, ltp, trades, today, a.funded, sess.broker)

    led, src = pd.DataFrame(), ""
    try:
        if a.ledger:
            led, src = read_ledger_file(os.path.expanduser(a.ledger)), \
                "file " + os.path.basename(a.ledger)
        elif sess.broker == "DHAN":
            led, src = dhan_ledger(sess, frm, today), "Dhan ledger API"
    except Exception as e:
        print("! ledger nahi mila (%s: %s) -- Dhan web se ledger download "
              "karke --ledger FILE do. Abhi sirf ESTIMATE." %
              (type(e).__name__, str(e)[:120]))
    ch = charges(led) if len(led) else {}

    print("\n==== MTF CHECK  %s  (%s)  %s ====" % (acc.label, sess.broker,
                                                   today))
    if len(tab):
        show = tab[["Symbol", "Qty", "Avg cost", "LTP", "P&L (Rs)", "P&L %",
                    "Held since (est.)", "Days", "Interest est. (Rs)"]]
        print(show.to_string(index=False))
    inv = tab["Invested (Rs)"].sum() if len(tab) else 0
    cur = tab["Current (Rs)"].sum() if len(tab) else 0
    pnl = tab["P&L (Rs)"].sum() if len(tab) else 0
    sell = tab["Sell cost today (Rs)"].sum() if len(tab) else 0
    est = tab["Interest est. (Rs)"].sum() if len(tab) else 0
    per_day = tab["Interest/day now (Rs)"].sum() if len(tab) else 0
    paid = ch.get("MTF interest", (None, 0))[0]
    other = sum(v[0] for k, v in ch.items() if k != "MTF interest")
    print("\nInvested (cost)        %s" % rs(inv))
    print("Current value          %s" % rs(cur))
    print("Price P&L (unrealised) %s  (%.1f%%)" % (rs(pnl),
                                                   100 * pnl / inv if inv else 0))
    if paid is not None:
        print("MTF interest PAID      %s  (%s, %s -> %s, %d entries)"
              % (rs(-paid), src, frm, today, ch["MTF interest"][1]))
    else:
        print("MTF interest PAID      ledger mein MTF interest nahi mila")
    print("MTF interest ESTIMATE  %s  (open positions, %.0f%% funded x "
          "12.49%%/yr x days; '?' days not counted)" % (rs(-est),
                                                         100 * a.funded))
    for k, (v, n) in sorted(ch.items()):
        if k != "MTF interest":
            print("%-22s %s  (%d entries)" % (k, rs(-v), n))
    print("Sell cost if sold today %s  (STT 0.1%% + exch + DP, estimate)"
          % rs(-sell))
    used = paid if paid is not None else est
    net = pnl - used - other - sell
    print("-" * 60)
    print("NET (P&L - interest%s - charges - sell cost)  %s"
          % (" PAID" if paid is not None else " est.", rs(net)))
    print("Interest chal raha hai: ~%s per din (~%s per mahina) jab tak hold "
          "karoge" % (rs(per_day), rs(per_day * 30)))
    if len(led):
        x = led[led["bucket"] != "_trade_or_money"]
        if len(x):
            print("\nLedger narrations used (check the buckets):")
            for (b, n), g in x.groupby(["bucket", "narration"]):
                print("  %-15s %-55s %s" % (b, str(n)[:55], rs(
                    g["debit"].sum() - g["credit"].sum())))

    os.makedirs(acc.reports, exist_ok=True)
    out = os.path.join(acc.reports, "MTF_Check_%s.xlsx" % today)
    summ = pd.DataFrame([
        ("Invested (cost)", inv), ("Current value", cur),
        ("Price P&L (unrealised)", pnl),
        ("MTF interest PAID (ledger)", -paid if paid is not None else None),
        ("MTF interest ESTIMATE", -est),
        ("Other charges (ledger)", -other), ("Sell cost today (est.)", -sell),
        ("NET", net), ("Interest per day now (est.)", -per_day),
        ("Ledger source", src or "none"), ("Period", "%s -> %s" % (frm, today))],
        columns=["Item", "Rs"])
    with pd.ExcelWriter(out) as w:
        summ.to_excel(w, sheet_name="Summary", index=False)
        tab.to_excel(w, sheet_name="Positions", index=False)
        if len(led):
            led[led["bucket"] != "_trade_or_money"].to_excel(
                w, sheet_name="Ledger_Charges", index=False)
    print("\nExcel: %s" % out)
    print("READ-ONLY: koi order nahi gaya.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
