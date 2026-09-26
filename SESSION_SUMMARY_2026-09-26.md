# SESSION_SUMMARY_2026-09-26.md — Claude Code session ka poora saar (25-26 Sep 2026)

Pichhli chat ka saar `CHAT_HANDOFF.md` mein hai. Ye file **is session** ka saar hai:
kya bana, kya test hua, results kya aaye, kaunse options hain, aage kya karna hai.
Saare exact numbers `CLAUDE.md` mein bhi hain. Code branch: `claude/vibrant-wright-eoo926`
(repo `ashutoshpadha8-svg/rb-screener`).

---

## 1. Ek line mein nateeja

- **Sabse achi strategy mili: Momentum (NSE-style, top 20, har mahine).** Tax ke baad ~18.7%/saal
  (2013-2026), Nifty ~9.8%. Realistic umeed ~13-16%/saal, girawat -40% tak.
- **F&O (stock futures):** kisi bhi strategy ke saath **nahi**. Tax aur carry cost milake cash se kharab.
  ₹2 lakh mein sirf 1 lot aata hai.
- **Fundamentals** ko filter ki tarah lagane se faayda **nahi** hua (backtest). Sirf info ke liye rakhe.
- **Purane chat ke numbers phule hue the** (173 bade survivor stocks): W+TT avg trade +20.8% se +11.8% pe aaya,
  Fusion 17.4% se 13.9% pe.

---

## 2. Kya bana / theek hua (files)

| File | Kya karti hai | Status |
|---|---|---|
| `daily_screener.py` | Roz ka W+TT screener (Weinstein + Minervini Trend Template), ₹10k+ universe | Bugs/purane claims theek; "Stop %" cell table ke neeche shift |
| `fundamentals.py` | Screener.in se fundamentals; **usi Excel** mein green columns (P/E, ROCE, ROE, D/E, growth, pledge) + grey Promoter/FII/DII Δ + naya "Fundamentals" sheet. **Koi stock nahi hatata.** | Naya (v2) |
| `position_tracker.py` | Holdings ke exit (swing + investing) | v2: Dhan gap-fill, live price, client ID token se; entry_date se har din rules check (missed exit bhi batata hai); M&M bug + crash fix |
| `backtest.py` | W+TT ka backtest (point-in-time ₹10k universe), portfolio study, fundamentals gate test | Naya |
| `fund_history.py` | Tickertape se purana quarterly/annual data (fundamentals backtest ke liye) | Naya |
| `fno_data.py` | NSE ki F&O bhavcopy 2013-2026 (3,383 din) download | Naya |
| `fusion_backtest.py` | Fusion vs W+TT, cash + futures, Dhan ke asli charges + tax | Naya |
| `strategy_lab.py` | 16 strategies ek saath (momentum, low-vol, mean reversion, timing) | Naya |
| `CLAUDE.md` | Saare results aur rules | Updated |

Roz ka tareeka: `dhan_token.txt` mein token → Terminal mein `rbscan` (ab screener + fundamentals dono chalata hai).

---

## 3. Backtest setup (sab tests mein same)

- **Universe:** NSE ke stocks jo **us din** ₹10,000 Cr+ the (point-in-time). Purana mcap = aaj ka mcap × price
  ratio (NSE files se check: ~97% sahi, error ~2.5%). Liquidity: 60-din median turnover > ₹5 Cr.
- **Data:** eod2_data (2012-2026), NSE F&O bhavcopy, Tickertape (fundamentals, 2016+).
- **Charges (Dhan pricing page):** delivery brokerage 0, STT 0.1% dono taraf, stamp, exchange, GST,
  DP ₹12.5+GST per sell, slippage 0.10%/side. Futures: ₹20/order, STT 0.025% sell, asli futures prices + roll.
- **Tax:** STCG 20.8%, LTCG 13% (₹1.25 lakh chhoot), F&O business income 31.2%.
- **₹2 lakh se shuru**, idle cash 6%, 2013-2026, **do daur alag**: 2013-19 aur 2020-26.
- **Engine check:** purane chat ke numbers reproduce hue (W+TT 3,815 vs 3,633 trades; Fusion 17.7% vs 17.4%);
  screener aur backtest ke signals 100% match.

---

## 4. Results

### 4a. Sab strategies (₹2 lakh, tax ke baad CAGR)
| Strategy | 2013-19 | 2020-26 | Poora | Max girawat |
|---|---|---|---|---|
| **Momentum top 20 monthly** | 11.5% | 26.7% | **18.7%** | -40% |
| Momentum top 10 monthly | 10.4% | 31.2% | 21.1% | -42% |
| Momentum 12-1 top 20 | 10.1% | 28.2% | 18.5% | -46% |
| Fusion 8 stocks (RS-ranked) | 14.3% | 19.2% | 17.1% | -47% |
| W+TT investing exit, 20 | 9.9% | 16.1% | 13.0% | -39% |
| Fusion 20 stocks | 8.7% | 15.7% | 12.0% | -42% |
| Low-volatility top 20 | 14.6% | 10.3% | 12.1% | **-28%** |
| W+TT swing exit, 8 | 7.2% | 8.8% | 9.1% | -46% |
| Nifty 200-DMA timing | 5.3% | 10.6% | 7.9% | **-17%** |
| 52-week high top 20 | 4.4% | 11.2% | 7.8% | -34% |
| Mean reversion RSI-2 | -2.2% | -3.0% | **-2.9%** | -51% |
| **Nifty 50 buy & hold** | 10.3% | 9.8% | **9.8%** | -38% |

### 4b. Stock dhoondhne mein kaun behtar (6 mahine mein universe se kitna aage)
| Strategy | Avg aage | Kitne % picks jeete |
|---|---|---|
| Momentum top 10 | +6.2% | 51% |
| W+TT | +4.2% | 38% (kam jeette hain, par bade winners) |
| Fusion | +2.4% | 37% |
| Low-vol | -1.6% | 45% |

### 4c. F&O (Fusion, 20 slots, asli futures data)
| | Tax se pehle | Tax ke baad | Girawat |
|---|---|---|---|
| Cash (same stocks) | 10.0% | 9.4% | -34% |
| Futures long 1x | 8.9% | 4.9% | -35% |
| Futures long 2x | 11.5% | 6.2% | -58% |
| Sirf short | -7.2% | -11.6% | -76% |
- ₹2 lakh: ek lot ka margin ~₹1.5-2 lakh (2016 se), 4 lots kabhi nahi → diversification namumkin.

### 4d. Fundamentals ka backtest (2018-2026, bina look-ahead)
| W+TT trades | 2018-21 avg | 2022-26 avg |
|---|---|---|
| Fundamentals FAIL | +26.4% | +18.2% |
| Fundamentals PASS | +3.9% | +18.3% |
- Filter ka faayda nahi → fundamentals sirf jaankari. Watch Score hataya.

### 4e. Aur findings
- **RS ranking** asli kaam karti hai: Fusion 8 slots random chunne pe median 11.4%, RS se 20.4%.
- **Momentum settings-proof:** rebalance din 1/6/11/16 → 18.7-20.8%; 10-30 stocks → 17.6-21.1%.
- **Nifty filter, RS≥85, 10 slots (W+TT)** — dono daur mein pass nahi hue, apnaye nahi.
- **Minervini/O'Neil poore** kyun nahi: purani chat mein akele 6.75% / 6.81% (Nifty se kam); VCP/cup-handle
  code mein pakadna mushkil; tight stops ne result kharab kiya.

---

## 5. Backtest kitna sahi hai

**Sahi:** point-in-time universe, asli charges + tax, do daur, engine + screener match.
**Kami (result upar kheenchti hai):**
- Delist/doobi companies ka data nahi → ~1-3%/saal zyada dikh sakta hai.
- 16 strategies test kin → sabse achi mein thoda luck.
- Zyada tar extra return 2020-26 ka hai; 2013-19 mein momentum ≈ Nifty.
**Realistic umeed (momentum):** ~13-16%/saal, -40% girawat, kuch saal Nifty se peeche.

---

## 6. Options (tumhare liye)

| Maqsad | Option | Umeed | Risk |
|---|---|---|---|
| Sabse zyada paisa | Momentum top 10-20, monthly | ~13-16% realistic | -40% girawat |
| Swing (signal-based) | Fusion 5-8 stocks, RS-ranked, cash | ~13-18% | -46% |
| Investing (lamba) | W+TT entry + Stage 4 exit | ~12-13% | -39%, tax kam (LTCG) |
| Kam mehnat | Momentum index fund (Nifty200 Momentum 30 jaisa) | backtest nahi hua | fund ke andar trades pe tax nahi |
| Kam girawat | Low-vol ya Nifty 200-DMA timing | 8-12% | -17% se -28% |
| Sabse aasan | Nifty index fund | ~10% | -38% |
| **Nahi karna** | F&O, shorting, mean reversion | loss / Nifty se kam | — |

---

## 7. Aage kya karna hai (pending)

1. **Momentum ka monthly screener** (har mahine: kya rakhna, kya khareedna, kya bechna). ← suggested next
2. **2-3 mahine paper trading** asli paise se pehle (momentum + ya Fusion/W+TT).
3. Optional: Fusion ka live screener (RS-ranked).
4. Optional: ₹1 lakh momentum + ₹1 lakh W+TT investing split ka backtest.
5. Optional: Gold ETF / BTC pe strategies; VCP rule test.
6. `split.csv` mein har holding ka sahi `entry_date` (YYYY-MM-DD) likhna — tracker iske bina sirf aaj check karta hai.

---

## 8. Yaad rakhne wali baatein
- Dhan token kabhi code/GitHub/output mein nahi.
- `fundamentals.py` chalane se pehle Excel file band karo.
- Rules badalne se pehle re-test; har nayi strategy ke liye dono daur (2013-19, 2020-26).
- Kisi bhi backtest ko 100% sach mat maano — umeed 3-5% neeche rakho.
