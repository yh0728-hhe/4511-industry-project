"""Opt-in public archive connectivity probe: no model, key, outcome or paid API."""
import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

from .readiness import ROOT, OUT, save, lease
from closed_loop.archive_transport import ArchivedWebsiteProvider, RetrievalFailed
from closed_loop.contracts import RunRequest, ResearchRequest
from closed_loop.guards import CallBudget, TemporalGateway, BudgetStopped


def probe(*, client=None):
    path=ROOT/'experiments/closed_loop_offline/weekly_smoke.py'
    spec=importlib.util.spec_from_file_location('readiness_smoke_selection',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    company=module.select_company()
    started=datetime.now(timezone.utc)
    request=RunRequest(company,'Historical source connectivity only; no investment verdict.',
        module.CUTOFF,'readiness-archive-connectivity-v1','NO_MODEL','NO_MODEL_PROMPTS',
        started+timedelta(seconds=30),0,2,1,1)
    budget=CallBudget(request);gateway=TemporalGateway(request,[])
    provider=ArchivedWebsiteProvider(request,gateway,budget,client=client,
        max_requests=2,per_request_timeout=8,max_body_bytes=262144)
    facts=[];status='NO_ADMITTED_SOURCE'
    try:
        for candidate in provider.search(ResearchRequest('other','Historical homepage connectivity only',company.company_id)):
            fact,rejection=gateway.admit(candidate)
            if fact:
                facts.append(dict(fact_id=fact.fact_id,source_id=fact.source_id,url=fact.url,
                    available_by=fact.availability_upper_bound.isoformat(),content_sha256=fact.content_sha256,
                    character_count=len(fact.text)))
        if facts:status='HISTORICAL_SOURCE_ADMITTED_NOT_A_MODEL_RUN'
    except (BudgetStopped,RetrievalFailed) as exc:
        status='UNKNOWN_RETRIEVAL_OR_BUDGET_STOP'
    return dict(status=status,company=asdict(company),cutoff=request.as_of.isoformat(),
        started_utc=started.isoformat(),finished_utc=datetime.now(timezone.utc).isoformat(),
        archive_http_attempts=provider.attempts,archive_receipts=provider.receipts,
        archive_http_requests=budget.used['search'],max_http_requests=2,
        actual_model_calls=0,paid_api_calls=0,raw_bodies_saved=False,y_read=False,
        admitted_fact_metadata=facts,historical_domain_ownership_independently_verified=False,
        identity_anchor=dict(path=module.COHORT.relative_to(ROOT).as_posix(),
            sha256=hashlib.sha256(module.COHORT.read_bytes()).hexdigest(),
            limitation='Repository-declared historical cohort, not independently verified historical identity.'),
        interpretation='Retrieval failure is unknown evidence availability, never no-funding or business failure.')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true',help='Opt in to at most two public archive HTTP requests.')
    args=parser.parse_args(argv)
    if not args.execute:
        print(json.dumps(dict(status='NOT_RUN',model_calls=0,http_requests=0,
                              next_step='Use --execute only for bounded public archive connectivity.')))
        return 0
    folder=OUT/'archive-connectivity';folder.mkdir(parents=True,exist_ok=True)
    path=folder/'receipt.json'
    with lease(folder):
        if path.exists():
            parser.error('Probe receipt already exists; preserve it and do not automatically repeat this probe.')
        result=probe();save(path,result)
    print(json.dumps({key:result[key] for key in ('status','company','archive_http_requests','actual_model_calls','paid_api_calls')},indent=2))
    return 0


if __name__=='__main__':main()
