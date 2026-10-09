"""MTF8: current holdings, four-section report. No API/order/credential access.
Estimated funding/interest/fees remain estimates; missing evidence stays UNKNOWN.
All input is the active-account result already reconciled by mtf_check.build.
"""
import datetime as dt
import math
import os
import tempfile
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.comments import Comment
from openpyxl.worksheet.datavalidation import DataValidation
from mtf_breakeven import cache_formula_values, validate_output_path

VERSION = 'v33'
UNKNOWN = 'UNKNOWN'
FEES_SOURCE = 'https://dhan.co/pricing/'
INTEREST_SOURCE = 'https://dhan.co/support/mtf-pledge-experience/mtf-general/how-is-interest-calculated-for-margin-trading-facility-mtf-transactions-and-what-should-i-know-about-the-process/'
RISK_SOURCE = 'https://dhan.co/risk-management-policy/'
EXCH=.000030699; SEBI=.000001; IPFT=.000000001; GST=.18
STT=.001; STAMP=.00015; BROKER=.0003; CAP=20; DP=12.5; PLEDGE=15

# Per-broker MTF rate cards (RB 9 Oct: 'har broker ke liye'). Statutory parts (STT, stamp,
# exchange, SEBI, GST) are the same for every broker; brokerage / DP / pledge / interest differ.
# Sources checked 9 Oct 2026; ESTIMATES -- confirm in the broker app.
BROKER_CARDS = {
    'DHAN': dict(BROKER=.0003, CAP=20, DP=12.5, PLEDGE=15, RATE=.1249,
                 FEES_SOURCE='https://dhan.co/pricing/', INTEREST_SOURCE=INTEREST_SOURCE, RISK_SOURCE=RISK_SOURCE),
    # Zerodha: brokerage 0.3% or Rs20 per MTF order, pledge/unpledge Rs15+GST per ISIN, 0.04%/day.
    'ZERODHA': dict(BROKER=.003, CAP=20, DP=13.0, PLEDGE=15, RATE=.146,
                    FEES_SOURCE='https://zerodha.com/tos/mtf', INTEREST_SOURCE='https://support.zerodha.com/category/trading-and-markets/margins/margin-trading-facility/articles/margin-trading-facility-mtf-faqs',
                    RISK_SOURCE='https://zerodha.com/tos/mtf'),
    # Angel One: brokerage 0.1% or Rs20, pledge/unpledge Rs20+GST per ISIN, DP Rs20+GST, 14.99% p.a.
    'ANGEL': dict(BROKER=.001, CAP=20, DP=20.0, PLEDGE=20, RATE=.1499,
                  FEES_SOURCE='https://www.angelone.in/margin-trading-facility', INTEREST_SOURCE='https://www.angelone.in/news/product-updates/pricing-update-2024',
                  RISK_SOURCE='https://www.angelone.in/margin-trading-facility'),
}
def set_broker(name):
    """Switch the module rate card (functions read these globals at call time)."""
    card = BROKER_CARDS.get(str(name).upper())
    if card is None:raise ValueError('No MTF rate card for broker '+str(name))
    g = globals()
    for k, v in card.items():
        if k != 'RATE':g[k] = v
    return card['RATE']

def finite(v):
    try:return v is not None and not isinstance(v,bool) and math.isfinite(float(v))
    except (ValueError,TypeError,OverflowError):return False

def number(n):
    return float(n.value) if getattr(n,'known',False) and finite(n.value) else None

def rounded(v,places=2):
    # Remove binary-float noise before the statutory half-up rounding.
    d=Decimal(str(v)).quantize(Decimal('0.0000000001'),rounding=ROUND_HALF_UP)
    return float(d.quantize(Decimal('1') if places==0 else Decimal('0.01'),rounding=ROUND_HALF_UP))

def fees(value,buy=False):
    if not finite(value) or value<0:return None
    v=float(value)
    out=dict(brokerage=rounded(min(CAP,BROKER*v)),stt=rounded(STT*v,0),exchange=rounded(EXCH*v),sebi=rounded(SEBI*v),ipft=rounded(IPFT*v),stamp=rounded(STAMP*v,0) if buy else 0,dp=0 if buy else DP,pledge=PLEDGE)
    out['gst']=rounded((out['brokerage']+out['exchange']+out['sebi']+out['ipft'])*GST)+rounded(out['dp']*GST)+rounded(out['pledge']*GST)
    out['total']=sum(out.values());return out

def target_net(price,qty,cost,past,buy,funded,rate,hold=0,settle=0,tax=0):
    v=price*qty
    return v-cost-past-buy-fees(v)['total']-funded*rate*hold/365-v*rate*settle/365-max(v-cost,0)*tax

def target(qty,cost,past,buy,funded,rate,hold=0,settle=0,tax=0,buffer=0,tick=.05):
    vals=(qty,cost,past,buy,funded,rate,hold,settle,tax,buffer,tick)
    if not all(finite(v) for v in vals) or qty<=0 or abs(qty-round(qty))>1e-8 or cost<=0 or min(past,buy,funded,hold,settle,buffer)<0 or not 0<=rate<1 or not 0<=tax<.8 or tick<=0:return None
    # Rounded STT creates local downward jumps: net is not strictly monotonic.
    # The continuous rate-card root and a Rs1 total rounding-error bound give
    # a complete interval; scan every tick in it to find the GLOBAL first hit.
    slope=1-tax-rate*settle/365-STT-(EXCH+SEBI+IPFT)*(1+GST)-BROKER*(1+GST)
    if slope<.05:return None
    seed=_seed(qty,cost,past,buy,funded,rate,hold,settle,tax,buffer)
    radius=1/(qty*slope)
    lo=max(1,math.floor((seed-radius)/tick));hi=math.ceil((seed+radius)/tick)+1
    for k in range(lo,hi+1):
        price=round(k*tick,8)
        if target_net(price,qty,cost,past,buy,funded,rate,hold,settle,tax)>=buffer:return price
    return None

def calculate(R,today,days=30,settlement=3,tax=.208,rate=.1249):
    loan=number(R.get('loan'));basis=number(R.get('open_cost_num'));unpaid=number(R.get('unpaid'))
    inp=all(finite(x) for x in (days,settlement,tax,rate)) and 0<=days<=3650 and 0<=settlement<=90 and 0<=tax<.8 and 0<=rate<1
    raw=R.get('rows',[]);costs=[number(x.get('Open cost (Rs)')) for x in raw]
    basis_ok=bool(raw) and finite(basis) and basis>0 and all(finite(c) and c>0 for c in costs) and abs(sum(costs)-basis)<.02
    loan_ok=basis_ok and finite(loan) and 0<=loan<=basis
    cash_basis=loan_ok and finite(unpaid) and unpaid>=0 and R.get('src',{}).get('ledger',('VERIFIED',))[0]!=UNKNOWN
    if getattr(R.get('exit'),'status',None)==UNKNOWN and not R.get('src',{}).get('ledger'):cash_basis=False
    out=[]
    current=R.get('current_lots',R.get('fifo',{}).get('lots',{}))
    for row in sorted(raw,key=lambda x:str(x.get('Symbol',''))):
        sym=str(row.get('Symbol','?'));q=row.get('Qty');c=number(row.get('Open cost (Rs)'));p=row.get('Price')
        qty_ok=finite(q) and q>0 and abs(q-round(q))<1e-8 and row.get('Inventory status')!=UNKNOWN
        price_ok=qty_ok and finite(p) and p>0
        if 'Value (Rs)' in row and number(row['Value (Rs)']) is None:price_ok=False
        value=q*p if price_ok else None;gain=value-c if value is not None and finite(c) and c>0 else None
        funded=loan*c/basis if loan_ok and finite(c) and c>0 and qty_ok else None
        daily=funded*rate/365 if funded is not None and inp else None
        lots=[];valid=bool(current.get(sym))
        for z in current.get(sym,[]):
            try:
                d=dt.date.fromisoformat(str(z[0]));n=float(z[1]);px=float(z[2]);economic=finite(n) and finite(px) and n>0 and abs(n-round(n))<1e-8 and px>0;good=economic and d<=today
                if not good:valid=False
                age=(today-d).days if good else None;v=n*px if economic else None
                lf=fees(v,True) if economic else None
                fund=v*loan/basis if economic and loan_ok else None
                interest=fund*rate*age/365 if fund is not None and inp and age is not None else None
                lots.append(dict(symbol=sym,date=d,qty=n,price=px,cost=v,days=age,funded=fund,interest=interest,fees=lf))
            except (TypeError,ValueError,IndexError,OverflowError):valid=False
        ready=inp and 1-tax-rate*settlement/365-STT-(EXCH+SEBI+IPFT)*(1+GST)-BROKER*(1+GST)>=.05 and funded is not None and valid and abs(sum(z['qty'] for z in lots)-q)<1e-8 and all(z['cost'] is not None for z in lots) and abs(sum(z['cost'] for z in lots)-c)<.02
        past=sum(z['interest'] for z in lots) if ready else None
        buy=sum(z['fees']['total'] for z in lots) if ready else None
        sell=fees(value) if value is not None else None
        outstanding=unpaid*c/basis if cash_basis and funded is not None else None
        extra=value*rate*settlement/365 if value is not None and inp else None
        cash=value-funded-sell['total']-outstanding-extra if None not in (value,funded,sell,outstanding,extra) else None
        net_asof=gain-past-buy-sell['total'] if None not in (gain,past,buy,sell) else None
        net_exit=net_asof-extra if None not in (net_asof,extra) else None
        reserve=max(gain,0)*tax if gain is not None and inp else None
        after_tax=net_exit-reserve if None not in (net_exit,reserve) else None
        paid_proxy=past-outstanding if past is not None and outstanding is not None and past>=outstanding else None
        own=c-funded if funded is not None else None
        pocket=own+paid_proxy+buy if None not in (own,paid_proxy,buy) else None
        pure=target(q,c,past,buy,funded,rate) if ready else None
        now_be=target(q,c,past,buy,funded,rate,settle=settlement) if ready else None
        safe=target(q,c,past,buy,funded,rate,days,settlement,tax,2) if ready else None
        hold_i=funded*rate*days/365 if funded is not None and inp else None
        safe_i=safe*q*rate*settlement/365 if safe is not None else None
        # RB 9 Oct: 'safe target choose kiya to 30 din mein net P/L kya hoga' -> sale at the safe
        # target on the LAST day (aaj + days): full hold interest + exit reserve; earlier = less interest.
        tgt_gross=safe*q if safe is not None else None
        tgt_fees=fees(tgt_gross)['total'] if tgt_gross is not None else None
        tgt_net=tgt_gross-c-past-buy-tgt_fees-hold_i-safe_i if None not in (tgt_gross,tgt_fees,hold_i,safe_i) else None
        tgt_net_tax=tgt_net-max(tgt_gross-c,0)*tax if tgt_net is not None else None
        out.append(dict(symbol=sym,qty=q if qty_ok else None,cmp=p if price_ok else None,cost=c,lots=lots,lot_basis_ok=bool(ready),funded=funded,own=own,daily=daily,past=past,buy=buy,sale_fees=sell,unpaid=outstanding,extra=extra,cash=cash,net_asof=net_asof,net_exit=net_exit,now_tax=reserve,now_net_tax=after_tax,paid_proxy=paid_proxy,pocket=pocket,pure=pure,today_be=now_be,full=safe,recovery=safe/p-1 if safe is not None and price_ok else None,target_date=today+dt.timedelta(days=int(days)) if inp else None,target_gross=tgt_gross,target_fees=tgt_fees,target_net=tgt_net,target_net_tax=tgt_net_tax,hold_interest=hold_i,safe_exit_interest=safe_i,value=value,price_pnl=gain,price_source=str(row.get('Price source','UNKNOWN')),status='ESTIMATED' if ready and safe is not None else UNKNOWN))
    return out

def total(rows,key):
    vals=[r.get(key) for r in rows]
    return sum(vals) if vals and all(finite(v) for v in vals) else None

def complete(R,rows):
    if not rows:return number(R.get('open_cost_num'))==0 and number(R.get('loan'))==0 and getattr(R.get('exit'),'known',False)
    return all(r['status']!=UNKNOWN and r['cash'] is not None and r['net_exit'] is not None for r in rows)

def print_report(R,rows,acc,today,args):
    def money(x,sign=False):
        if not finite(x):return 'UNKNOWN'
        return ('+' if sign and x>0 else '-' if x<0 else '')+RUPEE+'{:,.2f}'.format(abs(x))
    def line(label,x,note='',sign=False):print('  %-47s %20s %s'%(label,money(x,sign),note))
    print('\n==== CURRENT MTF | %s | %s | %s ===='%(acc.label,today,VERSION))
    print('Quote timestamps/sources below. MODEL != ACTUAL; no orders. Current holdings only.')
    print('\n1. AAPKA LAGAYA PAISA / CAPITAL BREAKDOWN')
    cost=number(R.get('open_cost_num'));loan=number(R.get('loan'))
    line('FIFO purchase cost',cost);line('Current broker loan',loan,getattr(R.get('loan'),'note',''))
    line('Own principal: cost minus current loan',total(rows,'own'),'not original deposits/top-ups')
    line('Actual original margin supplied by you',number(R.get('init_cash')),'' if number(R.get('init_cash')) is not None else 'broker API nahi deta -> ek baar: rbmtf --own-cash <Rs>')
    line('Accrued interest MODEL',total(rows,'past'));print('  Actual paid interest for current lots: UNKNOWN')
    line('Unpaid interest as of valuation',number(R.get('unpaid')),getattr(R.get('unpaid'),'note',''))
    line('Paid-interest PROXY',total(rows,'paid_proxy'),'model accrual minus modeled unpaid')
    line('Cash burden PROXY incl buy fees',total(rows,'pocket'),'actual cash out of pocket UNKNOWN')
    line('Current daily interest burn',total(rows,'daily'),'Rs/day; %.2f%% p.a.'%(args.rate*100))
    print('\n2. PER-STOCK HOLDING / LOAN STATUS')
    for r in rows:
        print('  %s | Qty %s | FIFO avg %s | buy cost %s'%(r['symbol'],r['qty'],money(r['cost']/r['qty']) if r['qty'] and r['cost'] is not None else 'UNKNOWN',money(r['cost'])))
        print('    Loan allocation %s | own principal %s | interest MODEL %s | daily %s'%(money(r['funded']),money(r['own']),money(r['past']),money(r['daily'])))
        print('    Price %s | %s'%(money(r['cmp']),r['price_source']))
        for z in r['lots']:print('    Lot %s: %s shares @ %s | %s calendar days | interest MODEL %s'%(z['date'],z['qty'],money(z['price']),z['days'],money(z['interest']) if r['lot_basis_ok'] else 'UNKNOWN'))
    if not rows:print('  No current MTF positions.' if complete(R,rows) else '  Current MTF inventory unavailable / not reconciled: UNKNOWN.')
    print('\n3. AAJ BECHO TOH KYA MILEGA (ESTIMATED)')
    for r in rows:
        print('  %s: sale %s | price P/L %s | cash credit %s | net P/L %s'%(r['symbol'],money(r['value']),money(r['price_pnl'],True),money(r['cash']),money(r['net_exit'],True)))
        if r['sale_fees']:
            print('    Charges: '+', '.join(k+' '+money(v) for k,v in r['sale_fees'].items() if k not in ('total','stamp')))
        print('    Loan %s | as-of unpaid %s | additional %d-day exit reserve %s'%(money(r['funded']),money(r['unpaid']),args.settlement_buffer,money(r['extra'])))
    line('TOTAL sale value',total(rows,'value'));line('TOTAL price P/L',total(rows,'price_pnl'),sign=True)
    line('TOTAL net cash credited scenario',total(rows,'cash'),'increment to trading account; not profit')
    line('TOTAL net P/L before extra exit days',total(rows,'net_asof'),sign=True)
    line('TOTAL net P/L including exit reserve',total(rows,'net_exit'),sign=True)
    line('Optional per-stock tax reserve',total(rows,'now_tax'),'not deducted from broker payout; setoffs not modeled')
    line('Net after optional tax reserve',total(rows,'now_net_tax'),sign=True)
    print('  Paid interest is not deducted again from payout; loan repayment is not another P/L loss.')
    print('\n4. BREAKEVEN / %d-DAY TARGET + %d EXIT RESERVE DAYS'%(args.buffer_days,args.settlement_buffer))
    for r in rows:
        print('  %s | Pure cost BE %s | BE including exit reserve %s | Safe + tax reserve %s | rise %s'%(r['symbol'],money(r['pure']),money(r['today_be']),money(r['full']),'UNKNOWN' if r['recovery'] is None else '%.2f%%'%(100*r['recovery'])))
        print('    Target date %s tak safe target %s pe becho -> net P/L %s (tax reserve ke baad %s) | AAJ becho -> net P/L %s'%(r['target_date'].strftime('%d-%b-%Y') if r['target_date'] else 'UNKNOWN',money(r['full']),money(r['target_net'],True),money(r['target_net_tax'],True),money(r['net_exit'],True)))
        print('    Interest kata hua: ab tak %s + aaj se target date tak %s'%(money(r['past']),money(r['hold_interest'])))
    line('TOTAL net P/L at safe targets (tax se pehle)',total(rows,'target_net'),sign=True)
    line('TOTAL net P/L AAJ becho',total(rows,'net_exit'),sign=True)
    value=total(rows,'value')
    if finite(loan) and finite(value) and value>0:
        print('  Risk SCENARIO only: equity/value %.2f%%; hypothetical 20%% floor uniform fall %.2f%% (zero extra collateral).'%(100*(value-loan)/value,100*(1-loan/.8/value)))
    print('  Actual margin-call levels: UNKNOWN (broker margin requirements/free collateral missing).')
    print('  Targets assume 30 funded-loan days (or chosen buffer) + full-sale-value exit reserve, .05 tick, Rs2 buffer.')
    if not complete(R,rows):
        print('\nINCOMPLETE: missing data stays UNKNOWN; no zero substitution.')
        for key,(st,note) in sorted(R.get('src',{}).items()):
            if st==UNKNOWN:print('  %s: %s'%(key,note))
        if getattr(R.get('exit'),'status',None)==UNKNOWN:print('  Cash basis: '+getattr(R['exit'],'note','UNKNOWN'))
    print('  Actual current-lot paid interest, original cash and realised settlement remain UNKNOWN.')
    print('  Fees: '+FEES_SOURCE+' | Interest model: '+INTEREST_SOURCE)
    if BROKER_CARDS['DHAN']['FEES_SOURCE']==FEES_SOURCE:  # --audit is Dhan-only
        print('  Detailed history/reconciliation: rbmtf --audit')

def _seed(q,c,past,buy,funded,rate,hold,settle,tax,buffer):
    a=1-STT-(EXCH+SEBI+IPFT)*(1+GST)-tax-rate*settle/365
    num=c+past+buy+funded*rate*hold/365+buffer+(DP+PLEDGE)*(1+GST)-tax*c
    unc=num/(a-BROKER*(1+GST))
    return (unc if unc<=CAP/BROKER else (num+CAP*(1+GST))/a)/q

# RB 9 Oct: amounts as Rs1,550.50 with the rupee sign (sheet + terminal); qty/days/% stay plain.
# ONE section only: Apple Numbers puts its own minus in front of an explicit negative
# section ('[Red]-"Rs"..' showed '--Rs37,066.30', RB 9 Oct). Red comes from conditional formatting.
MONEY_FMT='"\u20b9"#,##0.00'
def _rupee():
    import sys
    try:'\u20b9'.encode(getattr(sys.stdout,'encoding',None) or 'ascii');return '\u20b9'
    except (UnicodeEncodeError,LookupError):return 'Rs '
RUPEE=_rupee()


def _align(cell,sec2,start4):
    """RB 9 Oct: 'heading kahi aur, data kahi aur'. Text defaults left and numbers right in
    Excel/Numbers/Sheets, so a header never sat over its numbers. Column A = labels (left);
    every other table cell, header AND value, is centred; long text stays left."""
    r,c=cell.row,cell.column
    if c==1:return 'left'
    if 4<=r<=7:return 'right' if c in (3,5) else 'left' if c>=8 else 'center'   # input labels sit next to their values
    if 12<=r<=24 and c>=4:return 'left'             # Section 1 explanation text
    if r<start4-1 and c==11:return 'left'           # Section 2 price source (not the Section 4 header)
    return 'center'


def write_report(R,today,path,days=30,settlement=3,tax=.208,rate=.1249):
    """Atomic fixed-account worksheet; formulas plus display caches, no live calls."""
    rows=calculate(R,today,days,settlement,tax,rate);n=len(rows)
    w=Workbook();s=w.active;s.title='Breakeven';cache={}
    NAVY='243B53';PALE='E9EFF5';YELLOW='FFF2CC'
    def put(ref,value,note=None):
        s[ref]=value if value is not None else UNKNOWN
        if isinstance(value,str) and value.startswith(('=','+','@')):s[ref].data_type='s'
        if note:s[ref].comment=Comment(str(note),'Source / model')
    def f(ref,expr,value):
        s[ref]='=IFERROR('+expr.lstrip('=')+',"UNKNOWN")';cache[ref]=value if value is not None else UNKNOWN
    def bar(k,text):
        s.merge_cells(start_row=k,start_column=1,end_row=k,end_column=max(11,n+2));put('A'+str(k),text)
        s.row_dimensions[k].height=28
        for c in s[k]:c.fill=PatternFill('solid',fgColor=NAVY);c.font=Font(name='Arial',bold=True,color='FFFFFF')
    def note(k,text):
        s.merge_cells(start_row=k,start_column=1,end_row=k,end_column=max(11,n+2));put('A'+str(k),text);s.row_dimensions[k].height=34
    from openpyxl.utils import get_column_letter as col
    basis=number(R.get('open_cost_num'));loan=number(R.get('loan'));unpaid=number(R.get('unpaid'))
    cash_basis=R.get('src',{}).get('ledger',('VERIFIED',))[0]!=UNKNOWN
    if getattr(R.get('exit'),'status',None)==UNKNOWN and not R.get('src',{}).get('ledger'):cash_basis=False
    bar(1,'CURRENT MTF — OWN MONEY, LOAN, INTEREST, EXIT PAYOUT & TARGETS | '+VERSION)
    note(2,'MODEL != ACTUAL. Quote time/source is shown per stock. Missing current-lot paid interest, original deposits and actual margin-call levels remain UNKNOWN.')
    note(3,'Account: '+str(R.get('report_account','UNKNOWN'))+' | Refreshed '+today.isoformat()+' | Current positions only; historical closed trades excluded.')
    for ref,value,label in [('B4',today,'Valuation date'),('D4',rate,'Annual rate fraction'),('F4',days,'Future holding days'),('B5',loan,'Current total loan'),('D5',tax,'Optional tax reserve'),('F5',settlement,'Extra exit reserve days'),('B6',unpaid,'UNPAID interest at valuation'),('D6',basis,'Reconciled share purchase cost'),('F6',.05,'Assumed price tick'),('B7',number(R.get('init_cash')),'Your original own cash (blank = not known)'),('D7',2,'Safe-target Rs buffer'),('F7',int(cash_basis),'Ledger/settlement basis available')]:
        put(ref,value,label+'; supplied active-account input/model. Loan/unpaid interest source: '+getattr(R.get('loan' if ref=='B5' else 'unpaid'),'note','') if ref in ('B5','B6') else label+'; source: reconciled current account or user scenario.')
        label_ref=col(s[ref].column-1)+str(s[ref].row);put(label_ref,label)
        if ref!='F7':s[ref].fill=PatternFill('solid',fgColor=YELLOW)
    if number(R.get('init_cash')) is None:
        # RB 9 Oct (Sheets 'Invalid' popup): an input cell never holds the text UNKNOWN.
        s['B7']=None
        s['B7'].comment=Comment('Pata ho to apni jeb se MTF mein dala paisa yahan likho, ya ek baar: rbmtf --own-cash 150000 (account ke liye yaad rehta hai). Broker API ye number nahi deti.','Source / model')
    put('H4','Quote/date edits are scenarios; this worksheet does not fetch prices. Refresh broker loan, quote and interest evidence together.')
    s.merge_cells('H4:K7')
    # Layout indices scale with any current stock count.
    sec2=27;head2=29;start2=30;total2=start2+n
    sec3=total2+3;head3=sec3+1;start3=sec3+2
    metrics=[('Market value','value','J'),('Price profit/loss','price_pnl','K'),('Exit brokerage','brokerage','Q'),('Exit STT','stt','P'),('Exchange fees','exchange','M'),('SEBI','sebi','N'),('IPFT','ipft','O'),('DP base','dp','S'),('Unpledge base','pledge','T'),('GST on applicable fees','gst','R'),('TOTAL EXIT CHARGES','fee_total','L'),('Loan repayment','funded','E'),('As-of UNPAID interest','unpaid','U'),('Extra sale-realisation reserve','extra','V'),('NET CASH CREDIT SCENARIO','cash','X'),('Net P/L before extra exit days','net_asof','Y'),('Net P/L including exit reserve','net_exit','Z'),('Optional gross-gain tax reserve','now_tax','W'),('Net P/L after optional reserve','now_net_tax','AA'),('ACTUAL settlement / realised P/L',None,None)]
    map3={key:start3+j for j,(_,key,_) in enumerate(metrics) if key}
    sec4=start3+len(metrics)+3;head4=sec4+1;start4=sec4+2
    risk=start4+n+4;notes=risk+6;fee_start=notes+11;lot_head=fee_start+13;lot_start=lot_head+1
    all_lots=[z for r in rows for z in r['lots']];lot_end=lot_start+len(all_lots)-1
    hstart=max(300,lot_end+len(R.get('src',{}))+15);hend=hstart+n-1;lookup={r['symbol']:hstart+i for i,r in enumerate(rows)}
    const={'broker':BROKER,'cap':CAP,'exchange':EXCH,'sebi':SEBI,'ipft':IPFT,'gst':GST,'stt':STT,'stamp':STAMP,'dp':DP,'pledge':PLEDGE}
    refc={};bar(fee_start-1,'CHARGE ASSUMPTIONS — PUBLISHED DHAN RATE CARD; ALL ARE ESTIMATES')
    for j,(key,val) in enumerate(const.items()):
        k=fee_start+j;put('A'+str(k),key+' fraction/base Rs');put('B'+str(k),val,FEES_SOURCE+' | Checked 09-Oct-2026. One sell order/instruction per stock; one buy order/pledge per remaining tranche assumed.');refc[key]='$B$'+str(k)
    def fee_formula(v):
        br='ROUND(MIN(%s,%s*%s),2)'%(refc['cap'],v,refc['broker']);ex='ROUND(%s*%s,2)'%(v,refc['exchange']);sb='ROUND(%s*%s,2)'%(v,refc['sebi']);ip='ROUND(%s*%s,2)'%(v,refc['ipft'])
        return '+'.join([br,'ROUND(%s*%s,0)'%(v,refc['stt']),ex,sb,ip,refc['dp'],refc['pledge'],'ROUND((%s+%s+%s+%s)*%s,2)'%(br,ex,sb,ip,refc['gst']),'ROUND(%s*%s,2)'%(refc['dp'],refc['gst']),'ROUND(%s*%s,2)'%(refc['pledge'],refc['gst'])])
    bar(lot_head-1,'FIFO TRANCHES — DATED ACQUISITIONS; INTEREST IS A FUNDING PROXY')
    for j,label in enumerate(['Stock','Buy date','Qty','Buy price','Share cost','Days held','Funded proxy','Interest MODEL','Buy brokerage','STT','Stamp','Exchange','SEBI','IPFT','Trade GST','Pledge + GST','Buy costs MODEL'],1):put(col(j)+str(lot_head),label)
    for i,z in enumerate(all_lots):
        k=lot_start+i;put('A'+str(k),z['symbol']);put('B'+str(k),z['date']);put('C'+str(k),z['qty']);put('D'+str(k),z['price'])
        f('E'+str(k),'IF(AND(COUNT(C{0}:D{0})=2,C{0}>0,D{0}>0),C{0}*D{0},"UNKNOWN")'.format(k),z['cost'])
        f('F'+str(k),'IF(COUNT($B$4,B{0})=2,IF(B{0}<=$B$4,$B$4-B{0},"UNKNOWN"),"UNKNOWN")'.format(k),z['days'])
        f('G'+str(k),'IF(COUNT(E{0},$B$5,$D$6)=3,IF(AND($D$6>0,$B$5>=0,$B$5<=$D$6,COUNT($C${1}:$C${2})={3},ABS(SUM($C${1}:$C${2})-$D$6)<0.02),E{0}*$B$5/$D$6,"UNKNOWN"),"UNKNOWN")'.format(k,hstart,hend,n),z['funded'])
        f('H'+str(k),'IF(AND(COUNT(F{0},G{0},$D$4)=3,$D$4>=0,$D$4<1),F{0}*G{0}*$D$4/365,"UNKNOWN")'.format(k),z['interest'])
        lf=z['fees'] or {}
        for c,key,expr in [('I','brokerage','ROUND(MIN(%s,E%d*%s),2)'%(refc['cap'],k,refc['broker'])),('J','stt','ROUND(E%d*%s,0)'%(k,refc['stt'])),('K','stamp','ROUND(E%d*%s,0)'%(k,refc['stamp'])),('L','exchange','ROUND(E%d*%s,2)'%(k,refc['exchange'])),('M','sebi','ROUND(E%d*%s,2)'%(k,refc['sebi'])),('N','ipft','ROUND(E%d*%s,2)'%(k,refc['ipft'])),('O','trade_gst','ROUND((I%d+SUM(L%d:N%d))*%s,2)'%(k,k,k,refc['gst'])),('P','pledge_gst','%s+ROUND(%s*%s,2)'%(refc['pledge'],refc['pledge'],refc['gst']))]:
            value=lf.get(key)
            if key=='trade_gst' and lf:value=rounded((lf['brokerage']+lf['exchange']+lf['sebi']+lf['ipft'])*GST)
            if key=='pledge_gst' and lf:value=PLEDGE+rounded(PLEDGE*GST)
            f(c+str(k),'IF(COUNT(E%d)=1,%s,"UNKNOWN")'%(k,expr),value)
        f('Q'+str(k),'IF(COUNT(I{0}:P{0})=8,SUM(I{0}:P{0}),"UNKNOWN")'.format(k),lf.get('total'))
    nextrow=hend+5
    for i,r in enumerate(rows):
        k=hstart+i;visible=start4+i
        put('A'+str(k),r['symbol']);put('B'+str(k),r['qty']);put('C'+str(k),r['cost']);put('B'+str(visible),r['cmp'],r['price_source']);s['B'+str(visible)].fill=PatternFill('solid',fgColor=YELLOW)
        f('D'+str(k),'B'+str(visible),r['cmp'])
        cost_basis='AND(COUNT($B$5,$D$6,C{0})=3,$D$6>0,$B$5>=0,$B$5<=$D$6,COUNT($C${1}:$C${2})={3},ABS(SUM($C${1}:$C${2})-$D$6)<0.02)'.format(k,hstart,hend,n)
        f('E'+str(k),'IF(%s,$B$5*C%d/$D$6,"UNKNOWN")'%(cost_basis,k),r['funded'])
        f('F'+str(k),'IF(COUNT(C{0},E{0})=2,C{0}-E{0},"UNKNOWN")'.format(k),r['own'])
        f('G'+str(k),'IF(AND(COUNT(E{0},$D$4)=2,$D$4>=0,$D$4<1),E{0}*$D$4/365,"UNKNOWN")'.format(k),r['daily'])
        symrange='$A$%d:$A$%d'%(lot_start,max(lot_start,lot_end));nlot=len(r['lots'])
        check='AND(COUNT(B{0},C{0},E{0},$D$4,$F$4,$F$5,$D$5)=7,B{0}>0,B{0}=INT(B{0}),C{0}>0,$D$4>=0,$D$4<1,$F$4>=0,$F$4<=3650,$F$5>=0,$F$5<=90,$D$5>=0,$D$5<0.8,1-$D$5-$D$4*$F$5/365-{1}-({2}+{3}+{4})*(1+{5})-{6}*(1+{5})>=0.05)'.format(k,refc['stt'],refc['exchange'],refc['sebi'],refc['ipft'],refc['gst'],refc['broker'])
        if nlot:
            check='AND(%s,ABS(SUMIF(%s,A%d,$C$%d:$C$%d)-B%d)<1E-8,ABS(SUMIF(%s,A%d,$E$%d:$E$%d)-C%d)<0.02,SUMPRODUCT(--(%s=A%d),--ISNUMBER($H$%d:$H$%d))=%d,SUMPRODUCT(--(%s=A%d),--ISNUMBER($Q$%d:$Q$%d))=%d)'%(check,symrange,k,lot_start,lot_end,k,symrange,k,lot_start,lot_end,k,symrange,k,lot_start,lot_end,nlot,symrange,k,lot_start,lot_end,nlot)
        else:check='FALSE'
        f('AG'+str(k),'IFERROR(IF(%s,1,0),0)'%check,int(r['lot_basis_ok']))
        f('H'+str(k),'IF(AG%d=1,SUMIF(%s,A%d,$H$%d:$H$%d),"UNKNOWN")'%(k,symrange,k,lot_start,max(lot_start,lot_end)),r['past'])
        f('I'+str(k),'IF(AG%d=1,SUMIF(%s,A%d,$Q$%d:$Q$%d),"UNKNOWN")'%(k,symrange,k,lot_start,max(lot_start,lot_end)),r['buy'])
        for c,key,expr in [('J','value','IF(AND(COUNT(B{0},D{0})=2,B{0}>0,D{0}>0),B{0}*D{0},"UNKNOWN")'.format(k)),('K','price_pnl','IF(COUNT(C{0},J{0})=2,J{0}-C{0},"UNKNOWN")'.format(k)),('M','exchange','ROUND(J%d*%s,2)'%(k,refc['exchange'])),('N','sebi','ROUND(J%d*%s,2)'%(k,refc['sebi'])),('O','ipft','ROUND(J%d*%s,2)'%(k,refc['ipft'])),('P','stt','ROUND(J%d*%s,0)'%(k,refc['stt'])),('Q','brokerage','ROUND(MIN(%s,J%d*%s),2)'%(refc['cap'],k,refc['broker'])),('S','dp',refc['dp']),('T','pledge',refc['pledge'])]:
            val=r.get(key) if c in ('J','K') else (r['sale_fees'] or {}).get(key)
            if c not in ('J','K'):expr='IF(COUNT(J%d)=1,%s,"UNKNOWN")'%(k,expr)
            f(c+str(k),expr,val)
        f('R'+str(k),'IF(COUNT(M{0}:Q{0},S{0}:T{0})=7,ROUND((Q{0}+SUM(M{0}:O{0}))*{1},2)+ROUND(S{0}*{1},2)+ROUND(T{0}*{1},2),"UNKNOWN")'.format(k,refc['gst']),(r['sale_fees'] or {}).get('gst'))
        f('L'+str(k),'IF(COUNT(M{0}:T{0})=8,SUM(M{0}:T{0}),"UNKNOWN")'.format(k),(r['sale_fees'] or {}).get('total'))
        f('U'+str(k),'IF(AND(COUNT($B$6,E{0})=2,$B$6>=0,$F$7=1),$B$6*C{0}/$D$6,"UNKNOWN")'.format(k),r['unpaid'])
        f('V'+str(k),'IF(AND(COUNT(J{0},$D$4,$F$5)=3,$D$4>=0,$D$4<1,$F$5>=0,$F$5<=90),J{0}*$D$4*$F$5/365,"UNKNOWN")'.format(k),r['extra'])
        f('W'+str(k),'IF(AND(COUNT(K{0},$D$5)=2,$D$5>=0,$D$5<0.8),MAX(K{0},0)*$D$5,"UNKNOWN")'.format(k),r['now_tax'])
        expressions={'X':('cash','IF(COUNT(J{0},E{0},L{0},U{0},V{0})=5,J{0}-E{0}-L{0}-U{0}-V{0},"UNKNOWN")'), 'Y':('net_asof','IF(COUNT(K{0},H{0},I{0},L{0})=4,K{0}-H{0}-I{0}-L{0},"UNKNOWN")'), 'Z':('net_exit','IF(COUNT(Y{0},V{0})=2,Y{0}-V{0},"UNKNOWN")'), 'AA':('now_net_tax','IF(COUNT(Z{0},W{0})=2,Z{0}-W{0},"UNKNOWN")'), 'AB':('paid_proxy','IF(COUNT(H{0},U{0})=2,IF(H{0}>=U{0},H{0}-U{0},"UNKNOWN"),"UNKNOWN")'), 'AC':('pocket','IF(COUNT(F{0},AB{0},I{0})=3,F{0}+AB{0}+I{0},"UNKNOWN")'), 'AH':('hold_interest','IF(COUNT(E{0},$D$4,$F$4)=3,E{0}*$D$4*$F$4/365,"UNKNOWN")'), 'AI':('safe_exit_interest','IF(COUNT(AD{0},B{0},$D$4,$F$5)=4,AD{0}*B{0}*$D$4*$F$5/365,"UNKNOWN")')}
        for c,(key,expr) in expressions.items():f(c+str(k),expr.format(k),r[key])
        # Sale at the safe target on the last day of the holding scenario (RB 9 Oct).
        f('AJ'+str(k),'IF(COUNT(AD{0},B{0})=2,AD{0}*B{0},"UNKNOWN")'.format(k),r['target_gross'])
        f('AK'+str(k),'IF(COUNT(AJ%d)=1,%s,"UNKNOWN")'%(k,fee_formula('AJ'+str(k))),r['target_fees'])
        f('AL'+str(k),'IF(COUNT(AJ{0},C{0},H{0},I{0},AK{0},AH{0},AI{0})=7,AJ{0}-C{0}-H{0}-I{0}-AK{0}-AH{0}-AI{0},"UNKNOWN")'.format(k),r['target_net'])
        f('AM'+str(k),'IF(AND(COUNT(AL{0},AJ{0},C{0},$D$5)=4,$D$5>=0,$D$5<0.8),AL{0}-MAX(AJ{0}-C{0},0)*$D$5,"UNKNOWN")'.format(k),r['target_net_tax'])
        # Integer-tick binary search; robust to ROUND jumps and small quantities.
        # The documented net-proceeds slope bound handles fee-rounding jumps.
        for output,key,hold,settle,tx,buf in [('AE','pure','0','0','0','0'),('AF','today_be','0','$F$5','0','0'),('AD','full','$F$4','$F$5','$D$5','$D$7')]:
            seedrow=nextrow;nextrow+=1
            need='(C{0}+H{0}+I{0}+E{0}*$D$4*{1}/365+{2})'.format(k,hold,buf)
            a='(1-%s-(%s+%s+%s)*(1+%s)-%s-$D$4*%s/365)'%(refc['stt'],refc['exchange'],refc['sebi'],refc['ipft'],refc['gst'],tx,settle)
            num='(%s+(%s+%s)*(1+%s)-%s*C%d)'%(need,refc['dp'],refc['pledge'],refc['gst'],tx,k)
            unc='%s/(%s-%s*(1+%s))'%(num,a,refc['broker'],refc['gst']);capped='(%s+%s*(1+%s))/%s'%(num,refc['cap'],refc['gst'],a)
            seed=None
            if r['lot_basis_ok']:
                seed=_seed(r['qty'],r['cost'],r['past'],r['buy'],r['funded'],rate,days if hold!='0' else 0,settlement if settle!='0' else 0,tax if tx!='0' else 0,2 if buf!='0' else 0)
            f('B'+str(seedrow),'IF(AG%d=1,IF(%s<=%s/%s,%s,%s)/B%d,"UNKNOWN")'%(k,unc,refc['cap'],refc['broker'],unc,capped,k),seed)
            # All editable valid scenarios have slope >= .05. Therefore
            # seed +/- Rs20/qty brackets every possible rounded-fee root.
            q=r['qty'] if finite(r['qty']) and r['qty']>0 else 1
            width=math.ceil(40/q/.05)+3
            grid_start=nextrow;valid_prices=[]
            lowtick=max(1,math.floor((seed-20/q)/.05)) if seed is not None else None
            for offset in range(width):
                j=nextrow;nextrow+=1
                price=round((lowtick+offset)*.05,8) if lowtick is not None else None
                gross=price*q if price is not None else None
                cost_fee=fees(gross)['total'] if gross is not None else None
                net=target_net(price,q,r['cost'],r['past'],r['buy'],r['funded'],rate,days if hold!='0' else 0,settlement if settle!='0' else 0,tax if tx!='0' else 0) if price is not None else None
                needed=2 if buf!='0' else 0
                eligible=price if net is not None and net>=needed else 1E99 if net is not None else None
                if eligible is not None and eligible!=1E99:valid_prices.append(eligible)
                f('B'+str(j),'IF(COUNT(B%d,$B$%d)=2,(MAX(1,FLOOR((B%d-20/$B$%d)/$F$6,1))+%d)*$F$6,"UNKNOWN")'%(seedrow,k,seedrow,k,offset),price)
                f('C'+str(j),'B%d*$B$%d'%(j,k),gross)
                f('D'+str(j),fee_formula('C'+str(j)),cost_fee)
                f('E'+str(j),'C{0}-$C${1}-$H${1}-$I${1}-D{0}-$E${1}*$D$4*{2}/365-C{0}*$D$4*{3}/365-MAX(C{0}-$C${1},0)*{4}'.format(j,k,hold,settle,tx),net)
                f('F'+str(j),'IF(COUNT(B{0},E{0})=2,IF(E{0}>={1},B{0},1E99),"UNKNOWN")'.format(j,buf),eligible)
            f(output+str(k),'IF(AND(AG%d=1,COUNT($F$%d:$F$%d)=%d,MIN($F$%d:$F$%d)<1E99),MIN($F$%d:$F$%d),"UNKNOWN")'%(k,grid_start,nextrow-1,width,grid_start,nextrow-1,grid_start,nextrow-1),r[key])
    # Visible sections refer only to guarded helpers / documented source inputs.
    def sumfield(c,key):
        value=total(rows,key)
        expr='IF(AND(COUNT(%s%d:%s%d)=%d,COUNT($D$6)=1),SUM(%s%d:%s%d),"UNKNOWN")'%(c,hstart,c,hend,n,c,hstart,c,hend) if n else '0' if complete(R,rows) else '"UNKNOWN"'
        return expr,value if n else 0 if complete(R,rows) else None
    bar(10,'SECTION 1 — AAPKA LAGAYA PAISA / INVESTOR CAPITAL BREAKDOWN')
    caprows=[(12,'Total FIFO purchase value','D6',basis,'SOURCE','Share cost; purchase fees separate.'),(13,'Current broker funded loan','B5',loan,'SOURCE','Current principal, not historical funding.'),(14,'Own principal: cost - current loan','F','own','DERIVED','Current principal split; original deposits not proven.'),(15,'Actual ORIGINAL margin supplied','B7',number(R.get('init_cash')),'USER / UNKNOWN','Broker API does not give it: type it in B7 or run rbmtf --own-cash <Rs> once.'),(16,'Accrued interest MODEL','H','past','ESTIMATED','Current funded ratio x each lot cost x calendar age x rate/365.'),(17,'Actual interest PAID for current lots',None,None,'UNKNOWN','Account-wide history is not allocated to these remaining lots.'),(18,'As-of UNPAID interest','B6',unpaid,'SOURCE / MODEL','Excludes future exit reserve. See source comment.'),(19,'Paid-interest PROXY','AB','paid_proxy','ESTIMATED','Model accrual - outstanding proxy; not a ledger-certified amount.'),(20,'Own principal + paid proxy',None,None,'ESTIMATED','Requested cash-burden model before purchase fees.'),(21,'Purchase/pledge costs MODEL','I','buy','ESTIMATED','One purchase order + pledge per remaining tranche.'),(22,'Cash burden incl buy fees','AC','pocket','ESTIMATED','Reconciliation proxy; not original deposits.'),(23,'Current daily interest burn','G','daily','ESTIMATED','Rs/day; current funded balance x rate/365.'),(24,'ACTUAL total cash out of pocket',None,None,'UNKNOWN','Historical funding/interest allocation required.')]
    for k,label,expr,value,status,explain in caprows:
        put('A'+str(k),label);put('C'+str(k),status);put('D'+str(k),explain);s.merge_cells(start_row=k,start_column=4,end_row=k,end_column=11)
        if k==15:f('B15','IF(ISNUMBER(B7),B7,"UNKNOWN")',number(R.get('init_cash')))   # blank B7 -> UNKNOWN, never 0
        elif k==20:f('B20','IF(COUNT(B14,B19)=2,B14+B19,"UNKNOWN")',total(rows,'own')+total(rows,'paid_proxy') if total(rows,'own') is not None and total(rows,'paid_proxy') is not None else 0 if not n and complete(R,rows) else None)
        elif k in (14,16,19,21,22,23):ex,val=sumfield(expr,value);f('B'+str(k),ex,val)
        elif expr:f('B'+str(k),expr,value)
        else:put('B'+str(k),UNKNOWN)
    bar(sec2,'SECTION 2 — PER-STOCK HOLDINGS / LOAN / INTEREST')
    for j,label in enumerate(['Stock','Qty','FIFO avg','Buy cost','Loan proxy','Own principal','Kitne din se (purani se nayi buy)','Daily burn','Interest MODEL','Actual paid interest','Price source'],1):put(col(j)+str(head2),label)
    for i,r in enumerate(rows):
        k=hstart+i;v=start2+i;put('A'+str(v),r['symbol'])
        for c,helper,key in [('B','B','qty'),('D','C','cost'),('E','E','funded'),('F','F','own'),('H','G','daily'),('I','H','past')]:f(c+str(v),helper+str(k),r[key])
        f('C'+str(v),'IF(COUNT(B{0},D{0})=2,IF(B{0}>0,D{0}/B{0},"UNKNOWN"),"UNKNOWN")'.format(v),r['cost']/r['qty'] if r['cost'] is not None and r['qty'] else None)
        indices=[lot_start+j for j,z in enumerate(all_lots) if z['symbol']==r['symbol']]
        # RB 9 Oct: '303, 261, 261, 247, 239, 148' was unreadable (+ Numbers warned on TEXT()). Now
        # 'oldest se newest din (N buys)'; every lot stays listed in the FIFO tranche table below.
        dd=[z['days'] for z in r['lots']];nb=len(dd);bl='buy' if nb==1 else 'buys'
        dval=(('%d din (1 buy)'%dd[0]) if nb==1 else '%d se %d din (%d buys)'%(max(dd),min(dd),nb)) if dd and all(isinstance(x,int) for x in dd) else None
        rng=','.join('F%d'%k for k in indices)
        if indices:f('G'+str(v),('IF(COUNT({0})={1},MAX({0})&" se "&MIN({0})&" din ({1} buys)","UNKNOWN")' if nb>1 else 'IF(COUNT({0})=1,{0}&" din (1 buy)","UNKNOWN")').format(rng,nb),dval)
        else:put('G'+str(v),UNKNOWN)
        put('J'+str(v),UNKNOWN);put('K'+str(v),r['price_source']);s.row_dimensions[v].height=30
    put('A'+str(total2),'TOTAL')
    for c,helper,key in [('B','B','qty'),('D','C','cost'),('E','E','funded'),('F','F','own'),('H','G','daily'),('I','H','past')]:ex,val=sumfield(helper,key);f(c+str(total2),ex,val)
    bar(sec3,'SECTION 3 — AAJ BECHO: ACCOUNT CASH CREDIT vs NET P/L')
    put('A'+str(head3),'Metric');tcol=col(n+2)
    for i,r in enumerate(rows):put(col(i+2)+str(head3),r['symbol'])
    put(tcol+str(head3),'TOTAL')
    for j,(label,key,helper) in enumerate(metrics):
        v=start3+j;put('A'+str(v),label)
        values=[]
        for i,r in enumerate(rows):
            value=(r['sale_fees'] or {}).get('total' if key=='fee_total' else key) if helper in ('L','M','N','O','P','Q','R','S','T') else r.get(key)
            values.append(value)
            if key:f(col(i+2)+str(v),helper+str(hstart+i),value)
            else:put(col(i+2)+str(v),UNKNOWN)
        if key:
            val=sum(values) if values and all(finite(x) for x in values) and finite(basis) else 0 if not n and complete(R,rows) else None
            ex='IF(AND(COUNT(B{0}:{1}{0})={2},COUNT($D$6)=1),SUM(B{0}:{1}{0}),"UNKNOWN")'.format(v,col(n+1),n) if n else '0' if complete(R,rows) else '"UNKNOWN"'
            f(tcol+str(v),ex,val)
        else:put(tcol+str(v),UNKNOWN)
        if key in ('cash','net_exit','now_net_tax','fee_total'):
            for c in s[v]:c.fill=PatternFill('solid',fgColor=YELLOW)
    note(start3+len(metrics)+1,'Paid interest is not deducted again from payout. Tax reserve is separate from broker payout. Exit reserve = full gross sale value x rate x additional calendar days / 365; not confirmed T+3 settlement.')
    bar(sec4,'SECTION 4 — SAFE TARGET: %d DIN TAK HOLD KARO TO NET P/L vs AAJ BECHO'%days)
    # RB 9 Oct: per stock -> target price, by which date, net P/L at that target, net P/L if sold today.
    heads4=['Stock','LTP / scenario','Safe hold+exit+tax','Kitna upar %','Target date (aaj + %d din)'%days,'Interest ab tak (MODEL)','Interest aaj se target date tak','Net P/L target pe (tax se pehle)','Net P/L target pe (tax reserve ke baad)','Net P/L AAJ becho','Pure BE now','BE incl exit reserve','Safe exit reserve']
    for j,label in enumerate(heads4,1):put(col(j)+str(head4),label)
    serial=lambda d:(d-dt.date(1899,12,30)).days if d is not None else None
    for i,r in enumerate(rows):
        k=hstart+i;v=start4+i;put('A'+str(v),r['symbol'])
        for c,h,key in [('C','AD','full'),('F','H','past'),('G','AH','hold_interest'),('H','AL','target_net'),('I','AM','target_net_tax'),('J','Z','net_exit'),('K','AE','pure'),('L','AF','today_be'),('M','AI','safe_exit_interest')]:f(c+str(v),h+str(k),r[key])
        f('D'+str(v),'IF(COUNT(B{0},C{0})=2,IF(B{0}>0,C{0}/B{0}-1,"UNKNOWN"),"UNKNOWN")'.format(v),r['recovery'])
        f('E'+str(v),'IF(AND(COUNT($B$4,$F$4)=2,$F$4>=0),$B$4+$F$4,"UNKNOWN")',serial(r['target_date']))
    if n:
        put('A'+str(start4+n),'TOTAL')
        for c,key in [('F','past'),('G','hold_interest'),('H','target_net'),('I','target_net_tax'),('J','net_exit')]:
            vals=[r[key] for r in rows]
            f(c+str(start4+n),'IF(COUNT({0}{1}:{0}{2})={3},SUM({0}{1}:{0}{2}),"UNKNOWN")'.format(c,start4,start4+n-1,n),sum(vals) if all(finite(x) for x in vals) else None)
    note(start4+n+1,'Target date tak safe target pe becha to net P/L = H/I: ab tak ka interest (F) + aaj se target date tak ka interest (G, %d din) + %d din exit reserve + buy/sell charges sab kata hua; pehle becha to interest kam = net thoda zyada. I ~ Rs2 = safe target ki definition. J = aaj becho (exit reserve incl., tax reserve se pehle; Section 3 jaisa).'%(days,settlement))
    for j,label in enumerate(['Hypothetical equity floor','Critical portfolio value','Uniform fall %','Current equity %','Extra cash/collateral'],1):put(col(j)+str(risk),label)
    value=total(rows,'value')
    for i,m in enumerate([.20,.25,.30]):
        v=risk+i+1;put('A'+str(v),m)
        f('B'+str(v),'IF(COUNT($B$5)=1,$B$5/(1-A%d),"UNKNOWN")'%v,loan/(1-m) if loan is not None else None)
        valcell=tcol+str(map3['value'])
        f('C'+str(v),'IF(COUNT(B{0},{1})=2,IF({1}>0,1-B{0}/{1},"UNKNOWN"),"UNKNOWN")'.format(v,valcell),1-loan/(1-m)/value if loan is not None and value is not None and value>0 else None)
        f('D'+str(v),'IF(COUNT($B$5,{0})=2,IF({0}>0,({0}-$B$5)/{0},"UNKNOWN"),"UNKNOWN")'.format(valcell),(value-loan)/value if loan is not None and value is not None and value>0 else None)
        put('E'+str(v),'Zero extra collateral SCENARIO');s.row_dimensions[v].height=32
    note(risk+4,'Actual calls UNKNOWN: broker stock margins, VaR/ELM, free cash and combined collateral missing. Simplified equity/value scenarios are not broker trigger prices; RMS can act earlier.')
    notes_text=[
        'Past interest: today-funded ratio x each lot cost x calendar age. Funding conversion/settlement dates and historical rate/balance changes are not proven. Actual current-lot paid interest remains UNKNOWN.',
        'Cash bridge: payout - own principal - paid-interest PROXY - modeled buy costs = modeled net P/L through the same exit reserve. Negative paid proxy is UNKNOWN. Account-wide debits/credits are not included.',
        'Safe target: pure cost + future funded-loan holding interest + full-sale-value exit reserve + per-stock positive gross-gain reserve + Rs2 buffer. Exact minimum .05 tick UNDER THE MODEL; verify exchange tick before orders.',
        'Extreme rate/reserve combinations with net proceeds coefficient below 5% are unsupported and produce UNKNOWN targets. Standard 30+3-day scenarios meet this condition.',
        'Tax reserve is not tax payable/withheld. Capital-loss setoffs, deductions, long-term exemptions and surcharge are not modeled. Override the reserve only for a justified personal scenario.',
        'Buy fees: min(Rs20,.03%) once per remaining tranche plus one pledge request; actual order/instruction counts missing. Sell: one full-quantity order + DP + unpledge; no sell stamp duty. DP/unpledge base Rs27.50 excludes GST.',
        'Quote inputs are scenarios when edited. This workbook does not fetch prices; rbmtf refreshes available validated quotes and reconciled account data at each run. Missing/stale rejected prices remain UNKNOWN.',
        'Fees: '+FEES_SOURCE,
        'Interest: '+INTEREST_SOURCE,
        'Risk: '+RISK_SOURCE+' | Tax: https://www.incometaxindia.gov.in/en/sale-of-shares',
    ]
    for i,tx in enumerate(notes_text):note(notes+i,tx)
    # Preserve source failures visibly, including current inventory gaps.
    source_row=lot_end+3 if all_lots else lot_start+2
    for key,(status,text) in sorted(R.get('src',{}).items()):note(source_row,str(key)+' | '+str(status)+' | '+str(text));source_row+=1
    if getattr(R.get('exit'),'status',None)==UNKNOWN:note(source_row,'Cash basis UNKNOWN: '+getattr(R['exit'],'note','required settlement input missing'));source_row+=1
    if not rows:note(sec2+1,'No current MTF positions.' if complete(R,rows) else 'CURRENT INVENTORY NOT RECONCILED. No zero-position conclusion; financial results UNKNOWN.')
    for rr in s:
        for cell in rr:
            if cell.fill.fgColor.rgb not in (NAVY,'00'+NAVY):cell.font=Font(name='Arial',size=10,color='000000' if cell.data_type=='f' else '0000FF' if isinstance(cell.value,(int,float,dt.date)) else NAVY)
            cell.alignment=Alignment(wrap_text=True,vertical='center',horizontal=_align(cell,sec2,start4))
            if cell.data_type=='f' or isinstance(cell.value,(int,float)):cell.number_format=MONEY_FMT
    plain=['F4','F5','F7']+['B'+str(k) for k in range(start2,total2+1)]+[c+str(k) for k in range(lot_start,lot_end+1) for c in 'CF']
    for ref in plain:s[ref].number_format='#,##0'
    for ref in ['D4','D5']+['D'+str(start4+i) for i in range(n)]+[c+str(risk+i) for i in [1,2,3] for c in 'ACD']:s[ref].number_format='0.00%'
    s['B4'].number_format='dd-mmm-yyyy'
    for k in range(lot_start,lot_end+1):s['B'+str(k)].number_format='dd-mmm-yyyy'
    for i in range(n):s['E'+str(start4+i)].number_format='dd-mmm-yyyy'
    for k in [head2,head3,head4,risk,lot_head,total2]:
        s.row_dimensions[k].height=58 if k==head4 else 44
        for c in s[k]:c.fill=PatternFill('solid',fgColor=PALE);c.font=Font(name='Arial',bold=True,color=NAVY,size=10)
    # RB 9 Oct (2nd screenshot): 'column bahut bade' -> compact: labels 24, numbers 14, one-line rows.
    for k in range(4,8):s.row_dimensions[k].height=30
    for k in range(12,25):s.row_dimensions[k].height=28
    for k in range(start3,start3+len(metrics)):s.row_dimensions[k].height=26
    for k in range(start4,start4+n+1):s.row_dimensions[k].height=22
    for k in range(start4+n,start4+n+1):
        for c in s[k]:c.font=Font(name='Arial',size=10,bold=True,color='C00000' if isinstance(cache.get(c.coordinate),(int,float)) and cache[c.coordinate]<0 else '000000')
    for j in range(1,max(18,n+3)):s.column_dimensions[col(j)].width=24 if j==1 else 22 if j==11 else 14
    # RB 9 Oct: 'negative entries red honni chahiye' -> red font written into the cell itself
    # (works in Numbers/Sheets/Excel); the conditional rule below re-colours after edits in Excel/Sheets.
    for ref,val in cache.items():
        if isinstance(val,(int,float)) and not isinstance(val,bool) and val<0:s[ref].font=Font(name='Arial',size=10,color='C00000',bold=s[ref].font.bold)
    from openpyxl.formatting.rule import CellIsRule
    s.conditional_formatting.add('B4:AM%d'%max(nextrow,source_row),CellIsRule(operator='lessThan',formula=['0'],font=Font(name='Arial',size=10,color='C00000')))
    s.row_dimensions.group(hstart,nextrow,hidden=True)
    s.freeze_panes='B1';s.sheet_view.showGridLines=False;s.sheet_properties.pageSetUpPr.fitToPage=True;s.page_setup.orientation='landscape';s.page_setup.fitToWidth=1;s.page_setup.fitToHeight=0;s.print_area='A1:'+col(max(17,n+2))+str(max(source_row,lot_end,fee_start+10))
    for refs,kind,lo,hi in [('B5 B6 B7','decimal',0,1e10),('D4','decimal',0,.999),('D5','decimal',0,.799),('F4','whole',0,3650),('F5','whole',0,90)]+[('B'+str(start4+i),'decimal',.01,1e10) for i in range(n)]:
        dv=DataValidation(type=kind,operator='between',formula1=str(lo),formula2=str(hi),allow_blank=True);dv.showErrorMessage=True;dv.error='Enter an input in the documented range.';s.add_data_validation(dv)
        for ref in refs.split():dv.add(s[ref])
    w.calculation.fullCalcOnLoad=True;w.calculation.forceFullCalc=True;w.calculation.calcMode='auto'
    path=validate_output_path(Path(path));path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.mtf-report-',suffix='.xlsx',dir=str(path.parent));os.close(fd)
    try:
        w.save(tmp);cache_formula_values(tmp,cache);validate_output_path(path);os.replace(tmp,path)
    finally:
        for p in [tmp,tmp+'.tmp']:
            if os.path.exists(p):os.unlink(p)
    return rows
