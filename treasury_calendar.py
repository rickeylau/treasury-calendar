#!/usr/bin/env python3
"""US Treasury auction and quarterly financing calendar. No API keys or trading actions."""
import argparse, json, re, subprocess, tempfile, unicodedata, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from http.client import IncompleteRead
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parent
PDF='https://home.treasury.gov/system/files/221/Tentative-Auction-Schedule.pdf'
QRA='https://home.treasury.gov/policy-issues/financing-the-government/quarterly-refunding/most-recent-quarterly-refunding-documents'
API='https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query'
ANN='https://www.treasurydirect.gov/auctions/auction-announcements/'
TD_API='https://www.treasurydirect.gov/TA_WS/securities/search'
ET=ZoneInfo('America/New_York')
SNAP=ROOT/'dates.json'; OUTPUT=ROOT/'treasury.ics'
TERM=re.compile(r'^\s*(\d+\s*[-–]\s*(?:Week|Year)\s+(?:BILL|NOTE|BOND|TIPS|FRN))\b',re.I)
DRE=re.compile(r'\b(?:Mon(?:day)?|Tue(?:sday)?|Wed(?:nesday)?|Thu(?:rsday)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?),?\s+([A-Za-z]+)\s+(\d{1,2}),\s+(20\d{2})\b',re.I)
DATE_TEXT=re.compile(r'([A-Za-z]+)\s+(\d{1,2}),\s+(20\d{2})')

# Network settings: retry only transient transport/HTTP failures.
FETCH_TIMEOUT=45
RETRY_DELAYS=(3,8)
RETRY_HTTP={408,429,500,502,503,504}

def fetch(url,limit=15_000_000):
    attempts=len(RETRY_DELAYS)+1
    for attempt in range(1,attempts+1):
        print(f'Downloading {url} (attempt {attempt}/{attempts})',flush=True)
        req=Request(url,headers={'User-Agent':'Mozilla/5.0 TreasuryCalendar/1.2','Accept':'*/*'})
        try:
            with urlopen(req,timeout=FETCH_TIMEOUT) as r:
                data=r.read(limit+1)
            if len(data)>limit: raise ValueError('Response exceeds limit')
            return data
        except HTTPError as e:
            if e.code not in RETRY_HTTP or attempt==attempts:
                e.close()
                raise
            delay=RETRY_DELAYS[attempt-1]
            # Honor numeric Retry-After within the bounded job budget.
            retry_after=e.headers.get('Retry-After','') if e.headers else ''
            e.close()
            if retry_after.isdigit():
                if int(retry_after)>45:
                    print(f'HTTP {e.code}; Retry-After exceeds retry budget',flush=True)
                    raise
                delay=max(delay,int(retry_after))
            print(f'HTTP {e.code}; retry in {delay}s',flush=True)
        except (TimeoutError,URLError,ConnectionError,IncompleteRead) as e:
            if attempt==attempts: raise
            delay=RETRY_DELAYS[attempt-1]
            print(f'{type(e).__name__}: {e}; retry in {delay}s',flush=True)
        time.sleep(delay)

def date_parts(month,day,year):
    return datetime.strptime(f'{month[:3]} {day} {year}','%b %d %Y').date().isoformat()

def term(s):
    return re.sub(r'\s*-\s*','-',s.strip().replace('–','-')).title()

def parse_pdf_text(text):
    rows=[]
    for line in text.splitlines():
        m=TERM.match(line)
        if not m: continue
        dates=[date_parts(*x.groups()) for x in DRE.finditer(line)]
        if len(dates)<3: raise ValueError('Unparsed Treasury schedule row: '+line[:160])
        if not dates[0]<=dates[1]<=dates[2]: raise ValueError('Unexpected date order')
        rows.append(dict(date=dates[1],label=term(m[1]),issue=dates[2],maturity=dates[3] if len(dates)>3 else '',clock=None,source=PDF))
    if len(rows)<25 or len({r['date'] for r in rows})<12: raise ValueError('Incomplete tentative schedule')
    return rows

def parse_qra(html):
    # Normalize HTML token boundaries, nonbreaking spaces and invisible formatting.
    text=' '.join(BeautifulSoup(html,'html.parser').stripped_strings)
    text=unicodedata.normalize('NFKC',text)
    text=re.sub(r'[\u200b\u200c\u200d\ufeff\u00ad]', '', text)
    text=re.sub(r'\s+', ' ', text).strip()
    sections=re.split(r'\bDOCUMENTS\s+RELEASED\s+at\s+',text,flags=re.I)[1:]
    month=r'(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?'
    date_pattern=month+r'\s+(\d{1,2})\s*(?:,\s*|\s+)(20\d{2})\b'
    weekday=r'(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.?\s*,?\s+)?'
    rows=[]; seen=set()
    for section in sections:
        if re.search(r'\bfinancing\s+estimates\s*:',section,re.I):
            label='Treasury Borrowing Estimates'
        elif re.search(r'\bpolicy\s+statement\s*:',section,re.I):
            label='Quarterly Refunding Announcement'
        else:
            continue
        if label in seen: raise ValueError('Duplicate QRA category: '+label)
        head=re.match(r'(\d{1,2}\s*:\s*\d{2}\s*[AP]\.?\s*M\.?)\s+'+weekday+date_pattern,section,re.I)
        nxt=re.search(r'next\s+release\s+(?:is\s+)?scheduled\s+for\s+'+weekday+date_pattern,section,re.I)
        if not head or not nxt:
            raise ValueError('Missing QRA release dates for '+label+'; section starts: '+section[:160])
        clock=datetime.strptime(re.sub(r'[.\s]','',head[1]).upper(),'%I:%M%p').strftime('%H:%M')
        prev_date=date_parts(*head.groups()[1:])
        next_date=date_parts(*nxt.groups())
        if not prev_date<next_date: raise ValueError('Invalid QRA date order: '+label)
        for d in (prev_date,next_date):
            rows.append(dict(date=d,label=label,clock=clock,source=QRA,kind='qra'))
        seen.add(label)
    if len(rows)!=4: raise ValueError('Expected both quarterly release categories')
    return rows

def parse_clock(x):
    if not x or str(x).lower() in ('null','none'): return None
    for fmt in ('%I:%M %p','%I:%M%p','%H:%M','%H:%M:%S'):
        try:return datetime.strptime(str(x).strip().upper(),fmt).strftime('%H:%M')
        except ValueError:pass
    raise ValueError('Unknown competitive close time: '+str(x))

def actual_rows(data):
    result=[]
    for r in data:
        d=date.fromisoformat(r['auction_date']).isoformat()
        issue=date.fromisoformat(r['issue_date']).isoformat()
        maturity=date.fromisoformat(r['maturity_date']).isoformat()
        typ=r['security_type'].upper()
        if str(r.get('inflation_index_security','')).lower()=='yes' or typ=='TIPS': typ='TIPS'
        if str(r.get('floating_rate','')).lower()=='yes' or typ=='FRN': typ='FRN'
        # Bills can be reopenings of longer originals; remaining term is issue-to-maturity.
        if typ=='BILL':
            days=(date.fromisoformat(maturity)-date.fromisoformat(issue)).days
            n=round(days/7)
            label=f'{n}-Week Bill' if n in {4,6,8,13,17,26,52} and abs(days-7*n)<=3 else f'{r["security_term"]} Bill'
            if str(r.get('cash_management_bill_cmb','')).lower()=='yes':label='Cash Management Bill '+str(r['security_term'])
        else:
            raw=r.get('original_security_term') or r['security_term']
            if raw in ('null','None'):raw=r['security_term']
            label=term(str(raw)+' '+typ)
        result.append(dict(date=d,label=label,issue=issue,maturity=maturity,clock=parse_clock(r.get('closing_time_comp')),source=ANN,cusip=r.get('cusip') or '',amount=r.get('offering_amt') or '',confirmed=True))
    return result

def merge(schedule, actual, old, today):
    # Preserve past events, replace the published future tentative schedule, then overlay formal records.
    cutoff=(date.fromisoformat(today)-timedelta(days=90)).isoformat()
    rows={(r['date'],r['label']):r.copy() for r in old if cutoff<=r['date']<today and r.get('kind')!='qra'}
    for r in schedule:
        if r['date']>=cutoff: rows[(r['date'],r['label'])]=r.copy()
    for r in actual:
        if r['date']<cutoff:continue
        matches=[k for k,v in rows.items() if not v.get('confirmed') and ((v.get('issue')==r['issue'] and v.get('maturity') and v['maturity']==r['maturity']) or (v['date']==r['date'] and v['label'].lower()==r['label'].lower()))]
        if len(matches)>1: raise ValueError('Ambiguous auction match: '+str(r))
        if matches:
            k=matches[0]; orig=rows.pop(k); r={**orig,**r,'label':orig['label']}
        elif (r['date'],r['label']) in rows:
            orig=rows[(r['date'],r['label'])];r={**orig,**r}
        rows[(r['date'],r['label'])]=r
    # Preserve verified seed times if the new tentative row has no confirmed clock.
    for r in old:
        k=(r['date'],r['label'])
        if k in rows and r.get('clock') and not rows[k].get('clock') and not rows[k].get('confirmed'):
            rows[k]={**rows[k],'clock':r['clock'],'confirmed':r.get('confirmed',False),'source':r['source']}
    return list(rows.values())

def escape(s):return str(s).replace('\\','\\\\').replace('\n','\\n').replace(';','\\;').replace(',','\\,')
def fold(s):
    out=[]; part=''
    for c in s:
        if len((part+c).encode())>75:out.append(part);part=' '+c
        else:part+=c
    return '\r\n'.join(out+[part])
def render(rows,stamp):
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Treasury Calendar//EN','CALSCALE:GREGORIAN','X-WR-CALNAME:Treasury Calendar','X-WR-TIMEZONE:America/New_York']
    seen=set()
    for r in sorted(rows,key=lambda x:(x['date'],x.get('clock') or '',x['label'])):
        day=date.fromisoformat(r['date']); slug=re.sub('[^a-z0-9]+','-',r['label'].lower()).strip('-'); uid=f'{slug}-{day}@treasury-calendar'
        if uid in seen: raise ValueError('Duplicate UID '+uid)
        seen.add(uid); qra=r.get('kind')=='qra'; title=r['label'] if qra else 'Treasury Auction: '+r['label']
        if r.get('clock'):
            dt=datetime.combine(day,datetime.strptime(r['clock'],'%H:%M').time(),ET).astimezone(timezone.utc)
            times=[f'DTSTART:{dt:%Y%m%dT%H%M%SZ}',f'DTEND:{dt+timedelta(minutes=15):%Y%m%dT%H%M%SZ}']
            desc='Scheduled release time ET.' if qra else 'Competitive bid cutoff ET; results normally follow shortly. 15-minute block is only a display reminder.'
        else:
            title+=' (Time TBD)';times=[f'DTSTART;VALUE=DATE:{day:%Y%m%d}',f'DTEND;VALUE=DATE:{day+timedelta(days=1):%Y%m%d}'];desc='Tentative date or unavailable official closing time. Check formal auction announcement.'
        if r.get('cusip'):desc+='\nCUSIP: '+r['cusip']
        if r.get('amount'):desc+='\nOffering amount (USD): '+str(r['amount'])
        if r.get('issue'):desc+='\nSettlement: '+r['issue']
        desc+='\nSource: '+r['source']+'\nVerify current official announcement before trading.'
        lines+=['BEGIN:VEVENT','UID:'+uid,'DTSTAMP:'+stamp,*times,'SUMMARY:'+escape(title),'DESCRIPTION:'+escape(desc),'URL:'+r['source'],'TRANSP:TRANSPARENT','END:VEVENT']
    return ('\r\n'.join(fold(l) for l in lines+['END:VCALENDAR'])+'\r\n').encode()

# TreasuryDirect and Fiscal Data are both official Treasury sources.
# The Direct search uses an issue-date range, then filters by auction date.
# Accept both the old and the October 2026 field names.
def td_value(record, *names, required=False):
    for name in names:
        value=record.get(name)
        if value is not None and str(value).strip().lower() not in ('', 'null', 'none'):
            return str(value).strip()
    if required:
        raise ValueError('TreasuryDirect missing '+ '/'.join(names))
    return ''


def td_date(record, *names):
    value=td_value(record, *names, required=True)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:T[^ ]+)?',value):
        raise ValueError('Invalid TreasuryDirect date: '+value)
    return date.fromisoformat(value[:10]).isoformat()


def td_normalize(record):
    if not isinstance(record,dict):
        raise ValueError('Invalid TreasuryDirect record')
    kind=td_value(record,'type').upper()
    typ=td_value(record,'securityType','type',required=True).upper()
    if typ=='CMB': typ='BILL'
    if kind=='TIPS': typ='TIPS'
    if kind=='FRN': typ='FRN'
    if kind=='CMB': typ='BILL'
    if typ not in ('BILL','NOTE','BOND','TIPS','FRN'):
        raise ValueError('Unknown TreasuryDirect security type: '+typ)
    # Do not silently treat a missing closing-time field as a confirmed time.
    if not any(k in record for k in ('competitiveAuctionCloseTime','closingTimeCompetitive')):
        raise ValueError('TreasuryDirect closing-time field missing')
    cusip=td_value(record,'cusip',required=True)
    if not re.fullmatch(r'[0-9A-Z]{9}',cusip):
        raise ValueError('Invalid TreasuryDirect CUSIP')
    return dict(
        auction_date=td_date(record,'competitiveAuctionCloseDate','auctionDate'),
        issue_date=td_date(record,'issueDate'),
        maturity_date=td_date(record,'maturityDate'),
        security_type=typ,
        security_term=td_value(record,'securityTerm',required=True),
        original_security_term=td_value(record,'originalSecurityTerm'),
        inflation_index_security='Yes' if kind=='TIPS' or td_value(record,'inflationProtected','tips').lower()=='yes' else 'No',
        floating_rate='Yes' if kind=='FRN' or td_value(record,'floatingRate').lower()=='yes' else 'No',
        cash_management_bill_cmb='Yes' if kind=='CMB' or td_value(record,'cashManagementBill','cashManagementBillCMB').lower()=='yes' else 'No',
        closing_time_comp=td_value(record,'competitiveAuctionCloseTime','closingTimeCompetitive'),
        cusip=cusip,
        offering_amt=td_value(record,'offeringAmount'),
    )


def validate_actual(rows, today, old=()):
    """Reject incomplete/stale results; never publish a partial source as healthy."""
    today_d=date.fromisoformat(today)
    cutoff=(today_d-timedelta(days=30)).isoformat()
    rows=[r for r in rows if r['date']>=cutoff]
    if len(rows)<10:
        raise ValueError('Too few official auction records in recent window')
    past=[r['date'] for r in rows if r['date']<=today]
    if not past or max(past)<(today_d-timedelta(days=7)).isoformat():
        raise ValueError('Auction source appears stale')
    by_key={}
    for r in rows:
        key=(r.get('cusip'),r['date'])
        if not r.get('cusip') or key in by_key:
            raise ValueError('Missing or duplicate official auction identity: '+str(key))
        if not r['date']<=r['issue']<=r['maturity']:
            raise ValueError('Invalid official auction date order')
        by_key[key]=r
    # Compare recent previously verified auctions, not tentative PDF rows.
    # A missing or changed confirmed identity fails closed for manual review.
    for r in old:
        if not (r.get('confirmed') and r.get('cusip') and r['date']>=cutoff):
            continue
        key=(r['cusip'],r['date'])
        new=by_key.get(key)
        if new is None:
            raise ValueError('Official source missing previously confirmed auction: '+str(key))
        if r.get('clock') and not new.get('clock'):
            raise ValueError('Official source lost a previously confirmed closing time: '+str(key))
    return rows


def fetch_treasury_direct(today, old=()):
    today_d=date.fromisoformat(today)
    start=(today_d-timedelta(days=30)).isoformat()
    end=(today_d+timedelta(days=60)).isoformat()
    url=TD_API+'?'+urlencode({'startDate':start,'endDate':end,'format':'json'})
    data=json.loads(fetch(url))
    if not isinstance(data,list) or not data:
        raise ValueError('Empty or unexpected TreasuryDirect response')
    rows=actual_rows([td_normalize(r) for r in data])
    return validate_actual(rows,today,old)


def fetch_fiscal_data(today, old=()):
    start=(date.fromisoformat(today)-timedelta(days=30)).isoformat()
    # Keep the proven Fiscal Data query as a secondary source.
    url=API+'?'+urlencode({'filter':'auction_date:gte:'+start,'page[size]':1000,'sort':'auction_date'})
    data=json.loads(fetch(url)); rows=data['data']
    if not isinstance(rows,list) or not rows or int(data.get('meta',{}).get('total-pages',1))>1:
        raise ValueError('Empty or incomplete Fiscal Data response')
    return validate_actual(actual_rows(rows),today,old)


def fetch_actual(today, old=()):
    errors=[]
    for name,loader in (('TreasuryDirect',fetch_treasury_direct),('Fiscal Data',fetch_fiscal_data)):
        print(f'Checking official auction source: {name}',flush=True)
        try:
            rows=loader(today,old)
        except (OSError,URLError,IncompleteRead,ValueError,KeyError,TypeError,AttributeError) as e:
            errors.append(f'{name}: {type(e).__name__}: {e}')
            print(f'WARNING: {errors[-1]}',flush=True)
            continue
        print(f'Official auction source: {name}; {len(rows)} validated records',flush=True)
        return rows
    raise RuntimeError('Both official auction sources failed; existing calendar retained. '+' | '.join(errors))

def main():
    p=argparse.ArgumentParser();p.add_argument('--offline',action='store_true');args=p.parse_args()
    old=json.loads(SNAP.read_text());today=datetime.now(ET).date().isoformat()
    if args.offline: rows=old['events'];stamp=old['stamp']
    else:
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'schedule.pdf';path.write_bytes(fetch(PDF)); txt=subprocess.check_output(['pdftotext','-layout',str(path),'-'],timeout=30).decode('utf-8')
        schedule=parse_pdf_text(txt)
        horizon=max(r['date'] for r in schedule)
        previous=max((r['date'] for r in old['events'] if r.get('kind')!='qra'),default=today)
        if horizon<max(today,previous):raise ValueError('Official tentative schedule is stale or shortened; retaining existing calendar')
        actual=fetch_actual(today,old['events'])
        qra=parse_qra(fetch(QRA))
        if max(r['date'] for r in qra)<today:raise ValueError('Quarterly release page stale')
        rows=merge(schedule,actual,old['events'],today)
        qra_old=[r for r in old['events'] if r.get('kind')=='qra' and r['date']<today]
        rows+=list({(r['date'],r['label']):r for r in qra_old+qra}.values())
        rows=sorted(rows,key=lambda x:(x['date'],x['label']))
        stamp=old['stamp'] if rows==old['events'] else datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    payload=render(rows,stamp);snapshot=(json.dumps({'stamp':stamp,'events':rows},indent=2)+'\n').encode()
    for path,data in [(SNAP,snapshot),(OUTPUT,payload)]:
        if not path.exists() or path.read_bytes()!=data:
            tmp=path.with_suffix('.tmp');tmp.write_bytes(data);tmp.replace(path)
    print(f'{len(rows)} events, {sum(bool(r.get("clock")) for r in rows)} timed')
if __name__=='__main__':main()
