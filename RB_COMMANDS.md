# RB_Screener — saari commands (26 Sep 2026, v2: master scan + portfolio)

Sab kuch `~/Desktop/RB_Screener` mein. Terminal (zsh) mein chalao.

---

## 1. Sirf 6 commands

| Command | Kya karta hai | Kitni baar |
|---|---|---|
| `rbtoken` | token.txt kholta hai (naya token paste) | roz (Dhan) |
| `rbcheck` | account + funds + 1 price check, koi order nahi | jab chaaho |
| `rbscan` | **MASTER scan** -- sab accounts ke liye ek file | din mein 1 baar (dobara chalao to skip) |
| `rbport` | **TUMHARA portfolio**: har holding ka trend, technical, fundamental, news, NSE filings (red flag), strategy test, HOLD/EXIT + wajah, rebalance, Actions | jab chaaho |
| `rbtrack` | Actions sheet ke BUY / PAPER -> order / split.csv | 15:30 ke baad |
| `rbsync` | agli subah asli fill prices | subah 9:15 ke baad |

Shortcuts ek baar set karo (purane rb* hata ke naye 6):
```
sed -i '' '/^alias rb/d' ~/.zshrc && cat >> ~/.zshrc <<'X'
alias rbtoken='open -e ~/Desktop/RB_Screener/token.txt'
alias rbcheck='python3 ~/Desktop/RB_Screener/broker_api.py check'
alias rbscan='python3 ~/Desktop/RB_Screener/rb_scan.py'
alias rbport='python3 ~/Desktop/RB_Screener/portfolio.py'
alias rbtrack='python3 ~/Desktop/RB_Screener/auto_tracker_update.py'
alias rbsync='python3 ~/Desktop/RB_Screener/auto_tracker_update.py --sync'
X
source ~/.zshrc
```
Check: `alias | grep rb` -> 6 lines.

---

## 1b. Files kahan banti hain

```
reports/RB_Screener_2026-09-26.xlsx                                  <- MASTER scan, din ki 1 file, sab accounts ki
accounts/DHAN_1100120973/reports/Portfolio_DHAN_Ashutosh_2026-09-26.xlsx  <- tumhara portfolio (Holdings, Rebalance, Actions)
accounts/DHAN_1100120973/data/split.csv                               <- tumhari positions, hamesha ek file
```
Kholne ke liye: `open ~/Desktop/RB_Screener/reports/`  aur  `open ~/Desktop/RB_Screener/accounts/`

---

## 2. Roz ka routine

1. `rbtoken` -> naya Dhan token -> Cmd+S
2. `rbscan` -> master scan (aaj ho chuka to kuch nahi karega). Best: 15:30 ke baad.
3. `rbport` -> Portfolio file: **Holdings** sheet (har stock ka HOLD / EXIT / SELL + WHY),
   **Rebalance** (momentum, sirf mahine ka 1st trading day), **Actions** (dropdown)
4. Actions sheet mein BUY / PAPER / WATCH chuno -> save + close
5. 15:30 ke baad: `rbtrack --dry-run`, phir `rbtrack`
6. Agli subah: `rbsync`

Options: `rbscan --force` (dobara scan), `rbport --no-news` (tez), `rbport --no-fund`.
WATCH chuna = koi order nahi; stock tumhari watchlist mein jaata hai aur `rbport` roz uska analysis dikhata hai
(STRONG / WEAK / AVOID). Hatana: `rbtrack --unwatch SYMBOL` (kai ho to SYM1,SYM2).
Sell kabhi automatic nahi -- broker app mein khud.

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
python3 ~/Desktop/RB_Screener/position_tracker.py --no-news    # purana leg-wise tracker (rbport ne jagah le li)
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
| Excel `_fund.xlsx` bani | Excel khuli thi -> band karke `rbscan --force` |
| `No master scan yet` | pehle `rbscan`, phir `rbport` |
| `Could not read the Actions sheet` | pehle `rbport` |

Error aaye to aakhri 15 lines Claude ko paste karo (token / keys ke bina).

---

## 9. Angel One API — naya account jodna (ek baar)

1. Apna IP nikaalo:  `curl -4 -s https://api.ipify.org ; echo`
2. **smartapi.angelone.in** -> Angel client ID se login -> **+ ADD APP**
   - App Name: `RB_Screener`
   - Redirect URL: `https://www.angelone.in`  (127.0.0.1 invalid batata hai)
   - Post back URL: khaali
   - Primary Static IP: step 1 wala number;  Secondary: khaali
   - Add -> table mein **API Key** (aankh icon se dikhegi)
3. Upar menu **Enable TOTP** -> client ID + MPIN + OTP -> QR ke saath **lamba text code**
   (A-Z, 2-7) copy karo = TOTP Secret. QR ko Google Authenticator mein bhi scan karo.
4. `rbtoken` -> token.txt:
```
Broker: ANGEL
Client ID: <Angel client code>
Name: <naam>
Token: AUTO
API Key: <step 2>
MPIN: <4-digit MPIN>
TOTP Secret: <step 3>
```
5. `rbcheck` -> "token confirmed for Angel One ..." + funds + RELIANCE price.

Yaad rakho: IP hafte mein sirf 1 baar badal sakte ho (SmartAPI page). Ghar ka IP badla -> Angel ORDERS
reject honge (prices/scan chalte rahenge). API key / MPIN / TOTP ka screenshot kabhi nahi.
