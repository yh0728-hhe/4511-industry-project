"""Bounded Abel source-navigation probe; no models, credentials, Y or current site.

This tests retrieval plumbing only, not model-selected research or an investment
verdict. Historical links are metadata; targets require their own archive proof.
"""
import csv
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


def run():
    source=ROOT/'data/processed/w24_spreadsheet_2024-03-25.csv'
    with source.open(encoding='utf-8-sig',newline='') as stream:
        row=next(row for row in csv.DictReader(stream) if row['Company Name']=='Abel')
    domain=urlparse(row['Company Website']).hostname.lower()
    company=CompanySeed('w24:'+domain,'Abel',domain)
    now=datetime.now(timezone.utc)
    request=RunRequest(company,'Historical source navigation only; no investment verdict.',
        datetime(2024,4,4,23,59,59,tzinfo=timezone.utc),'archive-navigation-probe-v1',
        'NO_MODEL','NO_PROMPTS',min(now+timedelta(seconds=100),datetime(2026,11,9,10,45,tzinfo=timezone.utc)),0,8,1,1)
    budget=CallBudget(request);gateway=TemporalGateway(request,[])
    provider=ArchivedWebsiteProvider(request,gateway,budget,max_requests=8,
        per_request_timeout=8,max_body_bytes=2097152)
    facts={};status='COMPLETED_SOURCE_NAVIGATION_PROBE'
    try:
        for role,question in (('product','historical product information'),('unit_economics','pricing plans'),('founder','team founders')):
            for candidate in provider.search(ResearchRequest(role,question,company.company_id)):
                fact,rejection=gateway.admit(candidate)
                if fact:
                    facts[fact.fact_id]=dict(fact_id=fact.fact_id,source_id=fact.source_id,
                        available_by=fact.availability_upper_bound.isoformat(),source_url=fact.url,
                        text_sha256=fact.content_sha256,character_count=len(fact.text))
    except BudgetStopped as exc:status='STOPPED_'+str(exc)
    except RetrievalFailed:status='UNKNOWN_RETRIEVAL_FAILED'
    return dict(status=status,run_type='REAL_ABEL_SOURCE_NAVIGATION_NOT_MODEL_TEST',
        started_utc=now.isoformat(),finished_utc=datetime.now(timezone.utc).isoformat(),
        company_id=company.company_id,as_of=request.as_of.isoformat(),
        model_calls=0,paid_data_api_calls=0,archive_http_requests=budget.used['search'],
        archive_http_request_cap=8,admitted_source_metadata=list(facts.values()),
        historical_link_hints=list(provider.link_hints()),receipts=provider.receipts,attempts=provider.attempts,
        raw_bodies_saved=False,raw_company_text_saved=False,Y_read_or_modified=False,
        identity_anchor=dict(path=source.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            independent_historical_ownership_verified=False),
        limitations=['Questions are fixed plumbing probes, not new live model research.',
            'An observed old link does not establish its target existed then.',
            'Only same-domain pages were eligible; news and peers are outside this probe.',
            'Empty or failed retrieval is not a negative business outcome.'])


if __name__=='__main__':
    result=run()
    output=ROOT/'results/candidates/closed_loop_offline/archive_navigation_probe.json'
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status=result['status'],sources=len(result['admitted_source_metadata']),
        links=len(result['historical_link_hints']),http_requests=result['archive_http_requests'],model_calls=0)))
