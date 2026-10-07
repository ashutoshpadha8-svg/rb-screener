#!/usr/bin/env python3
"""
rb  --  THE daily command (everything that does NOT place an order)
===================================================================

  1. token check     Dhan token expired / token.txt missing -> opens
                     token.txt for you and stops (paste, Cmd+S, run rb again)
  2. fills           real prices of yesterday's AMOs      (rbtrack --sync)
  3. master scan     only if today's scan is not done yet (rb_scan.py)
  4. portfolio       Holdings, Journal, Actions, Rebalance ... + Drive copy
                     (portfolio.py)
  5. EMA screener    EMA 9/21 cross list + Watchlist_EMA.txt, once per
                     session (ema_screener.py; info only, never stops rb)

Orders are ONLY placed by `rbtrack` (after you picked Actions) -- on purpose,
money never moves from rb.

  rb               normal
  rb --force       scan again even if today's scan exists
  rb --no-news     faster (no Google News / NSE filings)
"""

import os
import sys
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def run(script, *args):
    print("\n" + "=" * 70 + "\n  %s %s\n" % (script, " ".join(args)) +
          "=" * 70)
    return subprocess.call([sys.executable, os.path.join(HERE, script)] +
                           list(args))


def open_token(why, alert=False):
    tok = os.path.join(HERE, "token.txt")
    print("\n!!! %s" % why)
    if alert:                       # phone knows too (auto-run, Mac unseen)
        try:
            import telegram_alert
            telegram_alert.send("⛔ rb ruk gaya: %s\nMac pe token.txt mein "
                                "naya token daalo, phir: rb" % why, quiet=True)
        except Exception:
            pass
    print("    token.txt khul raha hai: naya token 'Token:' line pe paste "
          "karo, Cmd+S, phir dobara: rb")
    if not os.path.exists(tok):
        with open(tok, "w") as f:
            f.write("Broker: DHAN\nClient ID: \nName: \nToken: \n")
    if sys.platform == "darwin":
        subprocess.call(["open", "-e", tok])
    sys.exit(1)


def main():
    a = sys.argv[1:]
    if "-h" in a or "--help" in a:
        print(__doc__)
        return
    if not os.path.exists(os.path.join(HERE, "token.txt")):
        open_token("token.txt nahi mila.")
    import account
    acc = account.activate()
    if not acc.token_ok:
        open_token("Token expire ho gaya (%s)." % acc.label, alert=True)
    import broker_api as ba                  # date OK != broker accepts it
    try:
        _, err = ba.available_funds(acc.session)
    except Exception as e:                   # network etc.: carry on
        err = ""
    e_ = (err or "").lower()
    if "token" in e_ or "dh-901" in e_ or "http 401" in e_ or "http 403" in e_:
        open_token("%s ne token REJECT kiya (%s). Date abhi valid thi -- "
                   "shayad naya token bana / logout hua. Naya token daalo."
                   % (acc.label, err[:80]), alert=True)
    if run("auto_tracker_update.py", "--sync") != 0:
        print("! fills sync failed -- continuing")
    r = run("rb_scan.py", *[x for x in a if x == "--force"])
    if r != 0:
        print("\n! scan stopped -- fix the error above, then run rb again.")
        sys.exit(r)
    r = run("portfolio.py", *[x for x in a if x in ("--no-news",
                                                    "--no-fund")])
    if r != 0:
        sys.exit(r)
    if run("ema_screener.py", *[x for x in a if x == "--force"]) != 0:
        print("! EMA screener failed -- portfolio is fine, carry on")
    print("\nEMA list: reports/EMA_Screener_*.xlsx | TradingView import: "
          "reports/Watchlist_EMA.txt")
    print("\nDONE. File kholo (Dashboard pehli tab). Kuch khareedna hai to "
          "Buy_Planner (doosri tab) bharo: budget + Pick BUY / MTF / WATCH, "
          "save + close, phir 15:30 ke baad: rbtrack")


if __name__ == "__main__":
    main()
