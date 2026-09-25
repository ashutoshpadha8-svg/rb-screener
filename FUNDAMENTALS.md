# FUNDAMENTALS.md — Fundamental layer for RB_Screener

Research done 24 Sep 2026 (claude.ai session). Read together with CLAUDE.md.

> BACKTEST RESULT (26 Sep 2026, backtest.py --fundamentals, 2018-2026, point-in-time):
> the section 9 swing gate did NOT help this price system - in 2018-21 PASS stocks did far worse
> than FAIL stocks, in 2022-26 no difference. The index evidence in section 2 does not carry over to
> "fundamentals on top of a Stage-2 breakout". Details in CLAUDE.md. Use as information only.
Goal: add a fundamental check on top of the technical screener (Weinstein + Minervini + RS)
for NSE stocks with market cap >= Rs 10,000 Cr, separately for SWING and INVESTING lists.

## 1. Core principle (do not violate)

Fundamentals are a **loose gate + light ranking**, never a tight filter and never an override of the price rules.
- Gate = remove red flags and junk.
- Rank = tilt towards quality and earnings momentum.
- Do NOT reject Stage-2 leaders for high P/E. Value is the weakest factor in Indian data and fights momentum.

## 2. What the evidence says (India)

| Factor | Evidence | Use |
|---|---|---|
| Price momentum | Nifty500 Momentum 50: 23.0% CAGR vs Nifty 500 14.9% (Apr 2005–Jun 2025), vol 22.6% | Core engine (already in screener) |
| Quality (ROE, low D/E, stable EPS growth) | Nifty200 Quality 30 TRI 18.2% vs 14.6% (2005–2025); max DD -56% vs -64% | Gate + tie-breaker |
| Momentum + Quality blend | Nifty500 Multicap Momentum Quality 50: 22.0% CAGR, vol 19.1%, beta 0.83; FY2019-20 -12.2% vs -21.6% pure momentum | The template to copy |
| Earnings surprise / PEAD | Harshita, Singh & Yadav (2018), Nifty 500 2002–2017: drift over days +2..+64 after results, top SUE decile +3.4%, bottom -1.4%; stronger in high-P/B stocks | "C" of CAN SLIM; swing timing |
| Value (low P/E, P/B) | Nifty500 Value 50: 17.0% CAGR but vol 25.9%, lowest risk-adjusted; -48.4% FY2019-20 | Sanity check only |
| Piotroski F-score | Weak/thin Indian evidence | Red-flag detector (<= 3 bad) |
| Promoter pledge | Kalia (2024), BSE 500 2011–2020: pledging raises crash risk; NSE Momentum-Quality index excludes pledge > 20% | Hard exclusion |
| Accruals / cash quality | Strong globally, thin in India | CFO/PAT gate |

Caveat: most Indian factor-index history before launch is back-tested. Treat as supportive, not proof.
Thresholds below are practitioner conventions, not optimised values.

## 3. NSE quality score (copy this method)

From NSE Quality index methodology:
- Inputs: ROE (latest FY), Debt/Equity (latest FY), EPS-growth variability (std dev of yearly EPS growth, last 5 years).
- Z-score each input within the universe.
- Non-financials: Q = 0.33*Z(ROE) - 0.33*Z(D/E) - 0.33*Z(EPS variability)
- Financials (banks/NBFC/insurance): Q = 0.5*Z(ROE) - 0.5*Z(EPS variability)  (D/E dropped)
- Exclude any stock with negative EPS in any of the last 6 fiscal years.

## 4. Parameter checklist and thresholds

### 4a. Red flags (hard exclusion, both lists)
- Promoter pledge > 20% of promoter holding, or pledge rising quarter on quarter.
- Statutory auditor resignation mid-term, qualified opinion, going-concern emphasis (last 2 years).
- SEBI / ED / SFIO action, forensic audit, results delayed beyond SEBI deadline.
Soft flags (2 or more = exclude for investing):
- CFO/PAT < 0.5 over 3+ years while profit grows.
- Debtor days or inventory days rising much faster than sales.
- Recurring "other income"/exceptional gains driving EPS growth.
- Contingent liabilities > 20-25% of net worth; big guarantees to group companies.
- Repeated preferential allotments/warrants to promoters; frequent QIPs without ROCE improvement.
- Promoter holding falling steadily with no reason; frequent CFO/independent director resignations.
- Large cash AND large borrowings at the same time; complex subsidiary structures.
- Piotroski F-score <= 3.

### 4b. Quality
| Parameter | Swing | Investing |
|---|---|---|
| ROE / ROCE (3-yr avg) | >= 10-12% | >= 15% (>= 20% strong) |
| Debt/Equity (non-financials) | <= 1.5 | <= 1.0 (<= 0.5 ideal) |
| Interest coverage | skip | >= 3x |
| CFO/PAT (3-5 yr cumulative) | skip | >= 0.7-0.8 |
| Loss years | allowed | none in last 5-6 years |
| Operating margin | skip | stable/rising over 4-8 quarters |

### 4c. Earnings momentum (CAN SLIM C & A)
| Parameter | Threshold |
|---|---|
| Latest quarter EPS/profit growth YoY | >= 20-25% (O'Neil floor 18-20%, ideal 40%+) |
| Latest quarter sales growth YoY | >= 15-20% |
| Acceleration | growth rising in 2 of last 3 quarters; 2 consecutive decelerations = warning |
| SUE proxy | (EPS this qtr - EPS same qtr last year) / price; top 20-30% of universe |
| Annual EPS | up each of last 3 years; 3-yr EPS CAGR >= 15% (large caps) |
| 3-5 yr sales CAGR | >= 12-15% |
Adjust: strip other income and exceptional items; ignore low-base jumps (e.g. after a loss quarter).

### 4d. Valuation (sanity check only)
- P/E > 2x own 10-yr median AND growth decelerating = caution for investing list. Never reject swing names on P/E.
- PEG > 3 = priced for perfection. EV/EBITDA for cyclicals. P/B only for lenders.

### 4e. Ownership
- Promoter holding flat/rising; drop > 2-3 pp in a year without disclosed reason = investigate.
- FII + DII holding rising over last 1-4 quarters = positive (CAN SLIM "I").
- Shares outstanding growth <= 2-3% per year.

## 5. Sector rules (general D/E rules do NOT apply to financials)

| Sector | Check |
|---|---|
| Banks | Net NPA < 1-2%, Gross NPA < 3%, CRAR >= 15%, ROA >= 1%, ROE >= 14%, NIM >= 3%, PCR >= 70% |
| NBFCs | GNPA/Stage-3 < 3%, ROA >= 2%, CRAR >= 15% (RBI min), no ALM mismatch |
| Insurance | Solvency >= 180% (IRDAI min 150%); life: VNB margin, persistency; general: combined ratio < 100-105% |
| IT | CC revenue growth, EBIT margin >= 20% tier-1, CFO/PAT >= 0.9 |
| Metals/cement/commodities | 5-7 yr average ROCE & margins, net debt/EBITDA <= 2x; lowest P/E often = cycle top |
| Capital goods/infra/defence | order book / sales 2-4x, order inflow growth, receivable days |
| Pharma | US FDA status (warning letters, import alerts) overrides ratios |
| FMCG | volume growth, gross margin, negative working capital is normal |

## 6. How to combine with the technical screener

1. Run technical screener unchanged.
2. Apply red-flag gate (4a hard flags).
3. Apply list-specific quality gate (4b: loose for swing, full for investing).
4. Rank survivors: score = 0.50 * RS percentile + 0.25 * earnings-momentum percentile (SUE / qtr EPS growth) + 0.25 * quality percentile (section 3).
5. Swing: prefer breakouts within ~60 trading days after a strong result (PEAD window).
6. Expect the blend to lag in some years (e.g. momentum-quality index FY2024-25 -4.5% vs Nifty 500 +6.4%).

## 7. Look-ahead bias (critical for any backtest)

- SEBI LODR Reg 33: quarterly results within 45 days of quarter-end; Q4/annual within 60 days.
- A quarter's numbers are usable only from the NEXT trading session after the exchange broadcast timestamp (results often come after market hours).
- Never use quarter-end dates. Annual ratios (ROE, D/E) usable only after the annual/Q4 result (~late May).
- Screener.in and similar sites restate history and have no announcement dates = NOT point-in-time. Fine for live screening, not for backtests.

## 8. Data sources

| Need | Source |
|---|---|
| Live screening | Screener.in (free: query builder, watchlists, per-company Excel export; Premium Rs 4,999/yr: CSV export of full screens) |
| Quarterly results + broadcast date/time | NSE Corporate Filings -> Financial Results (CSV, XBRL-to-Excel); BSE Corporate Announcements/Results |
| Upcoming result dates | NSE Corporate Filings -> Board Meetings; BSE results calendar |
| Shareholding / pledge | NSE/BSE quarterly shareholding pattern filings |
| RPTs, contingent liabilities, auditor report | Company annual reports |
| Indian factor returns | IIM Ahmedabad Fama-French & momentum data library (free) |
| Point-in-time history | CMIE Prowess, ACE Equity (institutional/paid) |
| Unofficial BSE API wrapper | github.com/BennyThadikaran/BseIndiaApi |

Screener query examples (use exact field names from Screener autocomplete):
- Investing gate: `Market Capitalization > 10000 AND Return on capital employed > 15 AND Average return on equity 3Years > 15 AND Debt to equity < 1 AND Profit growth 3Years > 15 AND Sales growth 3Years > 12 AND Pledged percentage < 5`
- Swing "C": `Market Capitalization > 10000 AND YOY Quarterly profit growth > 25 AND YOY Quarterly sales growth > 20 AND Pledged percentage < 20`

## 9. Priority checklists

### Investing (hold long term)
1. Governance red flags (none)
2. Pledge 0-5%, never > 20%
3. ROCE/ROE 3-yr avg >= 15%
4. D/E <= 1 and interest cover >= 3x (banks: CRAR >= 15%, NNPA < 1-2%)
5. CFO/PAT 3-5 yr >= 0.7-0.8
6. No loss year in 5-6 yrs, low EPS variability
7. 3-yr profit CAGR >= 15%, sales CAGR >= 12%
8. Last 2 quarters EPS & sales YoY positive, not sharply decelerating
9. Promoter flat/rising; FII+DII flat/rising
10. P/E not > 2x own 10-yr median with slowing growth

### Swing (fast; price trigger dominates)
1. Hard red flags only (pledge < 20%, no auditor/forensic issue)
2. Latest qtr EPS growth YoY >= 20-25% (ex other income, no low base)
3. Latest qtr sales growth YoY >= 15-20%
4. Breakout within ~60 trading days of a strong result
5. EPS acceleration (bonus)
6. SUE in top 30% (ranking input)
7. FII+DII rising last 1-2 qtrs (bonus)
8. Minimum quality: ROE >= 10-12%, D/E <= 1.5 (non-financials)

## 10. Implementation task for Claude (cloud session)

Build `fundamentals.py` that:
1. Reads the latest `reports/RB_Screener_YYYY-MM-DD.xlsx` (sheets Swing, Investing) OR a list of symbols.
2. Reads fundamentals from a CSV the user provides (Screener.in watchlist/screen export). Map columns by fuzzy name match; print which columns were found/missing.
   Expected columns: Symbol/NSE code, ROCE, ROE (3yr avg if available), Debt to equity, Pledged percentage,
   YOY Quarterly profit growth, YOY Quarterly sales growth, Profit growth 3Years, Sales growth 3Years,
   (optional) Industry/Sector, Interest coverage, CFO, Net profit, Piotroski score.
3. Detects financials (bank/NBFC/insurance) by industry text and skips D/E for them; marks "check NPA/CRAR manually".
4. Applies section 9 checklists separately for Swing and Investing -> adds columns: FUND_PASS (PASS/FAIL/CHECK), FAILED_RULES (text), FUND_SCORE.
5. Writes a new Excel next to the original with the added columns (keep Swing/Investing sheet names), using openpyxl, Arial font, rules explained in notes below the table.
6. Missing data = CHECK, never silent PASS.
7. Must run on RB's Mac: Python 3.9, pandas, openpyxl. No secrets in code. Never read or print dhan_token.txt.
8. Do not change daily_screener.py signal rules.
Later (separate task): backtest the fundamental gate using result broadcast dates only (section 7).
