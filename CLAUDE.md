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
  dhan_token.txt        # today's Dhan access token, one line. NEVER print or copy it anywhere
  data/                 # cached price history, NSE market-cap file, Dhan scrip master
  reports/              # RB_Screener_YYYY-MM-DD.xlsx (sheets: Swing, Investing)
```
Shortcut: `rbscan` (zsh alias) = `python3 ~/Desktop/RB_Screener/daily_screener.py`.
Daily routine: paste fresh Dhan token into dhan_token.txt (TextEdit, Cmd+A, Cmd+V, Cmd+S), then `rbscan`.

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

## Fundamental layer (research done, not yet coded)
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
- position_tracker.py still uses its own CLIENT_ID constant and the free (lagging) data source for exit decisions - needs the same Dhan gap-fill fix as the screener.

## Pending / next steps
1. Fix position_tracker.py: Dhan gap-fill + live price + read client ID from token (exit decisions on stale data are dangerous).
2. Backtest the >= Rs 10,000 Cr universe with the same rules (point-in-time where possible).
3. Add fundamental columns/PASS-FAIL to the Excel (needs Screener export or another data source).
4. Test RS >= 85 filter effect on win rate vs total return.
5. Position sizing: backtest used 20 slots x 5% each; 20% stop = ~1% capital risk per trade.
6. Paper-trade 2-3 months before real money on the new universe.
