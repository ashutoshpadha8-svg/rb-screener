# Futures Prop Bot — Plan (started 27 Sep 2026)

Fresh project, separate from the NSE swing screener. Nothing from the swing system carries over.

## Fixed decisions
- Firm: Topstep (EOD trailing drawdown, official ProjectX API allows bots in Combine + Express).
- Apex is out: its rules ban AI/bots/algos on all account types.
- Instruments: micros only (MES $5/pt, MNQ $2/pt). Full ES = $50/pt is too big for a $2,000 drawdown.
- Payout: bank wire / Rise only. No crypto.

## Topstep API rules (verify before going live)
- ProjectX API: $29/mo ($14.50 with code "topstep"). REST + WebSocket, works from Python.
- Allowed: Combine, Express Funded. NOT allowed: Live Funded via API.
- Orders must come from own device (Mac Mini). VPS / VPN / remote server = banned.
- No HFT. No sandbox - test on Practice account.
- Get written confirmation from Topstep support before running live.

## Phases (one at a time)
1. Data: 5-8 years of ES/NQ 1-minute bars (Databento, CME Globex OHLCV-1m).
2. Backtester with Topstep rules built in: $2,000 EOD trailing DD (50K), $3,000 target,
   flat by 4:10 PM ET, commission + 1 tick slippage per side, contract limits.
3. Test candidates, in-sample 2018-2022, out-of-sample 2023-2026:
   a. Intraday momentum / noise-area breakout (Zarattini, Aziz, Barbon 2024)
   b. Opening Range Breakout 5/15/30 min (Zarattini & Aziz 2023)
   c. Market intraday momentum, first 30 min -> last 30 min (Gao, Han, Li, Zhou 2018)
   d. VWAP mean reversion (for comparison)
   Key metric: % of simulated Combines passed vs blown, not just total return.
4. Pick 1 strategy that survives out-of-sample. If none survives, stop - don't buy an eval.
5. Bot: Python on Mac Mini -> ProjectX API. Every entry sent as a bracket order (stop at exchange).
   Kill switch at daily loss limit. Logs every order.
6. Practice account paper run: 4+ weeks, live results must match backtest.
7. Buy Topstep 50K Combine. Cancel subscription the day it passes.

## Results log

### Run 1 - 27 Sep 2026 (Dukascopy index CFD 1-min, 2016-2026, costs 1 tick slip/side + $0.75/side)
Paper parameters, no optimisation. IS = 2016-21, OOS = 2022-26. $/1 micro after costs.

| Strategy | Mkt | IS avg$ / PF / Sharpe | OOS avg$ / PF / Sharpe | Verdict |
|---|---|---|---|---|
| NOISE  | MNQ | +5.4 / 1.22 / 1.24 | +8.6 / 1.14 / 0.90 | Candidate #1 |
| ORB5   | MNQ | +3.0 / 1.10 / 0.47 | +9.5 / 1.13 / 0.61 | Candidate #2 |
| ORB30  | MNQ | -1.3 / 0.97 | +18.0 / 1.18 | Regime-dependent, reject |
| LAST30 | MNQ | negative | negative | Reject |
| VWAPMR | MNQ | negative | negative | Reject |
| All 5  | MES | ~0 or negative after costs | | S&P too slow for costs |

Combine pass rate (50K, $3k target, $2k EOD trailing MLL, 50% consistency), full period:
NOISE ~23-27%, ORB5 ~24-37% vs zero-edge baseline 13-28%. Median 60-300 sessions to pass.
=> Edge is real but thin; ~70% of Combines still fail. Next: improve pass rate (trade filters,
risk per trade), then confirm on real MNQ futures data before any money.
