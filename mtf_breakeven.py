"""One-sheet CURRENT MTF breakeven model; calendar-day holding buffer.
Estimated historical funding allocation/fees, not a certified settlement or tax result.
No broker calls or orders. Formulas remain editable; calculated caches are verified separately.
"""
import datetime as dt,math,os,re,tempfile,zipfile,xml.etree.ElementTree as ET
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font,PatternFill,Alignment
from openpyxl.formatting.rule import CellIsRule
from openpyxl.comments import Comment
from openpyxl.worksheet.datavalidation import DataValidation
EXCH=.0000307;SEBI=.000001;IPFT=.000000001;GST=.18;STT=.001;STAMP=.00015
BROK_CAP=20;BROK_RATE=.0003;DP=12.5;PLEDGE=15
SOURCE_FEES='https://dhan.co/support/mtf-pledge-experience/mtf-general/what-charges-do-i-have-to-pay-on-mtf/'
SOURCE_TAX='https://www.incometaxindia.gov.in/w/capital-gain'
def finite(v):
 try:return math.isfinite(float(v))
 except (TypeError,ValueError):return False
def ceil_tick(p,tick):return math.ceil(p/tick-1e-10)*tick
def sell_cost(value,orders=1):
 return value*(STT+(EXCH+SEBI+IPFT)*(1+GST))+min(BROK_CAP*orders,BROK_RATE*value)*(1+GST)+(DP+PLEDGE)*(1+GST)
def target(q,cost,past,future,buy,tax=0,orders=1,tick=.05,rounding=2):
 if not all(finite(x) for x in (q,cost,past,future,buy,tax,orders,tick,rounding)) or q<=0 or cost<=0 or min(past,future,buy,rounding)<0 or not 0<=tax<.8 or orders<1 or tick<=0:return None
 need=cost+past+future+buy+rounding
 a=1-STT-(EXCH+SEBI+IPFT)*(1+GST)-tax
 fixed=(DP+PLEDGE)*(1+GST)
 numerator=need+fixed-tax*cost
 uncapped=numerator/(a-BROK_RATE*(1+GST))
 gross=uncapped if uncapped<=BROK_CAP*orders/BROK_RATE else (numerator+BROK_CAP*orders*(1+GST))/a
 # Tax reserve on gross price gain is intentionally conservative (eligible
 # transaction deductions/setoffs are not modeled). Need >= cost => gain >=0.
 return ceil_tick(gross/q,tick)
def calculate(R,today,days=30,settlement=3,tax=.208,tick=.05):
 loan=R['loan'].value if R['loan'].known else None
 known_total=R['open_cost_num'].value if R['open_cost_num'].known else None
 out=[]
 rate=R.get('breakeven_rate',.1249)
 valid_inputs=all(finite(v) for v in (days,settlement,tax,tick,rate)) and 0<=days<=3650 and 0<=settlement<=90 and 0<=tax<.8 and tick>0 and 0<=rate<1
 for row in sorted(R['rows'],key=lambda r:(0 if r['Symbol']=='TCS' else 1,r['Symbol'])):
  sym=row['Symbol'];lots=R['fifo']['lots'].get(sym,[])
  c=row['Open cost (Rs)'].value if row['Open cost (Rs)'].known else None
  q=row['Qty'];date_qty=sum(x[1] for x in lots)
  try:valid_dates=all(dt.date.fromisoformat(x[0])<=today for x in lots)
  except (TypeError,ValueError):valid_dates=False
  ready=bool(valid_inputs and finite(loan) and finite(known_total) and known_total>0 and 0<=loan<=known_total and finite(c) and c>0 and q>0 and abs(date_qty-q)<1e-8 and valid_dates and abs(sum(x[1]*x[2] for x in lots)-c)<.02)
  funded=loan*c/known_total if ready else None
  # Current total funded share is an explicit estimated historical proxy.
  past=sum(x[1]*x[2]*(today-dt.date.fromisoformat(x[0])).days for x in lots)*loan/known_total*R.get('breakeven_rate',.1249)/365 if ready else None
  rate=R.get('breakeven_rate',.1249)
  future=funded*rate*(days+settlement)/365 if ready else None
  # Conservative cap per remaining purchase lot + one pledge per lot; no
  # claim this is actual contract-note fee allocation or order count.
  buy=c*(STT+STAMP+(EXCH+SEBI+IPFT)*(1+GST))+len(lots)*(BROK_CAP+PLEDGE)*(1+GST) if ready else None
  broker=target(q,c,past,future,buy,tax=0,tick=tick) if ready else None
  full=target(q,c,past,future,buy,tax=tax,tick=tick) if ready else None
  fee=sell_cost(q*full) if full is not None else None
  reserve=max(q*full-c,0)*tax if full is not None else None
  net=q*full-fee-reserve-c-past-future-buy if full is not None else None
  cmp=row.get('Price')
  valid_price=finite(cmp) and cmp>0 and finite(q) and q>0
  now_value=q*cmp if valid_price else None
  price_pnl=now_value-c if now_value is not None and finite(c) and c>0 else None
  with_interest=price_pnl-past if price_pnl is not None and past is not None else None
  now_sale_fee=sell_cost(now_value) if now_value is not None else None
  now_tax=max(price_pnl,0)*tax if price_pnl is not None and valid_inputs else None
  now_net=with_interest-buy-now_sale_fee if with_interest is not None and buy is not None and now_sale_fee is not None else None
  now_net_tax=now_net-now_tax if now_net is not None and now_tax is not None else None
  out.append(dict(now_value=now_value,price_pnl=price_pnl,with_interest=with_interest,now_sale_fee=now_sale_fee,now_tax=now_tax,now_net=now_net,now_net_tax=now_net_tax,price_source=row.get('Price source','quote provenance not supplied'),symbol=sym,qty=q,cmp=row.get('Price'),cost=c,lots=lots,funded=funded,past=past,future=future,buy=buy,broker=broker,full=full,sell_fee=fee,tax=reserve,net=net,status='ESTIMATED' if ready else 'UNKNOWN'))
 return out

def cache_formula_values(path,values):
 """Keep formulas, set display caches from the independent Python model.
 Excel recalculates all editable inputs on open. No macro/add-in required."""
 ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'};tag='{'+ns['s']+'}'
 with zipfile.ZipFile(path) as z: entries={name:z.read(name) for name in z.namelist()}
 root=ET.fromstring(entries['xl/worksheets/sheet1.xml'])
 for cell in root.findall('.//s:c',ns):
  ref=cell.attrib.get('r')
  if ref not in values or cell.find(tag+'f') is None:continue
  for v in list(cell):
   if v.tag==tag+'v':cell.remove(v)
  val=values[ref]
  if val is None:
   cell.set('t','str');ET.SubElement(cell,tag+'v').text=''
  elif isinstance(val,str):
   cell.set('t','str');ET.SubElement(cell,tag+'v').text=val
  else:
   cell.attrib.pop('t',None)
   ET.SubElement(cell,tag+'v').text=str(float(val))
 entries['xl/worksheets/sheet1.xml']=ET.tostring(root,encoding='utf-8',xml_declaration=True)
 tmp=str(path)+'.tmp'
 with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
  for name,data in entries.items():z.writestr(name,data)
 os.replace(tmp,path)

def write_report(R,today,path,days=30,settlement=3,tax=.208,rate=.1249):
 path=Path(path)
 if path.is_symlink():raise ValueError('Refusing symlink report destination')
 R=dict(R,breakeven_rate=rate);rows=calculate(R,today,days,settlement,tax)
 w=Workbook();s=w.active;s.title='Breakeven';cache={}
 def put(ref,value,note=None):
  s[ref]=value
  if note:s[ref].comment=Comment(note,'Source / assumption')
 def formula(ref,value,calc):put(ref,value);cache[ref]=calc
 s.merge_cells('A1:G1');put('A1','CURRENT MTF — %d DIN KA BREAKEVEN'%days)
 s.merge_cells('A3:G3');put('A3','Account: '+str(R.get('report_account','source snapshot / account not supplied')))
 s.merge_cells('A2:G2');put('A2','ESTIMATED targets: current holdings only; past closed trades excluded. Sell the FULL quantity at the target; not a live quote or guaranteed fill.')
 for ref,value in {'A4':'As of','B4':today,'C4':'Holding days','D4':days,'E4':'Annual rate','F4':rate,'A5':'Settlement buffer','B5':settlement,'C5':'Current loan Rs','D5':R['loan'].value if R['loan'].known else None,'E5':'Tax reserve rate','F5':tax,'A6':'Tick Rs','B6':.05,'C6':'Rounding buffer Rs','D6':2}.items():put(ref,value)
 put('D5',R['loan'].value if R['loan'].known else None,R['loan'].note)
 put('F5',tax,'Optional conservative tax reserve on gross positive price gain, no loss setoff/transaction deductions/surcharge. Not an actual tax liability. Source: '+SOURCE_TAX)
 put('B5',settlement,'Extra calendar days after the 30-day holding buffer. This default is a scenario reserve, not an NSE settlement calendar prediction. Change if broker settlement is longer.')
 headers=['Stock','Shares','Saved / current price Rs','Broker-cost BE Rs','BE + tax reserve Rs','Rise to tax target','Status']
 for j,h in enumerate(headers,1):s.cell(9,j,h)
 s.merge_cells('A8:G8');put('A8','Prices: '+'; '.join(r['symbol']+' — '+r['price_source'] for r in rows))
 s['A8'].alignment=Alignment(wrap_text=True,vertical='center');s.row_dimensions[8].height=32
 s.merge_cells('A7:G7');formula('A7','="Holding horizon: "&TEXT(B4+D4,"dd-mmm-yyyy")&"; interest reserve through "&TEXT(B4+D4+B5,"dd-mmm-yyyy")&". Split exits change targets."','Holding horizon: '+(today+dt.timedelta(days=days)).strftime('%d-%b-%Y')+'; interest reserve through '+(today+dt.timedelta(days=days+settlement)).strftime('%d-%b-%Y')+'. Split exits change targets.')
 s.merge_cells('A13:G13');put('A13','Blue cells = editable inputs. Loan is allocated by cost ratio; actual stock-wise loan and past charges were not provided.')
 s.merge_cells('A14:G14');put('A14','Past interest already includes paid + unbilled modeled days: no second deduction of the full account ledger interest or unpaid estimate.')
 start=44;lot_rows=[]
 for j,r in enumerate(rows):
  for date,q,p,fee in r['lots']:
   k=start+len(lot_rows);lot_rows.append((k,r['symbol'],date,q,p))
   put('A'+str(k),r['symbol']);put('B'+str(k),dt.date.fromisoformat(date));put('C'+str(k),q);put('D'+str(k),p)
   formula('E'+str(k),'=C%d*D%d'%(k,k),q*p)
   age=(today-dt.date.fromisoformat(date)).days
   formula('F'+str(k),'=MAX(0,$B$4-B%d)'%k,age)
   # Excel must preserve the same inventory/funding gate as the Python model.
   # A visible sum of candidate costs is not a reconciled funded-share basis.
   ready=r['status']=='ESTIMATED'
   formula('G'+str(k),'=IF(COUNT($D$5,$D$18)=2,IF($D$18>0,$D$5/$D$18,""),"")' if ready else '=""',R['loan'].value/R['open_cost_num'].value if ready else None)
   formula('H'+str(k),'=IF(COUNT(G%d)=1,E%d*F%d*G%d*$F$4/365,"")'%(k,k,k,k) if ready else '=""',q*p*age*(R['loan'].value/R['open_cost_num'].value)*rate/365 if ready else None)
 end=max(start,start+len(lot_rows)-1)
 s.cell(16,1,'COST BREAKUP (same sheet)')
 labels={17:'Quantity',18:'Current FIFO cost Rs',19:'Allocated loan Rs',20:'Past interest estimate Rs',21:'Next holding + settlement interest Rs',22:'Buy taxes/brokerage/pledge estimate Rs',23:'Recovery needed before sale Rs',24:'Broker-cost target Rs',25:'Target with tax reserve Rs',26:'Sell taxes/brokerage/DP/unpledge Rs',27:'Income-tax reserve Rs',28:'Net at tax target after model costs Rs'}
 for k,label in labels.items():put('A'+str(k),label)
 formula('D18','=SUM(B18:C18)',sum(r['cost'] for r in rows if r['cost'] is not None))
 # Published cost inputs are explicit, editable, documented, and referenced.
 constants=[('Variable sale fee fraction',STT+(EXCH+SEBI+IPFT)*(1+GST)),('Brokerage cap Rs',BROK_CAP),('Brokerage fraction',BROK_RATE),('GST rate',GST),('DP + unpledge base Rs',DP+PLEDGE),('Variable buy fee fraction',STT+STAMP+(EXCH+SEBI+IPFT)*(1+GST)),('Pledge base Rs',PLEDGE)]
 for k,(label,val) in enumerate(constants,31):put('A'+str(k),label);put('B'+str(k),val,'Published charges model; source: '+SOURCE_FEES+' and https://dhan.co/pricing/. One sell order and one unpledge per stock; buy cap/pledge per remaining lot assumed conservatively.')
 for j,r in enumerate(rows):
  c=chr(66+j);top=10+j;put(c+'16',r['symbol']);formula(c+'17','=SUMIF($A$%d:$A$%d,%s16,$C$%d:$C$%d)'%(start,end,c,start,end),r['qty'])
  # Third+ stocks use additional columns; this focused report supports all current rows.
  if j>1:raise ValueError('Focused breakeven report currently supports at most two stocks; use --audit for larger inventory')
  ready=r['status']=='ESTIMATED';put('A'+str(top),r['symbol']);formula('B'+str(top),'=%s17'%c,r['qty']);put('C'+str(top),r['cmp'])
  formule={18:'=SUMIF($A$%d:$A$%d,%s16,$E$%d:$E$%d)'%(start,end,c,start,end),19:'=IF(COUNT($D$5,$D$18)=2,IF($D$18>0,$D$5*%s18/$D$18,""),"")'%c,20:'=IF(COUNT(%s19)=1,SUMIF($A$%d:$A$%d,%s16,$H$%d:$H$%d),"")'%(c,start,end,c,start,end),21:'=IF(COUNT(%s19)=1,%s19*$F$4*($D$4+$B$5)/365,"")'%(c,c),22:'=%s18*$B$36+COUNTIF($A$%d:$A$%d,%s16)*($B$32+$B$37)*(1+$B$34)'%(c,start,end,c),23:'=IF(COUNT(%s18:%s22)=5,SUM(%s18,%s20:%s22)+$D$6,"")'%(c,c,c,c,c)}
  vals={18:r['cost'],19:r['funded'],20:r['past'],21:r['future'],22:r['buy'],23:r['cost']+r['past']+r['future']+r['buy']+2 if ready else None}
  for k,f in formule.items():formula(c+str(k),f if ready else '="UNKNOWN"',vals[k] if ready else 'UNKNOWN')
  for k,t,calc in [(24,'0',r['broker']),(25,'$F$5',r['full'])]:
   numerator='(%s23+$B$35*(1+$B$34)-%s*%s18)'%(c,t,c)
   a='(1-$B$31-%s)'%t
   uncapped='%s/(%s-$B$33*(1+$B$34))'%(numerator,a)
   capped='(%s+$B$32*(1+$B$34))/%s'%(numerator,a)
   f='=CEILING(IF(%s<=$B$32/$B$33,%s,%s)/%s17,$B$6)'%(uncapped,uncapped,capped,c)
   formula(c+str(k),f if ready else '="UNKNOWN"',calc if ready else 'UNKNOWN')
  formula(c+'26','=%s17*%s25*$B$31+MIN($B$32,%s17*%s25*$B$33)*(1+$B$34)+$B$35*(1+$B$34)'%(c,c,c,c) if ready else '="UNKNOWN"',r['sell_fee'] if ready else 'UNKNOWN')
  formula(c+'27','=MAX(%s17*%s25-%s18,0)*$F$5'%(c,c,c) if ready else '="UNKNOWN"',r['tax'] if ready else 'UNKNOWN')
  formula(c+'28','=%s17*%s25-SUM(%s18,%s20:%s22,%s26:%s27)'%(c,c,c,c,c,c,c) if ready else '="UNKNOWN"',r['net'] if ready else 'UNKNOWN')
  formula('D'+str(top),'=%s24'%c,r['broker'] if ready else 'UNKNOWN');formula('E'+str(top),'=%s25'%c,r['full'] if ready else 'UNKNOWN')
  formula('F'+str(top),'=IF(COUNT(C%d,E%d)=2,IF(C%d>0,E%d/C%d-1,""),"")'%(top,top,top,top,top),(r['full']/r['cmp']-1) if ready and finite(r['cmp']) and r['cmp']>0 else None)
  put('G'+str(top),r['status'])
 for refs,kind,lo,hi in [('D4','whole',0,3650),('B5','whole',0,90),('F4','decimal',0,.999),('F5','decimal',0,.799),('B6','decimal',.01,100),('D6','decimal',0,10000),('D5','decimal',0, sum(r['cost'] or 0 for r in rows))]:
  dv=DataValidation(type=kind,operator='between',formula1=str(lo),formula2=str(hi),allow_blank=False);dv.showErrorMessage=True;dv.errorTitle='Invalid assumption';dv.error='Enter a valid non-negative assumption in the documented range.';s.add_data_validation(dv);dv.add(s[refs])
 s.merge_cells('A39:G39');put('A39','Tax reserve uses 20.8% by default on gross gain. Actual setoffs, deductions, holding period, surcharge and personal tax can change it. This is a reserve, not tax advice.')
 s.merge_cells('A40:G40');put('A40','Source: supplied trade/ledger and saved price snapshot; historical stock interest uses current funded share as proxy. Unknown extra account costs cannot be certified as fully included.')
 for j,h in enumerate(['Stock','Buy date','Open qty','Buy price','Cost','Days held','Funded share proxy','Past interest'],1):s.cell(43,j,h)
 # Move the existing cost/assumption/lot sections intact so current P&L is
 # visible immediately after the sell targets. Rewrite references once from
 # the ORIGINAL coordinates, then move cells without a second translation.
 def newrow(k):
  return k+8 if 16<=k<=28 else k+21 if 31<=k<=37 else k+20 if 43<=k<=end else k
 def mapped_ref(ref):
  z=re.fullmatch(r'([A-Z]+)([0-9]+)',ref)
  return z[1]+str(newrow(int(z[2])))
 def map_formula(f):
  return re.sub(r'(\$?[A-Z]{1,3}\$?)([0-9]+)',lambda z:z[1]+str(newrow(int(z[2]))),f)
 for rr in s:
  for cell in rr:
   if cell.data_type=='f':cell.value=map_formula(cell.value)
 cache={mapped_ref(ref):v for ref,v in cache.items()}
 s.move_range('A43:H%d'%end,rows=20,cols=0,translate=False)
 s.move_range('A31:B37',rows=21,cols=0,translate=False)
 s.move_range('A16:D28',rows=8,cols=0,translate=False)
 s.merge_cells('A16:G16');put('A16','ABHI KA PROFIT / LOSS — INTEREST AUR COSTS KE SAATH (ESTIMATED)')
 for j,h in enumerate(['Stock','Buy cost Rs','Snapshot value Rs','Price P/L Rs','Interest till today Rs','P/L incl interest Rs','Net P/L if sold now Rs'],1):s.cell(17,j,h)
 for j,r in enumerate(rows):
  k=18+j;c=chr(66+j);top=10+j;put('A'+str(k),r['symbol'])
  cost_known=finite(r['cost']) and r['cost']>0 and abs(sum(x[1]*x[2] for x in r['lots'])-r['cost'])<.02
  formula('B'+str(k),'=SUMIF($A$64:$A$%d,%s24,$E$64:$E$%d)'%(end+20,c,end+20) if cost_known else '="UNKNOWN"',r['cost'] if cost_known else 'UNKNOWN')
  formula('C'+str(k),'=IF(COUNT(C%d)=1,IF(C%d>0,B%d*C%d,"UNKNOWN"),"UNKNOWN")'%(top,top,top,top),r['now_value'] if r['now_value'] is not None else 'UNKNOWN')
  formula('D'+str(k),'=IF(COUNT(B%d:C%d)=2,C%d-B%d,"UNKNOWN")'%(k,k,k,k),r['price_pnl'] if r['price_pnl'] is not None else 'UNKNOWN')
  formula('E'+str(k),'=%s28'%c,r['past'] if r['past'] is not None else 'UNKNOWN')
  formula('F'+str(k),'=IF(COUNT(D%d:E%d)=2,D%d-E%d,"UNKNOWN")'%(k,k,k,k),r['with_interest'] if r['with_interest'] is not None else 'UNKNOWN')
  formula(c+'37','=IF(COUNT(C%d)=1,C%d*$B$52+MIN($B$53,C%d*$B$54)*(1+$B$55)+$B$56*(1+$B$55),"UNKNOWN")'%(k,k,k),r['now_sale_fee'] if r['now_sale_fee'] is not None else 'UNKNOWN')
  formula(c+'38','=IF(COUNT(D%d)=1,MAX(D%d,0)*$F$5,"UNKNOWN")'%(k,k),r['now_tax'] if r['now_tax'] is not None else 'UNKNOWN')
  formula('G'+str(k),'=IF(COUNT(F%d,%s30,%s37:%s38)=4,F%d-SUM(%s30,%s37:%s38),"UNKNOWN")'%(k,c,c,c,k,c,c,c),r['now_net_tax'] if r['now_net_tax'] is not None else 'UNKNOWN')
  put('C'+str(top),r['cmp'],str(r['price_source']))
 put('A37','Sale charges at snapshot price Rs');put('A38','Tax reserve at snapshot price Rs')
 put('A20','TOTAL')
 names=['cost','now_value','price_pnl','past','with_interest','now_net_tax']
 for col,name in zip('BCDEFG',names):
  vals=[r[name] for r in rows];ok=bool(rows) and all(finite(v) for v in vals)
  formula(col+'20','=IF(COUNT(%s18:%s%d)=%d,SUM(%s18:%s%d),"UNKNOWN")'%(col,col,17+len(rows),len(rows),col,col,17+len(rows)) if rows else '="UNKNOWN"',sum(vals) if ok else 'UNKNOWN')
 s.merge_cells('A21:G21');put('A21','Current net P/L = value - purchase cost - interest till today - buy charges - estimated sale charges - optional tax reserve. Future 30-day interest is excluded here.')
 s.merge_cells('A22:G22');put('A22','Price column uses the quoted/saved source beside each stock (cell comment). A saved snapshot remains a snapshot; a newly fetched broker quote is identified by its source. Missing prices stay UNKNOWN.')
 s.conditional_formatting.add('D18:D20 F18:G20',CellIsRule(operator='lessThan',formula=['0'],font=Font(color='C00000',bold=True)))
 s.conditional_formatting.add('D18:D20 F18:G20',CellIsRule(operator='greaterThan',formula=['0'],font=Font(color='166534',bold=True)))
 for row in s:
  for cell in row:
   cell.font=Font(name='Arial',size=10,color='000000' if cell.data_type=='f' else '0000FF' if isinstance(cell.value,(int,float,dt.date)) else '243B53')
   cell.alignment=Alignment(vertical='center',wrap_text=True)
   if isinstance(cell.value,(int,float)) or cell.data_type=='f':cell.number_format='#,##0.00;[Red](#,##0.00);"-"'
 for k in [1,9,16,17,24,63]:
  for cell in s[k]:cell.fill=PatternFill('solid',fgColor='243B53');cell.font=Font(name='Arial',bold=True,color='FFFFFF',size=12 if k==1 else 10)
 for top in range(10,10+len(rows)):
  s['E'+str(top)].fill=PatternFill('solid',fgColor='D9EAD3');s['E'+str(top)].font=Font(name='Arial',size=16,bold=True,color='166534');s.row_dimensions[top].height=36;s['F'+str(top)].number_format='0.0%'
 for ref in ['B4','D4','F4','B5','D5','F5','B6','D6']:s[ref].fill=PatternFill('solid',fgColor='FFF2CC')
 for ref in ['B4']+[f'B{k+20}' for k,_,_,_,_ in lot_rows]:s[ref].number_format='dd-mmm-yyyy'
 for ref in ['F4','F5','B52','B54','B55','B57']:s[ref].number_format='0.0000%'
 for col,width in [('A',38),('B',16),('C',22),('D',22),('E',24),('F',20),('G',24),('H',18)]:s.column_dimensions[col].width=width
 for k in [2,7,13,14,21,22,39,40]:s.row_dimensions[k].height=32
 s.row_dimensions[16].height=24;s.row_dimensions[17].height=32
 for k in (18,19,20):
  for col in ('D','F','G'):s[col+str(k)].number_format='+#,##0.00;[Red](#,##0.00);"0.00"'
 for cell in s[20]:cell.fill=PatternFill('solid',fgColor='FFF2CC');cell.font=Font(name='Arial',bold=True,size=11,color='243B53')
 for k in (18,19,20):s.row_dimensions[k].height=28
 s.row_dimensions.group(52,58,hidden=True);s.row_dimensions.group(63,end+20,hidden=True)
 s.freeze_panes='A10';s.sheet_view.showGridLines=False;s.print_options.horizontalCentered=True;s.sheet_properties.pageSetUpPr.fitToPage=True;s.page_setup.orientation='landscape';s.page_setup.paperSize=s.PAPERSIZE_A3;s.page_setup.fitToWidth=1;s.page_setup.fitToHeight=1;s.print_area='A1:G40'
 path.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(prefix='.mtf-report-',suffix='.xlsx',dir=str(path.parent));os.close(fd)
 try:
  w.save(tmp);cache_formula_values(tmp,cache)
  if path.is_symlink():raise ValueError('Report destination became a symlink')
  os.replace(tmp,path)
 finally:
  for item in (tmp,tmp+'.tmp'):
   if os.path.exists(item):os.unlink(item)
 return rows
