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
