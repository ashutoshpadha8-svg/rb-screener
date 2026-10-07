# RB_Screener — saari commands (27 Sep 2026, v3: sirf 2 commands)

Sab kuch `~/RB_Screener` mein. Terminal (zsh) mein chalao.

---

## 1. Sirf 2 commands

| Command | Kya karta hai | Kab |
|---|---|---|
| `rb` | **Roz ka sab kuch** (koi order nahi): token check (expire ho to token.txt khud khulta hai) -> kal ke orders ke asli fill prices -> master scan (aaj ho chuka to skip) -> Portfolio file (Dashboard, Holdings cards, Journal, Actions...) + Google Drive copy | roz, best 15:30 ke baad |
| `rbtrack` | **Order bhejta hai**: Actions sheet ke BUY / BUY MTF / WATCH + jo **SIP** aaj due hai | 15:30 ke baad |

Shortcuts ek baar set karo (purane rb* hata ke naye 2):
```
sed -i '' '/^alias rb/d' ~/.zshrc && cat >> ~/.zshrc <<'X'
alias rb='python3 ~/RB_Screener/rb.py'
alias rbtrack='python3 ~/RB_Screener/auto_tracker_update.py'
alias rbsig='python3 ~/RB_Screener/signal_tracker.py'
alias rbema='python3 ~/RB_Screener/ema_screener.py'
X
source ~/.zshrc
```
Check: `alias | grep rb` -> 4 lines (rb, rbema, rbsig, rbtrack).

Options (kabhi kabhi):
```
rb --force            scan dobara (aaj ka scan hone ke baad bhi)
rb --no-news          tez (news / NSE filings nahi)
rbtrack --dry-run     sirf dikhata hai, kuch nahi bhejta
rbtrack --sold SYMBOL PRICE --date 2026-11-12    sell journal mein haath se (agar apne aap na pakda)
rbtrack --clear-paper                            purane PAPER trades hatao (PAPER band hai, 27 Sep)
rbtrack --unwatch SYM1,SYM2                      watchlist se hatao
python3 ~/RB_Screener/broker_api.py check        account + funds + 1 price (purana rbcheck)
```
Purani commands (rbscan, rbport, rbsync, rbcheck, rbtoken) ab `rb` ke andar hain.

---

## 1b. Files kahan banti hain

```
reports/RB_Screener_2026-09-26.xlsx                                  <- MASTER scan, din ki 1 file, sab accounts ki
accounts/DHAN_1100120973/reports/Portfolio_DHAN_Ashutosh.xlsx  <- tumhara portfolio: EK hi file, har rb pe update (purani: data/old_reports/)
accounts/DHAN_1100120973/data/split.csv                               <- tumhari positions, hamesha ek file
```
Kholne ke liye: `open ~/RB_Screener/reports/`  aur  `open ~/RB_Screener/accounts/`

**Roz sirf ek file kholo: Portfolio_...xlsx.** Usmein sab hai (tabs is order mein):
Dashboard (summary + aaj kya karna hai + sheet links) | Holdings | Actions | Rebalance | Watchlist |
Swing | Investing | Momentum_Top20 | Fundamentals (ye 4 master scan se copy hoti hain).
Master scan file (reports/RB_Screener_...) sirf data ke liye banti rehti hai, kholne ki zarurat nahi.
Dhyan: scan dobara chahiye to `rb --force`.

---

## 2. Roz ka routine

1. `rb` (15:30 ke baad best). Dhan token expire ho to token.txt khud khulega: naya token paste, Cmd+S, `rb` dobara.
2. File kholo (Mac pe ya Google Sheets: My Drive/RB_Reports/...). Pehli tab **Dashboard**.
   **Holdings** = har stock ek card (rang = ACTION). **Journal** = har trade ka hisaab (fees, dividend, tax ke baad).
3. Kuch khareedna ho: **Actions** sheet mein Action (BUY / BUY MTF / WATCH) + Amount (Rs) (khaali = Rs 10,000). Qty khud.
   Regular buying: **SIP** sheet (neeche section 2b).
4. `rbtrack --dry-run`, phir `rbtrack`.
5. Becha (broker app se)? Kuch nahi karna: agle `rb` pe journal khud pakdega (Dhan). Angel/Zerodha: usi din shaam `rb` chalao.
   Na pakde to: `rbtrack --sold SYMBOL PRICE --date YYYY-MM-DD`.

WATCH = koi order nahi; stock watchlist mein, `rb` roz analysis dikhata hai. Hatana: `rbtrack --unwatch SYMBOL`.
Sell kabhi automatic nahi -- broker app mein khud.

---

## 2a. TRADING switch + Sell sheet (har account ka alag)

**Dashboard, cell B2: `TRADING (buy + sell)` = ON / OFF** (default OFF)
- **OFF**: `rbtrack` koi order nahi bhejta: na BUY, na SIP, na SELL. (WATCH chalta hai.)
- **ON**: BUY / SIP / SELL orders jaate hain, par pehle `YES` / `YES MTF` / `YES SELL` type karna padta hai.

**Sell sheet**: jin stocks pe aaj rule ne bechne ko kaha:
| Sell? default | Kab |
|---|---|
| YES (agar TRADING ON) | EXIT (swing 20% stop / 40w MA, investing Stage 4) |
| YES (sirf mahine ke aakhri weekday / 1st trading day) | momentum SELL@REBAL (rank > 40) |
| NO (khud YES chuno to bikega) | bahar se khareeda stock, combined SELL (backtested nahi) |
| kabhi nahi | SIP stocks |
- Qty = sirf us strategy ka hissa jiska rule fire hua. Kisi ko rokna ho: Sell? = NO, save.
- `rbtrack` (15:30 ke baad) -> list dikhata hai -> `YES SELL` type -> agle din open pe MARKET sell. Agle `rb` pe journal khud band karta hai.
- Demat se bechne ke liye broker pe **DDPI / POA** chahiye (warna TPIN maangega aur API sell fail hogi).

---

## 2b. SIP (regular buying)

Portfolio file ki **SIP** tab mein peele columns bharo (ek row = ek plan):

| Symbol | Frequency | Day | Amount per buy (Rs) | Total capital (Rs) | Product | Active | Start date |
|---|---|---|---|---|---|---|---|
| NIFTYBEES | Monthly | 5 | 5000 | 60000 | BUY | YES | |
| TCS | Weekly | Mon | 2000 | 20000 | BUY | YES | |

- Day: Monthly = tarikh 1-28, Weekly = Mon..Fri, Daily = khaali.
- Amount = tumhara paisa har buy. BUY MTF = broker ka asli leverage x amount.
- Total capital khaali = koi limit nahi; poora lag gaya to plan "DONE".
- Save karo -> `rbtrack` (15:30 ke baad) jo due hai uska order lagata hai. Chhoota din usi mahine/hafte mein pakad leta hai.
- Rokna: Active = NO. Hatana: Symbol cell khaali.
- Har buy journal mein "SIP" ke naam se (fees, dividend, P&L). SIP stock pe koi sell rule nahi.
- Backtest (sip_backtest.py): seedhi monthly SIP ~ Nifty; weekly/daily se kuch extra nahi; single stock mein bura risk.

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
python3 ~/RB_Screener/broker_api.py zerodha-url
python3 ~/RB_Screener/broker_api.py zerodha-login <request_token>
```

**Kabhi mat karna:** token / MPIN / TOTP / API key ka screenshot ya copy kisi ko.

---

## 5. Account commands

```
python3 ~/RB_Screener/account.py                    # active + baaki accounts
python3 ~/RB_Screener/account.py --name "Naya Naam" # naam badlo
python3 ~/RB_Screener/broker_api.py check           # = rbcheck
ls ~/RB_Screener/accounts/                          # saare account folders
open ~/RB_Screener/accounts/                        # Finder mein
```

Account badalna = token.txt mein us account ki lines. Har account ki files alag:
`accounts/<BROKER>_<ID>/data/split.csv` aur `accounts/<BROKER>_<ID>/reports/`

---

## 6. Nayi files lagana (jab Claude files de)

```
mv -f ~/Downloads/<file1>.py ~/Downloads/<file2>.py ~/RB_Screener/
```
`mv -f` = purani replace, Downloads saaf (koi "(1)" copy nahi).

Downloads mein bachi screener files saaf karna:
```
find ~/Downloads -maxdepth 1 \( -name '*screener*.py' -o -name 'account*.py' -o -name 'broker_api*.py' -o -name '*tracker*.py' -o -name 'fundamentals*.py' -o -name 'CLAUDE*.md' \) -print -delete
```

---

## 7. Alag se chalana (bina shortcut)

```
python3 ~/RB_Screener/daily_screener.py
python3 ~/RB_Screener/momentum_screener.py
python3 ~/RB_Screener/fundamentals.py
python3 ~/RB_Screener/fundamentals.py --symbols TCS,INFY   # sirf ye stocks
python3 ~/RB_Screener/position_tracker.py --no-news    # purana leg-wise tracker (rbport ne jagah le li)
```

---

## 8. Kuch galat ho to

| Dikhe | Matlab / kya karo |
|---|---|
| `NO ACTIVE ACCOUNT` | token.txt khaali / galat -> `rbtoken`, sahi lines |
| `does not match the token` | Client ID aur token alag account ke -> sahi token daalo |
| `HTTP 401` / `DH-901` | Token expire -> naya token |
| `Market is open` | rbtrack 15:30 ke baad chalao |
| `Not enough funds` | Dhan mein paise nahi -> pehle paise daalo |
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

---

## 10. Google Sheets mein reports (Excel ki zarurat nahi)

`rbscan` aur `rbport` apni report ki **copy** Google Drive mein daalte hain (Mac ka Google Drive app upload karta hai):
```
My Drive/RB_Reports/Master_Scan/2026-09/RB_Screener_2026-09-27.xlsx
My Drive/RB_Reports/DHAN_Ashutosh/Portfolio_DHAN_Ashutosh.xlsx
My Drive/RB_Reports/DHAN_Ashutosh/Watchlist_DHAN_Ashutosh.txt
```
- drive.google.com -> RB_Reports -> file pe double click -> Google Sheets mein khulti hai.
- Actions sheet mein Action / Amount chuno -> Sheets khud save karta hai -> `rbtrack` / `rbport` wahi picks lete hain
  ("took your Google Sheets edits").
- Sirf reports jaate hain. token.txt, keys, split.csv kabhi nahi.
- Check: `python3 ~/RB_Screener/drive_copy.py` -> "Google Drive copy ON -> ..."

## 11. Watchlist TradingView mein
`rbport` banata hai: `accounts/<..>/reports/Watchlist_<BROKER>_<Naam>.txt` (NSE:SIGMAADV,NSE:STLTECH,...).
TradingView -> Watchlist -> ... -> **Import list** -> ye file. Broker apps (Dhan/Angel/Zerodha) ki API se watchlist
nahi banti, wahan haath se jodna padega.

## 12. Telegram alert (har account ko sirf uska apna summary)

Bot sirf message BHEJTA hai -- koi command nahi sunta, koi order nahi lagata.
Ek baar setup:
```
python3 ~/RB_Screener/telegram_alert.py bot      # Telegram @BotFather -> /newbot -> token 'Bot Token:' line pe paste, Cmd+S
```
Har account ke liye (us account ka token token.txt mein ho):
1. Us insaan ke phone pe bot kholo -> `/start` bhejo
2. 15 minute ke andar Mac pe:
```
python3 ~/RB_Screener/telegram_alert.py link     # test message aana chahiye
```
Phir har `rb` ke baad us account ka summary: value/P&L, EXIT/HOLD, SIP due, rebalance list, NSE red flags,
market RED/GREEN, TRADING ON/OFF. Token expire/reject hua to bhi alert.
`python3 ~/RB_Screener/telegram_alert.py test` = test message, `unlink` = band.

## 13. Signal Tracker (screener ke stocks ka asli result)
`rb` apne aap chalata hai: jitne bhi stocks screener ne aaj tak dhoondhe (W+TT BUY/FIT/LATE, Momentum Top 20),
har ek ka "mila tab price -> aaj", Nifty se tulna, sabse upar / sabse neeche, aur rule status.
File mein tab **Signal_Tracker** (upar summary, neeche har stock). 30 din se kam purane = grey = abhi kuch mat samjho.
Alag se chalana ho: `rbsig` (= `python3 ~/RB_Screener/signal_tracker.py`)
