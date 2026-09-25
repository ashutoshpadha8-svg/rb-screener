# RB_Screener — project context (handoff from claude.ai chat, 24 Sep 2026)

## Who I am / how to talk to me
- I'm RB. Casual Hinglish please.
- Trading feedback: direct and honest, no encouragement. If an idea is bad, say so with numbers.
- Teach one step at a time, not big info dumps.
- I run Python scripts but don't write code from scratch. Give exact terminal commands.
- Mac Mini, zsh, Python 3.9 (pip3). Everything lives in `~/Desktop/RB_Screener`.

## Folder layout
```
~/Desktop/RB_Screener/
  daily_screener.py     # v4 - main screener (run daily)
  position_tracker.py   # hold/exit tracker for my positions (swing + investing legs)
  fundamentals.py       # fundamental check on the screener shortlist (Screener.in public pages)
  backtest.py           # backtest of the screener rules (pit10k / today10k / b173 universes)
  FUNDAMENTALS.md       # research + thresholds behind fundamentals.py
  dhan_token.txt        # today's Dhan access token, one line. NEVER print or copy it anywhere
  data/                 # cached price history, NSE market-cap file, Dhan scrip master
  reports/              # RB_Screener_YYYY-MM-DD.xlsx (sheets: Swing, Investing; fundamentals.py
                        #   adds green columns to both + a Fundamentals sheet in the SAME file)
```
Shortcut: `rbscan` (zsh alias, since 25 Sep 2026) = screener THEN fundamentals:
`python3 ~/Desktop/RB_Screener/daily_screener.py && python3 ~/Desktop/RB_Screener/fundamentals.py`
(fundamentals only runs if the screener succeeded; ~3 s per shortlisted stock).
Daily routine: paste fresh Dhan token into dhan_token.txt (TextEdit, Cmd+A, Cmd+V, Cmd+S), then `rbscan`.

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
