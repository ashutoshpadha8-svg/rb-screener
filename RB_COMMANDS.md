# RB_Screener — saari commands (26 Sep 2026)

Sab kuch `~/Desktop/RB_Screener` mein. Terminal (zsh) mein chalao.

---

## 1. Shortcuts (ek baar setup)

Pehle se hain:
```
rbscan    = daily_screener -> momentum_screener -> fundamentals  (Excel banti hai)
rbtrack   = Excel ke Action (BUY / PAPER ...) -> order / split.csv
rbsync    = agli subah asli fill prices
rbpos     = positions ka HOLD / EXIT report
```

Naye 2 jodne ke liye (ek baar):
```
echo "alias rbtoken='open -e ~/Desktop/RB_Screener/token.txt'" >> ~/.zshrc && echo "alias rbcheck='python3 ~/Desktop/RB_Screener/broker_api.py check'" >> ~/.zshrc && source ~/.zshrc
```

Saare shortcuts dekhne ke liye:
```
alias | grep rb
```

---

## 2. Roz ka routine

| Kab | Command | Kya karna hai |
|---|---|---|
| Subah / shaam | `rbtoken` | Dhan web se naya token paste, Cmd+S |
| | `rbcheck` | Account + funds + 1 price (koi order nahi) |
| | `rbscan` | Excel banegi |
| | `open ~/Desktop/RB_Screener/accounts/DHAN_1100120973/reports/` | Excel kholo |
| | (Excel) | Strategy_Comparison -> Action dropdown: BUY / BUY MTF / PAPER / PAPER MTF / WATCH -> save + close |
| 15:30 ke baad | `rbtrack --dry-run` | Pehle dekho kya hoga (kuch nahi bhejta) |
| 15:30 ke baad | `rbtrack` | Asli (BUY pe YES type karna padega) |
| Agli subah 9:15 ke baad | `rbsync` | Asli fill price split.csv mein |
| Kabhi bhi | `rbpos` | HOLD / EXIT report + news |

Momentum: sirf mahine ke pehle trading din buy. Rank 40 se neeche jaaye to SELL (khud Dhan app mein).
Sell kabhi automatic nahi hai.

---

## 3. rbtrack ke options

```
rbtrack --dry-run      # sirf dikhata hai, kuch nahi bhejta / likhta
rbtrack --no-orders    # BUY rows split.csv mein, order khud app se
rbtrack --limit        # MARKET ki jagah LIMIT (last price + 2%)
rbtrack --file PATH    # koi aur report
rbsync                 # = rbtrack --sync
```

Pehla asli order: **1 row, 1 share**, phir Dhan order book check.

---

## 4. token.txt ke format

Kholne ke liye: `rbtoken`

**Dhan**
```
Broker: DHAN
Client ID: 1100120973
Name: Ashutosh
Token: <Dhan web wala token, isi line pe>
```
Sirf token paste (Cmd+A, Cmd+V) bhi chalta hai — Dhan token mein ID hoti hai.

**Angel One** (ek baar bharo, roz kuch nahi)
```
Broker: ANGEL
Client ID: <Angel client code>
Name: Ashutosh Angel
Token: AUTO
API Key: <smartapi.angelone.in wali key>
MPIN: <4-digit MPIN>
TOTP Secret: <Enable TOTP wala lamba text code>
```

**Zerodha**
```
Broker: ZERODHA
Client ID: <Zerodha user id, jaise AB1234>
Name: Ashutosh Kite
Token: -
API Key: <Kite Connect key>
API Secret: <Kite Connect secret>
```
Roz:
```
python3 ~/Desktop/RB_Screener/broker_api.py zerodha-url
python3 ~/Desktop/RB_Screener/broker_api.py zerodha-login <request_token>
```

**Kabhi mat karna:** token / MPIN / TOTP / API key ka screenshot ya copy kisi ko.

---

## 5. Account commands

```
python3 ~/Desktop/RB_Screener/account.py                    # active + baaki accounts
python3 ~/Desktop/RB_Screener/account.py --name "Naya Naam" # naam badlo
python3 ~/Desktop/RB_Screener/broker_api.py check           # = rbcheck
ls ~/Desktop/RB_Screener/accounts/                          # saare account folders
open ~/Desktop/RB_Screener/accounts/                        # Finder mein
```

Account badalna = token.txt mein us account ki lines. Har account ki files alag:
`accounts/<BROKER>_<ID>/data/split.csv` aur `accounts/<BROKER>_<ID>/reports/`

---

## 6. Nayi files lagana (jab Claude files de)

```
mv -f ~/Downloads/<file1>.py ~/Downloads/<file2>.py ~/Desktop/RB_Screener/
```
`mv -f` = purani replace, Downloads saaf (koi "(1)" copy nahi).

Downloads mein bachi screener files saaf karna:
```
find ~/Downloads -maxdepth 1 \( -name '*screener*.py' -o -name 'account*.py' -o -name 'broker_api*.py' -o -name '*tracker*.py' -o -name 'fundamentals*.py' -o -name 'CLAUDE*.md' \) -print -delete
```

---

## 7. Alag se chalana (bina shortcut)

```
python3 ~/Desktop/RB_Screener/daily_screener.py
python3 ~/Desktop/RB_Screener/momentum_screener.py
python3 ~/Desktop/RB_Screener/fundamentals.py
python3 ~/Desktop/RB_Screener/fundamentals.py --symbols TCS,INFY   # sirf ye stocks
python3 ~/Desktop/RB_Screener/position_tracker.py --no-news
```

---

## 8. Kuch galat ho to

| Dikhe | Matlab / kya karo |
|---|---|
| `NO ACTIVE ACCOUNT` | token.txt khaali / galat -> `rbtoken`, sahi lines |
| `does not match the token` | Client ID aur token alag account ke -> sahi token daalo |
| `HTTP 401` / `DH-901` | Token expire -> naya token |
| `Market is open` | rbtrack 15:30 ke baad chalao |
| `Not enough funds` | Dhan mein paise nahi -> PAPER use karo |
| `NotOpenSSLWarning` | Ignore, kuch nahi bigadta |
| Excel `_fund.xlsx` bani | Excel khuli thi -> band karke rbscan phir |

Error aaye to aakhri 15 lines Claude ko paste karo (token / keys ke bina).
