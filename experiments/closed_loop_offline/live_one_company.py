"""One-company guarded live smoke test, disabled without separate API approval.

This is not a historical-performance experiment or paper replication. No Y is
loaded. No raw archived page body or credential is saved in repository outputs.
"""
import argparse
import csv
from dataclasses import asdict
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from closed_loop.contracts import CompanySeed,RunRequest
from closed_loop.guards import CallBudget,TemporalGateway
from closed_loop.archive_transport import ArchivedWebsiteProvider
from closed_loop.model_lead import ModelLead
from closed_loop.native_committee import NativeDialecticCommittee,NativeConfig
from closed_loop.openai_backend import create_live_backend,MODEL
from closed_loop.runtime import ClosedLoopRuntime


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approve-api-usd',default=None,
        help='Only set after explicit user approval. This is separate from Codex subscription quota.')
    parser.add_argument('--env-file',default=None,help='Existing application configuration only; no new key created.')
    args=parser.parse_args()
    plan=dict(status='NOT_RUN_SEPARATE_API_APPROVAL_REQUIRED',companies=1,
        selection='first alphabetical historical cohort website row; no Y selection',model=MODEL,
        max_api_requests=24,max_output_tokens_per_request=1000,max_request_bytes=32768,
        proposed_conservative_api_budget_usd='0.20',max_archive_http_requests=6,
        native_config=asdict(NativeConfig(selection_policy='balanced_per_side')),
        as_of='2024-04-04T23:59:59+00:00',endpoint='https://api.openai.com/v1',
        no_automatic_model_fallback=True,no_sdk_retries=True,subscription_quota_is_not_api_credit=True,
        pretraining_leakage_not_guaranteed_absent=True,not_paper_replication=True)
    if args.approve_api_usd is None:
        output=ROOT/'results/candidates/closed_loop_offline/proposed_live_smoke_plan.json'
        output.write_text(json.dumps(plan,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(plan));return
    limit=Decimal(args.approve_api_usd)
    if not limit.is_finite() or not Decimal('0')<limit<=Decimal('0.20'):
        parser.error('this pilot accepts an approved budget above zero and at most $0.20')
    source=ROOT/'data/processed/w24_spreadsheet_2024-03-25.csv'
    with source.open(encoding='utf-8-sig',newline='') as stream:
        rows=sorted(csv.DictReader(stream),key=lambda row:row['Company Name'].casefold())
    row=next(row for row in rows if urlparse(row['Company Website']).hostname)
    domain=urlparse(row['Company Website']).hostname.lower()
    company=CompanySeed('w24:'+domain,row['Company Name'],domain)
    if company.name!='Abel' or company.domain!='www.tryabel.com':parser.error('approved pilot identity changed; do not select another company')
    started=datetime.now(timezone.utc)
    req=RunRequest(company,'Seed-stage software due diligence: examine product, team, market, competition and traction; '
        'identify essential unknowns before recommending INVEST, PASS or MORE_DILIGENCE.',
        datetime(2024,4,4,23,59,59,tzinfo=timezone.utc),'archive-raw-replay-v1',MODEL,
        'guarded-native-plus-lead-v1',min(started+timedelta(minutes=8),datetime(2026,11,9,10,45,tzinfo=timezone.utc)),
        24,6,1,2)
    budget=CallBudget(req);gateway=TemporalGateway(req,[])
    backend=create_live_backend(approved=True,limit_usd=str(limit),call_budget=budget,env_file=args.env_file,
        journal_path=ROOT.parent/'runtime-r002-20261108/abel_api_budget.jsonl',pilot_id='abel-w24-asof20240404')
    provider=ArchivedWebsiteProvider(req,gateway,budget,max_requests=6,max_body_bytes=2097152)
    native=NativeDialecticCommittee(backend,budget,NativeConfig(selection_policy='balanced_per_side'))
    runtime=ClosedLoopRuntime(req,gateway,budget,ModelLead(backend,budget),native,provider)
    try:result=runtime.run()
    except Exception as exc:
        result=dict(decision='MORE_DILIGENCE',stop_reason='VALIDATION_OR_RUNTIME_FAILURE',
            error_type=type(exc).__name__,rationale='No substantive decision recorded after validation failure.')
    result.update(status='ONE_REAL_COMPANY_GUARDED_SMOKE_NOT_INVESTMENT_BACKTEST',
        company_name=company.name,company_id=company.company_id,model=MODEL,
        started_utc=started.isoformat(),finished_utc=datetime.now(timezone.utc).isoformat(),
        actual_api_request_attempts=len(backend.attempts),actual_model_calls=None,
        provider_usage_attempt_records=backend.attempts,api_spend_envelope=backend.envelope.snapshot(),
        archive_http_requests=budget.used['search'],archive_receipts=provider.receipts,
        archive_attempts=provider.attempts,raw_bodies_saved=False,y_read=False,
        note='Model factual correctness and historical domain ownership are not certified; one run proves no prediction accuracy.')
    output=ROOT/'results/candidates/closed_loop_offline/live_one_company_result.json'
    try:
        output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(dict(company=company.name,decision=result['decision'],stop=result['stop_reason'],
            api_attempts=len(backend.attempts),spend=backend.envelope.snapshot())))
    finally:backend.envelope.close()


if __name__=='__main__':main()
