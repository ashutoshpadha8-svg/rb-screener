# RB_Screener — project context (handoff from claude.ai chat, 24 Sep 2026)

## Who I am / how to talk to me
- I'm RB. Casual Hinglish please.
- Trading feedback: direct and honest, no encouragement. If an idea is bad, say so with numbers.
- Teach one step at a time, not big info dumps.
- I run Python scripts but don't write code from scratch. Give exact terminal commands.
- Mac Mini, zsh, Python 3.9 (pip3). Everything lives in `~/Desktop/RB_Screener`.
- Trading capital ~Rs 2 lakh. Full history of the earlier claude.ai chat (Fusion strategy, EMA 9/33, crypto,
  gold, money maths) is in CHAT_HANDOFF.md.

## Folder layout
```
~/Desktop/RB_Screener/
  daily_screener.py     # v4 - main screener (run daily)
  position_tracker.py   # hold/exit tracker for my positions (swing + investing legs)
  fundamentals.py       # fundamental check on the screener shortlist (Screener.in public pages)
  backtest.py           # backtest of the screener rules (pit10k / today10k / b173 universes)
  fusion_backtest.py    # Fusion vs W+TT, cash + stock futures, real Dhan costs + Indian tax
  fno_data.py           # downloads NSE F&O bhavcopy history (2013+) into data/fno/
  strategy_lab.py       # 16 pre-registered strategies (momentum, low-vol, mean reversion, timing) vs baselines
  momentum_screener.py  # LIVE momentum (RAMOM top 20, sector cap 4) -> Momentum_Top20 + Strategy_Comparison sheets
  auto_tracker_update.py# rbtrack: Action BUY -> Dhan AMO (CNC, MARKET @ open, type YES) -> split.csv LIVE;
                        #   BUY MTF -> productType MTF, qty floor(10000x4/LTP), type "YES MTF";
                        #   PAPER / PAPER MTF -> split.csv PAPER; --sync = real fills; --no-orders; --dry-run
  broker_api.py         # ONLY place that talks to a broker: Dhan / Angel One (SmartAPI) / Zerodha (Kite)
                        #   prices, history fill, holdings, funds, AMO BUY (CNC/MTF), order status. No selling.
  news_feed.py          # Google News RSS headlines (no key, no extra package)
  split.csv             # symbol,swing_qty,investing_qty,momentum_qty,entry_price,entry_date,strategy,mode,product,order_id,note
  data/orders_log.csv   # every AMO attempt (ok / error) -> blocks a second order for the same stock that day
  FUNDAMENTALS.md       # research + thresholds behind fundamentals.py
  account.py            # token.txt -> broker + client + token -> accounts/<BROKER>_<ID>/ (see below)
  token.txt             # (was dhan_token.txt, auto-renamed once) Broker: / Client ID: / Name: / Token: lines. NEVER print or copy the token anywhere
  data/                 # SHARED market data: price history, NSE files, scrip master, Screener pages,
                        #   momentum_ranks_latest.csv, _nse_industry.csv (same for every account)
  accounts/<BROKER>_<CLIENT_ID>/  # PER ACCOUNT, e.g. DHAN_1100120973 (name never in the path)
    data/               #   split.csv, split_backup.csv, orders_log.csv
    reports/            #   RB_Screener_YYYY-MM-DD.xlsx (Swing, Investing, Momentum_Top20, Strategy_Comparison,
                        #   Rebalance_Dashboard, Fundamentals), RB_Fundamentals_*, tracker_*.csv
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
Shortcut: `rbscan` (zsh alias, since 26 Sep 2026) = daily_screener -> momentum_screener -> fundamentals
(each step only runs if the previous one succeeded). `rbtrack` = auto_tracker_update.py.
Daily routine: paste fresh Dhan token into token.txt (TextEdit, Cmd+A, Cmd+V, Cmd+S), then `rbscan`,
review Rebalance_Dashboard + Strategy_Comparison, pick BUY / BUY MTF (real AMO), PAPER / PAPER MTF (mock) or WATCH
(no order) from the Action DROPDOWN (data validation on the stock rows only), save, close
Excel, then `rbtrack` after 15:30 (it refuses AMOs during market hours). Next morning after the open:
`rbtrack --sync` (real fill prices). position_tracker.py shows LIVE legs, a PAPER PORTFOLIO section, totals and news
(`--no-news` to skip). Momentum trades only on the 1st trading day of the month; keep while rank <= 40.
Sells are NOT automated (place them in Dhan yourself).

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

## Fundamental layer (research done)
Order of checks: 1) red flags (promoter pledge > 20% = out, auditor resignation/qualification, SEBI/forensic action)
2) quality (ROE/ROCE >= 15% investing, >= 10-12% swing; D/E <= 1 non-financials; CFO/PAT >= 0.7-0.8 over 3-5 yrs; no loss year in 5-6 yrs)
3) earnings momentum (latest qtr profit YoY >= 20-25%, sales YoY >= 15-20%, not decelerating 2 qtrs; watch other income)
4) valuation only as sanity check - never reject Stage-2 leaders for high P/E.
Banks: Net NPA < 1-2%, CRAR >= 15%, ROA >= 1%. NBFC: GNPA < 3%, ROA >= 2%. Insurance: solvency >= 180%.
Data: Screener.in watchlist with columns ROCE, ROE, Debt to equity, Pledged percentage, YOY Quarterly profit growth,
YOY Quarterly sales growth, Profit growth 3Years, Sales growth 3Years. For backtests use result broadcast dates (NSE/BSE filings), not quarter-end.

## Known gotchas
- NEVER put the token inside a .py file or print it. It once got pasted into position_tracker.py docstring (fixed).
- Copying a terminal command overwrites the clipboard - don't use `pbpaste` right after copying a command.
- Dhan may not publish today's daily candle until later in the evening; prices are still live.
- Dhan 401/403 when token is not expired = check Data API subscription.
- position_tracker.py (v2) imports daily_screener.py for prices, so both files must sit in ~/Desktop/RB_Screener.
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
13. DONE: PAPER mode + news, Dhan AMO buy bridge (untested against the real Dhan API from the cloud -- first live use:
    ONE row, ONE share, then check the Dhan order book), Rebalance_Dashboard sheet (SELL/BUY/HOLD per LIVE/PAPER).
