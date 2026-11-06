"""Bounded free-source collection for all 240 original cohort companies.

One CDX query and at most one archived YC page per company; no model calls.
Resume saved results; failed queries never become absent evidence. Collected
pages require claim/identity review before any model-admissible packet exists.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import csv
import gzip
from datetime import datetime,timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import threading
import time
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'data/processed/w24_spreadsheet_2024-03-25.csv'
OUT=ROOT/'data/metadata/historical_x_240'
CACHE=ROOT/'.cache/historical_x_240'
CUTOFF='20240404235959'
stop=threading.Event()
RETRY_FAILED=False


class Text(HTMLParser):
    def __init__(self):super().__init__();self.skip=0;self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in ['script','style']:self.skip+=1
    def handle_endtag(self,tag):
        if tag in ['script','style'] and self.skip:self.skip-=1
    def handle_data(self,data):
        if not self.skip and data.strip():self.parts.append(data.strip())


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'columbia-ieor4511-research','Accept-Encoding':'identity'}),timeout=9) as r:
        return r.read(2000000)


def company(row):
    slug=row['YC Link'].rstrip('/').split('/')[-1];dest=OUT/'sources'/(slug+'.json')
    previous=json.loads(dest.read_text(encoding='utf-8')) if dest.exists() else None
    if previous and (not RETRY_FAILED or previous['query_status'] not in ['INDEX_QUERY_FAILED','BODY_QUERY_FAILED']):return previous
    record=dict(slug=slug,company_name=row['Company Name'],yc_url=row['YC Link'],cutoff='2024-04-04',
                query_status='NOT_ATTEMPTED',capture_date=None,capture_timestamp=None,archive_url=None,
                content_identity_status='NOT_REVIEWED',model_admissible=False,notes=[],requests=0)
    if previous:record['attempt_history']=previous.get('attempt_history',[])+[{k:previous.get(k) for k in ['query_status','requests','notes','retrieved_at_utc']}]
    if stop.is_set():record['notes'].append('Collection halted after source permission/rate-limit response');return record
    params={'url':row['YC Link'],'output':'json','fl':'timestamp,original,statuscode','to':CUTOFF,'filter':'statuscode:200','collapse':'timestamp:8','limit':'-1'}
    url='https://web.archive.org/cdx/search/cdx?'+urllib.parse.urlencode(params)
    record['query_url']=url
    try:
        record['requests']+=1;raw=fetch(url);rows=json.loads(raw)
        caps=[r for r in rows if r and r[0]!='timestamp' and r[0]<=CUTOFF]
        if not caps:record['query_status']='OK_NO_CAPTURE_RETURNED'
        else:
            cap=max(caps,key=lambda r:r[0]);ts,original=cap[:2]
            archive='https://web.archive.org/web/'+ts+'id_/'+original
            record.update(capture_timestamp=ts,capture_date=ts[:4]+'-'+ts[4:6]+'-'+ts[6:8],archive_url=archive,query_status='CAPTURE_INDEXED_BODY_PENDING')
            if stop.is_set():raise RuntimeError('Body fetch skipped after stop')
            record['requests']+=1;body=fetch(archive);decoded=gzip.decompress(body) if body[:2]==b'\x1f\x8b' else body;text=decoded.decode('utf-8',errors='replace');parser=Text();parser.feed(text)
            title=re.search(r'<title[^>]*>(.*?)</title>',text,re.I|re.S)
            title=title.group(1).strip() if title else ''
            clean=' '.join(parser.parts)
            name_ok=bool(re.search(r'(?<!\w)'+re.escape(row['Company Name'])+r'(?!\w)',title,re.I))
            batch_ok=bool(re.search(r'\bW24\b|Winter\s*2024',clean,re.I))
            record.update(query_status='ARCHIVE_BODY_FETCHED',page_title=title,
                body_sha256=hashlib.sha256(body).hexdigest(),text_excerpt=' '.join(clean.split()[:120]),
                content_identity_status='NAME_AND_BATCH_REVIEW_CANDIDATE' if name_ok and batch_ok else 'MANUAL_IDENTITY_REVIEW_REQUIRED',
                archived_name_in_title=name_ok,archived_w24_in_visible_text=batch_ok)
            (CACHE/(slug+'.html')).write_bytes(body)
            record['notes'].append('Archived body is a source candidate; individual team/product/market claims not yet independently extracted/reviewed')
    except Exception as e:
        code=getattr(e,'code',None)
        if code in [401,403,429]:stop.set()
        record['query_status']='BODY_QUERY_FAILED' if record['capture_timestamp'] else 'INDEX_QUERY_FAILED'
        record['notes'].append(type(e).__name__+': '+str(e))
    record['retrieved_at_utc']=datetime.now(timezone.utc).isoformat()
    dest.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    time.sleep(0.3)
    return record


def main():
    global RETRY_FAILED
    p=argparse.ArgumentParser();p.add_argument('--workers',type=int,default=3);p.add_argument('--retry-failed',action='store_true');args=p.parse_args()
    RETRY_FAILED=args.retry_failed
    if (OUT/'RATE_LIMIT_STOP.json').exists():raise RuntimeError('Source rate-limit stop exists; inspect it and confirm source access before any resumed run')
    (OUT/'sources').mkdir(parents=True,exist_ok=True);CACHE.mkdir(parents=True,exist_ok=True)
    with SOURCE.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    if len(rows)!=240 or len({r['YC Link'] for r in rows})!=240:raise ValueError('Invalid locked cohort')
    counts={};n=0
    with ThreadPoolExecutor(max_workers=min(3,max(1,args.workers))) as pool:
        for future in as_completed([pool.submit(company,r) for r in rows]):
            r=future.result();n+=1;counts[r['query_status']]=counts.get(r['query_status'],0)+1
            if n%20==0 or n==240:print(json.dumps(dict(processed=n,status_counts=counts,source_halted=stop.is_set())),flush=True)
    (OUT/'collection_summary.json').write_text(json.dumps(dict(cohort=240,status_counts=counts,source_halted=stop.is_set(),policy='One CDX + at most one archived YC page per original URL; failed/absent/collected distinct; all model_admissible false'),indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
