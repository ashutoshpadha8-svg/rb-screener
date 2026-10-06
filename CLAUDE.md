# RB_Screener — project context (handoff from claude.ai chat, 24 Sep 2026)

## Who I am / how to talk to me
- I'm RB. Casual Hinglish please.
- Trading feedback: direct and honest, no encouragement. If an idea is bad, say so with numbers.
- Teach one step at a time, not big info dumps.
- I run Python scripts but don't write code from scratch. Give exact terminal commands.
- Mac Mini, zsh, Python 3.9 (pip3). Everything lives in `~/RB_Screener` (moved off the Desktop 27 Sep: Google Drive
  was syncing Desktop incl. token.txt / Angel keys). Personal key notes: ~/RB_Secrets (outside the repo, never read).
  All scripts find their folder from __file__ (daily_screener/fundamentals HERE fixed 27 Sep).
- Trading capital ~Rs 2 lakh. Full history of the earlier claude.ai chat (Fusion strategy, EMA 9/33, crypto,
  gold, money maths) is in CHAT_HANDOFF.md.

## Folder layout
```
~/RB_Screener/
  daily_screener.py     # v4 - main screener (run daily)
  position_tracker.py   # hold/exit tracker for my positions (swing + investing legs)
  fundamentals.py       # fundamental check on the screener shortlist (Screener.in public pages)
  backtest.py           # backtest of the screener rules (pit10k / today10k / b173 universes)
  fusion_backtest.py    # Fusion vs W+TT, cash + stock futures, real Dhan costs + Indian tax
  fno_data.py           # downloads NSE F&O bhavcopy history (2013+) into data/fno/
  buy_delay_study.py    # live 1-session buy delay vs backtest (30 Sep): ~ -0.5 pt/yr
  strategy_lab.py       # 16 pre-registered strategies (momentum, low-vol, mean reversion, timing) vs baselines
  momentum_screener.py  # LIVE momentum (RAMOM top 20, sector cap 4) -> Momentum_Top20 + Strategy_Comparison sheets
  auto_tracker_update.py# rbtrack: Action BUY -> Dhan AMO (CNC, MARKET @ open, type YES) -> split.csv LIVE;
                        #   BUY MTF -> productType MTF, qty floor(10000x4/LTP), type "YES MTF";
                        #   PAPER / PAPER MTF -> split.csv PAPER; --sync = real fills; --no-orders; --dry-run
  broker_api.py         # ONLY place that talks to a broker: Dhan / Angel One (SmartAPI) / Zerodha (Kite)
                        #   prices, history fill, holdings, funds, AMO BUY/SELL (CNC/MTF), order status. SELL only via the Sell sheet.
  news_feed.py          # Google News RSS headlines + NSE corporate announcements (nse_announcements: official
                        #   filings, routine ones skipped, red flags = pledge/resign/default/strike/downgrade/...;
                        #   NSE sometimes 403s -> retries; works from the cloud too, 26 Sep). Info only, never a rule.
  rb_scan.py            # rbscan: MASTER scan = daily_screener -> momentum_screener -> fundamentals, ONCE a day,
                        #   shared by all accounts (skips if done; re-runs once if the last scan was intraday; --force)
  portfolio.py          # rbport: per account ONE file Portfolio_<BROKER>_<Name>.xlsx (27 Sep: overwritten each run, report
                        #   date = Dashboard A1; Action/Sell picks kept only same day; old dated files -> data/old_reports):
                        #   Holdings (demat + PAPER:
                        #   trend/stage, RSI, 52w, ATR, rets, W+TT today, swing/investing/momentum rule, fundamentals,
                        #   news, RECOMMENDATION + why), Watchlist (WATCH picks by mom rank), Rebalance (momentum),
                        #   Actions (dropdown -> rbtrack)
                        #   ONE-FILE view (27 Sep): Dashboard first (money, sell/red flags, new BUY, Super-Buy,
                        #   rebalance, watchlist, sheet links) + master Swing/Investing/Momentum_Top20/
                        #   Fundamentals copied in (Strategy_Comparison dropped: Actions = same list + picks)
                        #   Super-Buy sheet (27 Sep): stocks in BOTH W+TT swing list and momentum top 20 (backtest 30 Sep: better per trade, not as a portfolio)
                        #   Layout v2 (27 Sep, RB chose): Holdings = CARDS (4 per row, colour = ACTION, exit door),
                        #   Journal = month-wise first (Option 2), Holdings_Table = full sortable table (grey tab),
                        #   Actions columns reordered (Action/Amount/Qty first, Regime/Shares dropped), Watchlist
                        #   16 columns, number formats everywhere. Tabs: Dashboard, Holdings, Journal, Actions,
                        #   Super-Buy, Rebalance, Watchlist, Holdings_Table, Swing, Investing, Momentum_Top20, Fundamentals.
  drive_copy.py         # Output copies for Google Sheets (27 Sep, replaces gdrive_sync.py = retired, no OAuth):
                        #   copies ONLY RB_Screener_*.xlsx / Portfolio_*.xlsx / Watchlist_*.txt into the Google Drive
                        #   for desktop folder: My Drive/RB_Reports/{Master_Scan|<BROKER>_<Name>}/<YYYY-MM>/.
                        #   push() after rbscan/rbport; pull() before rbport/rbtrack takes a copy edited in Sheets
                        #   (mtime > our copy time, data/_drive_copy.json) over the local file (*.before_drive.xlsx
                        #   kept). Secrets/split.csv/data never copied. Tested with a fake Drive folder only.
                        #   rbport also writes reports/Watchlist_<TAG>.txt for TradingView 'Import list' (29 Sep: sections
                        #   ###Holdings / Super-Buy / Momentum Top 20 / W+TT BUY-FIT / My Watch, no duplicates).
  rb.py                 # rb = THE daily command (27 Sep, RB: "sirf 2-3 commands"): token check (expired -> opens
                        #   token.txt, stops) -> auto_tracker_update --sync -> rb_scan -> portfolio. No orders.
                        #   Commands now: rb + rbtrack (orders). rbscan/rbport/rbsync/rbcheck/rbtoken retired as aliases.
  journal.py            # Trade journal (27 Sep): accounts/<..>/data/journal.csv, one row per buy. PAPER logged from
                        #   split.csv, LIVE once seen in demat. LIVE sell = left demat AND broker trade history shows
                        #   SELL (broker_api.trades: Dhan /v2/trades/{from}/{to}/{page}; Angel getTradeBook / Kite
                        #   /trades = today only) else note + `rbtrack --sold SYM PRICE --date D` (PAPER: --paper).
                        #   Closed trade leaves split.csv. Dividends: NSE corporates-corporateActions (ex-date held x
                        #   qty, cached daily in data/_nse_ca). Fees: broker rate cards (official pages 27 Sep: STT
                        #   0.1% both, NSE 0.00307%, SEBI 10/cr, GST 18%, stamp 0.015% buy, DP Dhan 12.5+GST /
                        #   Zerodha 15.34 / Angel 20+GST, Angel brokerage min(20, 0.1%, >=5)); MTF interest 12.49%.
                        #   Tax ESTIMATE per FY: STCG 20.8%, LTCG 13% > 1.25L, set-off, STT not deductible; dividends
                        #   (slab) excluded. Exit signal date -> "Rule follow?". PAPER_AUTO_EXIT moot (PAPER removed).
                        #   Tested with mocked data only.
  sip.py                # SIP (27 Sep, RB): SIP sheet in the Portfolio file (Symbol, Frequency Monthly/Weekly/Daily,
                        #   Day, Amount per buy = own Rs, Total capital cap, Product BUY/BUY MTF, Active, Start) <->
                        #   accounts/<..>/data/sip.csv (+ sip_log.csv of buys). rbtrack places AMOs for due plans
                        #   (once per month/week/weekday, catch-up inside the same period, last buy cut to capital
                        #   left, MTF qty = amount x broker leverage). Buys -> split.csv strategy SIP (investing_qty
                        #   column, leg "sip" in portfolio = no sell rule) -> journal. No dip/up rules (backtest said no).
                        #   Symbol dropdown: hidden 'Symbols' sheet 'SYM | Company' (NSE EQUITY_L.csv + ETF list, weekly
                        #   cache data/_nse_symbols.csv, + broker symbols); read back as the part before ' | '.
                        #   Start date = real date cell + calendar picker (Sheets double-click); blank -> today;
                        #   typed 01-10-2026 = DAY first; unreadable -> plan PAUSED (Active NO) + warning. Day dropdown
                        #   (Mon..Fri, 1..28); Weekly '1'..'5' = Mon..Fri.
                        #   Due is judged on the AMO FILL day (next weekday; before 09:00 = same day), catch-up only
                        #   for a buy day >= Start date (Sunday run of a Mon plan = ONE buy Mon, not last week + this week).
                        #   PAPER / PAPER MTF actions REMOVED (27 Sep, RB): Actions = BUY / BUY MTF / WATCH;
                        #   `rbtrack --clear-paper` drops old PAPER rows from split.csv + journal.
  settings.py           # Per-account switch (27 Sep, RB): Dashboard B2 "TRADING (buy + sell)" ON/OFF (default OFF)
                        #   -> accounts/<..>/data/settings.json. OFF = rbtrack sends NO order (BUY, SIP, SELL); WATCH ok.
                        #   AUTO SELL (27 Sep, RB approved design): Portfolio "Sell" sheet = LIVE demat stocks whose rule
                        #   says sell: EXIT legs (default YES), momentum SELL@REBAL (YES only in the rebalance window =
                        #   last weekday of month / 1st weekday), untagged combined SELL (default NO, user may pick YES),
                        #   SIP never; qty = firing legs only (split.csv), per product CNC/MTF, capped at demat qty.
                        #   rbtrack: TRADING ON -> sells first (fresh demat check, sold_recently/ordered_today guard,
                        #   typed "YES SELL", broker_api.place_amo_order(side="SELL"), orders_log side column) -> journal
                        #   closes after the fill. Needs DDPI/POA. Mock-tested only; never sent a real SELL.
  nse_calendar.py       # NSE trading days/holidays (30 Sep): is_trading_day, next_trading_day, first_trading_day
  telegram_alert.py     # Telegram summary per account (27 Sep, RB): ONE bot (accounts/telegram_bot.txt, never printed),
                        #   each account linked to ONE chat (accounts/<..>/telegram.json via `telegram_alert.py link` =
                        #   /start of the last 15 min). rb/portfolio sends: value/P&L, EXIT/SELL@REBAL/WATCH/HOLD/SIP,
                        #   SIP next due, LIVE rebalance (next 1st weekday), NSE red flags, regime, TRADING. rb also
                        #   alerts when the token is expired/rejected. SEND-ONLY: no commands, no orders.
                        #   Mock-tested only (fake _api), never hit the real Telegram API from the cloud.
  signal_tracker.py     # (30 Sep, RB) every stock the screener EVER found: reads ALL reports/RB_Screener_*.xlsx
                        #   (plain file wins over *_fund copy) -> data/signals_log.csv (append/merge only; a deleted xlsx
                        #   keeps its rows; momentum stretch = out of top 20 > 20 days -> new find; W+TT = one per signal
                        #   date). Per find: scan price, now (broker fill + live if token), return, Nifty same days,
                        #   best/worst since (daily H/L), 20% stop hit, SWING EXIT (close<40w MA) / momentum rank>40.
                        #   < 30 days = TOO EARLY (grey). Tabs Signal_Tracker (every find, header+Symbol frozen, filter) +
                        #   Signal_Summary (groups incl. momentum rank 1-5/6-10/11-20) in the master scan (copied into Portfolio)
                        #   + data/signal_tracker_latest.csv. rb_scan runs it after every scan (never stops the scan)
                        #   and once if today's scan lacks the sheet. Mock-tested only.
  split.csv             # symbol,swing_qty,investing_qty,momentum_qty,entry_price,entry_date,strategy,mode,product,order_id,note
  data/orders_log.csv   # every AMO attempt (ok / error) -> blocks a second order for the same stock that day
  FUNDAMENTALS.md       # research + thresholds behind fundamentals.py
  account.py            # token.txt -> broker + client + token -> accounts/<BROKER>_<ID>/ (see below)
  token.txt             # (was dhan_token.txt, auto-renamed once) Broker: / Client ID: / Name: / Token: lines. NEVER print or copy the token anywhere
  reports/              # MASTER scan RB_Screener_YYYY-MM-DD.xlsx (Swing, Investing, Momentum_Top20,
                        #   Strategy_Comparison, Fundamentals) -- one per day, same for every account
  data/                 # SHARED market data: price history, NSE files, scrip master, Screener pages,
                        #   momentum_ranks_latest.csv, _nse_industry.csv (same for every account)
  accounts/<BROKER>_<CLIENT_ID>/  # PER ACCOUNT, e.g. DHAN_1100120973 (name never in the path)
    data/               #   split.csv, split_backup.csv, orders_log.csv
    reports/            #   Portfolio_<BROKER>_<Name>.xlsx (one file) + Watchlist_<TAG>.txt -- rb
    credentials.json    #   Angel/Zerodha api_key etc. (template auto-created; never printed)
    account_name.txt    #   display name
  accounts/.migrated    # marker: the one-time move of the old global files is done
  accounts/.last_session.json  # broker/client/name of the last good run (NO token) -> token-only paste works
```
Multi-account + multi-broker (account.py + broker_api.py, 26 Sep 2026): all 5 live scripts call
account.activate() first; NO script calls a broker directly any more (only broker_api.py does).
- token.txt: "Broker: DHAN|ANGEL|ZERODHA", "Client ID:", "Name:", "Token:" (":" "-" "=" all ok).
  Token-only file (Cmd+A Cmd+V): Dhan -> broker + ID read from the JWT; other brokers -> broker/ID/name from
  accounts/.last_session.json. Old 1-2 line files still work.
- STOPS: no token, unknown broker, bad ID, Dhan JWT ID != "Client ID:", Broker line contradicts the token
  (Dhan JWT vs ANGEL/ZERODHA), Angel JWT username != Client ID, only one of Broker/Client ID given.
- Orders: broker_api.verify_identity() must confirm the token belongs to the active Client ID (Dhan: signed
  in the JWT; Angel getProfile / Kite /user/profile) or NOTHING is sent. AMOs refused during 09:15-15:30
  (in rbtrack AND in the adapter). qty >= 1, symbol must be in the broker's symbol list.
- MTF mapping: Dhan productType MTF / Angel producttype MARGIN / Kite product MTF. CNC: CNC / DELIVERY / CNC.
- Keys may also be extra lines in token.txt ("API Key:", "MPIN:", "TOTP Secret:", "API Secret:";
  txt wins over credentials.json; never written to .last_session.json). "BO ID:" = Client ID.
- Angel: credentials.json api_key + mpin + totp_secret; Token: <jwtToken> or AUTO (login with stdlib TOTP,
  RFC 6238 test vectors pass). Zerodha: api_key + api_secret; daily `python3 broker_api.py zerodha-url`,
  log in, then `python3 broker_api.py zerodha-login REQUEST_TOKEN` (checks user_id, writes the Token line).
  Kite historical candles are a paid add-on -> without it the gap-fill is skipped (free source + LTP).
- `python3 broker_api.py check` = identity + funds + one LTP, no orders.
- 26 Sep: Angel LIVE-tested for login (TOTP AUTO) + history fill + LTP via rbscan (works). Angel symbols: -EQ, else
  -BE (STLTECH/HFCL/E2E etc. are BE on Angel). Angel orders still untested.
- TESTED: Dhan price/history/holdings in daily use; every broker's payloads/parsing only against mocked
  HTTP (26 Sep). Angel + Zerodha NEVER hit the real API; Dhan AMO never used on a real order -> 1 share first.
- Migrations: accounts/<digits>/ -> accounts/DHAN_<digits>/ (automatic); first-ever account still gets the
  old global split.csv/reports moved in (marker accounts/.migrated). Shared market data stays in data/
  (_dhan_scrip_master.csv, _angel_scrip_master.json, _kite_instruments_nse.csv, weekly refresh).
- `python3 account.py` shows the active + other accounts; `--name "X"` sets the display name.
- Routing also covers the `__main__` copy (python3 daily_screener.py runs as __main__, not daily_screener).
Commands (v2, 26 Sep 2026 -- RB: "one master scan a day, the rest on the portfolio"):
  rbtoken (open token.txt) | rbcheck (identity+funds+LTP) | rbscan (rb_scan.py, master, 1x/day) |
  rbport (portfolio.py) | rbtrack (Actions sheet of the Portfolio file -> AMO/PAPER) | rbsync (fills).
  rbpos / rbreview retired (position_tracker.py stays as a library + optional script; holdings_review merged
  into portfolio.py). Aliases: see RB_COMMANDS.md section 1.
Daily routine: rbtoken (fresh Dhan token) -> rbscan (best after 15:30) -> rbport -> pick Actions (BUY / BUY MTF /
PAPER / PAPER MTF / WATCH dropdown) in the Portfolio file, save, close -> rbtrack after 15:30 -> next morning rbsync.
Actions sheet 'Amount (Rs)' (optional, per row) = own money for that stock; blank = Rs 10,000 slot (tested
equal weight). MTF = Amount x the broker's per-stock leverage (Dhan /v2/margincalculator productType MTF
-> 'leverage', fallback totalMargin; Angel margin/v1/batch productType MARGIN -> totalMarginRequired; Kite
/margins/orders product MTF -> leverage/total; any error -> 4x ASSUMED + warning; mocked tests only, 27 Sep). 'Qty (auto)' = Excel formula preview; rbtrack recalculates qty with the order-time price.
Recommendation logic in portfolio.py: split.csv-tagged legs -> that strategy's backtested exit rule (worst leg
wins: EXIT > SELL@REBAL > WATCH > HOLD); untagged holdings -> combined check SELL (Stage 4, or < 40w MA AND rank
> 40) / WEAK / KEEP -- NOT backtested as a whole. Fundamentals, news and NSE filings ("Red flag" column) never change the verdict.
Momentum trades only on the 1st trading day of the month; keep while rank <= 40. Sells are NOT automated.
WATCH (Action): no order; rbport (and rbtrack) save it to accounts/<..>/data/watchlist.csv (symbol, added, price_added,
source); rbport analyses watchlist rows (Mode WATCH: STRONG / WEAK / AVOID via the combined check, P&L since added).
`rbtrack --unwatch A,B` removes them.

## How fundamentals.py works
- Input: latest reports/RB_Screener_*.xlsx (or `--file PATH`). `--symbols A,B` writes a separate RB_Fundamentals file.
- Data: free public Screener.in company page (consolidated, falls back to standalone when history is short;
  bank/NBFC NPA always from standalone). Pages cached per day in data/screener_pages/. 2.5 s pause per request.
- Writes INTO the same RB_Screener file (close it in Excel first; if open it saves *_fund.xlsx):
  Swing / Investing: green columns on the right (Fund Check (info), Failed/Missing, P/E, ROCE, ROE, D/E, growth,
  pledge, industry) + grey Promoter/FII/DII change columns. No row removed or re-ordered.
  Fundamentals sheet: every non-LATE stock, sorted by RS rank, full detail + Screener Cons.
- RB's rule + backtest: fundamentals NEVER remove a stock (the gate showed no benefit 2018-26). Watch Score removed.
- Re-running on the same day replaces its own columns/sheet (no duplicates).
- Swing sheet "Stop %" input now sits under the table (column F), not in Q1, so added columns can be sorted safely.
- Not automated: pledge % (only if Screener's Cons mention it), auditor, SEBI, bank CRAR, insurer solvency.

## How daily_screener.py works
- Universe: every NSE company with market cap >= Rs 10,000 Cr, from NSE's daily PR bhavcopy zip
  (`nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PRddmmyy.zip`, MCAP csv inside). ~586 names, ~532 usable.
- Price history: free adjusted CSVs from github.com/BennyThadikaran/eod2_data (daily/<symbol>.csv; index file is "nifty 50.csv").
  This source lags a few days, so missing days are filled from Dhan `/v2/charts/historical`, and today's price comes from Dhan `/v2/marketfeed/ltp`.
- Dhan client ID and token expiry are read from the JWT token itself (no config needed).
- Output: terminal summary + Excel with 2 sheets (Swing, Investing). Swing sheet has formulas: Stop = Price*(1-Q1), Effective Exit = MAX(Stop, 40w MA), Risk %.

## The rules (these match the backtest exactly — do not change without re-testing)
- Weinstein entry: close > 150DMA (30w), 150DMA rising vs 10 bars ago, RS rank > 50, close = 30-day high close,
  volume > 2x 50-day avg, 60-day median turnover > Rs 5 Cr.
- Minervini Trend Template: close > 50DMA > 150DMA > 200DMA, 200DMA rising vs 22 bars ago,
  close > 1.3x 52w low, close > 0.75x 52w high, RS >= 70.
- RS rank = 6-month return relative to Nifty 50, percentile across the universe.
- Entry = Weinstein AND Trend Template on the same day, buy next open.
- Swing exit: fixed stop 20% below entry (not trailing), or close below 40-week MA (200DMA). No profit target, no breakeven shift.
- Investing exit: only 10 straight closes below a falling 30-week MA (Stage 4).
- Status: BUY = signal on last session; FIT = older signal (<=20 sessions) still passing at today's price; LATE = >10% past signal (not tested, skip).

## Backtest results (2012-2026, 173 large NSE survivors, 0.25% cost/side)
- Weinstein + Trend Template, stop 20% / 40w MA exit: 3633 trades, win 47.5%, avg trade +20.8%, PF 3.99, avg win +58%, avg loss -13%.
- Tighter stops, 25% profit target, breakeven shift all made results worse (25% target: avg trade +3.9%).
- Adding O'Neil L+M filters cut trades and avg return. Real CAN SLIM (C, A) never tested - needs quarterly EPS with result-declaration dates.
- Only 6-month RS ranking survived in-sample AND out-of-sample among improvement ideas.
- Equal-weight buy & hold of the same 173 stocks (~21-22% CAGR, -38% DD) still beat every rule-based strategy; survivorship bias inflates that.
- Win rate 60-70% is NOT achievable with this trend-following family; it needs mean reversion.
- IMPORTANT: the >= Rs 10,000 Cr universe (~530 names, many mid-caps) was NOT backtested. Treat live signals as unverified; paper trade / small size.

## backtest.py results (run 25 Sep 2026, data Feb 2012 - 18 Sep 2026, first signal 2013, 0.25%/side)
One open trade per stock at a time (the old chat backtest counted EVERY signal day as a trade:
`--overlap` reproduces it: 3815 trades, win 46.9%, avg loss -13.1%, PF 3.63 -> engine matches).
Stop = day's LOW touching entry*0.8. Exits: 40w MA close -> next open. Investing: 10 closes < falling 30w MA.
| Universe | Trades | Win% | Avg% | PF | Invest avg% | Invest PF |
|---|---|---|---|---|---|---|
| b173 (today's big survivors) | 793 | 46.0 | +18.3 | 3.91 | +23.5 | 4.25 |
| today10k (today's list, whole period = look-ahead) | 1752 | 44.5 | +23.5 | 4.17 | +33.5 | 5.25 |
| **pit10k (point-in-time estimate) = the honest one** | **1773** | **39.3** | **+11.8** | **2.43** | **+17.2** | **2.93** |
- Look-ahead (using today's winners) roughly DOUBLES the avg trade. b173 has the same bias -> old +20.8% was inflated.
- pit10k is still biased up: stocks delisted before today are missing from eod2_data.
- Weak years pit10k swing avg: 2015 -10.7%, 2018 -6.3%, 2024 -6.1%, 2025 -1.1%.
- (pit10k numbers after the 26 Sep fix: an exit on an untraded next day no longer leaves the trade 'open'.)
- Market-cap estimate (today's mcap x price ratio) vs real NSE MCAP files 2024-26: median error ~2.5%,
  ~96-98% of the >= 10k list matches. NSE PR zips only carry MCAP csv from ~2024.

## Portfolio study (backtest.py --portfolio, pit10k, 2013-01 to 2026-09, idle cash 6%/yr, 0.25%/side)
Equal slots (equity/slots at entry), new signals ranked by RS, one position per stock. Pre-registered variants,
judged in-sample 2013-19 AND out-of-sample 2020-26 (each half starts from cash). ~89% invested on average.
| Variant | IS CAGR | OOS CAGR | FULL CAGR | FULL maxDD |
|---|---|---|---|---|
| BASE 20 slots, swing exit | 10.5 | 11.6 | 12.5 | -39.7 |
| + Nifty > 200DMA entry filter | 9.4 | 14.0 | 13.7 | -35.3 |
| RS >= 85 | 9.0 | 10.4 | 11.5 | -45.9 |
| 10 slots | 8.5 | 10.1 | 10.5 | -41.4 |
| investing (Stage 4) exit | 10.3 | 19.6 | 14.8 | -39.5 |
| NIFTY 50 price index (no dividends, TR ~ +1.3%/yr) | 10.8 | 10.2 | 10.5 | -38.4 |
- Verdict: swing system ~= Nifty total return with the same ~-40% drawdown, BEFORE tax (swing gains mostly STCG).
- RS >= 85 and 10 slots: worse in both halves -> rejected (pending #4, #5 answered: keep RS 70, 20 slots).
- Nifty filter: worse in-sample, better out-of-sample -> not proven, not adopted (does cut DD ~5 pts).
- Investing exit: equal in-sample, much better out-of-sample -> best candidate, but evidence is only 2020-26.
- Result depends a lot on the start date (cold start Jan 2020 = 11.4%; same years inside the full run = 14.4%).

## Fundamental gate backtest (backtest.py --fundamentals, 26 Sep 2026)
Data: Tickertape API history (fund_history.py), ~Sep 2016 on; each quarter used only from the SEBI deadline
(+45 days, Mar quarter +60) + 2 days -> no look-ahead from timing. Same rules as fundamentals.py (swing: qtr PBT
YoY >= 20, total revenue YoY >= 15, 3y ROE >= 10, D/E <= 1.5; pledge/auditor untestable). Signals 2018-2026, pit10k.
148 of 599 symbols not on Tickertape (renamed / newer listings) = NODATA, excluded from the comparison
(NODATA holds big 2020-24 winners - ADANIENSOL, IRFC, MAZDOCK - and fakes a "gate" benefit if left in).
| Trades (investing exit), swing verdict | 2018-21 avg | 2022-26 avg |
|---|---|---|
| fundamentals FAIL | +26.4% (281) | +18.2% (576) |
| fundamentals PASS | +3.9% (146) | +18.3% (203) |
- 2018-21: PASS was worse than 100% of random same-size subsets. 2022-26: no difference.
- One rule at a time (swing leg, all years): profit YoY >= 20 no effect (11.5 vs 10.4%), sales YoY >= 15 small +
  (14.2 vs 11.9%), ROE >= 10 slightly worse (13.7 vs 16.2%), D/E <= 1.5 worse (9.9 vs 28.5%, only 75 fails).
- Portfolio "PASS only" variants look better sometimes, but that is fewer candidates / different slot timing,
  not fundamentals (trade-level says so).
- VERDICT: the fundamental gate does NOT improve this system. Keep fundamentals.py as information only.
  -> Watchlist FAIL-exclusion and Watch Score removed (26 Sep 2026, RB agreed).

## Fusion backtest (fusion_backtest.py, 26 Sep 2026) - cash + stock futures, real costs, tax
Rules unchanged from the old chat. Engine check: Fusion on the old 173 survivors = 17.7% CAGR / -26.9% DD
(old chat 17.4% / -25.3%) -> engine matches. Costs = Dhan pricing page (delivery 0 brokerage, STT 0.1% both sides,
stamp, exchange, GST, DP Rs 12.5+GST per sell) + 0.10% slippage/side; futures Rs 20/order, STT 0.025% sell,
0.03% slippage, ACTUAL NSE futures prices (fno_data.py, 3,383 days 2013-2026), monthly roll, collateral 6%.
Tax: STCG 20.8%, LTCG 13% over 1.25L, F&O = business income 31.2%. Rs 2 lakh start, 2013-01 to 2026-09.
| Cash, >= Rs 10k pit | slots | 2013-19 | 2020-26 | FULL pre | FULL post-tax | maxDD |
|---|---|---|---|---|---|---|
| Fusion | 20 | 9.6 | 18.3 | 13.9 | 12.7 | -42.5 |
| Fusion | 8 | 15.9 | 23.7 | 20.4 | 18.2 | -46.1 |
| Fusion | 5 | 13.9 | 28.0 | 20.6 | 17.5 | -42.6 |
| W+TT investing exit | 20 | 10.6 | 17.7 | 14.2 | 13.9 | -38.6 |
| W+TT swing exit | 8 | 7.2 | 8.8 | 9.5 | 9.1 | -45.5 |
| Nifty 50 ETF (price only) | - | 10.8 | 10.2 | 10.5 | 9.8 | -38.4 |
- Old "Fusion 17.4%" was survivorship: on the honest universe 20 slots = 13.9% pre-tax with DD -42.5%.
- Slot luck (40 random orderings of same-day signals): Fusion 8 slots random median 11.4%, best 17.3%; RS-ranked
  20.4% -> RS ranking is what makes concentrated Fusion work (matches the old chat's RS finding).
  8 slots was chosen after seeing 20/8/5 -> treat 18% post-tax as optimistic; 20 slots ~ 12-13% is the floor.
- F&O (330 of 363 F&O names had spot history; 33 renamed/delisted dropped), 20 slots:
  cash on F&O stocks 10.0% pre / 9.4% post; futures LONG 1x 8.9 / 4.9; LONG 2x 11.5 / 6.2 (DD -58%);
  SHORT only -7.2 / -11.6 (DD -76%); long+short -0.1 / -4.2. Fusion shorts: PF 0.6, win 30% -> never short it.
  Futures lose to cash because of carry (futures premium ~ interest) + 31.2% slab tax vs 20.8% STCG.
- Rs 2 lakh and real lot sizes: median 1-lot margin Rs 1.5-2 lakh since 2016; 4 lots within Rs 2 lakh: ~0% of
  stocks since 2021 -> with Rs 2 lakh you can hold ONE futures position, no diversification.
- VERDICT: no F&O for this strategy. Best cash candidate = Fusion, RS-ranked, 5-8 slots (beat Nifty in both halves),
  but -46% drawdowns and 2013-19 was only ~5 pts above Nifty. Paper-trade before money.

## Strategy lab (strategy_lab.py, 26 Sep 2026) - 16 pre-registered strategies, same honest setup
Rs 2 lakh, >= Rs 10k pit universe + Rs 5 Cr liquidity, real Dhan costs + 0.10% slippage, tax, cash 6%, 2013-01..2026-09.
Rank strategies = monthly top-N equal weight, keep while rank < 2N. Post-tax CAGR %:
| Strategy | 2013-19 | 2020-26 | FULL | maxDD | trades/yr |
|---|---|---|---|---|---|
| RAMOM (NSE momentum style: z(6m/vol)+z(12m/vol)) top20 monthly | 11.5 | 26.7 | 18.7 | -40.0 | 43 |
| RAMOM top10 monthly | 10.4 | 31.2 | 21.1 | -42.0 | 26 |
| MOM12-1 top20 | 10.1 | 28.2 | 18.5 | -45.8 | 36 |
| MOM6 (RS) top20 | 11.2 | 22.4 | 17.5 | -39.5 | 52 |
| RAMOM + Nifty>200DMA | 5.2 | 21.0 | 12.8 | -29.8 | 47 |
| Low-vol top20 | 14.6 | 10.3 | 12.1 | -27.6 | 11 |
| 52W-high top20 | 4.4 | 11.2 | 7.8 | -33.5 | 113 |
| Fusion 8 slots | 14.3 | 19.2 | 17.1 | -47.4 | 22 |
| W+TT investing 20 | 9.9 | 16.1 | 13.0 | -38.9 | 20 |
| Mean reversion RSI-2 (58% of trades beat the universe) | -2.2 | -3.0 | -2.9 | -51.4 | 490 |
| Nifty 200DMA timing | 5.3 | 10.6 | 7.9 | -17.2 | 2 |
| Nifty buy & hold | 10.3 | 9.8 | 9.8 | -38.4 | - |
- Momentum robustness: RAMOM 18.7-20.8% for rebalance day 1/6/11/16; 17.6-21.1% for N = 10..30 -> not a fluke of
  settings. Independent support: NSE Momentum indices. BUT 2013-19 momentum only ~= Nifty; the edge is 2020-26.
- Mean reversion: high hit rate but costs (STT 0.1% each side + slippage, 490 trades/yr) make it lose money -> reject.
- Low-vol: best 2013-19 and lowest DD of stock strategies, lagged 2020-26.
- Stock finding (6-month excess vs universe per pick): RAMOM top10 +6.2%, W+TT +4.2% (only 38% of W+TT picks beat
  the universe - it lives on a few big winners), Fusion +2.4%, 52WH +0.5%, low-vol -1.6%.
- 16 strategies tested -> discount the winner. Momentum was expected to win from prior research (not a data-mined pick).

## Momentum enhancements (tested 26 Sep 2026 before coding, RAMOM top 20, post-tax CAGR %)
| Variant | 2013-19 | 2020-26 | FULL | maxDD | Verdict |
|---|---|---|---|---|---|
| BASE | 11.7 | 25.7 | 18.3 | -42.8 | |
| + sector cap 4 (NSE industry) | 11.9 | 27.7 | 20.3 | -37.0 | ON (better in both halves) |
| + ATR sizing (0.5x-2x) | 11.9 | 22.9 | 17.3 | -36.0 | OFF by default (switch ATR_SIZING) |
| + trailing 3xATR (+/- breakeven 20%) | -4.2 | 8.3 | 2.4 | -55.2 | OFF (switch MOMENTUM_SMART_SL in tracker) |
| + trailing 6xATR / 10xATR | 5.7 / 9.8 | 19.7 / 24.2 | 12.4 / 17.2 | -48 / -39 | rejected |
| + breakeven only (+20%) | 9.3 | 26.1 | 16.6 | -39.5 | rejected |
| + Nifty<200DMA: no new buys | 9.2 | 23.4 | 15.8 | -34.9 | warning/label only, no blocking |
| all four together (RB's package) | -1.6 | 5.5 | 2.4 | -40.3 | rejected |
(BASE moves +/-0.4 between runs as the data cache refreshes.) Sector map: NSE Nifty Total Market list
(data/_nse_industry.csv, weekly refresh); ~4 of the top 20 are usually outside it ("?", not capped).

## Momentum lab (momentum_lab.py, 29 Sep 2026) - 4 pre-registered research ideas vs the LIVE strategy
| Variant | 2013-19 post | 2020-26 post | FULL post | maxDD | worst 12m | trades/yr |
|---|---|---|---|---|---|---|
| BASE RAMOM top20 + sector cap 4 (live) | 11.8 | 27.9 | 20.5 | -34.3 | -30.8 | 43 |
| 1 BLEND 50% BASE + 50% low-vol top20 | 13.3 | 20.8 | 17.2 | -29.8 | -23.2 | 54 |
| 2 SMOOTH (frog in the pan) | 7.9 | 27.1 | 17.3 | -37.6 | -31.0 | 44 |
| 3 RESIDUAL momentum | 10.8 | 30.7 | 20.0 | -32.8 | -29.4 | 38 |
| 4 VOLMGD (vol target 18%, approx) | 11.7 | 23.6 | 16.9 | -33.5 | -20.8 | 43 |
| low-vol top20 alone | 14.6 | 10.3 | 12.1 | -27.6 | -21.4 | 11 |
| Nifty 50 | 10.3 | 9.8 | 9.8 | -38.4 | -31.9 | - |
- NONE beats BASE in both halves -> BASE stays. SMOOTH worse in both. RESIDUAL = same overall (worse IS, better OOS).
- BLEND / VOLMGD = risk reducers: -3 to -4 pts/yr return for a milder worst year (-23/-21% vs -31%). Only if RB
  prefers a smoother ride; not adopted (27 Sep live setup unchanged). Industry list: niftyindices.com fallback URL.

## Rank study (rank_study.py, 30 Sep 2026) - is the momentum rank right? (no costs, raw rank, no sector cap)
Monthly 2013-01..2026-09, bought at the rebalance-day open. MOM = live RAMOM rank.
| MOM rank | picks | 3m avg | 3m median | 3m >=15% | 3m <=-10% | 6m avg | 6m median | 6m >=15% | 6m <=-10% | 6m beat univ |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 160 | 10.4 | 4.8 | 31% | 26% | 27.1 | 14.5 | 49% | 31% | 53% |
| 2-5 | 640 | 6.1 | 3.7 | 28% | 23% | 12.4 | 7.0 | 40% | 26% | 49% |
| 6-10 | 800 | 5.9 | 3.2 | 26% | 21% | 12.3 | 7.5 | 37% | 22% | 51% |
| 11-20 | 1600 | 4.1 | 2.3 | 24% | 22% | 9.4 | 6.0 | 36% | 24% | 48% |
| 21-40 | 3200 | 4.5 | 2.9 | 25% | 21% | 9.3 | 6.0 | 35% | 24% | 48% |
| 41-100 | 9372 | 4.2 | 2.2 | 24% | 21% | 8.4 | 4.5 | 35% | 26% | 45% |
| 101+ | 23173 | 3.1 | 1.1 | 22% | 23% | 5.7 | 2.1 | 30% | 29% | 41% |
- Rank works as an ORDER (top 20 > 41-100 > 101+; big gap only vs the bottom) but per stock it is ~a coin flip vs the
  universe (48-53% beat). Averages come from a few big winners (avg >> median). Rank 1 = lottery: 6m avg 27% but
  median 14.5%, 31% lose >10%; 2013-19 rank 1 3m median 5.9%, 2020-26 0.7%. RS6m rank gives almost the same table.
- '15-20% per stock in 3 months' happens for ~1 in 4-5 top-20 picks, not as a rule -> RB's target is unrealistic per pick.
- Signal tracker now shows 'Rank then' + live groups momentum rank 1-5 / 6-10 / 11-20.

## MTF leverage check (26 Sep 2026, momentum top 20 + sector cap, pre-tax, Dhan MTF 12.49%/yr on the funded part)
| Leverage | CAGR | maxDD | worst month | Rs 2L -> |
|---|---|---|---|---|
| 1x (CNC) | 22.8 | -34.5 | -21.3 | 33.3 L |
| 2x | 27.4 | -69.4 | -41.4 | 55.2 L |
| 3x | 26.0 | -90.3 | -58.6 | 47.3 L |
| 4x (RB's BUY MTF) | 18.4 | -97.5 | -72.7 | 20.2 L |
- Simulation holds through drawdowns; a real margin call would have liquidated 3-4x at the Mar-2020 bottom.
- 4x returns LESS than 1x. BUY MTF exists because RB asked; tracker shows interest and P&L on own money.
  Not every stock gets 4x on Dhan (lower limit -> reject / more margin).

## SIP backtest (sip_backtest.py, 27 Sep 2026) - RB's SIP idea, tested before coding
Rs 10,000/month, waiting cash 6%/yr, Dhan buy costs + 0.1% slippage, fractional units, XIRR on money put in.
NIFTY 50 index (price only) + 145 b173 SURVIVOR stocks (bias favours buying dips). Nifty XIRR % / stocks median XIRR %:
| Rule | FULL 2013-26 | 2013-19 | 2020-26 | idle cash |
|---|---|---|---|---|
| SIP monthly | 10.0 / 14.6 | 10.5 / 13.1 | 8.2 / 13.1 | 0% |
| SIP weekly / daily | 10.0 / 14.5, 9.9 / 14.4 | ~same | ~same | 0-2% |
| DIP 5% / 10% below last buy | 6.8 / 8.3, 6.8 / 7.7 | 7.5 / 7.9 | 6.9 / 7.9 | ~50-60% (price runs away, cash waits) |
| DIP 10% below 52w high | 10.1 / 14.4 | 10.9 / 13.5 | 7.4 / 13.3 | 1-9% |
| DIP 20% below 52w high | 11.1 / 13.7 | 10.9 / 12.0 | 7.6 / 12.8 | 4-49% |
| UP 5% / 10% above last buy | 9.5 / 12.2, 9.3 / 11.9 | 9.3 / 9.5 | 7.2 / 9.9 | 5-12% |
- Plain monthly SIP is as good as anything; weekly/daily add nothing. Buying only on dips / only on rises: worse,
  or mixed across halves (DIP52-20 on Nifty +0.4 in 2013-19, -0.6 in 2020-26) -> no proven edge.
- Single stocks: median 14.6% but worst 10% of stocks 4.2% (FULL) and about -4% in each half; survivors only.
- VERDICT: if SIP, plain monthly on a Nifty ETF; the broker's own SIP runs even with the Mac off. Dip/up rules rejected.

## Super-Buy backtest (superbuy_backtest.py, 30 Sep 2026) - W+TT signal AND RAMOM rank <= 20 same day
Pre-registered, same honest setup. 8157 W+TT signal days, 2931 of them Super-Buy. Trades (0.5% round trip):
| Entry / exit | trades | win% | avg% | median% | 13-19 avg | 20-26 avg |
|---|---|---|---|---|---|---|
| SUPER-BUY investing exit | 791 | 46.8 | +19.9 | -2.8 | +8.8 | +26.8 |
| ALL W+TT investing exit | 1769 | 46.9 | +16.7 | -3.0 | +5.6 | +20.6 |
| SUPER-BUY swing exit | 791 | 39.8 | +14.7 | -6.5 | +7.2 | +19.4 |
| SUPER-BUY momentum exit (rank > 40 at rebal) | 855 | 44.9 | +9.8 | -2.6 | +8.8 | +10.5 |
Portfolio post-tax CAGR (2013-19 / 2020-26 / FULL / maxDD): SB inv 20 slots 10.1 / 16.5 / 13.0 / -34.6;
SB inv 10 8.7 / 21.7 / 12.1 / -31.2; SB mom-exit 10 4.4 / 33.5 / 17.4 / -40.5; W+TT inv 20 10.0 / 16.2 / 13.6 / -37.6;
LIVE momentum top20+cap 12.2 / 28.0 / 20.3 / -35.9; Nifty 10.3 / 9.7 / 9.8 / -38.4.
- Per trade Super-Buy is better than plain W+TT in BOTH halves (+3 / +6 pts) -> a real quality label.
- As a portfolio it does NOT beat W+TT (too few signals, cash waits) and loses to live momentum in both halves.
- VERDICT: keep Super-Buy as a highlight on W+TT picks, not a separate strategy. Tracker: Age column (TODAY /
  1-5 / 6-29 / 30+ days) with soft row colours (green / blue / beige / white), freeze C4.
  signal_tracker.paint_ages (30 Sep, RB: "har sheet main"): same colours on Swing / Investing ('Days Since Signal',
  sessions; Investing got that column) / Momentum_Top20 (new 'Days in Top 20' col C, calendar days from
  signals_log.csv via momentum_screener.days_in_top) / Signal_Tracker; today's days cell darker green A9D08E + bold;
  LATE orange + fundamentals colours kept. Tracker pushes the master to the Drive copy after writing (rbsig).
  Momentum_Top20 also 'In Top 20 since' (date, col D; scans started 26 Sep 2026 -> nothing earlier).
  xl_fit.py (30 Sep, RB: "columns fit karo sab jagah"): width from header words (header <= 2 lines) + shown values
  (cap 45), ALL table cells one line (wrap off, saved row heights cleared). `python3 xl_fit.py check` = what the
  newest master really has (Momentum cols/widths, Drive copy age, script sizes). Run on the master by
  signal_tracker (last step of every scan / rbsig) and on the Portfolio file before save (Dashboard, Holdings cards skipped).

## EMA 9/21 cross (ema_backtest.py, 29 Sep 2026) - RB's idea, pre-registered, same honest setup
Buy next open after EMA9 crosses above EMA21; exit X1 = EMA9 back below EMA21, X2 = close < 50DMA. 7 filters x 2 exits.
| Variant (X1 exit) | trades | win% | avg% | median% | beat univ% | 13-19 post | 20-26 post | FULL post | maxDD | trades/yr |
|---|---|---|---|---|---|---|---|---|---|---|
| plain cross | 16622 | 29.8 | +1.1 | -3.0 | 32 | 2.9 | 11.0 | 7.5 | -34 | 194 |
| + RS>=70 | 4438 | 31.1 | +1.4 | -3.1 | 33 | 5.8 | 14.7 | 10.6 | -34 | 160 |
| + Trend Template | 2870 | 31.7 | +1.4 | -3.2 | 34 | 2.2 | 14.3 | 8.4 | -29 | 134 |
| + momentum top40 (best) | 2208 | 34.4 | +2.2 | -2.8 | 36 | 5.5 | 16.4 | 11.2 | -28 | 135 |
| W+TT investing (baseline) | 1765 | 46.6 | +16.9 | -2.8 | 39 | 9.6 | 16.9 | 13.3 | -38 | 20 |
| RAMOM top20 (baseline) | - | - | - | - | - | 11.6 | 26.1 | 18.7 | -43 | 43 |
| Nifty 50 | - | - | - | - | - | 10.3 | 9.8 | 9.8 | -38 | - |
- X2 (50DMA exit) worse than X1 in every filter. Every EMA variant < Nifty in 2013-19; hold ~3 weeks, 130-240 trades/yr
  -> costs + STCG eat it. No filter combo got win% above 35% or beat-universe above 36%.
- VERDICT: EMA 9/21 rejected as an entry system. Adding it to momentum/W+TT not tested; as a stand-alone it only adds
  trading. 'Most accurate' stock finders remain W+TT (39% beat univ, +5.2% excess/trade) and RAMOM rank.

## Fundamental layer (research done)
Order of checks: 1) red flags (promoter pledge > 20% = out, auditor resignation/qualification, SEBI/forensic action)
2) quality (ROE/ROCE >= 15% investing, >= 10-12% swing; D/E <= 1 non-financials; CFO/PAT >= 0.7-0.8 over 3-5 yrs; no loss year in 5-6 yrs)
3) earnings momentum (latest qtr profit YoY >= 20-25%, sales YoY >= 15-20%, not decelerating 2 qtrs; watch other income)
4) valuation only as sanity check - never reject Stage-2 leaders for high P/E.
Banks: Net NPA < 1-2%, CRAR >= 15%, ROA >= 1%. NBFC: GNPA < 3%, ROA >= 2%. Insurance: solvency >= 180%.
Data: Screener.in watchlist with columns ROCE, ROE, Debt to equity, Pledged percentage, YOY Quarterly profit growth,
YOY Quarterly sales growth, Profit growth 3Years, Sales growth 3Years. For backtests use result broadcast dates (NSE/BSE filings), not quarter-end.

## Known gotchas
- 30 Sep Codex review (REVIEW.md from RB): FIXED (1) rebalance_plan now fills ONLY the free slots from the FULL
  ranking with the sector cap counting kept holdings = strategy_lab.run_rank (old: ignored held sectors, listed BUY
  rows beyond free slots); (7) order POSTs use _call(once=True): an ambiguous network error is NOT retried (was up to
  6 tries = duplicate-order risk) -> 'ORDER STATUS UNKNOWN', logged, and ordered_today/sold_recently treat it as
  placed. OPEN (minor): rebal_window uses weekdays not NSE holidays; '?' sectors uncapped (same in backtest);
  live slot = Rs 10k fixed vs backtest equity/20 (Amount column is RB's choice). Codex's RAMOM 23.9% used only 535
  cached stocks (fewer delisted names) -> more survivorship than our 1300-stock run (20.3%); today-universe 30% = look-ahead.
  Codex note #2 (30 Sep) also FIXED: (3) rbtrack plan() refuses momentum BUYs past 20 slots / 4 per industry (split.csv
  Momentum holdings minus SELL-sent + this run; sectors from momentum_ranks_latest.csv); (4) ordered_today/sold_recently(
  sess=) ask the broker: REJECTED/CANCELLED/EXPIRED no longer block a re-send, unknown/no order id still blocks;
  (5) nse_calendar.py (NSE holiday-master API 'CM', weekly cache data/_nse_holidays.json, fallback weekdays + warning)
  -> portfolio.rebal_window uses trading days. (6) stop_policy_study.py: live stop (low hit -> next-open AMO) vs backtest
  intraday fill: avg trade 12.1 vs 11.8% (same), but stop exits worse than -25%: 20 vs 10, worst -84 vs -63% ->
  20% is NOT a max loss; close-based stop 12.6% avg but 29 tails. Live policy kept (a resting SL/GTT = new feature, RB decides).
  MILESTONE 1 (execution, 30 Sep) v2 after Codex's check: INTENT LEDGER accounts/<..>/data/order_intents.csv
  (tag, date, symbol, side, qty, product, state INTENT/UNKNOWN/ACCEPTED/REJECTED/CLOSED/NOT_PLACED, order_id).
  Every order: new_intent() saved BEFORE the POST with a NEW random tag (RB+yymmdd+B|S+8 chars = 17; Dhan
  correlationId / Angel ordertag / Kite tag) -> send -> update_intent. Lost reply -> book lookup by tag: found =
  ACCEPTED, else UNKNOWN (an empty/day-only book is NEVER proof of 'not placed'). INTENT/UNKNOWN rows block that
  stock+side on EVERY later day until the book shows the order or RB runs `rbtrack --resolve TAG placed|not-placed`;
  rbtrack lists open ones at start. fcntl lock data/rbtrack.lock = one rbtrack per account. orders_log only counts
  ok rows (column order kept on append). sync(): cumulative broker fills set the qty (3,3,6 -> no double count).
  tests/test_execution.py = 26 mocked checks incl. delayed book, next day, save-fail after accept, 2 processes.
  Codex re-check #3 (30 Sep, 5 bugs) FIXED: (1) ACCEPTED intent that is not final (PENDING/unknown) blocks on ANY
  day (was: only today -> next-day duplicate); TRADED older than the window -> DONE. (2) a SENT momentum SELL keeps its
  slot until the sale is confirmed (row leaves split.csv) -> rebalance buys one session after the sells (rebalance day
  buy_delay_study.py: delay 0/1/2 = 20.9/20.4/21.0% post-tax, 2013-19 12.8/12.3/13.4, 2020-26 27.4/26.5/26.1 -> ~0.5 pt/yr). (3) order POST: HTTP 5xx or a reply without an order id = STATUS UNKNOWN -> book
  lookup (was: treated as rejected -> re-run duplicated). (4) Dhan check_order_status uses the order's own
  filledQty/averageTradedPrice when the trade book is empty; sync keeps qty for non-final fills and fills without a
  price. (5) journal.sync updates an OPEN row's qty (+fees) when split.csv qty grows (3 -> 6). Tests now 36/36.
  Codex recheck #4 (30 Sep; Mac: 36/36 + Codex 6/6 pass, follow-up 0/3) FIXED: P1 a lost-reply BUY found later
  (even TRADED after midnight) is REBUILT into split.csv once by recover() (runs before plan() and in sync(); needs
  a session) from intent meta (strategy, leg, price; tracked=1 after); untracked BUY intents block the stock and hold a
  momentum slot (strategy momentum or unknown). P2 final fill without a price -> note 'PRICE?' -> re-asked every sync
  until the real average arrives. sync selects any real order id (not len>3). send_one returns (ok,res,status,tag).
  strategy_lab.run_rank(buy_delay=N). Tests 43/43.
  Codex delay backtest (30 Sep, RB pasted; own whole-share engine, Rs 10k FIXED slots, est. hist 10k universe):
  same open 14.12% / DD -19.07; buy next session old list 13.95 / -18.98; refreshed list 14.10 / -18.56; no cash
  interest 12.66. -> delay cost small (matches ours). The 14% vs our 20.4% is SIZING: fixed Rs 10k x 20 = Rs 2 L
  invested forever, growth piles up in 6% cash (lower CAGR AND lower DD). Live default = fixed Rs 10k -> decision
  for RB (milestone 2): slot = current account value / 20 like the backtest. Median hold 120 days (not 1-2 weeks).
  Codex UI asks (prototype xlsx on RB's Mac, not seen): page 1 exits / pending orders / cash + free slots / data
  freshness; compact shortlist; signal date + last complete bar + LTP time per stock; 4 '?' sectors; tracker 5/10
  session returns with costs + sample size.
  SIZING A (RB 30 Sep 2026): per-stock slot = ACCOUNT VALUE / 20 (broker_api.account_value = free cash + demat qty
  x LTP; momentum_screener.slot_for; no value/no token -> CAPITAL/SLOTS = Rs 10k). rbtrack prints the slot and plan()
  uses it; Portfolio: Actions 'Qty (auto)', Rebalance shares, Dashboard line 'Per-stock slot'. Amount column still
  overrides. Master scan Momentum_Top20 'Shares to Buy' stays per Rs 10k (shared file, no account). Tests 46/46.
  Codex prototype RB_Daily_Review_Prototype.xlsx (uploaded 30 Sep): tabs Daily_Review, Shortlist (13 cols),
  Backtest_Comparison, All_Results (64 rows), Data_Quality, Output_Changes (8-item checklist), Methods, Equity_Data.
  Codex NAV/20 numbers (535-stock cache): est-hist 22.1% same open / 22.7% +1 session refreshed, DD ~-37;
  today-survivors ~29-31% (look-ahead). Data_Quality also flags the DHAN Portfolio file as stale (27 Sep).
  30 Sep: RB installed the full code zip (MANIFEST.txt sizes) in ~/RB_Screener AND ~/Downloads/codex/RB_Screener
  (Codex review copy); both "check done", no duplicate files; tests 26/26 on the Mac (Python 3.9, LibreSSL warning harmless).
  CODEX FIXES 1-3 MERGED (30 Sep, zip RB_Screener_FIXES_1_3; built on our v3 = 36-test code, so it overlapped our
  v4/v5): Codex's recovery REPLACES ours (recover()/tracked meta gone): intent ledger + position_data (full planned
  split row as JSON, saved before the POST), position_saved, filled_qty, avg_price, avg_qty; auto_tracker_update
  recover_buys() (runs before planning + in sync; crash before reply / before split write / before marker all safe;
  legacy intent without data = blocked + reserved + warning), _fill_row (qty never goes down, price tied to the qty
  it prices, ' | fill price pending' re-asked), split.csv extra cols intent_tag, ordered_qty, filled_qty_confirmed,
  fill_avg_price, fill_avg_qty, price_pending; buy_reservations() = untracked BUYs hold momentum slots; atomic fsync
  writes; SIP log dedups order ids; Dhan lagging trade book -> price pending. position_sizing.py (slot_budget,
  whole_shares). Kept ours on top: sizing A (account value / 20, slot_for -> NAV mode), 8-char tags, account_value,
  v5 ledger columns (strategy/leg/price/tracked) auto-read into position_data. DISAGREED + changed: (a) Codex made
  FIXED Rs 10k the live AND strategy_lab default -> live stays sizing A (RB), run_rank default = NAV/N (all research
  numbers above are NAV/N); (b) their sync crashed on pandas 3 (int column <- 101.5; Mac pandas 2 only warns) ->
  sp.astype(object). run_rank now: whole shares incl. costs + accrued tax kept back from buying power (never
  negative cash). Same data, RAMOM top20 cap4: old engine 20.9% post / 22.8 pre; new 22.2 / 22.9 -> pre same, post
  +1.3 = path effect of funding tax (2013-19 -0.5, 2020-26 +2.2), NOT an edge. Delay study new engine: 0/1/2 =
  22.2/21.2/21.4 post (Codex: +1 session not robust; 0% interest flips it) -> ~0.5-1 pt/yr cost, still accepted.
  Tests: test_execution 37, reports/code_audit independent 6 + followup 3, test_recovery_tax 24, test_sizing_a 9.
  Codex funded backtest (their 535-stock cache, 6% cash): fixed Rs 10k 14.1%, NAV/20 23.3% (+1 session 22.8), DD -36.
  MOMENTUM TOP 5 HIGHLIGHT (1 Oct, Codex proposal, RB approved A+C; B = 'NEW IN TOP 5' NOT built): momentum_focus.py
  (display only) focus = selected in_top AND rank 1-5 (cap-skipped rank never replaced by 6). Gold F7E3A5 / text 79601E
  on Momentum_Top20 Symbol + Mom Rank, Actions Ticker, Signal_Tracker Symbol (MOMENTUM rows in today's focus), the
  Signal_Summary 'rank 1-5 when found' group; terminal 'TOP 5 = look here first' block; Dashboard section after
  DO / CHECK TODAY (#rank, sector, score, ~price, HELD, cohort line with signals/stocks/beat-of-compared/days/30+ =
  TOO EARLY). Signal_Summary C: + Stocks, Days tracked, Best/Worst now %, 'rank 11+ (selected)'. Not a buy signal:
  RB's 4/5 = 5 finds x 4 days; rank 6-10 also 4/5; rank_study per-stock beat ~50%. tests/test_focus.py 25.
  CAP MIX STUDY (5 Oct, cap_mix_study.py, RB's 60/25/15 Mid/Large/Small idea, pre-registered): run_rank(cap_class,
  cap_targets, cap_order) = fill 12 MID / 5 LARGE / 3 SMALL in rank order, leftovers MID > LARGE > SMALL. Class =
  rank by est. mcap among loaded NSE stocks (1-100 L, 101-250 M, 251+ S). Post-tax 2013-19 / 2020-26 / FULL / DD /
  trades: BASE 11.7 / 30.3 / 22.0 / -33.9 / 44; MIX 60/25/15 14.7 / 30.4 / 23.6 / -35.2 / 56. Post-hoc checks:
  50/30/20 14.3 / 31.3 / 23.0; 70/20/10 15.7 / 30.3 / 21.3; mid-first no target 14.3 / 26.7 / 21.8. Raw top 20:
  2013-19 L 12.8 / M 7.0 / S 0 (no smallcaps were >= 10k then), 2020-26 L 5.5 / M 7.7 / S 6.1. -> gain = less
  LARGE in 2013-19; 2020-26 equal. NOT live yet (RB decides). ChatGPT technical research (5 Oct, 20 finds of 26 Sep):
  no pre-signal common rule (35 indicators, BH q>=0.13); later pullback->reversal->continuation fits the 4 winners
  in hindsight only; short-horizon (5/10 session) momentum unstable by period. cap_class.py (display): 'Mcap (Rs Cr)'
  + 'Cap Class' appended at the END of every table sheet (skip Dashboard/Holdings/Journal/SIP/Signal_Summary) in the
  master (signal_tracker) + Portfolio (before xl_fit); AMFI-style rank in NSE's full mcap file (2,600 names).
  Dashboard Top-5 lines show the class. tests/test_cap_class.py 12.
  LIVE 5 Oct (RB approved): (1) CAP MIX in momentum: momentum_screener.CAP_TARGETS {M 12, L 5, S 3}, CAP_ORDER
  M>L>S>?; fill_slots() = run_rank's logic, used by select() (Momentum_Top20 = in_top) and rebalance_plan() (kept
  holdings count toward class + sector); class = cap_of() via cap_class.py (NSE full mcap rank); CAP_TARGETS=None
  = old rank-only rule. Holdings still kept while rank <= 40. (2) BUY PLANNER (buy_planner.py): sheet 'Buy_Planner'
  right after Dashboard: account (broker cash, holdings value/cost, unrealised, realised = LIVE closed journal
  NET, 'Kul paise add kiye' typed once -> settings.json money_added, overall), budget (settings planner_budget)
  split by class % (C21:C23, settings planner_shares) equal inside a class, empty class -> top class present,
  'Qty (you)' fixes a row and re-splits the rest, whole shares + one +1-share leftover pass down the list.
  Shortlist = momentum top 20 + W+TT BUY/FIT (no LATE), order Mid > Large > Small, Super-Buy, mom rank, RS.
  Pick/Qty kept same day only. Live formulas; rbtrack planner_rows() re-reads the INPUTS and recomputes with
  buy_planner.distribute() (= the formulas, checked with pycel) -> act BUY rows with 'Qty' -> plan() uses that qty
  (CNC only; momentum 20-slot / 4-industry checks still apply). Planner wins over an Actions BUY for the same stock.
  (3) Actions dropdown = BUY MTF / WATCH (old BUY rows still read). xl_fit + cap columns skip Buy_Planner.
  feature_study.py (3,140 monthly top-20 picks 2013-26, 15 technical features, pass = same sign >= 2 pts + t >= 2
  in both halves): NONE passes; median 3m excess by class Mid +2.3 / +1.8 best in both halves (L +0.7 / -0.4,
  S 2020-26 -2.2). tests/test_planner.py 23.
  6 Oct (RB): Actions sheet GONE from the Portfolio file (portfolio.ACTIONS_SHEET = False; rbtrack still reads an old
  file's Actions). Buy_Planner Pick dropdown = BUY / MTF / WATCH, blank = not taken (old 'YES' read as BUY, never
  offered). MTF rows: own money per share = price / 'MTF leverage (andaaza)' E19 (default 4, settings planner_mtf_lev);
  auto MTF -> rbtrack 'BUY MTF' with own Rs as Amount (broker leverage sets qty), own Qty -> exactly that qty.
  WATCH -> watchlist (rbport + rbtrack). tests/test_planner.py 29.
  6 Oct (RB): SELL from the Holdings CARDS -- no Sell sheet (portfolio.SELL_SHEET = False). Every LIVE demat card gets
  2 rows: caption SELL_CAP + 'Sell qty (held N, CNC|MTF)', then inputs Sell? (dropdown SELL / blank) + Sell qty
  (whole >= 1). sell_rows(): rule rows first (EXIT / SELL@REBAL / SELL, default SELL only if backtested + TRADING
  ON, qty = firing legs) + every other LIVE demat stock (blank, qty = all held); same-day picks (pick, qty) kept,
  qty capped at held. read_sell_table() finds the caption cells (symbol 9 rows above); old files' Sell sheet still
  read (YES -> SELL). rbtrack read_sells(): SELL rows, blank qty = all held; place_sells still re-checks the demat.
  tests/test_holdings_sell.py 13.
  6 Oct (RB): TODAY'S gain/loss per stock: analyse() 'Aaj %' + 'Aaj (Rs)' = last bar vs the one before x qty
  (load_prices puts today's live price as the last bar once the session started; before that / weekends it is the
  last session -> card label 'Last session DD Mon'). Card line 1 'Aaj' (green/red), Holdings_Table columns, Holdings
  P&L box + Dashboard holdings line + terminal 'aaj +Rs X'. Cards are 1 row taller: Sell caption at r0+10 (symbol 10
  rows above; read_sell_table also accepts 9 for the first v11 files). tests/test_holdings_sell.py 17.
  6 Oct: RB's screenshot (Ashish G Angel, 37 stocks) -> prices checked vs NSE bhavcopy 29 Sep: DISHTV 2.15 (554 sh =
  Rs 1,163, entry 21.97 = -90% is REAL), IRFC 80.26, IRCON 102.47 -> correct. Day change now uses the last bar of a
  strictly EARLIER date (two bars for today -> was 0.00%); LIVE/PAPER band on Holdings shows 'AAJ +/-Rs X (y%)'.
  tests/test_holdings_sell.py 19.
  6 Oct (RB: "1,163 invested hai kya?"): card row 2 = 'Lagaya Rs <entry x qty> -> Ab Rs <value>' (mode is on the band),
  line 'Qty: buy -> aaj' = 'N sh @ entry -> LTP'; Holdings_Table + 'Invested (Rs)'. tests/test_holdings_sell.py 21.
  NEXT (Codex plan, one at a time): 2 shared live/backtest spec module; 3 better history (NSE old CM bhavcopies incl.
  delisted, corporate actions); 4 risk controls tradeoffs; 5 separate 1-2 week strategy = research + paper ledger only.
  GTT/SL (Codex+RB 30 Sep): A = W+TT swing leg only first (momentum stop = strategy change, needs its own backtest);
  B = per broker (Kite GTT LIMIT-only, Dhan Forever MARKET/LIMIT), model each fill separately; a GTT SELL and an
  AMO SELL must never both hold the same qty (cancel/shrink the GTT before an AMO SELL) -> needs its own test. Dhan order APIs need a
  whitelisted STATIC IP (docs) -> needed before TRADING ON.
- 29 Sep: Angel getCandleData rate limit (3/s, 180/min) -> HTTP 403 'exceeding access rate' was read as a bad token,
  the fill stopped after ~50 big caps and momentum ranked ONLY those (liq needed the last bar). Fixed: throttle,
  rate-limit = retry, per-stock failures skip, loud 'N stocks not filled' warning, liq min_periods=50.
- 30 Sep: gap fill first from NSE CM bhavcopy (broker_api.bhav_fill, BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip,
  series EQ/BE/BZ, cached data/_bhav/, split guard 0.6-1.4x) -> broker only for leftovers + Nifty + today's bar before
  NSE publishes it (evening). Checked vs eod2: 4578 stock-days (23-25 Sep), 0 mismatches in OHLC and volume.
  NSE sometimes 403s one header set -> tries NSE_HDRS, plain UA, NSE_HDRS.
- NEVER put the token inside a .py file or print it. It once got pasted into position_tracker.py docstring (fixed).
- Copying a terminal command overwrites the clipboard - don't use `pbpaste` right after copying a command.
- Dhan may not publish today's daily candle until later in the evening; prices are still live.
- Dhan 401/403 when token is not expired = check Data API subscription.
- position_tracker.py (v2) imports daily_screener.py for prices, so both files must sit in ~/RB_Screener.
  Verdicts marked "*" use today's live price during market hours - only valid if the stock closes there.
  Exit rules are checked on every bar since entry_date (split.csv): a missed exit shows "rule already fired".
  Keep entry_date in split.csv correct (YYYY-MM-DD) or only today's bar is checked.
- Screener and backtest.py give identical signals (checked 25 Sep 2026: 52 signals in 20 sessions,
  43 FIT/LATE + 9 NO-FIT, zero mismatches).
- NSE / BSE APIs block cloud servers (403). Tickertape API works (fund_history.py). Tickertape search still
  lists some OLD tickers (MOTHERSON -> MOTHERSUMI); a single EXACT match is accepted.
- FIT has no lower bound: a stock can be FIT at -19% vs signal (NIACL, 25 Sep) = right above the
  original stop. The terminal now prints % vs signal for every FIT name.

## Pending / next steps
1. DONE (v2): position_tracker.py uses Dhan gap-fill + live price + client ID from token; fixed M&M history filename bug.
2. DONE: backtest.py pit10k + portfolio study (see above). Next: add tax (STCG/LTCG) to the portfolio sim.
3. DONE: fundamentals.py v2 (columns + Fundamentals sheet in the same file, nothing removed); gate backtested (no benefit).
4. DONE: RS >= 85 worse in both halves -> keep RS >= 70.
5. DONE: 20 slots beat 10 slots in both halves -> keep 20 x 5%.
6. Paper-trade 2-3 months before real money on the new universe.
7. DONE: 5/8/20 slots with real Dhan costs + tax (see "Fusion backtest"): W+TT swing collapses at 5-8 slots.
8. DONE: Fusion cash + F&O backtest (see "Fusion backtest"). Next: a live Fusion screener (RS-ranked) if RB wants it.
9. Tax (STCG/LTCG) in the portfolio sim. Optional: strategies on Gold ETF / BTC-ETH with fees.
10. Optional: VCP rule test (Minervini) - old chat: "Minervini alone" 6.75% CAGR, "O'Neil L+M" 6.81% (173 stocks).
11. DONE: live momentum chain (momentum_screener.py, auto_tracker_update.py, tracker momentum leg). Next: paper trade it.
12. DONE: BUY MTF / PAPER MTF (4x qty, "YES MTF" confirm, MTF summary in tracker) -- leverage test above says no.
14. DONE: multi-broker adapter (broker_api.py) + accounts/<BROKER>_<ID>/. Angel/Zerodha untested live.
15. IDEAS PARKED (27 Sep, RB: "yaad dilaate rehna, research karte rehna") -- REMIND RB at the start of new work:
    a) `rb --all`: ONE folder ~/RB_Screener/users/*.txt (token.txt format + 'Telegram Chat ID:' + 'Active: YES/NO',
       chmod 700, never Drive) -> master scan once, then per active user: holdings/SIP/file/Drive + Telegram to
       THAT user only; one bad token never stops the others (alert that user). Orders stay rbtrack-only, per account.
       Needs account.activate() to take a token-file path. Limits: Dhan token daily by hand (Angel AUTO ok), all
       keys in one folder (FileVault!), each user /start's the bot once, get their consent.
    b) Auto-run: macOS launchd weekdays ~16:15 -> rb (or rb --all); pair with Telegram alerts.
    c) 'Telegram Chat ID:' line in token.txt instead of `telegram_alert.py link` (phone number can NOT be used:
       bots need chat_id and the user must /start first).
    d) Moneycontrol: NO login scraping (ToS, password risk, news never changes a verdict); optional free public
       RSS feeds in news_feed.py if RB wants.
    e) Research to do before building a): per-user token storage, SEBI retail-algo rules for API orders
       (static IP / registration) before any unattended orders, Telegram rate limits, launchd + sleep/wake.
    f) ORDER FLOW (29 Sep, RB: "abhi nahi"): use only as an ENTRY TIMING filter on W+TT/momentum picks (delta, VWAP,
       book imbalance -> 'BUY OK / WAIT' column), never a stock picker, never overrides exit rules. Tick history is
       quote-only/expensive (TickData.com NSE since 2012 ~Rs 2.5-8 L+ guess; NSE D&A; TrueData tick = 5-20 days only)
       -> not worth it on Rs 2 L. Plan if revived: 1) free daily proxies first (close location / A-D line, NSE
       delivery %) as entry filters, pre-registered, both halves; 2) only if they help, self-record Dhan/Angel feed
       (needs 2-3+ yrs, ~300 trades per group, incl. a bear phase).
13. DONE: PAPER mode + news, Dhan AMO buy bridge (untested against the real Dhan API from the cloud -- first live use:
    ONE row, ONE share, then check the Dhan order book), Rebalance_Dashboard sheet (SELL/BUY/HOLD per LIVE/PAPER).
