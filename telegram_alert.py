#!/usr/bin/env python3
"""
TELEGRAM ALERT  --  every account gets ONLY its own summary on its own phone
============================================================================

One bot for everybody. Each account (accounts/<BROKER>_<ID>/) is linked to ONE
Telegram chat. `rb` sends that account's summary to that chat only.

The bot only SENDS. It never reads commands and can never place an order.
Messages carry names, stocks and P&L -- never a token, key or client ID.

Setup (once):
  1. Telegram -> @BotFather -> /newbot -> copy the bot token
  2. python3 telegram_alert.py bot          (opens the file: paste the token
                                              on the 'Bot Token:' line, save)
  3. The person opens the bot in Telegram and sends  /start
  4. With THAT person's account active in token.txt:
        python3 telegram_alert.py link      (takes the /start of the last
                                              15 minutes, sends a test message)
  Check:   python3 telegram_alert.py test
  Unlink:  python3 telegram_alert.py unlink

Files: accounts/telegram_bot.txt (bot token, never printed / copied to Drive)
       accounts/<BROKER>_<ID>/telegram.json (chat id + first name)
"""

import os
import sys
import json
import time
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
BOT_FILE = os.path.join(HERE, "accounts", "telegram_bot.txt")
API = "https://api.telegram.org/bot%s/%s"
MAX = 3900                                  # Telegram limit is 4096 chars


def bot_token():
    try:
        for line in open(BOT_FILE):
            v = line.split(":", 1)[1] if line.lower().startswith("bot token") \
                else line
            v = v.strip()
            if ":" in v and len(v) > 30:            # 123456:ABC... format
                return v
    except (IOError, OSError, IndexError):
        pass
    return None


def _chat_file():
    import momentum_screener as ms           # routed by account.activate()
    return os.path.join(os.path.dirname(os.path.dirname(ms.SPLIT_FILE)),
                        "telegram.json")


def linked():
    try:
        with open(_chat_file()) as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return None


def _api(method, **params):
    import requests
    tok = bot_token()
    if not tok:
        raise RuntimeError("no bot token (python3 telegram_alert.py bot)")
    r = requests.post(API % (tok, method), data=params, timeout=20)
    j = r.json() if r.content else {}
    if not j.get("ok"):                       # never echo the URL (has token)
        raise RuntimeError("Telegram %s failed: %s"
                           % (method, j.get("description", r.status_code)))
    return j.get("result")


def send(text, quiet=False):
    """Send to the ACTIVE account's chat. Silent no-op when not set up."""
    who = linked()
    if not who or not bot_token():
        return False
    if len(text) > MAX:
        text = text[:MAX - 20] + "\n... (baaki file mein)"
    try:
        _api("sendMessage", chat_id=who["chat_id"], text=text,
             disable_web_page_preview="true")
        if not quiet:
            print("  Telegram alert sent to %s" % who.get("name", "chat"))
        return True
    except Exception as e:
        if not quiet:
            print("  ! Telegram alert failed (%s) -- file is fine." % e)
        return False


# ------------------------------------------------------------ the summary
def _pct(v):
    return "%+.1f%%" % v if v is not None and v == v else "n/a"


def _next_rebalance(today):
    import pandas as pd
    d = pd.Timestamp(today)
    for m in (0, 1):
        first = (d + pd.offsets.MonthBegin(m)) if m else \
            pd.Timestamp(d.year, d.month, 1)
        while first.weekday() >= 5:
            first += pd.Timedelta(days=1)
        if first >= d.normalize():
            return first.strftime("%a %d %b")
    return "-"


def summary(acc, today, hold, rebal, sip_rows, regime_red, trading, val,
            cost, news_on=True):
    name = getattr(acc, "name", "") or acc.broker
    L = ["📊 %s | %s" % (name, today)]
    if val:
        L.append("Value Rs %s | P&L %s" % (format(int(val), ","),
                                           _pct((val / cost - 1) * 100
                                                if cost else None)))
    own = [h for h in hold if h["Mode"] != "WATCH"]
    groups = [("🔴 EXIT", ("EXIT", "SELL")), ("🟠 SELL@REBAL", ("SELL@REBAL",)),
              ("🟡 WATCH", ("WATCH", "WEAK")), ("🟢 HOLD", ("HOLD", "KEEP")),
              ("🔵 SIP", ("SIP",))]
    for lab, keys in groups:
        xs = [h for h in own if h["Recommendation"] in keys]
        if xs:
            L.append("%s: %s" % (lab, ", ".join(
                "%s %s%s" % (h["Symbol"], _pct(h.get("P&L %")),
                             "" if h["Mode"] == "LIVE" else " (paper)")
                for h in xs)))
    if not own:
        L.append("(koi holding nahi)")
    # SIP
    for r in sip_rows or []:
        if r["Active"] == "YES" and not str(r["Next due"]).startswith("DONE"):
            L.append("💰 SIP %s Rs %s: %s" % (
                r["Symbol"], format(int(r["Amount per buy (Rs)"] or 0), ","),
                r["Next due"]))
    # rebalance (LIVE)
    rr = [x for x in rebal if x["Mode"] == "LIVE"]
    if rr:
        sells = [x["Symbol"] for x in rr if x["Section"] == "SELL"]
        buys = [x["Symbol"] for x in rr if x["Section"] == "BUY"
                and "fills" in x.get("Note", "")]
        L.append("🔄 Rebalance %s: SELL %s | BUY %d: %s" % (
            _next_rebalance(today), ", ".join(sells) or "-", len(buys),
            ", ".join(buys) or "-"))
    # news red flags (holdings + watchlist)
    if news_on:
        flags = [h for h in hold if h.get("Red flag")]
        for h in flags:
            first = (h.get("NSE filings (30d)") or "").split(" || ")[0]
            L.append("🚩 %s: %s" % (h["Symbol"], first[:120]))
        if not flags:
            L.append("🚩 Red flags: koi nahi (NSE filings 30 din)")
    else:
        L.append("🚩 Red flags: check nahi hua (--no-news)")
    L.append("%s | TRADING: %s" % ("⚠️ Market RED" if regime_red
                                    else "✅ Market GREEN", trading))
    L.append("(info only -- orders sirf rbtrack + YES se)")
    return "\n".join(L)


# ------------------------------------------------------------ CLI
def _cli():
    a = sys.argv[1:]
    cmd = a[0] if a else "help"
    if cmd == "bot":
        os.makedirs(os.path.dirname(BOT_FILE), exist_ok=True)
        if not os.path.exists(BOT_FILE):
            with open(BOT_FILE, "w") as f:
                f.write("Bot Token: \n")
        os.chmod(BOT_FILE, 0o600)
        print("Paste the @BotFather token on the 'Bot Token:' line, Cmd+S.")
        if sys.platform == "darwin":
            subprocess.call(["open", "-e", BOT_FILE])
        return
    import account
    acc = account.activate()
    if cmd == "link":
        ups = _api("getUpdates") or []
        now = time.time()
        starts = [u["message"] for u in ups if u.get("message")
                  and str(u["message"].get("text", "")).startswith("/start")
                  and now - u["message"].get("date", 0) < 15 * 60]
        if not starts:
            sys.exit("No /start in the last 15 minutes. Open the bot in "
                     "Telegram on that person's phone, send /start, run again.")
        m = starts[-1]
        who = {"chat_id": m["chat"]["id"],
               "name": m["chat"].get("first_name") or m["chat"].get("title")
               or "chat"}
        with open(_chat_file(), "w") as f:
            json.dump(who, f)
        os.chmod(_chat_file(), 0o600)
        print("Linked %s -> Telegram user '%s'." % (acc.label, who["name"]))
        send("✅ RB Screener alerts ON for %s. Sirf is account ka summary "
             "yahan aayega." % (acc.name or acc.broker))
    elif cmd == "test":
        who = linked()
        if not who:
            sys.exit("This account is not linked (python3 telegram_alert.py "
                     "link).")
        send("🧪 Test message for %s." % (acc.name or acc.broker))
    elif cmd == "unlink":
        try:
            os.remove(_chat_file())
            print("Unlinked %s." % acc.label)
        except OSError:
            print("Was not linked.")
    else:
        print(__doc__)


if __name__ == "__main__":
    _cli()
