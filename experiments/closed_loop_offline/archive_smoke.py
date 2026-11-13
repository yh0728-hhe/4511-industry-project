"""One real-company historical-source probe; zero model/paid-data calls.

Select the first alphabetical company from the existing historical cohort,
without using Y. At most two public archive HTTP requests, no retries and no
current website fallback. Save provenance/unknowns, not copyrighted page bodies.
"""
import csv
import argparse
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from closed_loop.contracts import CompanySeed,RunRequest,ResearchRequest
from closed_loop.guards import CallBudget,TemporalGateway,BudgetStopped
from closed_loop.archive_transport import ArchivedWebsiteProvider,RetrievalFailed


def run(max_body_bytes=262144):
    source=ROOT/'data/processed/w24_spreadsheet_2024-03-25.csv'
    with source.open(encoding='utf-8-sig',newline='') as stream:
        rows=sorted(csv.DictReader(stream),key=lambda row:row['Company Name'].casefold())
    row=next(row for row in rows if urlparse(row['Company Website']).hostname)
    domain=urlparse(row['Company Website']).hostname.lower()
    company=CompanySeed('w24:'+domain,row['Company Name'],domain)
    now=datetime.now(timezone.utc)
    request=RunRequest(company,'Historical-source connectivity check only; no investment decision.',
        datetime(2024,4,4,23,59,59,tzinfo=timezone.utc),'archive-source-probe-v1',
        'NO_MODEL','NO_PROMPTS',now+timedelta(seconds=30),0,2,1,1)
    budget=CallBudget(request);gateway=TemporalGateway(request,[])
    provider=ArchivedWebsiteProvider(request,gateway,budget,max_requests=2,per_request_timeout=8,max_body_bytes=max_body_bytes)
    status='COMPLETED_SOURCE_PROBE';facts=[]
    try:
        for candidate in provider.search(ResearchRequest('market','historical company website',company.company_id)):
            fact,rejection=gateway.admit(candidate)
            if fact:facts.append(dict(fact_id=fact.fact_id,source_id=fact.source_id,
                availability_upper_bound=fact.availability_upper_bound.isoformat(),
                source_url=fact.url,content_sha256=fact.content_sha256,character_count=len(fact.text)))
    except BudgetStopped as exc:status='STOPPED_'+str(exc)
    except RetrievalFailed:status='UNKNOWN_RETRIEVAL_FAILED'
    if status=='COMPLETED_SOURCE_PROBE' and not facts:status='PROBE_COMPLETED_NO_ADMITTED_SOURCE'
    return dict(run_type='REAL_COMPANY_HISTORICAL_SOURCE_PROBE_NOT_MODEL_PREDICTION',
        status=status,company_name=company.name,domain=domain,company_id=company.company_id,
        selection='first alphabetical historical cohort row with website; Y not read',
        started_utc=now.isoformat(),finished_utc=datetime.now(timezone.utc).isoformat(),
        as_of=request.as_of.isoformat(),actual_model_calls=0,paid_data_api_calls=0,
        archive_http_requests=budget.used['search'],max_body_bytes=max_body_bytes,admitted_source_count=len(facts),
        admitted_source_metadata=facts,receipts=provider.receipts,attempts=provider.attempts,
        raw_bodies_saved=False,funding_or_survival_label_assigned=False,
        identity_anchor=dict(source_file=source.relative_to(ROOT).as_posix(),
            sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            declared_snapshot='2024-03-25 from repository metadata',
            independent_historical_ownership_verified_this_probe=False),
        limitations=['A failed/empty probe establishes no company outcome.',
            'Only one exact homepage URL and its latest returned eligible capture were checked.',
            'Availability/content verification does not independently establish past domain ownership.'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-body-bytes',type=int,default=262144)
    args=parser.parse_args()
    if not 128<=args.max_body_bytes<=2097152:parser.error('bounded body limit must be 128..2097152')
    result=run(args.max_body_bytes)
    output=ROOT/'results/candidates/closed_loop_offline/real_archive_source_probe.json'
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:result[key] for key in ('status','company_name','archive_http_requests','admitted_source_count','actual_model_calls')}))
